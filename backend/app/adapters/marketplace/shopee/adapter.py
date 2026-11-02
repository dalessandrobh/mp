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
MAX_SUB_IDS = 5

_PRODUCT_QUERY = f"""
query productOfferV2(
  $keyword: String, $sortType: Int, $listType: Int, $page: Int, $limit: Int
) {{
  productOfferV2(
    keyword: $keyword, sortType: $sortType, listType: $listType, page: $page, limit: $limit
  ) {{
    nodes {{ {mapping.PRODUCT_FIELDS} }}
    pageInfo {{ page limit hasNextPage }}
  }}
}}
"""

_CONVERSION_QUERY = f"""
query conversionReport(
  $purchaseTimeStart: Int, $purchaseTimeEnd: Int, $limit: Int, $scrollId: String
) {{
  conversionReport(
    purchaseTimeStart: $purchaseTimeStart, purchaseTimeEnd: $purchaseTimeEnd,
    limit: $limit, scrollId: $scrollId
  ) {{
    nodes {{ {mapping.CONVERSION_FIELDS} }}
    pageInfo {{ limit hasNextPage scrollId }}
  }}
}}
"""

_VALIDATED_QUERY = f"""
query validatedReport($limit: Int, $scrollId: String) {{
  validatedReport(limit: $limit, scrollId: $scrollId) {{
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

    def __init__(self, client: ShopeeClient, *, sort_type: int = SORT_ITEM_SOLD_DESC) -> None:
        self._client = client
        self._sort_type = sort_type

    @classmethod
    def from_settings(cls, settings: Settings) -> "ShopeeAdapter":
        return cls(
            ShopeeClient(
                url=settings.shopee_api_url,
                auth=ShopeeAuth(settings.shopee_app_id, settings.shopee_secret),
                timeout=settings.shopee_timeout_seconds,
                min_interval=settings.shopee_min_interval_seconds,
                max_retries=settings.shopee_max_retries,
            )
        )

    # ---------------------------------------------------------------- produtos

    def search_products(
        self, *, keyword: str | None = None, limit: int = 50
    ) -> list[ProductOffer]:
        offers: list[ProductOffer] = []
        page = 1
        # keyword vazio vira None: a API trata "" como busca por nada.
        while len(offers) < limit:
            variables = {
                "keyword": keyword or None,
                "sortType": self._sort_type,
                "listType": 0,
                "page": page,
                "limit": min(PAGE_SIZE_PRODUCTS, limit - len(offers)),
            }
            present = {k: v for k, v in variables.items() if v is not None}
            data = self._client.execute(_PRODUCT_QUERY, present)
            block = data.get("productOfferV2") or {}
            for node in block.get("nodes") or []:
                offer = mapping.offer_from_product(node)
                if offer is None:
                    logger.warning("shopee_product_skipped", extra={"itemId": node.get("itemId")})
                    continue
                offers.append(offer)
            if not (block.get("pageInfo") or {}).get("hasNextPage"):
                break
            page += 1
        return offers[:limit]

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
        variables = {
            "purchaseTimeStart": _start_of_day(since),
            "purchaseTimeEnd": _end_of_day(until),
        }
        nodes = self._scroll(_CONVERSION_QUERY, "conversionReport", variables)
        return [r for node in nodes for r in mapping.records_from_conversion(node)]

    def fetch_validated_conversions(
        self, *, since: date, until: date, hint_sub_ids: Sequence[str] = ()
    ) -> list[ConversionRecord]:
        """ValidatedReport: comissão FINAL.

        A query documentada não tem filtro de data (só `validationId`, o lote de liquidação),
        então traz o que a API devolver e filtramos o intervalo aqui.
        """
        nodes = self._scroll(_VALIDATED_QUERY, "validatedReport", {})
        records = [r for node in nodes for r in mapping.records_from_validated(node)]
        return [r for r in records if since <= r.conversion_date <= until]

    def _scroll(self, query: str, root: str, variables: dict) -> list[dict]:
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
