# Runbook de operação

Como operar o MP no dia a dia. Para **instalar** (DNS, banco, containers) veja
`deploy/RUNBOOK.md`; para os workflows, `n8n/README.md`.

O n8n só agenda, encadeia, faz retry e notifica. Toda a regra mora no backend — então o
que o n8n faz, você também pode fazer à mão com `curl` e a mesma chave.

## 1. O que roda sozinho

Fuso `America/Sao_Paulo`. Os horários seguem a dependência entre as etapas: o funil enche
antes, o motor decide, e só então saem links e campanhas.

| Workflow | Quando | O que faz | Se falhar |
|---|---|---|---|
| 01 Descoberta | diário 03h | 40 mais vendidos por categoria (~1000) **+ varredura de comissão alta** (300 por categoria, por preço decrescente) → qualifica → pontua | próxima rodada refaz (idempotente) |
| 02 Promover | 05:00 | `QUALIFICATION` → `CANDIDATE` | idem; exige autonomia ≥ 2 |
| 07 Decisão da IA | 05:30 | analisa (RECOMMEND) → aplica o que a autonomia permite | recomendações ficam PENDING |
| 03 Links | 06:00 | gera `sub_id` + link p/ produtos em teste | exige autonomia ≥ 3 |
| 04 Conteúdo e proposta de pins | 07:00 | monta o pacote (legenda + foto + link), manda no WhatsApp e **avisa quantos pins aguardam a sua aprovação** | as legendas saem mesmo se o aviso falhar |
| 04b Publicar aprovados | a cada 1h | publica no Pinterest **só os pins que você aprovou** no painel; avisa só se algo saiu ou falhou | exige autonomia ≥ 4; falha passageira não perde o pin aprovado |
| 05 Campanhas | 06:30 | cria campanhas **PAUSED** (máx. 2 por execução) | `ABORTED` notifica; exige autonomia ≥ 4 |
| 06 Performance | a cada 4h | Insights + conversões → consolida → scores → snapshot | alerta de dado velho em 12h |
| 08 Alertas | a cada 1h | avalia regras, notifica só alerta **novo** | — |
| 09 Resumo do dia | 21:00 | atualiza vendas e manda no WhatsApp o que aconteceu, o que mudou e o que espera por você | o resumo sai mesmo assim e avisa que o dado está velho |
| 00 Erro | quando qualquer um falha | notifica no seu webhook | — |

Cada chamada tem retry (3 tentativas, 5 s) e uma `Idempotency-Key` por execução: um retry
depois de resposta perdida devolve o resultado guardado em vez de repetir o efeito.

**Notificações no WhatsApp:** `n8n/install.sh --whatsapp-to …` (veja `n8n/README.md`). Use uma
instância da Evolution só do MP, sem webhook — nunca a do chat de atendimento.

## 2. Subir devagar (nesta ordem)

O backend nasce no modo mais seguro. Cada degrau é uma variável em `deploy/.env.prod`;
depois de mudar, aplique com `docker compose -f deploy/docker-compose.prod.yml --env-file
deploy/.env.prod up -d backend`.

| Degrau | Variáveis | O que muda |
|---|---|---|
| 0 · inicial | `DRY_RUN=true`, `MOCK_*=true`, `AI_AUTONOMY_LEVEL=1` | workflows rodam, **nada é gravado**; dashboard vazio |
| 1 · dados mock | `DRY_RUN=false` | funil, performance e decisões gravam (dados fictícios) |
| 2 · autonomia | `AI_AUTONOMY_LEVEL=2…4` | 2 promove candidatos · 3 entra/sai do portfólio e gera links · 4 cria campanhas PAUSED |
| 3a · Shopee real | `MOCK_MARKETPLACE=false` + `SHOPEE_APP_ID`/`SHOPEE_SECRET` | descoberta, links e relatórios de conversão da Shopee de verdade (veja §2.1) |
| 3b · Meta real | `MOCK_ADS=false` | **ainda não disponível**: depende do UNKNOWN-7 (Meta Marketing API) |

Mude **um degrau por vez** e olhe o dashboard (Visão geral → "Trilhos de segurança") antes
do próximo. Em nenhum nível a plataforma ativa campanha: isso é sempre manual no
Gerenciador de Anúncios do Meta.

Com `AI_AUTONOMY_LEVEL=1` a decisão continua possível, mas **só por você**: aprove em
Inteligência → "Aprovar e executar".

