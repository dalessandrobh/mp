# Shopee Affiliate API — Schema Reference

**Última atualização:** 2026-09-06  
**Status:** Documentação oficial do usuário  
**Fontes:** Painel de afiliado Shopee

---

## 1. ShopeeOfferV2 Query (Ofertas Gerais)

### Endpoint
```
POST https://open-api.affiliate.shopee.br/graphql
Authorization: SHA256 Credential={AppId}, Signature={sig}, Timestamp={ts}
Content-Type: application/json
```

### Query
```graphql
query shopeeOfferV2(
  $keyword: String
  $sortType: Int
  $page: Int
  $limit: Int
) {
  shopeeOfferV2(keyword: $keyword, sortType: $sortType, page: $page, limit: $limit) {
    nodes { /* ShopeeOfferV2 fields */ }
    pageInfo { /* PageInfo */ }
  }
}
```

### Parameters

| Field | Type | Required | Values | Description |
|---|---|---|---|---|
| `keyword` | String | No | "clothes" | Busca por nome da oferta |
| `sortType` | Int | No | 1, 2 | 1=LATEST_DESC, 2=HIGHEST_COMMISSION_DESC |
| `page` | Int | No | 2 | Número da página |
| `limit` | Int | No | 10 | Itens por página |

### Response: ShopeeOfferV2

| Field | Type | Description | Usado em |
|---|---|---|---|
| `commissionRate` | String | Taxa de comissão (ex: "0.0123" = 1.23%) | ✅ Opportunity Score |
| `imageUrl` | String | URL da imagem | ✅ Conteúdo |
| `offerLink` | String | Link da oferta | ✅ Tracking |
| `originalLink` | String | Link original Shopee | ✅ Tracking |
| `offerName` | String | Nome da oferta | ✅ Título |
| `offerType` | Int | 1=COLLECTION, 2=CATEGORY | ✅ Contexto |
| `categoryId` | Int64 | ID da categoria | ✅ Filtro |
| `collectionId` | Int64 | ID da coleção | ✅ Filtro |
| `periodStartTime` | Int | Unix timestamp início | ✅ Validade |
| `periodEndTime` | Int | Unix timestamp fim | ✅ Validade |

### Response: PageInfo

| Field | Type |
|---|---|
| `page` | Int |
| `limit` | Int |
| `hasNextPage` | Bool |

---

## 2. ShopOfferV2 Query (Ofertas por Loja)

### Query
```graphql
query shopOfferV2(
  $shopId: Int64
  $keyword: String
  $shopType: [Int]
  $isKeySeller: Bool
  $sortType: Int
  $sellerCommCoveRatio: String
  $page: Int
  $limit: Int
) {
  shopOfferV2(...) {
    nodes { /* ShopOfferV2 fields */ }
    pageInfo { /* PageInfo */ }
  }
}
```

### Parameters

| Field | Type | Required | Values | Description |
|---|---|---|---|---|
| `shopId` | Int64 | No | 84499012 | Buscar por ID da loja (NEW) |
| `keyword` | String | No | "demo" | Buscar por nome da loja |
| `shopType` | [Int] | No | [1,2,4] | Filtrar por tipo de loja (NEW) |
| `isKeySeller` | Bool | No | true/false | Apenas "key sellers" da Shopee (NEW) |
| `sortType` | Int | No | 1, 2, 3 | 1=LATEST_DESC, 2=HIGHEST_COMMISSION_DESC, 3=POPULAR_SHOP_DESC (NEW) |
| `sellerCommCoveRatio` | String | No | "0.123" | Mín ratio de produtos com comissão (NEW) |
| `page` | Int | No | 2 | Página |
| `limit` | Int | No | 10 | Itens/página |

### ShopType Values

| Valor | Significado |
|---|---|
| `1` | OFFICIAL_SHOP — Lojas oficiais / Shopee Mall |
| `2` | PREFERRED_SHOP — Lojas preferidas (Star) |
| `4` | PREFERRED_PLUS_SHOP — Lojas preferidas (Star+) |

