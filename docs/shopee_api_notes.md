# Shopee Affiliate API — Validação Oficial

**Data:** 2026-09-06  
**Status:** Documentação oficial fornecida pelo usuário  
**Fonte:** Painel de desenvolvimento Shopee Affiliate

---

## 1. Endpoint e Protocolo

| Campo | Valor |
|---|---|
| **URL** | `https://open-api.affiliate.shopee.br/graphql` |
| **Protocolo** | GraphQL |
| **Método HTTP** | POST |
| **Content-Type** | `application/json` |

---

## 2. Autenticação

### Formato do Header

```
Authorization: SHA256 Credential={AppId}, Signature={signature}, Timestamp={timestamp}
```

### Cálculo da Signature

```
Signature = SHA256(AppId + Timestamp + Payload + AppSecret)
```

Onde:
- `AppId`: ID da aplicação registrada no painel Shopee
- `Timestamp`: Unix timestamp em segundos (ex: 1577836800)
- `Payload`: JSON bruto da query/mutation GraphQL (ordem exata importa)
- `AppSecret`: Secret da aplicação (NUNCA compartilhar)

### Exemplo válido

```bash
Authorization: SHA256 Credential=123456, Signature=x9bc0bd3ba6c41d98a591976bf95db97a58720a9e6d778845408765c3fafad69d, Timestamp=1577836800
```

---

## 3. Operações Confirmadas

### 3.1 generateShortLink (Mutation)

Encurta URLs e registra sub_ids para rastreamento.

**Query GraphQL:**

```graphql
mutation {
  generateShortLink(input: {
    originUrl: "https://shopee.com.br/Apple-Iphone-11-128GB-Local-Set-i.52377417.6309028319",
    subIds: ["s1", "s2", "s3", "s4", "s5"]
  }) {
    shortLink
  }
}
```

**Parâmetros de entrada:**
- `originUrl` (String, obrigatório): URL completa do produto Shopee
- `subIds` (Array[String], obrigatório): até 5 strings para rastreamento

**Resposta de sucesso:**

```json
{
  "shortLink": "https://shp.ee/ABC123DEF"
}
```

**Observação:** Uma chamada gera UM shortLink para todos os 5 sub_ids. Útil para gerar link único
com múltiplos identificadores internos de rastreamento.

---

## 4. Operações Ainda Pendentes

As seguintes operações estão **mencionadas na documentação** mas seus schemas **NÃO foram
fornecidos** pelo usuário:

| Operação | Uso | Status |
|---|---|---|
| `productOfferV2` | Buscar/listar produtos do marketplace | ⏳ PENDENTE |
| `conversions` ou relatório similar | Relatório de comissões e conversões | ⏳ PENDENTE |
| Outras queries | Ainda a descobrir | ⏳ PENDENTE |

---

## 5. UNKNOWNs Resolvidos vs. Pendentes

| UNKNOWN | Item | Status | Valor |
|---------|------|--------|-------|
| UNKNOWN-1 | Endpoint GraphQL | ✅ VALIDADO | `https://open-api.affiliate.shopee.br/graphql` |
| UNKNOWN-2 | Fórmula de assinatura | ✅ VALIDADO | SHA256(AppId + Timestamp + Payload + AppSecret) |
| UNKNOWN-3 | `sub_id` no relatório | ⏳ **CRÍTICO** | Ainda não confirmado (bloqueia decisor) |
| UNKNOWN-4 | Tamanho máx de sub_id | ⏳ PARCIAL | Array de até 5 strings; tamanho individual desconhecido |
| UNKNOWN-5 | Rate limits | ⏳ PENDENTE | Não informado |
| UNKNOWN-6 | Campos de demanda | ⏳ PENDENTE | Precisa documentação de productOfferV2 |

---

## 6. Checklist de Próximos Passos

- [ ] Obter schema completo de `productOfferV2` ou query de listagem de produtos
- [ ] Validar **campos de demanda** (vendas históricas, rating, estoque, etc.)
- [ ] Confirmar se o **relatório de conversões devolve `sub_id`** nativo
- [ ] Documentar **rate limits** e **paginação máxima**
- [ ] Testar autenticação com AppId/AppSecret reais
- [ ] Confirmar **latência do relatório de conversões** (dias até estar disponível)
- [ ] Validar **período de cancelamento** (após quantos dias a comissão é final?)

---

## 7. Implementação no Projeto

### ShopeeAdapter

**Arquivo:** `backend/app/adapters/marketplace/shopee/adapter.py`

Será composto por:

1. **ShopeeAuth** — classe para assinar requisições (SHA256, timestamps)
2. **ShopeeAdapter** — implementação de `MarketplaceAdapter`
   - ✅ `generate_short_link()` — pronto para implementar
   - ⏳ `search_products()` — aguarda UNKNOWN-6
   - ⏳ `fetch_conversions()` — aguarda UNKNOWN-3

### Configuração

**Variáveis de ambiente obrigatórias:**