### 2.1 Ligar a Shopee de verdade

1. Rode o teste de fumaça (somente leitura) **antes** de mexer em qualquer variável:
   ```bash
   docker exec -e SHOPEE_APP_ID=... -e SHOPEE_SECRET=... mp-backend \
     python -m app.adapters.marketplace.shopee.smoke
   ```
   Ele confere se a assinatura é aceita, se os campos pedidos existem e o que cada consulta devolve
   (acrescente `--short-link` para também gerar um link). É o que a documentação não garante.
2. **Liquidação:** o `validatedReport` da Shopee exige o ID do lote de liquidação (`validationId`)
   e não há como listá-los pela API. Pegue-os no painel de afiliado (Billing) e ponha em
   `SHOPEE_VALIDATION_IDS` (separados por vírgula; acrescente um a cada ciclo). **Sem eles nenhum
   dia vira SETTLED, e o motor nunca corta produto por ROI negativo** — o lado seguro de errar,
   mas o portfólio não se renova sozinho.
3. Em `deploy/.env.prod`: `SHOPEE_APP_ID`, `SHOPEE_SECRET`, `MOCK_MARKETPLACE=false` e confira que
   `SHOPEE_API_URL` é `https://open-api.affiliate.shopee.com.br/graphql` (o `.shopee.br` da
   documentação original **não resolve**). Mantenha `DRY_RUN=true` no primeiro dia.
4. `up -d backend`, rode o workflow 01 à mão e olhe o dashboard. A Shopee **nunca informa estoque
   nem número de avaliações**: o score ignora essas duas peças (não é "dado faltando") e usa as
   vendas como medida de confiança da nota — está registrado em cada score.
5. Só então `DRY_RUN=false`.

Cuidados: produtos do mock que sobraram no banco **não** recebem link da Shopee (o gerador só
atende produtos do marketplace ativo). O limite de requisições da Shopee não é documentado
(UNKNOWN-5): o cliente espaça as chamadas (0,5 s) e, no erro 10030, espera e tenta de novo (até 4
vezes, com espera crescente). Se aparecerem muitos 10030, aumente `SHOPEE_MIN_INTERVAL_SECONDS`.

## 3. Rotina

**Diária (2 min):** abra o dashboard.
- *Visão geral*: os três trilhos seguem como você deixou? Há recomendações pendentes?
- *Inteligência*: aprove ou rejeite o que o motor propôs. Leia o "porquê" e o diagnóstico.
- *Campanhas*: as criadas pelo MP chegam `PAUSED` e aguardando revisão. Olhe no Meta, ative lá
  se quiser, e marque como revisada aqui (isso **não** ativa nada). Passar de 10 sem revisar
  **bloqueia** a criação de novas.

**Semanal:** *Financeiro* → 30 dias. ROI só vale com dado **liquidado**; "Estimado" é
tendência, não veredito. Confira também *Portfólio* → "Orçamento de hoje".

## 4. Alertas e o que fazer

| Código | Severidade | Significa | Ação |
|---|---|---|---|
| `UNREVIEWED_QUEUE_FULL` | CRITICAL | campanhas demais sem revisão; criação bloqueada | dashboard → Campanhas → "Marcar revisada" (ou rejeite) |
| `BUDGET_NEAR_CAP` | WARNING | ≥ 90% do teto diário comprometido | nada, a menos que queira subir `MAX_DAILY_AD_SPEND` |
| `ROI_NEGATIVE_3D` | WARNING | produto com ROI < 0 por 3 dias seguidos | **nada foi pausado.** Olhe o diagnóstico em Inteligência; o motor só troca com dado liquidado |
| `PERFORMANCE_DATA_STALE` | WARNING | sem sync de performance há 12h | o workflow 06 está ativo? o n8n alcança o backend? |
| `CAMPAIGN_CREATED_NOT_PAUSED` | CRITICAL | o Meta criou uma campanha fora de PAUSED; a plataforma pausou | **confira no Meta agora** |
| `PRODUCT_REPLACED` | INFO | produto trocado | se a campanha dele foi ativada no Meta, desative-a lá |

O mesmo alerta não repete em 24h. Marque como visto com `POST /api/v1/alerts/{id}/acknowledge`
(dashboard autenticado).

## 5. Parar tudo (botão de emergência)

Do mais leve ao mais pesado:

