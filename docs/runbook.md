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
| 01 Descoberta | diário 03h | descobre 40 mais vendidos por categoria (~1000) → qualifica → pontua | próxima rodada refaz (idempotente) |
| 02 Promover | 05:00 | `QUALIFICATION` → `CANDIDATE` | idem; exige autonomia ≥ 2 |
| 07 Decisão da IA | 05:30 | analisa (RECOMMEND) → aplica o que a autonomia permite | recomendações ficam PENDING |
| 03 Links | 06:00 | gera `sub_id` + link p/ produtos em teste | exige autonomia ≥ 3 |
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

## 8. O que ainda não existe

- **Leitura do Instagram** (alcance, salvamentos): ainda não existe, então o orgânico tem
  clique e venda medidos, mas não impressão — e portanto não tem CTR.
- **Meta real:** o MP cria campanhas só em mock; o Meta depende do UNKNOWN-7.
- **Shopee real:** produtos e conversões foram validados contra a API real (somente leitura).
  Ainda **não** exercitados de verdade: `generateShortLink` (a mutation bate com o schema por
  introspecção, mas nunca foi executada — rode o teste de fumaça com `--short-link`) e o
  `validatedReport` (precisa de um `validationId` real do painel).
- **Troca de criativo:** o motor recomenda ("manter o produto e trocar o criativo"), mas não
  há geração de criativo para executar isso.
- **Ajuste de orçamento pela IA (autonomia 5):** nada recomenda nem executa ainda.