```bash
SHOPEE_APP_ID=seu_app_id_aqui
SHOPEE_APP_SECRET=seu_secret_aqui
SHOPEE_API_ENDPOINT=https://open-api.affiliate.shopee.br/graphql
SHOPEE_REGION=BR
```

---

## 8. Referências

- **Fonte da documentação:** Painel de afiliado Shopee (validado 2026-09-06)
- **Exemplo de curl completo:**

```bash
curl -X POST 'https://open-api.affiliate.shopee.br/graphql' \
  -H 'Authorization:SHA256 Credential=123456, Signature=x9bc0bd3ba6c41d98a591976bf95db97a58720a9e6d778845408765c3fafad69d, Timestamp=1577836800' \
  -H 'Content-Type: application/json' \
  --data-raw '{"query":"mutation{\n    generateShortLink(input:{originUrl:\"https://shopee.com.br/Apple-Iphone-11-128GB-Local-Set-i.52377417.6309028319\",subIds:[\"s1\",\"s2\",\"s3\",\"s4\",\"s5\"]}){\n        shortLink\n    }\n}"}'
```



---

## 9. Atualizações Recentes da Plataforma (2026-03-05)

### Product Feed API (NEW)

**Propósito:** Substituir downloads manuais; automatizar atualização de catálogo.

**Fluxo recomendado:**

1. **Get Product Feed Offer List API** — listar feeds disponíveis
2. **FULL download** — primeira carga (todos os produtos)
3. **DELTA downloads** — diários, apenas mudanças (otimiza banda)

**Campos retornados (esperado):**
- Product information (ID, título, preço, etc.)
- `product_short_link` — URL encurtada otimizada para Shopee app
- Commission information
- Status updates

**UNKNOWN-6 (Campos de demanda):** Esperamos encontrar:
- Vendas/popularity
- Rating
- Estoque
- Comissão
- Status do item

### Conversion Report API (Atualizado 2024-11-15)

**Novos campos:**
- `netCommission` — comissão líquida
- `campaignType` — tipo de campanha
- Detalhes de comissão mais granulares

**Campos existentes atualizados:**
- Item Status
- Shop Info
- Billing details (por validation_id)

**CRÍTICO para UNKNOWN-3:**
> "The Conversion Report API now includes new fields such as netCommission and campaignType"

Isso sugere que há **atribuição granular** no relatório. Precisa-se confirmar:
- Existe campo de **rastreamento** (tipo `sub_id` ou `tracking_id`)?
- Qual é exatamente o nome do campo de rastreamento?
- Retorna em qual nível? (pedido? item? clique?)

### ShopOfferV2 API (Atualizado 2023-08-04)

**Novos campos adicionados:**
- Item Info
- Shop Info
- Offer Status
- Seller commission related info
- Sorting by popular shop

**Isso resolve UNKNOWN-6 parcialmente:** ShopOfferV2 parece retornar dados suficientes para
Opportunity Score (comissão, estoque, popularidade, etc.).

---

## 10. UNKNOWNs Revisados com Novas Informações

| UNKNOWN | Item | Status | Evidência |
|---------|------|--------|-----------|
| UNKNOWN-1 | Endpoint GraphQL | ✅ VALIDADO | Confirmado em documentação oficial |
| UNKNOWN-2 | Assinatura SHA256 | ✅ VALIDADO | Confirmado em curl example |
| **UNKNOWN-3** | `sub_id` no Conversion Report | 🟠 **QUASE RESOLVIDO** | Conversion Report API foi atualizado (2024-11-15); precisa confirmar nome exato do campo de rastreamento |
| **UNKNOWN-5** | Rate limits | ⏳ PENDENTE | Ainda não encontrado |
| **UNKNOWN-6** | Campos de demanda (ShopOfferV2) | 🟢 **QUASE RESOLVIDO** | ShopOfferV2 inclui Item Info, Shop Info, commission info; precisa schema completo |
| UNKNOWN-4 | Tamanho máx de `sub_id` | ⏳ PENDENTE | Ainda não documentado |

---

## 11. Checklist Revisado — Alta Prioridade

Para **desbloquear Fase 1 (Discovery):**

- [ ] **Obter schema de ShopOfferV2** (ou ProductOfferV2) — quais campos exatos são retornados?
- [ ] **Confirmar Conversion Report fields** — qual é o nome do campo de rastreamento/atribuição?
  - Esperado: `sub_id`, `tracking_id`, ou similar
  - **Crítico:** deve estar disponível em cada linha de conversão
- [ ] **Product Feed API endpoints** — URLs de Get Feed List, download FULL, download DELTA
- [ ] **Rate limits** — requisições/minuto para cada endpoint

---

## 12. Arquivos de Exemplo Esperados

Para implementação de `ProductFeedAdapter`:

Esperamos receber (ou ter acesso no painel a):
- `product_feed_full_example.csv` ou `.json` — estrutura FULL
- `product_feed_delta_example.csv` ou `.json` — estrutura DELTA
- Schema da Conversion Report — quais colunas exatas?