1. **Pausar a automação:** no n8n, desative os workflows "MP …". Nada mais dispara.
2. **Congelar o que o backend grava:** `DRY_RUN=true` em `deploy/.env.prod` e `up -d backend`.
   Os gatilhos continuam respondendo, mas sem efeito.
3. **Tirar a IA do volante:** `AI_AUTONOMY_LEVEL=1`. Só decisões aprovadas por você executam.
4. **Campanhas no Meta:** a plataforma nunca ativa nada, então não há o que "desligar" do
   lado dela. O que estiver ativo foi ativado por você — pause no Gerenciador.

## 6. Quando algo dá errado

**Chegou "falha no workflow X" no webhook.** Abra o n8n → Executions → a execução com
erro → o nó em vermelho. `401` = chave errada (veja §7); `ECONNREFUSED`/`ENOTFOUND` = o n8n
não enxerga o `mp-backend` (`docker network connect coolify <container-n8n>`); `409` com
`BUDGET_EXCEEDED`/`LOCK_UNAVAILABLE` = esperado em alguns casos, a próxima rodada refaz.

**Workflow 05 "ABORTOU".** A fila de campanhas sem revisão passou do limite. Revise em
Campanhas (dashboard); a criação volta sozinha. O alerta `UNREVIEWED_QUEUE_FULL` acompanha.

**Dashboard sem dado.** Normal nos degraus 0 (DRY_RUN) e antes do primeiro sync. Veja
`GET /api/v1/performance/summary` e `workflow_runs` (cada gatilho deixa uma linha).

**`/health` ok mas o domínio dá 503.** Container `unhealthy` (o Traefik tira do roteamento):
`docker ps` e `docker inspect <nome> -f '{{json .State.Health}}'`.

**Nunca rode `GRANT <role> TO CURRENT_USER` no Postgres do Supabase.** Na imagem
`supabase/postgres:15.8.1.085` isso derruba o backend do servidor com segfault (reproduzido).
Crie bancos e roles como `supabase_admin`, como o `deploy/bootstrap.sh` faz.

## 7. Trocar a chave do n8n

```bash
# 1. gere a nova e troque N8N_API_KEY em deploy/.env.prod
openssl rand -hex 32
# 2. recrie o backend para ele ler a nova
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.prod up -d backend
# 3. reimporte a credencial (atualiza a "MP API Key" no n8n)
bash n8n/install.sh --notify-url <seu-webhook>
# o install.sh deixa os workflows INATIVOS: religue o botão "Active" de cada "MP …" no n8n
# (sem reiniciar o n8n, que atende outras automações)
```

Enquanto os passos 2 e 3 não terminam, os workflows recebem 401 — e o workflow 00 avisa.

## 7.1 Pacote diário de conteúdo orgânico (workflow 04, 07:00)

Para cada um dos até `CONTENT_DAILY_COUNT` (padrão 3) produtos do portfólio (WINNER > ACTIVE >
TEST, os menos divulgados primeiro, só com foto) o MP monta um post: legenda em português, a
foto do produto e um **link rastreado próprio** (canal `ig`, com o id do post no sub_id — a
venda volta ao post exato). Chega no WhatsApp como imagem com a legenda; você copia, publica e
cola o link na bio ou no sticker de link dos Stories.

- **Sem LLM** (`LLM_PROVIDER=null`): modelo de texto com fatos da API (preço, vendas, nota).
- **Com Claude**: `LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY` e, se quiser, `LLM_MODEL`
  (padrão `claude-haiku-5-5`). O teto diário é `LLM_DAILY_COST_CAP_USD` (padrão 1,00) e o custo
  é estimado por `LLM_INPUT_USD_PER_MTOK` / `LLM_OUTPUT_USD_PER_MTOK` — confira os preços.
- **Salvaguardas**: a legenda do LLM só passa se não trouxer número fora dos fatos, promessa
  (garantido, frete grátis, estoque…), link, hashtag ou a palavra "Shopee" (Termos 2.3(a)); senão cai no modelo de texto. O aviso
  de afiliado é sempre acrescentado pelo código. Toda chamada fica em `llm_calls`.
- Exige autonomia 3 (gera link). Reexecutar no mesmo dia não duplica posts.

### Quantos produtos entram em teste (e quantos pacotes saem)

São dois números independentes, e o primeiro é menos óbvio do que parece:

