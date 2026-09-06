# ARCHITECTURE.md — Affiliate Intelligence & Automation Platform

> Documento de especificação (fonte da verdade do produto).
> O planejamento técnico derivado dele está em [`PLANNING.md`](./PLANNING.md).

## CONTEXTO

Plataforma de automação e inteligência para marketing de afiliados.
Primeira integração: **Shopee Brasil**. A arquitetura deve estar preparada desde o início para
posteriormente integrar Amazon, Mercado Livre, AliExpress e outros marketplaces/programas.

A plataforma funciona como um **gestor autônomo de portfólio de produtos afiliados**.
Não se trata de encontrar produtos e gerar anúncios. A IA deve:

- Descobrir oportunidades
- Avaliar milhares de produtos
- Filtrar produtos com maior potencial
- Montar um portfólio de produtos para teste
- Monitorar continuamente a performance
- Identificar vencedores e perdedores
- Substituir produtos de baixa performance
- Aumentar a prioridade dos produtos vencedores
- Buscar continuamente novos produtos para exploração
- Controlar tudo através de regras, dados e orçamento
- Registrar todas as decisões tomadas
- **Nunca inventar métricas ou informações inexistentes**

## STACK TECNOLÓGICA OBRIGATÓRIA

- **Backend:** Python com FastAPI e SQLAlchemy
- **Banco de Dados:** PostgreSQL hospedado no Supabase
- **Frontend (Dashboard):** React, Vite e Tailwind CSS
- **Orquestração de Workflows:** n8n
- **Inteligência (Decision Engine):** algoritmos estatísticos internos + chamadas de API para LLMs
  (ex.: Claude ou Gemini) para avaliações qualitativas quando necessário

---

## 1. PRINCÍPIO FUNDAMENTAL: PORTFÓLIO DINÂMICO

**Não** utilizar regra fixa de "30 produtos". O número de produtos ativos é dinâmico; os 30
produtos eram apenas hipótese de partida e **não** são limite obrigatório.

Separação clara entre:

- **Produtos descobertos** — encontrados pelas APIs/fontes de dados (1.000, 5.000, 10.000+)
- **Produtos candidatos** — passaram pelos filtros iniciais
- **Produtos em teste** — selecionados para exposição/anúncios experimentais
- **Portfólio ativo** — fazem parte da estratégia principal de divulgação
- **Vencedores** — desempenho comprovadamente superior; recebem maior orçamento

## 2. A IA DEVE DEFINIR O TAMANHO IDEAL DO PORTFÓLIO

A quantidade de produtos ativos não é definida apenas por constante. A IA considera orçamento
diário, custo médio por teste, volume de cliques, conversões, ROI e maturidade do produto.

Parâmetros configuráveis: `MIN_ACTIVE_PRODUCTS`, `MAX_ACTIVE_PRODUCTS`, `MAX_DAILY_AD_SPEND`,
`MIN_DAILY_TEST_BUDGET`, `EXPLORATION_PERCENTAGE`, `EXPLOITATION_PERCENTAGE`,
`MIN_DATA_FOR_DECISION`, `MIN_TEST_DURATION`.

A IA deve ser capaz de **recomendar** alterações nestes valores com base na performance.

## 3. ORÇAMENTO COMO PRINCIPAL LIMITADOR

A capacidade de testar produtos depende principalmente do orçamento disponível.
A capacidade de testes é calculada dinamicamente a partir de `MAX_DAILY_AD_SPEND`.

## 4. EXPLORATION × EXPLOITATION

- **Exploration** (ex.: 30%) — busca e teste de novos produtos
- **Exploitation** (ex.: 70%) — maximizar retorno de produtos comprovados

A IA pode alterar a proporção conforme a performance geral do portfólio.

## 5. FUNIL DE PRODUTOS

```
DISCOVERY → QUALIFICATION → CANDIDATE → TEST → ACTIVE → WINNER
```

Estados auxiliares: `REJECTED`, `PAUSED`, `UNDER_REVIEW`, `REPLACED`, `EXPIRED`.