### Response: ShopOfferV2

| Field | Type | Description | Novo? | Usado em |
|---|---|---|---|---|
| `commissionRate` | String | Taxa de comissão | — | ✅ Opportunity Score |
| `imageUrl` | String | URL da imagem | — | ✅ Conteúdo |
| `offerLink` | String | Link da oferta | — | ✅ Tracking |
| `originalLink` | String | Link da loja Shopee | — | ✅ Tracking |
| `shopId` | Int64 | ID da loja | — | ✅ Filtro/Contexto |
| `shopName` | String | Nome da loja | — | ✅ Título |
| `ratingStar` | String | Rating da loja | NEW ✅ | ✅ **Opportunity Score (demanda proxy)** |
| `shopType` | [Int] | Tipo de loja | NEW ✅ | ✅ Filtro/confiança |
| `remainingBudget` | Int | Estado do orçamento da oferta | NEW ✅ | ✅ **Risco de expiração** |
| `periodStartTime` | Int | Unix timestamp início | — | ✅ Validade |
| `periodEndTime` | Int | Unix timestamp fim | — | ✅ Validade |
| `sellerCommCoveRatio` | String | Ratio de produtos com comissão | NEW ✅ | ✅ Filtro/qualidade |
| `bannerInfo` | BannerInfo | Informações de banner | NEW ✅ | ✅ Criativos |

### RemainingBudget Values

| Valor | Significado |
|---|---|
| `0` | Unlimited — sem limite de orçamento |
| `3` | Normal — >50% orçamento restante |
| `2` | Low — <50% orçamento (risco médio) |
| `1` | Very Low — <30% orçamento (risco alto) |

### BannerInfo Structure

| Field | Type | Description |
|---|---|---|
| `count` | Int | Número de banners |
| `banners` | [Banner] | Array de banners |

### Banner Structure

| Field | Type | Description |
|---|---|---|
| `fileName` | String | Nome do arquivo |
| `imageUrl` | String | URL da imagem |
| `imageSize` | Int | Tamanho em bytes |
| `imageWidth` | Int | Largura em pixels |
| `imageHeight` | Int | Altura em pixels |

---

## 3. Error Codes

| Code | Description | Ação |
|---|---|---|
| 11000 | Business Error | Contatar suporte |
| 11001 | Params Error: {reason} | Validar parâmetros |
| 11002 | Bind Account Error: {reason} | Reautenticar |
| 10020 | Invalid Signature | Validar SHA256, Timestamp |
| 10020 | Request Expired | Atualizar Timestamp |
| 10020 | Invalid Timestamp | Sincronizar hora do servidor |
| 10020 | Invalid Credential | Validar AppId |
| 10020 | Invalid Authorization Header | Validar formato do header |
| 10030 | Rate limit exceeded | Aguardar e implementar backoff exponencial |
| 10031 | Access deny | Permissões insuficientes |
| 10032 | Invalid affiliate id | Conta não é afiliado |
| 10033 | Account is frozen | Contatar suporte |
| 10034 | Affiliate id in black list | Contatar suporte |
| 10035 | No access to Shopee Affiliate Open API | Solicitar acesso via https://help.shopee.com.br |

---

## 4. Componentes do Opportunity Score (Validado)

Com `shopOfferV2`, temos:

✅ **Comissão** (`commissionRate`)  
✅ **Rating da loja** (`ratingStar`) — proxy de demanda/qualidade  
✅ **Tipo de loja** (`shopType`) — confiança (1=oficial, 2/4=preferred)  
✅ **Saúde da oferta** (`remainingBudget`) — risco de expiração  
✅ **Cobertura de comissão** (`sellerCommCoveRatio`) — % de produtos com comissão  
✅ **Validade** (`periodStartTime`, `periodEndTime`)  
✅ **Recursos visuais** (`bannerInfo`) — para criativos  