- **Vagas de teste** = `MAX_DAILY_AD_SPEND × EXPLORATION_PERCENTAGE ÷ MIN_DAILY_TEST_BUDGET`
  (hoje 100 × 30% ÷ 10 = **3**). A conta vem do orçamento de anúncio, mesmo no orgânico, e
  quem enche as vagas é o ciclo das 05:30, pelos candidatos de maior receita por clique. Para
  ter mais produtos em teste sem aumentar o teto de gasto, **suba `EXPLORATION_PERCENTAGE`**
  (e baixe `EXPLOITATION_PERCENTAGE` para fechar 100): a soma das vagas não muda. Os dois
  vivem em `config_parameters` e valem na hora, sem deploy.
- **Pacotes por dia** = `CONTENT_DAILY_COUNT` (variável do `.env.prod`, de 1 a 10, padrão 3).
  Exige reiniciar o backend.

Toda vaga é de um produto que se pode divulgar: o guarda de réplica (§7.4) barra o suspeito
**na entrada do portfólio**, não só na publicação. Sem isso, quem posta à mão receberia no
WhatsApp um produto que a publicação automática teria barrado.

## 7.1.1 As duas varreduras da descoberta

| Varredura | Ordenação | O que acha | Critério para guardar |
|---|---|---|---|
| mais vendidos | vendas (`sortType 2`) | demanda provada, **comissão baixa** | tudo |
| comissão alta | preço decrescente (`sortType 3`) | a cauda de comissão alta | comissão ≥ `COMMISSION_SWEEP_MIN_VALUE` **e** vendas ≥ `COMMISSION_SWEEP_MIN_SALES` |

Nenhuma das duas basta sozinha, e isso foi medido na API real em 02/11/2026:

- Por vendas, o topo de cada categoria é barato: comissão mediana de **R$ 3,03** por venda.
  Para R$ 10 mil no mês seriam 3.300 vendas — 110 por dia.
- Por preço decrescente, a primeira página traz geladeira de R$ 85 mil pagando R$ 6.846 de
  comissão e **zero venda**. Comissão alta sem demanda não vale nada.
- A interseção é grande: em 5 categorias, 300 itens cada, **338 produtos** com ≥ R$ 15 de
  comissão e ≥ 100 vendas. O catálogo construído só por vendas tinha 23 em 1.061.

Por isso a varredura de comissão exige as duas condições. O resultado explica cada item lido:
`kept`, `skipped_low_commission`, `skipped_low_sales` e `skipped_unknown` (preço, comissão ou
vendas não informados — "não sei" nunca vira "reprovado por ser ruim"). Produto que já
acompanhamos é guardado mesmo abaixo do piso: a série de snapshots dele não pode ter buraco,
é dela que saem velocidade e aceleração.

Rodar à mão, por exemplo com pisos diferentes:

```bash
curl -s -X POST https://mp.dsearch.com.br/api/v1/trigger/discovery \
  -H "X-API-Key: $N8N_API_KEY" -H 'Content-Type: application/json' \
  -d '{"by_commission": true, "min_commission_value": 10, "min_sales": 50}'
```

A qualificação também passou a ter piso de comissão em dinheiro
(`QUALIFICATION_MIN_COMMISSION_VALUE`, padrão R$ 5,00): 8% de R$ 22 é R$ 1,76 por venda, e a
taxa sozinha engana. **`REJECTED` é terminal** — baixar o piso depois não ressuscita produto já
rejeitado.

## 7.2 Página pública e contagem de clique

Três endpoints **sem autenticação** (é o visitante que acessa), servidos pelo backend fora do
`/api`:

| Caminho | O que é |
|---|---|
| `/go/{sub_id}` | redirect 302 para o link de afiliado. Grava o clique em `link_clicks` |
| `/l` | página "link na bio": vitrine dos produtos do portfólio que já têm link |
| `/robots.txt` | nega `/go/`, `/l` e `/api/` a buscador obediente |

Configure `PUBLIC_BASE_URL` em `deploy/.env.prod`. **Sem ela o pacote diário sai com o link de
afiliado direto, o clique não é medido e o pacote avisa isso nos warnings.**

Por que o desvio existe, em vez de pôr o link de afiliado direto no post:

1. **Medição.** A Shopee informa venda, nunca clique, e o Instagram não devolve clique de link
   na bio. `link_clicks` é a única fonte de CVR que temos — e sem CVR não há aprendizado
   estatístico nenhum (`docs/plano-10k.md` §3).
2. **Conformidade.** Os Termos 4.3(k) proíbem indexar URL que carregue o ID de afiliado. A
   página é `noindex` e o link de afiliado só aparece no 302, depois do clique.