Toda mudança de estado é registrada no banco. Produtos não são excluídos sem rastro.

## 6. DESCOBERTA DE PRODUTOS E INTEGRAÇÃO

- Utilizar **exclusivamente** APIs oficiais/documentadas
- Validar endpoints, parâmetros e paginação
- **Não inventar endpoints**

**Segurança e autenticação:** parâmetros (`APP_ID`, `SECRET`) sempre de variáveis de ambiente.
O adapter implementa a criptografia/assinatura da requisição (hash e timestamps) conforme a
documentação oficial. **Nunca chumbar credenciais no código.**

Criar `MarketplaceAdapter` com implementação inicial `ShopeeAdapter`.

## 7. SCORE DE OPORTUNIDADE

`Opportunity Score` = demanda + comissão + conversão estimada + competitividade + etc.

Deve estar explícito no código se a avaliação é puramente estatística (parâmetros da API) ou se
envia dados (título, descrição, imagens) a uma LLM externa para avaliar potencial de oferta/conteúdo.

**IMPORTANTE:** se um dado não existir → `data_available = false`. Nunca fabricar estimativas.

## 8. SCORE DE PERFORMANCE

`Performance Score` = CTR + CPC + conversão + ROI + ROAS + estabilidade, etc.
Totalmente separado do Opportunity Score.

## 9. MOTOR DE DECISÃO DA IA

Serviço que analisa o portfólio, cruza dados estatísticos do banco e decide quem entra, quem sai e
quem recebe mais orçamento. Lógica implementada no backend (FastAPI) sobre o PostgreSQL.

## 10. REGRA DE SUBSTITUIÇÃO

Não substituir produtos por poucos cliques no primeiro dia. Respeitar
`MIN_CLICKS_FOR_DECISION`, `MIN_IMPRESSIONS_FOR_DECISION`, `MIN_TEST_DURATION`.

## 11. SUBSTITUIÇÃO INTELIGENTE

Identificar o motivo do fracasso antes de substituir (ex.: ROI negativo com CTR bom = problema na
oferta). O diagnóstico direciona a escolha do candidato substituto.

## 12. PORTFÓLIO ADAPTATIVO

A IA recomenda aumento ou redução do tamanho do portfólio conforme orçamento disponível versus
fragmentação de dados.

## 13. PORTFOLIO SIMULATOR

Simula cenários de orçamento e estima velocidade de aprendizado e capacidade de testes,
deixando explícito que são **estimativas**.

## 14. META ADS (REGRA CRÍTICA)

Integração com Meta Ads cria Campaign, Ad Set e Ad de forma automatizada.
**Tudo criado automaticamente nasce com status `PAUSED`.**
Nunca ativar campanhas automaticamente — a ativação é manual, pelo administrador.

## 15. LIMITES DE SEGURANÇA

- `MAX_CAMPAIGNS_PER_EXECUTION = 2`
- Mais de 10 campanhas `UNREVIEWED` → **ABORT** e notificar
- Nunca criar campanhas indefinidamente

## 16. ORÇAMENTO DE ANÚNCIOS

`MAX_DAILY_AD_SPEND` global, nunca ultrapassado. O motor fatia entre Exploration e Exploitation.

## 17. TRACKING

Todo link afiliado possui UTM/`sub_id`.
Estrutura: `marketplace_campaign_product_creative_channel_date` (formato exato definido no código).

## 18. MÉTRICAS

Consolidar métricas do Marketplace, Meta Ads, Instagram e as calculadas
(Revenue, Profit, ROI, ROAS, EPC).

## 19. REGRA DE ROI NEGATIVO

ROI < 0 por 3 dias consecutivos = **alerta**. Não pausar automaticamente só por essa regra;
a decisão passa pelo Motor de Decisão.

## 20. BANCO DE DADOS

PostgreSQL via Supabase. Histórico completo; decisões não são sobrescritas (append-only para logs).
Tabelas essenciais: `marketplaces`, `products`, `portfolio_products`, `performance_daily`,
`campaigns`, `ai_decisions`, `audit_logs`, entre outras.