❌ **Demanda histórica** (vendas, cliques) — usar LLM ou não disponível

---

## 5. Limitações Conhecidas

- Não há query para **demanda histórica** (vendas, visualizações) do produto/oferta
- `ratingStar` é da **loja**, não do **produto** — é um proxy
- Requer autenticação com credenciais de afiliado aprovado
- Sujeito a rate limits (código 10030)

---

## 6. Implementação no Projeto

### ShopeeAdapter Methods

```python
class ShopeeAdapter(MarketplaceAdapter):
    
    def search_products(
        self,
        keyword: str = None,
        page: int = 1,
        limit: int = 10,
        sort_by: str = "commission"
    ) -> List[Product]:
        """Query shopeeOfferV2 — ofertas gerais"""
        # graphql call para shopeeOfferV2
        
    def search_shops(
        self,
        keyword: str = None,
        shop_type: List[int] = None,
        is_key_seller: bool = None,
        page: int = 1,
        limit: int = 10
    ) -> List[Shop]:
        """Query shopOfferV2 — ofertas por loja"""
        # graphql call para shopOfferV2
        
    def get_shop_offers(
        self,
        shop_id: int,
        page: int = 1,
        limit: int = 10
    ) -> List[ShopOffer]:
        """Query shopOfferV2 com shopId"""
        # Conveniência para buscar ofertas de uma loja específica
```

### ShopeeAuth Class

```python
class ShopeeAuth:
    def sign_request(
        self,
        app_id: str,
        payload: dict,
        secret: str
    ) -> str:
        """Gera SHA256 signature"""
        timestamp = int(time.time())
        payload_str = json.dumps(payload, separators=(',', ':'))
        message = f"{app_id}{timestamp}{payload_str}{secret}"
        signature = hashlib.sha256(message.encode()).hexdigest()
        
        return f"SHA256 Credential={app_id}, Signature={signature}, Timestamp={timestamp}"
```



---

## 7. ProductOfferV2 Query (Ofertas por Produto)

**A query mais granular — retorna dados por PRODUTO INDIVIDUAL.**

### Query
```graphql
query productOfferV2(
  $shopId: Int64
  $itemId: Int64
  $productCatId: Int32
  $listType: Int
  $matchId: Int64
  $keyword: String
  $sortType: Int
  $isAMSOffer: Bool
  $isKeySeller: Bool
  $page: Int
  $limit: Int
) {
  productOfferV2(...) {
    nodes { /* ProductOfferV2 fields */ }
    pageInfo { /* PageInfo */ }
  }
}
```

### Parameters

| Field | Type | Required | Values | Description |
|---|---|---|---|---|
| `shopId` | Int64 | No | 84499012 | Buscar por ID da loja (NEW) |
| `itemId` | Int64 | No | 17979995178 | Buscar por ID do item/produto (NEW) |
| `productCatId` | Int32 | No | 100001 | Filtrar por categoria (Nível 1/2/3) (NEW) |
| `listType` | Int | No | 0-6 | Tipo de lista (recomendação, categoria, loja, etc.) |
| `matchId` | Int64 | No | 10012 | ID para filtro de listType (categoria/loja/coleção) |
| `keyword` | String | No | "shopee" | Buscar por nome do produto |
| `sortType` | Int | No | 1-5 | 1=RELEVANCE, 2=SOLD_DESC, 3=PRICE_DESC, 4=PRICE_ASC, 5=COMMISSION_DESC |
| `isAMSOffer` | Bool | No | true/false | Apenas ofertas com comissão do seller (AMS) (NEW) |
| `isKeySeller` | Bool | No | true/false | Apenas de "key sellers" (NEW) |
| `page` | Int | No | 2 | Página |
| `limit` | Int | No | 10 | Itens/página |

### ListType Values