O que a contagem faz e não faz:

- **Pré-visualizador de link não é clique.** WhatsApp, Facebook, Telegram e crawlers buscam a
  URL para montar o card: ficam gravados com `is_bot=true` e **fora** da conta. Sem isso o CVR
  de todo produto compartilhado viraria ruído.
- **O mesmo visitante no mesmo dia conta uma vez** (`is_unique`). O bruto fica ao lado; a
  diferença entre bruto e contado é a fatia de robô do canal.
- **O IP nunca é gravado**: só `sha256(ip + user-agent + CLICK_HASH_SALT + dia)` truncado.
- O clique é best-effort: se gravar falhar, o visitante é redirecionado do mesmo jeito.
- `sub_id` desconhecido ou revogado é **404**, nunca redirect — do contrário o domínio viraria
  open redirect.

A consolidação (workflow 06) leva esses cliques para `performance_daily` no canal do `sub_id`
(`ig`, `pin`, `bio`), separado do pago (`meta`). No orgânico `ad_spend` fica `NULL` e não zero:
não existe gasto de anúncio ali, e somar como zero inflaria o ROI do pago com receita que não
veio dele. A métrica do orgânico é `epc` (receita por clique) e `cvr`.

## 7.3 Receita esperada por clique (ev_v1)

O Opportunity Score responde "este produto é bom?" numa escala de 0 a 100. A meta de
comissão pergunta outra coisa: **"quanto este produto rende no slot de hoje?"**. São
perguntas diferentes e por isso há dois números.

```
receita esperada por clique = comissão em dinheiro × conversão estimada
```

- **Comissão em dinheiro** = preço × taxa. Exata, vem da API.
- **Conversão estimada** = média da posterior `Beta(α, β)`, com prior da categoria (ou
  global) e evidência vinda dos cliques do nosso redirect e das vendas atribuídas por
  `sub_id`.

Onde esse número manda hoje:

| Lugar | O que mudou |
|---|---|
| vaga no portfólio | o candidato de maior R$/clique entra primeiro, não o de maior score |
| página `/l` | ordenada por R$/clique |
| pacote diário | primeiro quem nunca foi divulgado, depois maior R$/clique |
| tela de Produtos | coluna **R$/clique** e ordenação "Maior receita esperada" |

Sem EV calculado, cada um desses cai no Opportunity Score: nunca se deixa de decidir por
falta de um número novo.

### Como ler a coluna

`sem clique` em âmbar significa que o número **ainda é prior**: foi calculado, mas nenhum
clique próprio existe por trás dele. É hipótese, não medição, e a gaveta do produto diz
isso em letras. Quando o clique chega, a posterior se estreita e o aviso sai.

O prior não é achatado — se fosse, o ranking viraria "maior comissão em dinheiro" e o topo
de toda lista seria iPhone de R$ 9.149, que paga R$ 366 por venda e converte pouquíssimo
vindo de rede social. Ele é moldado por preço (conversão cai com o preço), demanda, nota e
**momento** (aceleração das vendas, por Theil–Sen sobre a série de snapshots). Todo fator é
limitado, é 1,0 quando o dado não veio — ausência nunca penaliza — e aparece em
`components`, auditável.

### O que ele ainda não é

Não é Thompson sampling. A alocação de slot desta fase são dois degraus (nunca divulgado
primeiro, depois maior EV); o sorteio contínuo da posterior é a Fase 2 do
`docs/plano-10k.md`. E **não se tira significância daqui**: distinguir CVR de 2% de 3%
exige ~3.800 cliques por produto. `MIN_CLICKS_FOR_DECISION = 50` é portão de sanidade, não
teste estatístico.

Rodar à mão:

```bash
curl -s -X POST https://mp.dsearch.com.br/api/v1/trigger/scoring/ev \
  -H "X-API-Key: $N8N_API_KEY"
```

Roda sozinho no workflow 01 (após as varreduras) e no 06 (após consolidar cliques e vendas).

## 7.4 Publicação no Pinterest: o MP propõe, você aprova cada pin

O pacote de conteúdo continua chegando no WhatsApp — serve para o Instagram, que ainda é
manual. O mesmo pacote vira uma **fila de aprovação** no painel (menu **Publicação**), e o
workflow 04b publica no Pinterest o que você aprovou.

### Por que não publica sozinho