## 21. HISTÓRICO DA IA

Cada decisão (`REPLACE`, `KEEP`, `INCREASE`…) é salva em JSON estruturado explicando:
**o quê**, **por quê**, **dados utilizados**, **quem saiu**, **quem entrou**.

## 22. ORQUESTRAÇÃO COM N8N

n8n como orquestrador. O backend expõe endpoints REST consumidos por nós HTTP Request
(ex.: `/api/v1/trigger/discovery`, `/api/v1/portfolio/analyze`).

Workflows independentes: Discovery, Portfolio Manager, Affiliate Links, Content, Meta Ads,
Performance, Alerts. Entregues exportados em `.json` para importação direta.

## 23. DASHBOARD (REACT/VITE)

Visão geral, Financeiro, Portfólio detalhado e Inteligência/Recomendações da IA.

## 24. RECOMENDAÇÃO DE TAMANHO DO PORTFÓLIO

Função `calculateOptimalPortfolioSize()` retorna a alocação recomendada com base no orçamento.
O sistema separa a **recomendação** (`RECOMMEND`) da **execução** (`EXECUTE`).

## 25. NÍVEL DE AUTONOMIA

`AI_AUTONOMY_LEVEL` de 1 a 5. Mesmo no nível 5, campanhas no Meta Ads permanecem `PAUSED`.

## 26. MODO DRY RUN

`DRY_RUN=true` — o sistema simula todo o pipeline sem alterar dados externos.

## 27. MOCK MODE

`MOCK_MARKETPLACE=true` — dados fictícios para desenvolver sem depender das APIs reais.

## 28. TESTES

Testes automatizados focados especialmente em prevenir overspending e garantir a regra `PAUSED`.

## 29. MULTI-MARKETPLACE

Arquitetura abstrata baseada em interfaces: `MarketplaceAdapter` base + `ShopeeAdapter` concreto,
preparado para Amazon/Mercado Livre.

## 30. PRINCÍPIO CENTRAL

O sistema é uma **inteligência que administra dinamicamente um portfólio de oportunidades**,
não um gerador de links fixos.

## 31. FLUXO FINAL

Ciclo contínuo gerido pelo n8n chamando os endpoints do FastAPI:

```
Discovery → Filter → Candidates → Test → Content → Meta (Paused)
   → Tracking → Performance → AI Decision → Update
```

## 32. OBJETIVO FINAL

O usuário informa orçamento, % de exploração e nível de autonomia; a IA calcula e executa o fluxo
completo, decidindo volumes, trocas e manutenções.

## 33. EXECUÇÃO DA PRIMEIRA IMPLEMENTAÇÃO

Não gerar código de aplicação de imediato. Ordem:

1. Analisar a arquitetura e identificar dependências
2. Propor o schema do banco (PostgreSQL/Supabase)
3. Propor a estrutura de pastas e arquitetura dos serviços FastAPI e frontend React
4. Propor o mapeamento dos endpoints que o n8n vai consumir
5. Escrever conclusões e propostas em `PLANNING.md`
6. **Aguardar aprovação do `PLANNING.md`** antes de codificar a Fase 1

## 34. REGRA ABSOLUTA (PREVENÇÃO DE ALUCINAÇÃO)

Não inventar APIs, endpoints, parâmetros ou capacidades não comprovadas.
Sem documentação: **MARK AS UNKNOWN** e pedir validação.

## 35. PADRÕES DE CÓDIGO E COMENTÁRIOS (CRÍTICO)

Todo código gerado (Python, React, SQL) deve ser comentado para facilitar entendimento, auditoria e
manutenção humana:

- Comentários curtos, resumidos e diretos
- Evitar parágrafos longos ou explicações redundantes do que a linguagem já deixa óbvio
- Focar no **porquê** da lógica de negócio e na regra aplicada
- Manter o código limpo, legível e profissional