| Valor | Significado |
|---|---|
| `0` | ALL — Lista de recomendação (sem sort) |
| `1` | HIGHEST_COMMISSION — Comissão mais alta (deprecated) |
| `2` | TOP_PERFORMING — Produtos top (sem sort) |
| `3` | LANDING_CATEGORY — Categoria landing page (sem sort) |
| `4` | DETAIL_CATEGORY — Categoria específica (com sort) |
| `5` | DETAIL_SHOP — Loja específica (com sort) |
| `6` | DETAIL_COLLECTION — Coleção (deprecated) |

### SortType Values

| Valor | Significado | Compatível |
|---|---|---|
| `1` | RELEVANCE_DESC | Apenas keyword search |
| `2` | ITEM_SOLD_DESC | Vendas altas primeiro |
| `3` | PRICE_DESC | Preço alto primeiro |
| `4` | PRICE_ASC | Preço baixo primeiro |
| `5` | COMMISSION_DESC | Comissão alta primeiro |

### Response: ProductOfferV2

| Field | Type | Description | Novo? | ✅ Usado em |
|---|---|---|---|---|
| `itemId` | Int64 | ID único do produto | — | ✅ Identificação |
| `commissionRate` | String | Taxa máxima de comissão | — | ✅ **Opportunity Score** |
| `sellerCommissionRate` | String | Comissão do seller (AMS) | NEW ✅ | ✅ **Oportunidade** |
| `shopeeCommissionRate` | String | Comissão do Shopee | NEW ✅ | ✅ Contexto |
| `commission` | String | Comissão calculada (preço × taxa) | NEW ✅ | ✅ **Receita potencial** |
| `sales` | Int32 | **Número de vendas** | — | ✅ **DEMANDA (crítico!)** |
| `priceMax` | String | Preço máximo | NEW ✅ | ✅ **Contexto econômico** |
| `priceMin` | String | Preço mínimo | NEW ✅ | ✅ **Contexto econômico** |
| `productCatIds` | [Int] | Categorias (L1, L2, L3) | NEW ✅ | ✅ Filtro/contexto |
| `ratingStar` | String | **Rating do produto** | NEW ✅ | ✅ **DEMANDA (qualidade)** |
| `priceDiscountRate` | Int | Taxa de desconto (%) | NEW ✅ | ✅ Atratividade |
| `imageUrl` | String | URL da imagem do produto | — | ✅ Conteúdo/creative |
| `productName` | String | Nome do produto | — | ✅ Título |
| `shopId` | Int64 | ID da loja | NEW ✅ | ✅ Contexto |
| `shopName` | String | Nome da loja | — | ✅ Contexto |
| `shopType` | [Int] | Tipo de loja (oficial/preferred) | NEW ✅ | ✅ Confiança |
| `productLink` | String | Link do produto Shopee | — | ✅ Tracking |
| `offerLink` | String | Link da oferta encurtada | — | ✅ Tracking |
| `periodStartTime` | Int | Unix timestamp início | — | ✅ Validade |
| `periodEndTime` | Int | Unix timestamp fim | — | ✅ Validade |

### Deprecated Fields (To Be Removed)

```
appExistRate, appNewRate, webExistRate, webNewRate, price
HIGHEST_COMMISSION (listType), DETAIL_COLLECTION (listType)
```

---

## 8. UNKNOWN-6 COMPLETAMENTE RESOLVIDO! ✅✅✅

Com `productOfferV2`, temos **TODOS** os dados necessários para Opportunity Score:

| Componente | Campo | Tipo | Exemplo | Confiança |
|---|---|---|---|---|
| **Comissão** | `commissionRate` | String | "0.0123" (1.23%) | ✅✅✅ Alto |
| **Demanda** | `sales` | Int | 25 vendas | ✅✅✅ **Alto (fato real)** |
| **Qualidade** | `ratingStar` | String | "4.7" ⭐ | ✅✅✅ Alto |
| **Preço** | `priceMin`, `priceMax` | String | "45.99" - "55.99" | ✅✅✅ Alto |
| **Desconto** | `priceDiscountRate` | Int | 10% | ✅✅✅ Atratividade |
| **Receita potencial** | `commission` | String | "27000" BRL | ✅✅✅ Alto |
| **Tipo de loja** | `shopType` | [Int] | [1, 4] | ✅✅✅ Confiança |
| **Validade** | `periodStart/End` | Int | 1687539600 | ✅✅✅ Alto |