A regra 4.3 das Diretrizes de Desenvolvedor do Pinterest proíbe iniciar ações
automaticamente sem que a pessoa considere cada uma. O exemplo é o nosso caso: num
agendador de pins, "the end user must choose each Pin to be published". Por isso o MP só
**propõe**; a decisão é sua, pin a pin. Não existe configuração que desligue isso.

- No painel, **Publicação** lista os pins dos últimos 3 dias, com imagem, preço, comissão e
  legenda. **Aprovar** marca o pin para sair na próxima rodada horária; **Rejeitar** o tira
  da fila. Dá para mudar de ideia enquanto ele não saiu. Há seleção em lote: você escolhe
  cada pin marcando a caixa dele.
- A decisão é gravada com o seu e-mail (`publish_approvals`, append-only). **O n8n não
  consegue aprovar**: os endpoints exigem o login do painel e recusam a chave da automação.
- Aprovar **não contorna** o guarda de réplica (abaixo): produto suspeito aprovado continua
  barrado, e o painel nem deixa aprovar.
- Falha passageira (token, limite de taxa, rede) **não perde** o pin aprovado: ele segue
  aprovado e é tentado de novo na rodada seguinte. Só a recusa do próprio Pinterest (que se
  repetiria igual) é definitiva.

No workflow 04, a publicação continua sendo um **ramo paralelo**, e não elo da cadeia, por
um motivo técnico: o nó "Um post por mensagem" divide a resposta em N itens, e qualquer nó
depois dele rodaria N vezes. Às 07:00 esse ramo quase sempre publica zero e serve para
avisar no WhatsApp quantos pins aguardam você.

### Antes de ligar: o Pinterest precisa aprovar o app

Esta é a parte que **não** se automatiza, e é o caminho crítico:

1. **Conta business.** Apps registrados a partir de 14/09/2026 recebem
   `403 PINNER_DATA_ACCESS_DENIED` quando a conta é pessoal.
2. **App em developers.pinterest.com**, com escopos `boards:read`, `boards:write`,
   `pins:read`, `pins:write`.
3. **Standard access.** Em **Trial access o pin criado é visível só para o dono da conta** —
   publicar de verdade nesse estado gasta cota e não entrega alcance nenhum. Para subir:
   gravar um **vídeo** do app executando uma ação na API, mostrando o fluxo OAuth e que não
   se armazena dado sensível (gravação de terminal é aceita), depois *Upgrade* no cartão do
   app em *My apps*. Exige também link de política de privacidade. A revisão não tem prazo
   divulgado. Motivos comuns de recusa: vídeo sem o fluxo de autenticação, login que não é
   OAuth, demonstração sem integração real.

Enquanto a aprovação não sai, deixe `MOCK_SOCIAL=true`: o fluxo roda inteiro, registra em
`social_posts` e não toca a rede.

### Autorizar o app (uma vez, depois que o Trial for aprovado)

O Pinterest só entrega o refresh token depois que você aprova o app no navegador. O comando
abaixo faz isso sem servidor local (o MP roda num servidor remoto, e o redirecionamento para
`localhost` cairia no aparelho de quem aprova). Antes: ponha `PINTEREST_APP_ID` e
`PINTEREST_APP_SECRET` no `deploy/.env.prod` e recrie o backend (`up -d backend`) — o container
só lê o `.env` ao ser criado. O secret só aparece no painel do Pinterest depois da aprovação
do Trial.

```
docker exec -w /srv mp-backend python -m app.cli.pinterest_authorize start
```

1. Abra o endereço impresso no navegador, logado na conta **business**, e clique em permitir.
2. O navegador vai mostrar um erro de conexão com `localhost:8085`. **É esperado.** Copie a URL
   **inteira** da barra de endereço (no iPad, toque nela para ver o endereço completo).
3. Rode o `finish` com a URL (você tem 15 minutos desde o `start`):

```
docker exec -w /srv mp-backend python -m app.cli.pinterest_authorize finish --redirect-url 'COLE_A_URL'
```

O `finish` troca o código pelo token, **grava em `oauth_tokens`** (sem imprimir nada sensível)
e lista o que o Pinterest mostra para a conta: tipo da conta, **boards** (use o id numérico em
`PINTEREST_BOARD_ID`) e **contas de anúncios** (`PINTEREST_AD_ACCOUNT_ID`, moeda BRL). Se faltar
algum escopo concedido, ele avisa. `... check` repete só a listagem, a qualquer momento.