---

## 13. VALIDADO: ShopeeOfferV2 Query (Complete Schema)

**Query GraphQL:**

```graphql
query shopeeOfferV2(
  $keyword: String
  $sortType: Int
  $page: Int
  $limit: Int
) {
  shopeeOfferV2(
    keyword: $keyword
    sortType: $sortType
    page: $page
    limit: $limit
  ) {
    nodes {
      commissionRate
      imageUrl
      offerLink
      originalLink
      offerName
      offerType
      categoryId
      collectionId
      periodStartTime
      periodEndTime
    }
    pageInfo {
      page
      limit
      hasNextPage
    }
  }
}
```

### Query Parameters

| Field | Type | Required | Example | Notes |
|---|---|---|---|---|
| `keyword` | String | Opcional | "clothes" | Busca por nome da oferta |
| `sortType` | Int | Opcional | 1 ou 2 | 1=LATEST_DESC, 2=HIGHEST_COMMISSION_DESC |
| `page` | Int | Opcional | 2 | Número da página |
| `limit` | Int | Opcional | 10 | Itens por página (máximo?) |

### Response: ShopeeOfferV2 Node

| Field | Type | Description | Usado em Opp Score |
|---|---|---|---|
| `commissionRate` | String | Taxa de comissão (ex: "0.0123" = 1.23%) | ✅ **SIM** |
| `imageUrl` | String | URL da imagem da oferta | ✅ Conteúdo |
| `offerLink` | String | Link da oferta | ✅ Tracking |
| `originalLink` | String | Link original (produto Shopee) | ✅ Tracking |
| `offerName` | String | Nome da oferta | ✅ Título |
| `offerType` | Int | 1=COLLECTION, 2=CATEGORY | ✅ Contexto |
| `categoryId` | Int64 | ID da categoria (se offerType=2) | ✅ Filtro |
| `collectionId` | Int64 | ID da coleção (se offerType=1) | ✅ Filtro |
| `periodStartTime` | Int | Unix timestamp início | ✅ Validade |
| `periodEndTime` | Int | Unix timestamp fim | ✅ Validade |

### Response: PageInfo

| Field | Type | Description |
|---|---|---|
| `page` | Int | Página atual |
| `limit` | Int | Itens por página retornados |
| `hasNextPage` | Bool | Há próxima página? |

---

## 14. VALIDADO: Limitation e Observações

### O que temos:
✅ Comissão (crítico para Opportunity Score)  
✅ Nome, link, imagem (conteúdo)  
✅ Tipo de oferta e IDs (filtros)  
✅ Validade (período)  
✅ Paginação  

### O que **NÃO temos** nesta query:
❌ Demanda/vendas históricas do produto  
❌ Rating do produto  
❌ Estoque disponível  
❌ Número de clicks/conversões passadas da oferta  

**Impacto:** O Opportunity Score será baseado em:
- ✅ Commission rate (comissão)
- ✅ Offer type (se é categoria ou coleção — mais genérico = menos oportunidade)
- ✅ Period validity (está ativo? vai expirar?)
- ❌ Demanda (não disponível nesta query)

**Solução:** Buscar demanda em outro endpoint, ou usar LLM para avaliar potencial pelo nome/imagem.

---

## 15. UNKNOWNs RESOLVIDOS — Atualização Final

| UNKNOWN | Antes | Agora | Status |
|---------|-------|-------|--------|
| UNKNOWN-1 | Endpoint desconhecido | `https://open-api.affiliate.shopee.br/graphql` | ✅ **VALIDADO** |
| UNKNOWN-2 | Assinatura desconhecida | SHA256(AppId + Timestamp + Payload + AppSecret) | ✅ **VALIDADO** |
| UNKNOWN-4 | Tamanho de sub_id | Array de até 5 strings | ✅ **VALIDADO** |
| UNKNOWN-6 | Campos de demanda | ShopeeOfferV2 retorna: commissionRate, offerName, categoryId, validade, etc. | 🟠 **PARCIAL** — comissão sim, mas demanda/sales/rating não |
| UNKNOWN-5 | Rate limits | ⏳ Ainda pendente | ⏳ **PENDENTE** |

---

## 16. Roadmap Desbloqueado — Fase 1 Pode Começar!

Com `shopeeOfferV2` validado, consigo:

✅ Implementar `ShopeeAdapter.search_products()`  
✅ Estruturar Opportunity Score com componentes disponíveis  
✅ MockAdapter com dados realistas  
✅ Fase 1 completa (Discovery + Qualification)  

**Bloqueadores restantes:**
⏳ UNKNOWN-3 (Conversion Report — qual é o campo de rastreamento?)  
⏳ UNKNOWN-5 (Rate limits — quantas requisições/minuto?)  

Sem esses dois, não há bloqueio. Posso começar a **Fase 1 agora em modo mock**, e a Fase 5 (Performance) só depende de UNKNOWN-3.

