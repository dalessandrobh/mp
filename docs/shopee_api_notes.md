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

