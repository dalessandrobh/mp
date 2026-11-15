"""ShopeeAdapter: Shopee Afiliados BR via GraphQL (Fase 9).

Só chama operações documentadas. O que a API NÃO entrega é declarado em
`unsupported_fields`, para o score saber que a ausência é estrutural (a Shopee nunca
informa) e não um dado que falhou em chegar.
"""

import json
import logging
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta

from app.adapters.marketplace.base import (
    SORT_PRICE_DESC,
    SORT_SALES,
    AffiliateLink,
    ConversionRecord,
    MarketplaceAdapter,
    ProductOffer,
)
from app.adapters.marketplace.shopee import mapping
from app.adapters.marketplace.shopee.auth import ShopeeAuth
from app.adapters.marketplace.shopee.client import (
    ShopeeClient,
    ShopeeError,
    ShopeeInvalidParams,
)
from app.core.config import Settings

logger = logging.getLogger(__name__)

PAGE_SIZE_PRODUCTS = 20
PAGE_SIZE_REPORTS = 500  # máximo documentado para os relatórios
MAX_SCROLL_PAGES = 200
SORT_ITEM_SOLD_DESC = 2
SORT_PRICE_HIGH_TO_LOW = 3
# Ordenações documentadas: 1=RELEVANCE, 2=SOLD_DESC, 3=PRICE_DESC, 4=PRICE_ASC,
# 5=COMMISSION_DESC. A 5 está fora de propósito: medido, devolve item de 50% de comissão
# e zero venda. A 3 serve porque a comissão em dinheiro cresce com o preço, e a venda
# mínima é exigida depois, no serviço.
_SORT_TYPES = {SORT_SALES: SORT_ITEM_SOLD_DESC, SORT_PRICE_DESC: SORT_PRICE_HIGH_TO_LOW}
LIST_ALL = 0  # recomendação sem ordem (ruído: muitos itens sem venda)
LIST_TOP_PERFORMING = 2  # os que mais performam; a API não aceita ordenação aqui
LIST_BY_CATEGORY = 3  # com `matchId` = categoria; medido: funciona em todas, com sortType
MAX_ITEMS_PER_LIST = 500  # teto medido: 25 páginas de 20
MAX_SUB_IDS = 5

_PRODUCT_QUERY = f"""
query productOfferV2(
  $keyword: String, $sortType: Int, $listType: Int, $page: Int, $limit: Int,
  $matchId: Int64
) {{
  productOfferV2(
    keyword: $keyword, sortType: $sortType, listType: $listType, page: $page, limit: $limit,
    matchId: $matchId
  ) {{
    nodes {{ {mapping.PRODUCT_FIELDS} }}
    pageInfo {{ page limit hasNextPage }}
  }}
}}
"""

# Busca por id: `itemId` sozinho basta (medido na API real em 15/11/2026, inclusive para item
# que nunca apareceu em nenhuma varredura nossa). Int64 vai como string.
_PRODUCT_BY_ID_QUERY = f"""
query productById($itemId: Int64) {{
  productOfferV2(itemId: $itemId, limit: 1) {{
    nodes {{ {mapping.PRODUCT_FIELDS} }}
  }}
}}
"""


def _conversion_query(*, scrolling: bool) -> str:
    # O argumento `scrollId` só entra a partir da 2ª página: declarado e sem valor, a API
    # recusa a consulta ("got null for non-null", erro 10010) — medido na API real.
    declare = ", $scrollId: String" if scrolling else ""
    use = ", scrollId: $scrollId" if scrolling else ""
    return f"""
query conversionReport(
  $purchaseTimeStart: Int64, $purchaseTimeEnd: Int64, $limit: Int{declare}
) {{
  conversionReport(
    purchaseTimeStart: $purchaseTimeStart, purchaseTimeEnd: $purchaseTimeEnd,
    limit: $limit{use}
  ) {{
    nodes {{ {mapping.CONVERSION_FIELDS} }}
    pageInfo {{ limit hasNextPage scrollId }}
  }}
}}
"""


def _validated_query(*, scrolling: bool) -> str:
    declare = ", $scrollId: String" if scrolling else ""
    use = ", scrollId: $scrollId" if scrolling else ""
    return f"""
query validatedReport($validationId: Int64!, $limit: Int{declare}) {{
  validatedReport(validationId: $validationId, limit: $limit{use}) {{
    nodes {{ {mapping.VALIDATED_FIELDS} }}
    pageInfo {{ limit hasNextPage scrollId }}
  }}
}}
"""


