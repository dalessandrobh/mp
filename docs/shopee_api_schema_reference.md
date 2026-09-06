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