---

## 9. Oportunidade Score — Formula Completa

```
OpportunityScore = (
    w_commission  × normalize(commissionRate) +
    w_sales       × normalize(sales) +
    w_rating      × normalize(ratingStar) +
    w_price       × normalize(commission_value) +
    w_shop_trust  × shopType_score +
    w_discount    × normalize(priceDiscountRate) +
    w_time        × remaining_days_factor
) × 100

Onde:
- normalize(x) = (x - min) / (max - min) [0..1]
- shopType_score = 1.0 (oficial) > 0.8 (preferred+) > 0.6 (preferred) > 0.5 (outro)
- remaining_days_factor = 1.0 (>30 dias) > 0.5 (7-30 dias) > 0.2 (<7 dias)
- weights (w_*) configuráveis, default = 0.25 cada
```

---

## 10. Três Queries de Shopee — Caso de Uso

### ShopeeOfferV2 — Exploração
```
Quando: Descoberta inicial (Discovery phase)
Retorna: Ofertas gerais com comissão alta, ratings, risco
Uso: Encontrar "hotspots" de oportunidade (lojas, tipos)
```

### ShopOfferV2 — Filtragem
```
Quando: Después de ShopeeOfferV2 (Qualification phase)
Retorna: Ofertas por loja com detalhes de budget
Uso: Validar saúde da loja, risco de expiração
```

### ProductOfferV2 — Granular
```
Quando: Scores e decisão (Opportunity Scoring phase)
Retorna: Dados por PRODUTO com vendas, rating, preço
Uso: Oportunidade Score definitivo
```

**Fluxo recomendado:**
```
ShopeeOfferV2 (find high-commission offers)
  → ShopOfferV2 (validate shop health)
    → ProductOfferV2 (detailed product scoring)
      → Opportunity Score
        → Add to CANDIDATE
```

---

## 11. Campos de Categoria

Shopee usa **3 níveis de categoria** (Level 1, 2, 3).

Exemplo: `productCatIds = [100012, 100068, 100259]`
- Level 1: 100012 (Categoria geral)
- Level 2: 100068 (Subcategoria)
- Level 3: 100259 (Subcategoria específica)

**Referências por país:**
- BR: https://seller.shopee.com.br/edu/category-guide
- (Outros países acima no schema)

---

## 12. Implementação no ShopeeAdapter

```python
class ShopeeAdapter(MarketplaceAdapter):
    
    def search_offers_general(
        self,
        keyword: str = None,
        sort_by: str = "commission",
        limit: int = 100
    ) -> List[Offer]:
        """ShopeeOfferV2 — ofertas gerais (discovery)"""
        
    def search_offers_by_shop(
        self,
        shop_id: int,
        limit: int = 50
    ) -> List[ShopOffer]:
        """ShopOfferV2 — ofertas de uma loja (validation)"""
        
    def search_products(
        self,
        keyword: str = None,
        category_id: int = None,
        sort_by: str = "commission",
        limit: int = 100,
        is_key_seller: bool = True,
        is_ams_offer: bool = True
    ) -> List[ProductOffer]:
        """ProductOfferV2 — produtos com scores detalhados (scoring)"""
        # Retorna: itemId, commissionRate, sales, ratingStar, 
        #          priceMin/Max, commission (calculado), shopType
        
    def get_product_opportunity_score(
        self,
        product: ProductOffer
    ) -> float:
        """Calcula Opportunity Score usando ProductOfferV2 data"""
        # Formula acima (§9)
```

