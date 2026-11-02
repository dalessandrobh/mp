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
| 01 Descoberta | a cada 6h | descobre → qualifica → pontua | próxima rodada refaz (idempotente) |
| 02 Promover | 05:00 | `QUALIFICATION` → `CANDIDATE` | idem; exige autonomia ≥ 2 |
| 07 Decisão da IA | 05:30 | analisa (RECOMMEND) → aplica o que a autonomia permite | recomendações ficam PENDING |
| 03 Links | 06:00 | gera `sub_id` + link p/ produtos em teste | exige autonomia ≥ 3 |
| 05 Campanhas | 06:30 | cria campanhas **PAUSED** (máx. 2 por execução) | `ABORTED` notifica; exige autonomia ≥ 4 |
| 06 Performance | a cada 4h | Insights + conversões → consolida → scores → snapshot | alerta de dado velho em 12h |
| 08 Alertas | a cada 1h | avalia regras, notifica só alerta **novo** | — |
| 00 Erro | quando qualquer um falha | notifica no seu webhook | — |

Cada chamada tem retry (3 tentativas, 5 s) e uma `Idempotency-Key` por execução: um retry
depois de resposta perdida devolve o resultado guardado em vez de repetir o efeito.

## 2. Subir devagar (nesta ordem)

O backend nasce no modo mais seguro. Cada degrau é uma variável em `deploy/.env.prod`;
depois de mudar, aplique com `docker compose -f deploy/docker-compose.prod.yml --env-file
deploy/.env.prod up -d backend`.

| Degrau | Variáveis | O que muda |
|---|---|---|
| 0 · inicial | `DRY_RUN=true`, `MOCK_*=true`, `AI_AUTONOMY_LEVEL=1` | workflows rodam, **nada é gravado**; dashboard vazio |
| 1 · dados mock | `DRY_RUN=false` | funil, performance e decisões gravam (dados fictícios) |
| 2 · autonomia | `AI_AUTONOMY_LEVEL=2…4` | 2 promove candidatos · 3 entra/sai do portfólio e gera links · 4 cria campanhas PAUSED |
| 3 · real | `MOCK_MARKETPLACE=false`, `MOCK_ADS=false` | **ainda não disponível**: depende dos adapters reais (Fase 9) e do UNKNOWN-7 (Meta) |

Mude **um degrau por vez** e olhe o dashboard (Visão geral → "Trilhos de segurança") antes
do próximo. Em nenhum nível a plataforma ativa campanha: isso é sempre manual no
Gerenciador de Anúncios do Meta.

Com `AI_AUTONOMY_LEVEL=1` a decisão continua possível, mas **só por você**: aprove em
Inteligência → "Aprovar e executar".

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
bash n8n/install.sh --notify-url <seu-webhook> --activate   # e reinicie o n8n
```

Enquanto os passos 2 e 3 não terminam, os workflows recebem 401 — e o workflow 00 avisa.

## 8. O que ainda não existe

- **Workflow 04 (geração de conteúdo):** o endpoint `/trigger/content/generate` não foi
  construído (depende da decisão sobre LLM, UNKNOWN-9). O workflow só será entregue com ele.
- **Adapters reais (Shopee e Meta):** o MP roda inteiro em mock. A Shopee está validada na
  documentação (Fase 9); o Meta depende do UNKNOWN-7.
- **Troca de criativo:** o motor recomenda ("manter o produto e trocar o criativo"), mas não
  há geração de criativo para executar isso.
- **Ajuste de orçamento pela IA (autonomia 5):** nada recomenda nem executa ainda.