A URL de retorno carrega um código de uso único que não serve sem o App secret, mas apague-a do
histórico do terminal se preferir. Reautorizar substitui o token anterior; o refresh token
renova a cada uso, e 60 dias sem uso exigem repetir este procedimento.

### Configuração

| variável | para quê |
|---|---|
| `MOCK_SOCIAL` | `true` (padrão) não publica nada de verdade |
| `PINTEREST_APP_ID` / `PINTEREST_APP_SECRET` | credenciais do app |
| `PINTEREST_REFRESH_TOKEN` | **semente** da primeira autorização, só |
| `PINTEREST_BOARD_ID` | id numérico do board (`GET /v5/boards`) |
| `PUBLISH_MAX_PER_RUN` | pins por execução (padrão 10) |
| `PUBLISH_PRICE_CEILING` | teto do guarda de marca (padrão R$ 800) |
| `PUBLISH_BRAND_CATEGORIES` | ids de categoria de risco |

E **autonomia 4**: publicar é a primeira ação do MP que fica pública. Campanha, mesmo no
nível 4, nasce PAUSED e não alcança ninguém sem um clique humano; um pin publicado alcança.
Em produção a autonomia está em 3, então a publicação fica inerte até você subir de
propósito.

### O token rotaciona — e isso tem consequência operacional

O refresh token do Pinterest é *continuous refresh*: **expira em 60 dias, renovável
indefinidamente**, e cada renovação devolve um token novo que invalida o anterior. Por isso
ele é guardado na tabela `oauth_tokens` (a única tabela mutável do projeto, de propósito) e
gravado em transação própria — se fosse gravado junto da publicação e a publicação falhasse,
o rollback jogaria fora o token novo enquanto o antigo já não vale.

**O que isso significa para você:** publicar todo dia renova de sobra. Mas **60 dias com o
workflow desligado matam a integração**, e aí só se recupera reautorizando o app no
navegador à mão. Não há como o sistema se recuperar sozinho.

### Produto suspeito é barrado

Acima de `PUBLISH_PRICE_CEILING`, um produto com marca no título (iPhone, Samsung,
PlayStation…) ou em categoria de risco **não é publicado**, e o motivo fica em
`social_posts.reason_code` (`RISK_HIGH_TICKET_BRAND` / `RISK_HIGH_TICKET_CATEGORY`).

A razão: a varredura de comissão alta trouxe a cauda de ticket alto, e é ali que se
concentra o anúncio de marca que pode não ser o que diz ser. A API da Shopee não dá sinal
para separar — não informa vendedor verificado nem histórico de loja, e a nota vem quase
sempre 5,00 sem contagem de avaliações.

Barrar é o lado seguro porque os dois erros não custam igual: publicar réplica no seu nome
é prejuízo que não se desfaz; não publicar é receita adiada. **Essa é a política decidida
(03/11/2026)**: o suspeito não é publicado e não vai para fila de aprovação. Se um produto
barrado interessar, o caminho é ajustar `PUBLISH_PRICE_CEILING` ou
`PUBLISH_BRAND_CATEGORIES` — uma decisão de política, registrada em configuração, e não uma
decisão por produto tomada no WhatsApp todo dia.

### Canal próprio na atribuição

O link do pin tem canal `pin`, não `ig`. Se reusasse o link do Instagram, o clique do
Pinterest entraria como Instagram e a CVR por canal viraria ficção. O pin aponta para o
nosso `/go/{sub_id}` — é ele que conta o clique e mantém a URL com o id de afiliado fora de
página indexável (Termos 4.3(k)).

A divulgação de afiliado é acrescentada pelo código e tem **orçamento reservado antes** do
truncamento da legenda: numa descrição de 800 caracteres, o que estoura é o fim do texto —
que é exatamente onde a divulgação ficaria. Post sem divulgação é problema de lei e de
termos, não de estética.

## 7.5 Campanhas no Pinterest Ads (workflow 03, `ads/create`)

O caminho de criação é o mesmo de sempre — `AdsGateway`, `BudgetGuard`, autonomia 4,
campanha **sempre PAUSED**. O que muda com `MOCK_ADS=false` e `ADS_PROVIDER=pinterest` é
quem fala com a rede. **Nenhum endpoint ativa campanha**: depois de criada, ligar é um clique
seu no Gerenciador de Anúncios do Pinterest.

### O que cada peça vira