class ShopeeAdapter(MarketplaceAdapter):
    code = "shopee"
    display_name = "Shopee Afiliados BR"
    # A API nunca informa estes campos: ausência estrutural, não falha de coleta.
    unsupported_fields = frozenset({"stock", "rating_count", "original_price"})

    def __init__(
        self,
        client: ShopeeClient,
        *,
        sort_type: int = SORT_ITEM_SOLD_DESC,
        validation_ids: Sequence[int] = (),
    ) -> None:
        self._client = client
        self._sort_type = sort_type
        self._validation_ids = tuple(validation_ids)

    @classmethod
    def from_settings(cls, settings: Settings) -> "ShopeeAdapter":
        return cls(
            ShopeeClient(
                url=settings.shopee_api_url,
                auth=ShopeeAuth(settings.shopee_app_id, settings.shopee_secret),
                timeout=settings.shopee_timeout_seconds,
                min_interval=settings.shopee_min_interval_seconds,
                max_retries=settings.shopee_max_retries,
            ),
            validation_ids=settings.validation_ids,
        )

    # ---------------------------------------------------------------- produtos

    def search_products(
        self,
        *,
        keyword: str | None = None,
        limit: int = 50,
        category: str | None = None,
        sort: str | None = None,
    ) -> list[ProductOffer]:
        offers: list[ProductOffer] = []
        page = 1
        if sort is not None and sort not in _SORT_TYPES:
            raise ShopeeError(f"ordenação desconhecida: {sort}")
        sort_type = _SORT_TYPES[sort] if sort else self._sort_type
        # Medido na API real: sem palavra-chave, a lista "recomendada" (0) devolve muito item
        # sem venda; "top performing" (2) devolve os que vendem, mas não aceita ordenação. Com
        # palavra-chave, a lista 0 + ordenação por vendas é a que funciona (ordenar por
        # comissão traz itens de 50% de comissão e zero venda).
        keyword = keyword or None  # "" vira "sem busca"
        list_type = LIST_ALL if keyword else LIST_TOP_PERFORMING
        if category:
            # `productCatId` sozinho falha em algumas categorias (erro 10000); listType 3 +
            # matchId funciona em todas. Int64 vai como string.
            list_type = LIST_BY_CATEGORY
        limit = min(limit, MAX_ITEMS_PER_LIST)
        seen: set[str] = set()
        while len(offers) < limit:
            # Tamanho de página CONSTANTE: `page` é um índice sobre esse tamanho. Pedir 20 e depois
            # 10 faria a página 2 reler itens da 1 (medido na API real: 30 pedidos, 20 únicos).
            variables = {
                "keyword": keyword,
                "sortType": sort_type if (keyword or category) else None,
                "listType": list_type,
                "matchId": str(category) if category else None,
                "page": page,
                "limit": PAGE_SIZE_PRODUCTS,
            }
            present = {k: v for k, v in variables.items() if v is not None}
            data = self._client.execute(_PRODUCT_QUERY, present)
            block = data.get("productOfferV2") or {}
            for node in block.get("nodes") or []:
                offer = mapping.offer_from_product(node)
                if offer is None:
                    logger.warning("shopee_product_skipped", extra={"itemId": node.get("itemId")})
                    continue
                if offer.external_product_id in seen:
                    continue  # a mesma oferta pode reaparecer entre páginas
                seen.add(offer.external_product_id)
                offers.append(offer)
            if not (block.get("pageInfo") or {}).get("hasNextPage"):
                break
            page += 1
        return offers[:limit]

    def get_product(self, external_product_id: str) -> ProductOffer | None:
        data = self._client.execute(_PRODUCT_BY_ID_QUERY, {"itemId": str(external_product_id)})
        for node in (data.get("productOfferV2") or {}).get("nodes") or []:
            offer = mapping.offer_from_product(node)
            if offer is not None and offer.external_product_id == str(external_product_id):
                return offer
        return None

    # ------------------------------------------------------------------- links

    def generate_affiliate_link(
        self, *, origin_url: str, sub_ids: tuple[str, ...]
    ) -> AffiliateLink:
        if not 1 <= len(sub_ids) <= MAX_SUB_IDS:
            raise ShopeeError(
                f"a Shopee aceita de 1 a {MAX_SUB_IDS} subIds, recebi {len(sub_ids)}"
            )
        # A mutation vai inline (o tipo do input não é documentado): json.dumps produz
        # literais de string válidos em GraphQL e escapa aspas e barras do valor.
        subs = ", ".join(_literal(s) for s in sub_ids)
        query = (
            "mutation { generateShortLink(input: {"
            f"originUrl: {_literal(origin_url)}, subIds: [{subs}]"
            "}) { shortLink } }"
        )
        data = self._client.execute(query)
        short = ((data.get("generateShortLink") or {}).get("shortLink") or "").strip()
        if not short:
            raise ShopeeError("generateShortLink não devolveu shortLink")
        return AffiliateLink(short_url=short, sub_ids=sub_ids)

    # -------------------------------------------------------------- conversões

    def fetch_conversions(
        self, *, since: date, until: date, hint_sub_ids: Sequence[str] = ()
    ) -> list[ConversionRecord]:
        """ConversionReport: comissão ESTIMADA. Filtra por data do clique/compra."""
        # Int64 vai como STRING no JSON: como número a API recusa ("wrong type", erro 10010).
        variables = {
            "purchaseTimeStart": str(_start_of_day(since)),
            "purchaseTimeEnd": str(_end_of_day(until)),
        }
        nodes = self._scroll(_conversion_query, "conversionReport", variables)
        return [r for node in nodes for r in mapping.records_from_conversion(node)]

    def fetch_validated_conversions(
        self, *, since: date, until: date, hint_sub_ids: Sequence[str] = ()
    ) -> list[ConversionRecord]:
        """ValidatedReport: comissão FINAL.

        A API EXIGE `validationId` (o lote de liquidação, que só o painel de afiliado mostra em
        "Billing"): não existe consulta que liste os lotes. Sem IDs configurados
        (SHOPEE_VALIDATION_IDS) não há o que buscar, e nenhum dia vira SETTLED — o motor então
        nunca corta produto por ROI negativo, que é o lado seguro de errar.
        """
        if not self._validation_ids:
            logger.warning("shopee_no_validation_ids")
            return []
        records: list[ConversionRecord] = []
        for validation_id in self._validation_ids:
            nodes = self._scroll(
                _validated_query, "validatedReport", {"validationId": str(validation_id)}
            )
            records.extend(r for node in nodes for r in mapping.records_from_validated(node))
        return [r for r in records if since <= r.conversion_date <= until]

    def _scroll(self, build_query, root: str, variables: dict) -> list[dict]:
        """Pagina por scrollId, TUDO numa execução.

        O scrollId vale 30 s: não dá para dividir a paginação entre execuções. Se expirar
        no meio (11001), recomeça uma vez do zero; a segunda falha é erro de verdade.
        """
        for restart in range(2):
            nodes: list[dict] = []
            scroll_id: str | None = None
            try:
                for _ in range(MAX_SCROLL_PAGES):
                    page_vars = {**variables, "limit": PAGE_SIZE_REPORTS}
                    if scroll_id:
                        page_vars["scrollId"] = scroll_id
                    query = build_query(scrolling=scroll_id is not None)
                    block = self._client.execute(query, page_vars).get(root) or {}
                    nodes.extend(block.get("nodes") or [])
                    info = block.get("pageInfo") or {}
                    scroll_id = info.get("scrollId")
                    if not info.get("hasNextPage") or not scroll_id:
                        return nodes
                raise ShopeeError(f"{root}: mais de {MAX_SCROLL_PAGES} páginas, abortando")
            except ShopeeInvalidParams:
                if scroll_id is None or restart == 1:
                    raise
                logger.warning("shopee_scroll_expired", extra={"root": root})
        raise ShopeeError(f"{root}: scroll não concluiu")  # inalcançável; satisfaz o tipo


def _literal(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _start_of_day(day: date) -> int:
    return int(datetime.combine(day, time.min, mapping.LOCAL_TZ).timestamp())


def _end_of_day(day: date) -> int:
    next_midnight = datetime.combine(day + timedelta(days=1), time.min, mapping.LOCAL_TZ)
    return int(next_midnight.timestamp()) - 1
