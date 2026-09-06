# PLANNING.md — Affiliate Intelligence & Automation Platform

> Documento de **planejamento**. Nenhum código de aplicação foi escrito ainda.
> Conforme a instrução 33 do ARCHITECTURE.md, este arquivo aguarda **aprovação explícita**
> antes do início da Fase 1 de codificação.
>
> Status: **AGUARDANDO APROVAÇÃO**
> Branch: `claude/affiliate-automation-platform-tp21lt`

---

## 0. Sumário

1. [Análise da arquitetura e dependências](#1-analise-da-arquitetura-e-dependencias)
2. [Itens marcados como UNKNOWN (bloqueiam decisões)](#2-itens-marcados-como-unknown)
3. [Schema do banco de dados](#3-schema-do-banco-de-dados-postgresqlsupabase)
4. [Estrutura de pastas e arquitetura de serviços](#4-estrutura-de-pastas-e-arquitetura-de-servicos)
5. [Mapeamento de endpoints consumidos pelo n8n](#5-mapeamento-de-endpoints-para-o-n8n)
6. [Workflows n8n propostos](#6-workflows-n8n-propostos)
7. [Camada de segurança e guardrails](#7-camada-de-seguranca-e-guardrails)
8. [Motor de decisão — desenho algorítmico](#8-motor-de-decisao--desenho-algoritmico)
9. [Estratégia de testes](#9-estrategia-de-testes)
10. [Roadmap por fases](#10-roadmap-por-fases)
11. [Decisões que preciso que você aprove](#11-decisoes-que-preciso-que-voce-aprove)

---

## 1. Análise da arquitetura e dependências

### 1.1 O que o sistema realmente é

Não é um gerador de links. É um **sistema de controle em malha fechada** (closed-loop) sobre um
portfólio de ativos (produtos afiliados), com orçamento como recurso escasso:

```
                    ┌──────────────────────────────────────────────┐
                    │              n8n (orquestrador)              │
                    │  agenda, retry, fan-out, notificações        │
                    └───────────────┬──────────────────────────────┘
                                    │ HTTP (REST, autenticado)
                    ┌───────────────▼──────────────────────────────┐
                    │            FastAPI (cérebro + regras)        │
                    │  ┌────────────┐  ┌──────────────┐            │
                    │  │ Discovery  │  │  Scoring     │            │
                    │  ├────────────┤  ├──────────────┤            │
                    │  │ Portfolio  │  │  Decision    │            │
                    │  │ Manager    │◄─┤  Engine      │            │
                    │  ├────────────┤  ├──────────────┤            │
                    │  │ Tracking   │  │ Budget Guard │◄── choke   │
                    │  ├────────────┤  ├──────────────┤    point   │
                    │  │ Content    │  │ Ads Gateway  │◄── choke   │
                    │  └────────────┘  └──────────────┘    point   │
                    └───┬──────────────┬──────────────┬────────────┘
                        │              │              │
              ┌─────────▼───┐  ┌───────▼─────┐  ┌────▼──────────┐
              │ Marketplace │  │  Ads        │  │  LLM          │
              │ Adapter     │  │  Adapter    │  │  Adapter      │
              │ (Shopee/    │  │  (Meta)     │  │  (Claude/     │
              │  Mock)      │  │             │  │   Gemini)     │
              └─────────────┘  └─────────────┘  └───────────────┘
                        │
              ┌─────────▼────────────────────────────────────────┐
              │        PostgreSQL / Supabase (append-only logs)   │
              └──────────────────────────────────────────────────┘
                                    │
                       ┌────────────▼──────────────┐
                       │  React + Vite + Tailwind  │
                       └───────────────────────────┘
```

### 1.2 Grafo de dependências (ordem obrigatória de construção)

```
Config/Parâmetros ──┐
                    ├──► Marketplace Adapter ──► Discovery ──► Opportunity Score
Schema do banco ────┘                                                │
                                                                     ▼
Tracking (sub_id) ◄──────────────────────────────────────────── Candidatos
       │                                                             │
       │                                                             ▼
       │                                                        Portfólio (TEST)
       │                                                             │
       ▼                                                             ▼
Affiliate Links ────► Content/Creative ────► Ads Gateway (Meta, PAUSED)
       │                                              │
       │                                              ▼
       └──────────────► Ingestão de Performance ◄── Meta Insights (custo)
                                │
                                ├── Marketplace conversions (receita)
                                ▼
                        performance_daily
                                │
                                ▼
                        Performance Score
                                │
                                ▼
                        AI Decision Engine ──► ai_decisions (append-only)
                                │
                                ▼
                        Atualização do portfólio (loop fecha)
```

### 1.3 Dependência crítica nº 1 — atribuição por `sub_id`

**Este é o ponto de falha estrutural do projeto inteiro.**

O motor de decisão só funciona se conseguirmos casar, por produto:

- **custo** → vem do Meta Ads Insights (nível de ad/adset)
- **receita** → vem do relatório de conversões do marketplace (nível de `sub_id`)

Se o marketplace não devolver o `sub_id` no relatório de conversões, ou devolver com granularidade
insuficiente, **ROI por produto é impossível de calcular** e todo o portfólio degenera para decisões
baseadas apenas em CTR/CPC — o que o próprio documento proíbe (nunca fabricar métricas).

**Consequência de projeto:** todo registro de performance carrega `data_available` e
`attribution_confidence`. O motor de decisão **recusa-se a decidir** sobre um produto cujo dado de
receita não esteja disponível/confirmado — em vez de assumir receita zero. Ver §2 (UNKNOWN-3).

### 1.4 Dependência crítica nº 2 — latência e janelas de atribuição divergentes

Meta Insights e relatórios de comissão do marketplace têm latências e janelas diferentes
(o marketplace tipicamente confirma comissão só após o pedido sair do período de cancelamento).
Isso significa que **o ROI de hoje não é o ROI final de hoje**.

**Consequência de projeto:**

- `performance_daily` é **mutável por reprocessamento** (upsert por chave natural), mas cada
  reprocessamento gera uma linha em `performance_daily_revisions` (append-only).
- Existe o conceito de **maturidade do dado**: `settlement_status ∈ (PROVISIONAL, PARTIAL, SETTLED)`.
- `MIN_TEST_DURATION` deve ser medido em **dias com dado maduro**, não em dias corridos.
- O motor de decisão usa dados `SETTLED` para decisões de corte (REPLACE/PAUSE) e pode usar
  `PROVISIONAL` para decisões reversíveis (ajuste de orçamento).

### 1.5 Dependência crítica nº 3 — orçamento como recurso global compartilhado

`MAX_DAILY_AD_SPEND` é global, mas quem gasta é o Meta, de forma assíncrona e fora do nosso controle
transacional. Não conseguimos "reservar" gasto atomicamente no Meta.

**Consequência de projeto:**

- Mantemos um **`budget_ledger`** interno: toda alocação planejada gera um lançamento de *commitment*;
  toda leitura do Insights gera um lançamento de *actual*.
- O `BudgetGuard` valida contra `committed + actual`, não só contra o realizado.
- Como todas as campanhas nascem **PAUSED**, o risco de overspend automático é estruturalmente baixo —
  a proteção real é impedir que o sistema *crie* estrutura acima do teto e que recomende ativações
  cuja soma de daily budgets ultrapasse o teto.

### 1.6 Dependência crítica nº 4 — idempotência sob orquestração externa

O n8n faz retry. Um retry de "criar campanha" que não seja idempotente cria campanhas duplicadas no
Meta — dinheiro real.

**Consequência de projeto:** todo endpoint mutador exige header `Idempotency-Key`, gravado em
`idempotency_keys` com o hash do request e a resposta original. Além disso, `execution_locks`
impede duas execuções concorrentes do mesmo workflow.

### 1.7 Separação RECOMMEND × EXECUTE

Consta no documento (itens 25 e 27) e é adotada como regra transversal:

| Camada | Produz | Efeito colateral externo |
|---|---|---|
| `RECOMMEND` | linha em `ai_recommendations` | nenhum |
| `EXECUTE` | linha em `ai_decisions` + mutação | sim (interno e/ou externo) |

`AI_AUTONOMY_LEVEL` decide quais classes de recomendação podem ser auto-promovidas a execução.
**Ativar campanha no Meta nunca é auto-promovível, em nenhum nível.**

---

## 2. Itens marcados como UNKNOWN

Conforme a REGRA ABSOLUTA (item 34), estes pontos **não serão implementados por suposição**.
Tentei validar a documentação oficial da Shopee nesta sessão: `affiliate.shopee.com.br/open_api/home`
está **bloqueado pelo proxy de rede** deste ambiente e exige login de afiliado aprovado.
Portanto **não confirmei nada da API da Shopee em fonte oficial**.

| ID | Item | Status | Como resolver |
|---|---|---|---|
| **UNKNOWN-1** | Endpoint, protocolo (GraphQL vs REST) e schema da Shopee Affiliate Open API BR | **NÃO VALIDADO** | Você cola aqui a doc oficial (print/PDF/texto) do painel de afiliado |
| **UNKNOWN-2** | Esquema exato de assinatura (header `Authorization`, ordem de concatenação, tolerância de timestamp) | **NÃO VALIDADO** | Idem — fontes comunitárias sugerem SHA256 sobre `appid+timestamp+payload+secret`, mas **não trato isso como fato** |
| **UNKNOWN-3** | O relatório de conversões da Shopee devolve `sub_id`? Quantos slots? Com que latência? | **NÃO VALIDADO** | **Bloqueia o motor de decisão inteiro.** Prioridade máxima |
| **UNKNOWN-4** | Limites de charset/tamanho dos `sub_id` | **NÃO VALIDADO** | Define o formato final do tracking (§7.4) |
| **UNKNOWN-5** | Rate limits e paginação máxima da API de ofertas | **NÃO VALIDADO** | Define o throughput real do Discovery |
| **UNKNOWN-6** | Quais campos de demanda existem (vendas históricas, rating, estoque) | **NÃO VALIDADO** | Define quais componentes do Opportunity Score têm `data_available=true` |
| **UNKNOWN-7** | Versão da Meta Marketing API a fixar + permissões do token | **A CONFIRMAR** | Você informa `act_id`, versão e escopos do app |
| **UNKNOWN-8** | Fonte das métricas de Instagram (Graph API business account?) | **A CONFIRMAR** | Item 19 do documento cita Instagram; pode ficar fora da Fase 1 |
| **UNKNOWN-9** | Provedor de LLM e chave (Claude vs Gemini) | **A CONFIRMAR** | Adapter suporta ambos; default proposto: `NullLLMAdapter` |

**Regra de implementação:** o `ShopeeAdapter` nasce com a interface completa e os métodos
levantando `NotImplementedError("UNKNOWN-1: aguardando documentação oficial")`.
O `MockAdapter` fornece o dado para desenvolver tudo o mais em paralelo.
**Nenhum endpoint será inventado.**

---

## 3. Schema do banco de dados (PostgreSQL/Supabase)

### 3.1 Princípios

1. **Append-only para tudo que é decisão, score ou log.** Nada de `UPDATE` em histórico.
2. **Estado atual em tabela separada do histórico** (leitura rápida × auditoria completa).
3. `data_available BOOLEAN` + `data_source TEXT` em toda métrica que possa faltar. Sem `DEFAULT 0`.
4. `NUMERIC` para dinheiro (nunca `FLOAT`). Moeda explícita.
5. Toda tabela de fato tem chave natural com `UNIQUE` para permitir upsert idempotente.
6. `updated_at`/`created_at` em `TIMESTAMPTZ` (UTC). Datas de negócio em `DATE` com timezone de
   referência configurável (`America/Sao_Paulo`).

### 3.2 Enums

```sql
CREATE TYPE product_state AS ENUM (
  'DISCOVERY','QUALIFICATION','CANDIDATE','TEST','ACTIVE','WINNER',
  'REJECTED','PAUSED','UNDER_REVIEW','REPLACED','EXPIRED'
);

CREATE TYPE portfolio_tier AS ENUM ('EXPLORATION','EXPLOITATION');

CREATE TYPE decision_type AS ENUM (
  'PROMOTE','KEEP','REPLACE','PAUSE','RESUME','INCREASE_BUDGET',
  'DECREASE_BUDGET','REJECT','RESIZE_PORTFOLIO','ADJUST_PARAMETER','NO_ACTION'
);

CREATE TYPE decision_mode AS ENUM ('RECOMMEND','EXECUTE');

CREATE TYPE settlement_status AS ENUM ('PROVISIONAL','PARTIAL','SETTLED');

CREATE TYPE campaign_review_status AS ENUM ('UNREVIEWED','APPROVED','REJECTED','ARCHIVED');

CREATE TYPE run_status AS ENUM ('RUNNING','SUCCESS','FAILED','ABORTED','SKIPPED');
```

### 3.3 Tabelas — visão geral

| Grupo | Tabelas |
|---|---|
| Catálogo | `marketplaces`, `products`, `product_snapshots` |
| Funil | `product_state_transitions`, `product_current_state` (view materializada ou tabela) |
| Scoring | `opportunity_scores`, `performance_scores` |
| Portfólio | `portfolio_products`, `portfolio_snapshots` |
| Tracking | `affiliate_links`, `tracking_subids` |
| Conteúdo | `creatives` |
| Ads | `campaigns`, `ad_sets`, `ads` |
| Métricas | `ad_metrics_raw`, `conversions_raw`, `performance_daily`, `performance_daily_revisions` |
| IA | `ai_recommendations`, `ai_decisions`, `llm_calls` |
| Controle | `config_parameters`, `config_parameter_history`, `budget_ledger`, `alerts`, `audit_logs`, `workflow_runs`, `idempotency_keys`, `execution_locks`, `simulations` |

### 3.4 DDL proposto (esboço — sujeito à sua aprovação)

```sql
-- ============ CATÁLOGO ============

-- Cada marketplace integrado. Config não-secreta em JSONB; segredos só em env/Vault.
CREATE TABLE marketplaces (
  id             SMALLSERIAL PRIMARY KEY,
  code           TEXT NOT NULL UNIQUE,          -- 'shopee_br', 'amazon_br', 'mock'
  display_name   TEXT NOT NULL,
  currency       CHAR(3) NOT NULL DEFAULT 'BRL',
  is_active      BOOLEAN NOT NULL DEFAULT TRUE,
  adapter_class  TEXT NOT NULL,                 -- resolve o adapter em runtime
  config         JSONB NOT NULL DEFAULT '{}',   -- NUNCA credenciais
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Produto canônico. Identidade = (marketplace, id externo).
CREATE TABLE products (
  id                  BIGSERIAL PRIMARY KEY,
  marketplace_id      SMALLINT NOT NULL REFERENCES marketplaces(id),
  external_product_id TEXT NOT NULL,
  external_shop_id    TEXT,
  title               TEXT NOT NULL,
  category_path       TEXT[],
  product_url         TEXT NOT NULL,
  image_url           TEXT,
  first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  raw_payload         JSONB,                    -- resposta bruta da API, para auditoria
  UNIQUE (marketplace_id, external_product_id)
);

-- Histórico append-only de preço/comissão. Preço muda; decisão passada precisa do preço da época.
CREATE TABLE product_snapshots (
  id                 BIGSERIAL PRIMARY KEY,
  product_id         BIGINT NOT NULL REFERENCES products(id),
  captured_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  price              NUMERIC(14,2),
  original_price     NUMERIC(14,2),
  commission_rate    NUMERIC(7,4),              -- fração: 0.0850 = 8,5%
  commission_value   NUMERIC(14,2),
  rating             NUMERIC(3,2),
  rating_count       INTEGER,
  sales_volume       INTEGER,
  stock              INTEGER,
  data_available     JSONB NOT NULL DEFAULT '{}', -- {"sales_volume": false, ...}
  raw_payload        JSONB
);
CREATE INDEX ON product_snapshots (product_id, captured_at DESC);

-- ============ FUNIL (máquina de estados) ============

-- Append-only. A verdade sobre "por que este produto está aqui".
CREATE TABLE product_state_transitions (
  id            BIGSERIAL PRIMARY KEY,
  product_id    BIGINT NOT NULL REFERENCES products(id),
  from_state    product_state,                 -- NULL na primeira entrada
  to_state      product_state NOT NULL,
  reason_code   TEXT NOT NULL,                 -- 'LOW_OPPORTUNITY_SCORE', 'ROI_NEGATIVE_3D', ...
  reason_detail TEXT,
  decision_id   BIGINT,                        -- FK -> ai_decisions (quando veio da IA)
  actor         TEXT NOT NULL,                 -- 'ai_engine' | 'human:<email>' | 'system'
  metrics_used  JSONB,                         -- snapshot dos números que justificaram
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON product_state_transitions (product_id, created_at DESC);

-- Estado corrente desnormalizado (leitura rápida do dashboard). Mantido por trigger/serviço.
CREATE TABLE product_current_state (
  product_id      BIGINT PRIMARY KEY REFERENCES products(id),
  state           product_state NOT NULL,
  since           TIMESTAMPTZ NOT NULL,
  last_transition BIGINT REFERENCES product_state_transitions(id)
);

-- ============ SCORING ============

-- Append-only e versionado: o score de ontem não é reescrito pelo de hoje.
CREATE TABLE opportunity_scores (
  id                BIGSERIAL PRIMARY KEY,
  product_id        BIGINT NOT NULL REFERENCES products(id),
  score             NUMERIC(6,3) NOT NULL,        -- 0..100
  algorithm_version TEXT NOT NULL,                -- 'opp_v1'
  components        JSONB NOT NULL,               -- {"demand":{"value":..,"weight":..,"available":true}}
  data_available    BOOLEAN NOT NULL,             -- false => score é indicativo, não decisório
  missing_fields    TEXT[] NOT NULL DEFAULT '{}',
  llm_used          BOOLEAN NOT NULL DEFAULT FALSE,
  llm_call_id       BIGINT,
  computed_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON opportunity_scores (product_id, computed_at DESC);

CREATE TABLE performance_scores (
  id                BIGSERIAL PRIMARY KEY,
  product_id        BIGINT NOT NULL REFERENCES products(id),
  window_days       SMALLINT NOT NULL,            -- 3, 7, 14
  score             NUMERIC(6,3),
  algorithm_version TEXT NOT NULL,
  components        JSONB NOT NULL,               -- ctr, cpc, cvr, roi, roas, epc, stability
  data_available    BOOLEAN NOT NULL,
  sample_sufficient BOOLEAN NOT NULL,             -- passou MIN_CLICKS / MIN_IMPRESSIONS?
  settlement        settlement_status NOT NULL,
  computed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (product_id, window_days, computed_at)
);

-- ============ PORTFÓLIO ============

CREATE TABLE portfolio_products (
  id                 BIGSERIAL PRIMARY KEY,
  product_id         BIGINT NOT NULL REFERENCES products(id),
  tier               portfolio_tier NOT NULL,
  entered_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  exited_at          TIMESTAMPTZ,                 -- NULL = ativo
  exit_reason_code   TEXT,
  allocated_daily_budget NUMERIC(12,2) NOT NULL DEFAULT 0,
  priority_weight    NUMERIC(6,3) NOT NULL DEFAULT 1.0,
  entry_decision_id  BIGINT,
  exit_decision_id   BIGINT
);
-- Um produto só pode estar ativo uma vez no portfólio.
CREATE UNIQUE INDEX ON portfolio_products (product_id) WHERE exited_at IS NULL;

-- Fotografia diária do portfólio para gráficos históricos.
CREATE TABLE portfolio_snapshots (
  snapshot_date       DATE PRIMARY KEY,
  active_count        INTEGER NOT NULL,
  exploration_count   INTEGER NOT NULL,
  exploitation_count  INTEGER NOT NULL,
  winner_count        INTEGER NOT NULL,
  total_daily_budget  NUMERIC(12,2) NOT NULL,
  recommended_size    INTEGER,
  sizing_rationale    JSONB,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============ TRACKING ============

CREATE TABLE affiliate_links (
  id             BIGSERIAL PRIMARY KEY,
  product_id     BIGINT NOT NULL REFERENCES products(id),
  campaign_id    BIGINT,
  creative_id    BIGINT,
  channel        TEXT NOT NULL,                  -- 'meta_ads','instagram_bio','whatsapp',...
  sub_id         TEXT NOT NULL UNIQUE,           -- ver §7.4 (formato depende de UNKNOWN-4)
  utm_source     TEXT, utm_medium TEXT, utm_campaign TEXT,
  utm_content    TEXT, utm_term TEXT,
  short_url      TEXT,
  raw_url        TEXT NOT NULL,
  generated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  revoked_at     TIMESTAMPTZ
);
CREATE INDEX ON affiliate_links (product_id) WHERE revoked_at IS NULL;

-- ============ CONTEÚDO ============

CREATE TABLE creatives (
  id             BIGSERIAL PRIMARY KEY,
  product_id     BIGINT NOT NULL REFERENCES products(id),
  format         TEXT NOT NULL,                  -- 'image_single','carousel','video'
  headline       TEXT, primary_text TEXT, description TEXT, call_to_action TEXT,
  asset_urls     TEXT[],
  generated_by   TEXT NOT NULL,                  -- 'llm:claude-...' | 'template' | 'human'
  llm_call_id    BIGINT,
  approved_by    TEXT, approved_at TIMESTAMPTZ,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============ ADS ============

CREATE TABLE campaigns (
  id                  BIGSERIAL PRIMARY KEY,
  external_id         TEXT UNIQUE,               -- id no Meta
  platform            TEXT NOT NULL DEFAULT 'meta',
  ad_account_id       TEXT NOT NULL,
  name                TEXT NOT NULL,
  objective           TEXT NOT NULL,
  status              TEXT NOT NULL,             -- espelho do Meta; criado sempre 'PAUSED'
  created_paused      BOOLEAN NOT NULL DEFAULT TRUE,
  review_status       campaign_review_status NOT NULL DEFAULT 'UNREVIEWED',
  reviewed_by         TEXT, reviewed_at TIMESTAMPTZ,
  daily_budget        NUMERIC(12,2),
  created_by_run_id   BIGINT,
  dry_run             BOOLEAN NOT NULL DEFAULT FALSE,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- Invariante de segurança gravada no schema, não só no código.
  CONSTRAINT campaigns_must_be_created_paused CHECK (created_paused = TRUE)
);

CREATE TABLE ad_sets (
  id            BIGSERIAL PRIMARY KEY,
  campaign_id   BIGINT NOT NULL REFERENCES campaigns(id),
  external_id   TEXT UNIQUE,
  name          TEXT NOT NULL,
  status        TEXT NOT NULL,
  daily_budget  NUMERIC(12,2),
  targeting     JSONB,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ads (
  id             BIGSERIAL PRIMARY KEY,
  ad_set_id      BIGINT NOT NULL REFERENCES ad_sets(id),
  product_id     BIGINT NOT NULL REFERENCES products(id),
  creative_id    BIGINT REFERENCES creatives(id),
  affiliate_link_id BIGINT REFERENCES affiliate_links(id),
  external_id    TEXT UNIQUE,
  status         TEXT NOT NULL,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============ MÉTRICAS ============

-- Ingestão bruta, append-only. Nunca agregamos por cima do bruto sem guardá-lo.
CREATE TABLE ad_metrics_raw (
  id             BIGSERIAL PRIMARY KEY,
  source         TEXT NOT NULL,                  -- 'meta_insights'
  metric_date    DATE NOT NULL,
  external_ad_id TEXT,
  payload        JSONB NOT NULL,
  ingested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source, metric_date, external_ad_id, ingested_at)
);

CREATE TABLE conversions_raw (
  id               BIGSERIAL PRIMARY KEY,
  marketplace_id   SMALLINT NOT NULL REFERENCES marketplaces(id),
  external_order_id TEXT,
  sub_id           TEXT,                         -- pode vir NULL -> não atribuível
  conversion_date  DATE,
  commission_value NUMERIC(14,2),
  order_value      NUMERIC(14,2),
  status           TEXT,                         -- status do pedido conforme marketplace
  payload          JSONB NOT NULL,
  ingested_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (marketplace_id, external_order_id, sub_id)
);
CREATE INDEX ON conversions_raw (sub_id, conversion_date);

-- Fato consolidado. Upsert por chave natural; toda revisão é registrada.
CREATE TABLE performance_daily (
  id                BIGSERIAL PRIMARY KEY,
  metric_date       DATE NOT NULL,
  product_id        BIGINT NOT NULL REFERENCES products(id),
  campaign_id       BIGINT REFERENCES campaigns(id),
  channel           TEXT NOT NULL,
  impressions       BIGINT,
  clicks            BIGINT,
  ad_spend          NUMERIC(14,2),
  conversions       INTEGER,
  revenue           NUMERIC(14,2),               -- comissão bruta
  profit            NUMERIC(14,2),               -- revenue - ad_spend
  ctr               NUMERIC(8,5),
  cpc               NUMERIC(12,4),
  cvr               NUMERIC(8,5),
  roi               NUMERIC(10,4),
  roas              NUMERIC(10,4),
  epc               NUMERIC(12,4),
  cost_data_available    BOOLEAN NOT NULL DEFAULT FALSE,
  revenue_data_available BOOLEAN NOT NULL DEFAULT FALSE,
  settlement        settlement_status NOT NULL DEFAULT 'PROVISIONAL',
  computed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (metric_date, product_id, campaign_id, channel)
);
CREATE INDEX ON performance_daily (product_id, metric_date DESC);

-- Auditoria de reprocessamento (o ROI de ontem mudou? aqui está o antes).
CREATE TABLE performance_daily_revisions (
  id                   BIGSERIAL PRIMARY KEY,
  performance_daily_id BIGINT NOT NULL REFERENCES performance_daily(id),
  previous_values      JSONB NOT NULL,
  new_values           JSONB NOT NULL,
  reason               TEXT NOT NULL,
  revised_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============ IA ============

CREATE TABLE ai_recommendations (
  id              BIGSERIAL PRIMARY KEY,
  run_id          BIGINT,
  decision_type   decision_type NOT NULL,
  subject_type    TEXT NOT NULL,                 -- 'product','portfolio','parameter','campaign'
  subject_id      TEXT,
  rationale       JSONB NOT NULL,                -- O QUE / POR QUE / DADOS USADOS
  confidence      NUMERIC(4,3),
  expected_impact JSONB,
  status          TEXT NOT NULL DEFAULT 'PENDING', -- PENDING|APPROVED|REJECTED|EXPIRED|EXECUTED
  reviewed_by     TEXT, reviewed_at TIMESTAMPTZ,
  executed_decision_id BIGINT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Append-only. Nunca UPDATE, nunca DELETE.
CREATE TABLE ai_decisions (
  id                 BIGSERIAL PRIMARY KEY,
  run_id             BIGINT,
  recommendation_id  BIGINT REFERENCES ai_recommendations(id),
  mode               decision_mode NOT NULL,
  decision_type      decision_type NOT NULL,
  autonomy_level     SMALLINT NOT NULL,
  dry_run            BOOLEAN NOT NULL DEFAULT FALSE,
  subject_type       TEXT NOT NULL,
  product_in         BIGINT REFERENCES products(id),   -- quem entrou
  product_out        BIGINT REFERENCES products(id),   -- quem saiu
  payload            JSONB NOT NULL,   -- {what, why, data_used, thresholds, alternatives, diagnosis}
  engine_version     TEXT NOT NULL,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON ai_decisions (created_at DESC);

-- Toda chamada de LLM registrada: custo, prompt, resposta, para auditoria e reprodutibilidade.
CREATE TABLE llm_calls (
  id            BIGSERIAL PRIMARY KEY,
  purpose       TEXT NOT NULL,                  -- 'opportunity_qualitative','creative_copy'
  provider      TEXT NOT NULL, model TEXT NOT NULL,
  prompt        TEXT NOT NULL, response TEXT,
  input_tokens  INTEGER, output_tokens INTEGER, cost_usd NUMERIC(10,6),
  latency_ms    INTEGER, success BOOLEAN NOT NULL,
  error         TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============ CONTROLE ============

-- Parâmetros vivos, editáveis pelo dashboard e recomendáveis pela IA.
CREATE TABLE config_parameters (
  key           TEXT PRIMARY KEY,               -- 'MAX_DAILY_AD_SPEND'
  value         JSONB NOT NULL,
  value_type    TEXT NOT NULL,                  -- 'int','decimal','bool','enum'
  min_value     JSONB, max_value JSONB,         -- limites duros; IA não pode ultrapassar
  description   TEXT NOT NULL,
  ai_adjustable BOOLEAN NOT NULL DEFAULT FALSE, -- IA pode recomendar mudança?
  updated_by    TEXT NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE config_parameter_history (
  id          BIGSERIAL PRIMARY KEY,
  key         TEXT NOT NULL,
  old_value   JSONB, new_value JSONB NOT NULL,
  changed_by  TEXT NOT NULL, decision_id BIGINT REFERENCES ai_decisions(id),
  changed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Razão contábil do orçamento: compromissos planejados + gasto real.
CREATE TABLE budget_ledger (
  id            BIGSERIAL PRIMARY KEY,
  ledger_date   DATE NOT NULL,
  entry_type    TEXT NOT NULL,                  -- 'COMMITMENT'|'ACTUAL'|'RELEASE'
  scope         TEXT NOT NULL,                  -- 'GLOBAL'|'EXPLORATION'|'EXPLOITATION'
  product_id    BIGINT REFERENCES products(id),
  campaign_id   BIGINT REFERENCES campaigns(id),
  amount        NUMERIC(14,2) NOT NULL,
  decision_id   BIGINT REFERENCES ai_decisions(id),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON budget_ledger (ledger_date, scope);

CREATE TABLE alerts (
  id            BIGSERIAL PRIMARY KEY,
  severity      TEXT NOT NULL,                  -- 'INFO','WARNING','CRITICAL','ABORT'
  code          TEXT NOT NULL,                  -- 'ROI_NEGATIVE_3D','UNREVIEWED_LIMIT'
  subject_type  TEXT, subject_id TEXT,
  message       TEXT NOT NULL, details JSONB,
  acknowledged_by TEXT, acknowledged_at TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE audit_logs (
  id           BIGSERIAL PRIMARY KEY,
  actor        TEXT NOT NULL,
  action       TEXT NOT NULL,
  entity_type  TEXT NOT NULL, entity_id TEXT,
  before       JSONB, after JSONB,
  request_id   TEXT, ip_address INET,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Uma linha por execução de workflow do n8n. Base de observabilidade.
CREATE TABLE workflow_runs (
  id             BIGSERIAL PRIMARY KEY,
  workflow_name  TEXT NOT NULL,
  n8n_execution_id TEXT,
  status         run_status NOT NULL DEFAULT 'RUNNING',
  dry_run        BOOLEAN NOT NULL DEFAULT FALSE,
  started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at    TIMESTAMPTZ,
  items_processed INTEGER, error TEXT, summary JSONB
);

-- Proteção contra retry do n8n criando efeitos duplicados.
CREATE TABLE idempotency_keys (
  key            TEXT PRIMARY KEY,
  endpoint       TEXT NOT NULL,
  request_hash   TEXT NOT NULL,
  response_body  JSONB,
  status_code    INTEGER,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at     TIMESTAMPTZ NOT NULL
);

-- Proteção contra execuções concorrentes do mesmo workflow.
CREATE TABLE execution_locks (
  lock_name    TEXT PRIMARY KEY,
  acquired_by  TEXT NOT NULL,
  acquired_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at   TIMESTAMPTZ NOT NULL
);

CREATE TABLE simulations (
  id           BIGSERIAL PRIMARY KEY,
  inputs       JSONB NOT NULL,
  outputs      JSONB NOT NULL,
  assumptions  JSONB NOT NULL,   -- explicita que são ESTIMATIVAS
  created_by   TEXT NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 3.5 Segurança no Supabase

- **RLS habilitado em todas as tabelas, com política padrão `DENY`** para `anon` e `authenticated`.
- O backend FastAPI acessa via **connection string direta com role dedicada** (`app_backend`),
  não via `service_role` key do PostgREST.
- O frontend **nunca** fala com o Postgres diretamente. Só com o FastAPI.
- Supabase Auth é usado apenas para login do dashboard; o FastAPI valida o JWT.
- `REVOKE UPDATE, DELETE` nas tabelas append-only (`ai_decisions`, `product_state_transitions`,
  `audit_logs`, `*_raw`) para a role da aplicação — a imutabilidade vira garantia do banco.

---

## 4. Estrutura de pastas e arquitetura de serviços

```
mp/
├── ARCHITECTURE.md
├── PLANNING.md
├── README.md
├── docker-compose.yml               # postgres local, n8n local, backend, frontend
├── .env.example                     # TODAS as variáveis, sem valores reais
│
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── migrations/                  # Alembic (versionamento do schema)
│   └── app/
│       ├── main.py                  # cria a app, monta routers, middlewares
│       ├── core/
│       │   ├── config.py            # Pydantic Settings; lê .env; valida na subida
│       │   ├── security.py          # auth do n8n (API key) + JWT do dashboard
│       │   ├── logging.py           # log estruturado JSON com request_id
│       │   ├── idempotency.py       # dependency de Idempotency-Key
│       │   ├── locks.py             # execution_locks
│       │   └── exceptions.py
│       ├── db/
│       │   ├── session.py
│       │   └── base.py
│       ├── models/                  # SQLAlchemy (1 arquivo por grupo do §3.3)
│       ├── schemas/                 # Pydantic (request/response)
│       ├── repositories/            # acesso a dados; sem regra de negócio
│       ├── domain/
│       │   ├── enums.py
│       │   ├── state_machine.py     # transições legais do funil; nada muda estado sem passar aqui
│       │   └── formulas.py          # ROI, ROAS, EPC, CTR — funções puras, testáveis
│       ├── services/
│       │   ├── discovery_service.py
│       │   ├── qualification_service.py
│       │   ├── opportunity_scoring.py
│       │   ├── performance_scoring.py
│       │   ├── portfolio_service.py
│       │   ├── portfolio_sizer.py        # calculateOptimalPortfolioSize()
│       │   ├── decision_engine.py        # o cérebro
│       │   ├── replacement_service.py    # diagnóstico + substituição inteligente
│       │   ├── budget_guard.py           # CHOKE POINT de orçamento
│       │   ├── ads_gateway.py            # CHOKE POINT de criação de campanha
│       │   ├── tracking_service.py       # sub_id / UTM
│       │   ├── content_service.py
│       │   ├── ingestion_service.py      # raw -> performance_daily
│       │   ├── alert_service.py
│       │   └── simulator_service.py
│       ├── adapters/
│       │   ├── marketplace/
│       │   │   ├── base.py               # MarketplaceAdapter (ABC)
│       │   │   ├── registry.py           # code -> classe
│       │   │   ├── mock/adapter.py       # MOCK_MARKETPLACE=true
│       │   │   ├── shopee/
│       │   │   │   ├── adapter.py        # ShopeeAdapter
│       │   │   │   ├── auth.py           # assinatura HMAC/SHA256 (UNKNOWN-2)
│       │   │   │   └── mapping.py        # payload externo -> modelo canônico
│       │   │   ├── amazon/               # placeholder, NotImplementedError
│       │   │   └── mercadolivre/         # placeholder, NotImplementedError
│       │   ├── ads/
│       │   │   ├── base.py               # AdsAdapter (ABC)
│       │   │   ├── meta/adapter.py
│       │   │   └── mock/adapter.py
│       │   └── llm/
│       │       ├── base.py               # LLMAdapter (ABC)
│       │       ├── anthropic_adapter.py
│       │       ├── gemini_adapter.py
│       │       └── null_adapter.py       # default: não chama LLM nenhum
│       └── api/v1/
│           ├── router.py
│           └── routes/
│               ├── health.py     ├── discovery.py   ├── products.py
│               ├── portfolio.py  ├── decisions.py   ├── links.py
│               ├── content.py    ├── ads.py         ├── performance.py
│               ├── alerts.py     ├── config.py      ├── simulator.py
│               └── dashboard.py
│
├── frontend/
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   └── src/
│       ├── main.tsx, App.tsx, routes.tsx
│       ├── lib/{api.ts,queryClient.ts,format.ts}
│       ├── types/api.ts               # gerado do OpenAPI do FastAPI
│       ├── components/ui/             # botões, tabelas, cards, badges
│       ├── features/
│       │   ├── overview/              # KPIs gerais
│       │   ├── financial/             # receita, custo, lucro, ROI/ROAS
│       │   ├── portfolio/             # tabela do funil, estados, tiers
│       │   ├── products/              # detalhe + histórico de estados
│       │   ├── intelligence/          # recomendações da IA + aprovar/rejeitar
│       │   ├── campaigns/             # fila UNREVIEWED, revisão manual
│       │   ├── simulator/
│       │   ├── config/                # parâmetros e autonomia
│       │   └── alerts/
│       └── hooks/
│
├── n8n/workflows/                     # .json prontos para importar
│   ├── 01_discovery.json              ├── 02_portfolio_manager.json
│   ├── 03_affiliate_links.json        ├── 04_content_generation.json
│   ├── 05_meta_ads_creation.json      ├── 06_performance_sync.json
│   ├── 07_ai_decision_cycle.json      └── 08_alerts_monitor.json
│
└── docs/
    ├── shopee_api_notes.md            # o que foi CONFIRMADO vs UNKNOWN
    ├── tracking_spec.md
    ├── decision_engine_spec.md
    └── runbook.md
```

### 4.1 Regras arquiteturais que serão respeitadas no código

1. **Routers não contêm regra de negócio.** Só validam entrada, chamam serviço, formatam saída.
2. **Serviços não conhecem HTTP.** Recebem e devolvem objetos de domínio.
3. **Adapters não conhecem o banco.** Devolvem dataclasses canônicas.
4. **Nada muda estado de produto fora de `state_machine.py`.**
5. **Nada cria estrutura no Meta fora de `ads_gateway.py`.**
6. **Nada aloca orçamento fora de `budget_guard.py`.**
7. **Comentários curtos e diretos**, focados no *porquê* da regra de negócio (item 35).

---

## 5. Mapeamento de endpoints para o n8n

Convenções:

- Prefixo: `/api/v1`
- Auth n8n: header `X-API-Key` (chave de serviço, distinta do JWT do dashboard)
- Mutadores exigem `Idempotency-Key`
- Todos aceitam `?dry_run=true` (ou herdam `DRY_RUN` global)
- Resposta padrão: `{ run_id, status, dry_run, summary, items, warnings[] }`

### 5.1 Endpoints de gatilho (consumidos pelo n8n)

| # | Método | Rota | Workflow | Efeito | Idempotente |
|---|---|---|---|---|---|
| 1 | POST | `/trigger/discovery` | 01 | Busca produtos no marketplace → `DISCOVERY` | sim |
| 2 | POST | `/trigger/qualification` | 01 | Aplica filtros duros → `QUALIFICATION`/`REJECTED` | sim |
| 3 | POST | `/trigger/scoring/opportunity` | 01 | Calcula Opportunity Score | sim |
| 4 | POST | `/trigger/candidates/promote` | 02 | `QUALIFICATION` → `CANDIDATE` | sim |
| 5 | POST | `/portfolio/analyze` | 07 | Roda o Decision Engine (modo RECOMMEND) | sim |
| 6 | POST | `/portfolio/apply` | 07 | Executa recomendações permitidas pela autonomia | **exige key** |
| 7 | POST | `/trigger/links/generate` | 03 | Gera `sub_id` + link afiliado para produtos em TEST/ACTIVE | **exige key** |
| 8 | POST | `/trigger/content/generate` | 04 | Gera criativos (LLM opcional) | **exige key** |
| 9 | POST | `/trigger/ads/create` | 05 | Cria Campaign/AdSet/Ad **PAUSED** no Meta | **exige key** |
| 10 | POST | `/trigger/performance/sync` | 06 | Puxa Meta Insights + conversões do marketplace | sim |
| 11 | POST | `/trigger/performance/consolidate` | 06 | `*_raw` → `performance_daily` + scores | sim |
| 12 | POST | `/trigger/alerts/evaluate` | 08 | Avalia regras (ROI<0 3d, UNREVIEWED>10, budget) | sim |
| 13 | POST | `/trigger/portfolio/snapshot` | 06 | Grava `portfolio_snapshots` do dia | sim |

### 5.2 Endpoints de leitura (n8n + dashboard)

| Método | Rota | Uso |
|---|---|---|
| GET | `/health` | liveness do n8n |
| GET | `/health/ready` | checa DB + credenciais configuradas |
| GET | `/products` | lista com filtros (`state`, `marketplace`, `min_score`) |
| GET | `/products/{id}` | detalhe + snapshots + histórico de estados |
| GET | `/products/{id}/timeline` | transições + decisões |
| GET | `/portfolio` | portfólio ativo, tiers, orçamento alocado |
| GET | `/portfolio/sizing` | `calculateOptimalPortfolioSize()` (**RECOMMEND**, não executa) |
| GET | `/portfolio/capacity` | capacidade de teste dado o orçamento |
| GET | `/decisions` | histórico de `ai_decisions` |
| GET | `/recommendations` | recomendações pendentes |
| GET | `/performance/daily` | série temporal |
| GET | `/performance/summary` | KPIs consolidados |
| GET | `/campaigns?review_status=UNREVIEWED` | fila de revisão manual |
| GET | `/budget/status` | teto, comprometido, realizado, disponível |
| GET | `/alerts` | alertas abertos |
| GET | `/config` | parâmetros atuais |

### 5.3 Endpoints de ação humana (só dashboard, JWT)

| Método | Rota | Regra |
|---|---|---|
| POST | `/recommendations/{id}/approve` | promove RECOMMEND → EXECUTE |
| POST | `/recommendations/{id}/reject` | registra motivo |
| POST | `/campaigns/{id}/review` | marca APPROVED/REJECTED; **não ativa no Meta** |
| PATCH | `/config/{key}` | respeita `min_value`/`max_value`; grava histórico |
| POST | `/alerts/{id}/acknowledge` | |
| POST | `/simulator/run` | cenários de orçamento (estimativa explícita) |

### 5.4 O que NÃO existirá como endpoint

- **Não haverá endpoint para ativar campanha no Meta.** A ativação é feita pelo administrador
  diretamente no Gerenciador de Anúncios. Isso remove por completo a possibilidade de a plataforma
  (ou o n8n, ou um bug, ou a IA) ligar um anúncio.

---

## 6. Workflows n8n propostos

Todos com: nó `Schedule` → `HTTP Request` (com `X-API-Key` e `Idempotency-Key` gerada) →
`IF` de erro → nó de notificação. Entregues em `.json` importáveis.

| Arquivo | Frequência sugerida | Cadeia |
|---|---|---|
| `01_discovery.json` | 6/6h | discovery → qualification → scoring/opportunity |
| `02_portfolio_manager.json` | diário | candidates/promote |
| `03_affiliate_links.json` | diário | links/generate |
| `04_content_generation.json` | diário | content/generate |
| `05_meta_ads_creation.json` | diário | ads/create (respeita `MAX_CAMPAIGNS_PER_EXECUTION=2`) |
| `06_performance_sync.json` | 4/4h | performance/sync → consolidate → snapshot |
| `07_ai_decision_cycle.json` | diário | portfolio/analyze → (se autonomia permitir) portfolio/apply |
| `08_alerts_monitor.json` | 1/1h | alerts/evaluate → notificação |

O n8n **não contém regra de negócio** — apenas agenda, encadeia, faz retry e notifica.
Toda a lógica vive no FastAPI, onde é testável.

---

## 7. Camada de segurança e guardrails

### 7.1 Ads Gateway — invariantes verificadas em runtime

Toda criação passa por `ads_gateway.create_campaign_bundle()`, que verifica, nesta ordem:

1. `DRY_RUN` ativo → simula e retorna sem chamar a API do Meta.
2. Contagem de `UNREVIEWED` > `MAX_UNREVIEWED_CAMPAIGNS` (10) → **ABORT** + alerta CRITICAL.
3. Campanhas já criadas nesta execução ≥ `MAX_CAMPAIGNS_PER_EXECUTION` (2) → para.
4. `BudgetGuard.can_commit(valor)` → se estourar o teto, recusa.
5. Força `status="PAUSED"` no payload — **ignora qualquer status recebido**.
6. Após a resposta do Meta, **relê** o objeto criado e confirma `status == PAUSED`;
   se não for, **pausa imediatamente** e emite alerta CRITICAL.

O passo 6 existe porque confiar no request enviado não é o mesmo que verificar o estado real.

### 7.2 Budget Guard

`disponivel = MAX_DAILY_AD_SPEND - (COMMITMENT + ACTUAL do dia)`
Fatiado em `EXPLORATION_PERCENTAGE` / `EXPLOITATION_PERCENTAGE`.
Nenhuma alocação é gravada sem passar por aqui.

### 7.3 Níveis de autonomia

| Nível | IA pode | Sempre humano |
|---|---|---|
| 1 | apenas descobrir e pontuar | tudo o mais |
| 2 | + promover a CANDIDATE | entrada no portfólio |
| 3 | + entrar/sair do portfólio, gerar links | criação de campanha |
| 4 | + gerar conteúdo e criar campanhas **PAUSED** | ativação |
| 5 | + ajustar orçamentos e recomendar mudança de parâmetros | **ativação (sempre)** |

Em **todos** os níveis: campanha nasce PAUSED e só um humano ativa.

### 7.4 Formato do `sub_id` (item 18)

Formato canônico proposto:

```
{mp}-{campaign}-{product}-{creative}-{channel}-{yyyymmdd}
ex: shp-c0421-p018377-cr07-meta-20260905
```

Componentes com prefixo de letra + id interno em base36 para caber em campos curtos.
O mapeamento reverso fica em `affiliate_links.sub_id` (UNIQUE), então mesmo que a Shopee trunque,
detectamos colisão na ingestão.

**Bloqueado por UNKNOWN-4** (tamanho e charset permitidos). Enquanto não validado, o
`tracking_service` gera o formato acima e **valida contra um limite configurável**
`SUBID_MAX_LENGTH`, falhando alto em vez de truncar silenciosamente.

UTM (para o lado do Meta): `utm_source=meta`, `utm_medium=cpc`, `utm_campaign={campaign}`,
`utm_content={creative}`, `utm_term={product}`.

---

## 8. Motor de decisão — desenho algorítmico

### 8.1 Ciclo

```
1. Carrega parâmetros vigentes (config_parameters)
2. Carrega portfólio ativo + performance_daily das últimas N janelas
3. Para cada produto ativo, classifica em uma de 5 zonas:
     WINNER          — score alto + amostra suficiente + ROI positivo estável
     PROMISING       — tendência positiva, amostra ainda insuficiente
     INCONCLUSIVE    — não atingiu MIN_CLICKS/MIN_IMPRESSIONS/MIN_TEST_DURATION
     UNDERPERFORMER  — amostra suficiente + ROI negativo
     NO_DATA         — dado indisponível (revenue_data_available = false)
4. Diagnostica cada UNDERPERFORMER (§8.2)
5. Calcula tamanho ótimo do portfólio (portfolio_sizer)
6. Monta plano: substituições, ajustes de orçamento, entradas novas
7. Valida plano contra BudgetGuard e limites duros
8. Grava ai_recommendations (sempre)
9. Se autonomia permitir → grava ai_decisions + executa
```

**Regras de proteção obrigatórias:**

- `INCONCLUSIVE` e `NO_DATA` **nunca** são substituídos. Aguardam dado.
- ROI < 0 por 3 dias → gera **alerta**, entra como *input* do diagnóstico, **não pausa sozinho**
  (item 21 do documento).
- Nenhum produto sai antes de `MIN_TEST_DURATION` em dias de dado maduro.

### 8.2 Diagnóstico antes de substituir (item 12)

| CTR | CVR | ROI | Diagnóstico | Ação sugerida |
|---|---|---|---|---|
| baixo | — | <0 | criativo/segmentação fraca | trocar criativo antes de trocar produto |
| bom | baixo | <0 | oferta/preço/landing fraca | trocar **produto**, manter criativo |
| bom | bom | <0 | comissão insuficiente vs CPC | buscar candidato com comissão maior |
| bom | bom | ≥0 | saudável | manter/aumentar orçamento |
| — | — | — | dados insuficientes | **não decidir** |

O diagnóstico é gravado em `ai_decisions.payload.diagnosis` e **direciona a escolha do substituto**
(ex.: diagnóstico "comissão insuficiente" → filtra candidatos por `commission_rate` acima da mediana).

### 8.3 `calculateOptimalPortfolioSize()`

Entradas: `MAX_DAILY_AD_SPEND`, `MIN_DAILY_TEST_BUDGET`, CPC médio observado,
cliques necessários para significância (`MIN_CLICKS_FOR_DECISION`), split exploration/exploitation.

```
budget_exploration = MAX_DAILY_AD_SPEND * EXPLORATION_PERCENTAGE
slots_exploration  = floor(budget_exploration / MIN_DAILY_TEST_BUDGET)
dias_para_decidir  = MIN_CLICKS_FOR_DECISION / (MIN_DAILY_TEST_BUDGET / cpc_medio)
```

Retorna: tamanho recomendado, slots por tier, dias estimados até decisão e **os pressupostos usados**.
Se `cpc_medio` não existir ainda → `data_available=false` e retorna faixa, não número único.
É **RECOMMEND**. A execução é separada.

### 8.4 Uso de LLM (item 8) — decisão explícita

- **Opportunity Score é estatístico por padrão.** Componentes numéricos vindos da API.
- O LLM é usado **apenas** como componente qualitativo opcional
  (`OPPORTUNITY_USE_LLM=false` por default), avaliando título/imagem/atratividade da oferta,
  devolvendo `qualitative_score` 0–100 + justificativa, com peso configurável e limite de gasto.
- **O LLM nunca inventa métrica numérica** (vendas, conversão). Se um dado não veio da API,
  ele permanece `data_available=false` — o LLM não preenche essa lacuna.
- Toda chamada gravada em `llm_calls`.

---

## 9. Estratégia de testes

Prioridade do documento (item 30): **overspending** e **regra PAUSED**.

### 9.1 Testes de guardrail (bloqueiam merge se falharem)

| Teste | Garante |
|---|---|
| `test_campaign_always_created_paused` | payload enviado ao Meta tem `status=PAUSED` |
| `test_campaign_status_reverified_after_creation` | se o Meta devolver ACTIVE, pausamos + alerta |
| `test_no_endpoint_activates_campaign` | varre as rotas; nenhuma expõe ativação |
| `test_max_campaigns_per_execution` | 3ª campanha na mesma execução é recusada |
| `test_abort_on_unreviewed_threshold` | >10 UNREVIEWED → ABORT + alerta |
| `test_budget_never_exceeds_cap` | property-based: nenhuma sequência de alocações estoura o teto |
| `test_budget_counts_commitments_and_actuals` | o teto considera comprometido + realizado |
| `test_dry_run_makes_no_external_calls` | adapters mockados não recebem chamada |
| `test_dry_run_writes_no_external_state` | nenhuma linha com `dry_run=false` é criada |

### 9.2 Testes de integridade da decisão

| Teste | Garante |
|---|---|
| `test_no_replacement_before_min_duration` | respeita `MIN_TEST_DURATION` |
| `test_no_replacement_below_min_clicks` | respeita `MIN_CLICKS_FOR_DECISION` |
| `test_no_decision_when_data_unavailable` | produto NO_DATA não é cortado |
| `test_missing_metric_never_defaults_to_zero` | `data_available=false`, não `0` |
| `test_every_state_change_has_transition_row` | rastro completo |
| `test_every_execute_decision_has_rationale` | payload com what/why/data_used |
| `test_append_only_tables_reject_update` | teste contra o banco real |
| `test_state_machine_rejects_illegal_transitions` | ex.: DISCOVERY → WINNER |

### 9.3 Testes de idempotência

`test_same_idempotency_key_returns_cached_response`,
`test_concurrent_workflow_runs_blocked_by_lock`.

Alvo: **≥90% de cobertura** em `budget_guard`, `ads_gateway`, `state_machine`, `decision_engine`.

---

## 10. Roadmap por fases

| Fase | Escopo | Depende de | Bloqueado por |
|---|---|---|---|
| **0** | Scaffold, Docker, Alembic, schema completo, config, seeds de parâmetros, CI | — | nada |
| **1** | `MarketplaceAdapter` + `MockAdapter` + Discovery + Qualification + Opportunity Score + state machine | 0 | nada |
| **2** | Portfolio Service + `portfolio_sizer` + Decision Engine (RECOMMEND) + `ai_decisions` | 1 | nada |
| **3** | Tracking (`sub_id`) + Affiliate Links | 2 | **UNKNOWN-3/4** |
| **4** | `AdsGateway` + Meta (PAUSED) + BudgetGuard + suíte de guardrails | 2 | **UNKNOWN-7** |
| **5** | Ingestão de performance + `performance_daily` + Performance Score | 3, 4 | **UNKNOWN-3** |
| **6** | Decision Engine em modo EXECUTE + substituição inteligente + autonomia | 5 | nada |
| **7** | Dashboard React (4 visões) | 2, 5 | nada |
| **8** | Workflows n8n `.json` + runbook | 1–6 | nada |
| **9** | `ShopeeAdapter` real | 1 | **UNKNOWN-1/2/5/6** |
| **10** | Simulador + portfólio adaptativo + recomendação de parâmetros | 6 | nada |

**Observação importante:** as fases 1–8 rodam integralmente em `MOCK_MARKETPLACE=true`.
Ou seja, **a ausência da documentação da Shopee não bloqueia o projeto** — bloqueia apenas a Fase 9.

---

## 11. Decisões que preciso que você aprove

Antes de eu escrever a primeira linha de código de aplicação:

1. **Schema (§3)** — aprova as tabelas, os enums e a separação estado-atual × histórico?
   Alguma métrica de negócio que você já sabe que vai querer e não está aí?

2. **Formato do `sub_id` (§7.4)** — aprova o padrão `shp-c0421-p018377-cr07-meta-20260905`?
   O documento pedia `marketplace_campaign_product_creative_channel_date`; usei hífen em vez de
   underscore por segurança de parsing em URL, mas mudo se preferir underscore.

3. **Sem endpoint de ativação (§5.4)** — confirma que a ativação de campanha será **sempre** manual
   no Gerenciador do Meta, sem nenhum botão no dashboard? (É a proteção mais forte possível.)

4. **LLM desligado por padrão (§8.4)** — confirma `OPPORTUNITY_USE_LLM=false` como default,
   ligando só depois com teto de custo?

5. **Ordem das fases (§10)** — começo pela Fase 0+1 em modo mock, ou você prefere que eu ataque
   primeiro a integração real da Shopee (o que exige você me passar a documentação antes)?

6. **UNKNOWNs (§2)** — em especial o **UNKNOWN-3** (o relatório de conversões devolve `sub_id`?).
   Sem isso, a Fase 5 não tem como calcular ROI por produto e o motor de decisão fica cego.
   Consegue extrair essa informação do painel de afiliado?

7. **Credenciais** — confirma que você tem: conta de afiliado Shopee aprovada com `app_id`/`secret`,
   app do Meta com Marketing API e `act_id`, projeto Supabase criado, instância n8n disponível?

---

### Fontes consultadas nesta sessão

Nenhuma fonte **oficial** da Shopee pôde ser aberta a partir deste ambiente
(`affiliate.shopee.com.br` bloqueado pelo proxy de egress). Os resultados de busca encontrados são
comunitários e **não foram tratados como fato** — estão registrados apenas como pistas a validar:

- [Discussão sobre erro "Invalid Signature" na API GraphQL de afiliado (Stack Overflow)](https://kiwix.ounapuu.ee/content/stackoverflow.com_en_all_2023-11/questions/75154612/resquest-to-api-graphql-shopee-affiliate-failed-error-invalid-signature-python)
- [Repositório comunitário `bcat95/shopee-aff` (GitHub)](https://github.com/bcat95/shopee-aff)
- [Pacote comunitário `Shopee.Affiliate` (Libraries.io)](https://libraries.io/nuget/Shopee.Affiliate)