| MP | Pinterest | Observação |
|---|---|---|
| campanha | campaign, `CONSIDERATION` | otimiza por clique |
| conjunto | ad group, `CLICKTHROUGH`, orçamento diário, lance máximo | |
| anúncio | ad `REGULAR` que **promove um pin** | o pin precisa estar PUBLICADO (§7.4) |

**Por que `CONSIDERATION` e não `WEB_CONVERSION`:** otimizar por conversão exige a tag do
Pinterest na página de destino, que é a Shopee — não temos como instalá-la. A venda continua
vindo do relatório da Shopee, atribuída pelo sub_id.

### O lance não é livre

A API exige um lance máximo por clique nesse objetivo. O MP usa o **menor** entre
`PINTEREST_ADS_MAX_CPC` e o piso de receita por clique do produto (`comissão × CVR do quantil
10%`, o mesmo corte que o EV usa para decidir cortar). Em palavras: **nunca se paga por clique
mais do que o pior cenário plausível do produto rende.** Produto sem EV, ou cujo piso não
sustenta lance nenhum, não ganha anúncio.

### Quem recebe campanha

Só produto com **pin publicado** no canal `pin`. Isso herda o guarda de réplica de graça: o
produto que o §7.4 barrou não tem pin, logo não tem anúncio. O resultado da execução traz
`skipped` com o motivo de cada produto pulado ("sem pin publicado", "sem EV calculado"…).

O anúncio tem **destino próprio**, um link `/go/` de canal `pinads`. Sem isso o clique pago
herdaria o link do pin e entraria como orgânico (`pin`).

### Antes do primeiro real

1. **Escopos.** Reautorize o app com `ads:read` e `ads:write` e semeie o refresh token de novo.
2. **Conta de anúncios** em BRL, com cartão. Anote o id numérico em `PINTEREST_AD_ACCOUNT_ID`.
3. **Segmentação não foi exercitada contra a API real.** O MP envia `GEO: ["BR"]` e
   `LOCALE: ["pt"]`, mas a especificação traz exemplos contraditórios para `LOCATION`/`GEO`.
   Como tudo nasce PAUSED, um formato errado aparece como `FAILED_PROVIDER` na primeira
   criação, sem gastar nada. A correção é uma linha em `targeting_spec()`.
4. **Pin em sandbox.** No Trial access o pin criado pela API é sandbox (visível só a você).
   Se o Pinterest recusar promover um pin sandbox, o motivo aparece nos avisos da execução.
5. **Teto diário** também no painel do Pinterest, além do `BudgetGuard`: redundância barata.

### Falha no meio da criação

Se a campanha foi criada mas o grupo ou o anúncio falhou, ela existe no Pinterest **pausada e
sem gasto**, mas não há linha no MP. O alerta `CAMPAIGN_ORPHANED` traz o id externo: apague-a
no Gerenciador. Erro de token, limite de taxa, rede fora ou conta em moeda errada
**interrompem o lote** (são fatais); recusa de um item (lance abaixo do mínimo, pin não
promovível) só pula aquele produto.

### Sobre gastar agora

O EV hoje é **modelado, não medido** — não há clique real no sistema. Pagar tráfego antes de
ter CVR medida é comprar o dado ao preço mais alto. A ordem barata é orgânico primeiro,
algumas centenas de cliques, e o pago só nos produtos com CVR medida.

## 8. O que ainda não existe

- **Leitura do Instagram** (alcance, salvamentos): ainda não existe, então o orgânico tem
  clique e venda medidos, mas não impressão — e portanto não tem CTR.
- **Publicação no Instagram:** continua manual. O Pinterest publica o que você aprova (§7.4); o
  Instagram depende da Graph API, que exige conta business e revisão de app própria.
- **Anúncio real:** o adapter do Pinterest Ads existe e é coberto por testes com HTTP simulado
  (§7.5), mas **nunca falou com a API real** — a primeira criação é o teste de verdade, e
  nasce PAUSED. O adapter do Meta continua dependendo do UNKNOWN-7.
- **Shopee real:** produtos e conversões foram validados contra a API real (somente leitura).
  Ainda **não** exercitados de verdade: `generateShortLink` (a mutation bate com o schema por
  introspecção, mas nunca foi executada — rode o teste de fumaça com `--short-link`) e o
  `validatedReport` (precisa de um `validationId` real do painel).
- **Troca de criativo:** o motor recomenda ("manter o produto e trocar o criativo"), mas não
  há geração de criativo para executar isso.
- **Ajuste de orçamento pela IA (autonomia 5):** nada recomenda nem executa ainda.
