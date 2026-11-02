import json
from datetime import date

import pytest

from app.adapters.marketplace.registry import get_marketplace_adapter
from app.adapters.marketplace.shopee.adapter import ShopeeAdapter
from app.adapters.marketplace.shopee.auth import ShopeeAuth
from app.adapters.marketplace.shopee.client import (
    ShopeeClient,
    ShopeeError,
    ShopeeInvalidParams,
)
from app.core.config import Settings
from tests.shopee.fakes import APP_ID, SECRET, FakeShopee, error


def _adapter(server: FakeShopee, validation_ids: tuple[int, ...] = (555,)) -> ShopeeAdapter:
    return ShopeeAdapter(
        ShopeeClient(
            url="https://shopee.test/graphql",
            auth=ShopeeAuth(APP_ID, SECRET),
            http=server.client(),
            min_interval=0,
            sleep=lambda s: None,
        ),
        validation_ids=validation_ids,
    )


def _node(i: int) -> dict:
    return {
        "itemId": i, "productName": f"Produto {i}", "productLink": f"https://s/{i}",
        "priceMin": "10.00", "commissionRate": "0.05", "sales": i, "ratingStar": "4.5",
    }


def test_the_adapter_declares_what_the_api_never_reports():
    assert ShopeeAdapter.unsupported_fields == {"stock", "rating_count", "original_price"}


# ---------- produtos ----------


def test_search_pages_until_the_limit_and_stops():
    def handler(variables, n):
        start = (variables["page"] - 1) * variables["limit"]
        return {
            "productOfferV2": {
                "nodes": [_node(start + i) for i in range(variables["limit"])],
                "pageInfo": {"hasNextPage": True},
            }
        }

    server = FakeShopee(productOfferV2=handler)

    offers = _adapter(server).search_products(limit=45)

    assert len(offers) == 45
    assert [c["variables"]["page"] for c in server.calls] == [1, 2, 3]
    assert all(c["variables"]["listType"] == 2 for c in server.calls)  # sem palavra-chave: top
    # Página de tamanho constante: com tamanhos diferentes a página 2 releria itens da 1.
    assert [c["variables"]["limit"] for c in server.calls] == [20, 20, 20]


def test_an_offer_repeated_between_pages_is_returned_once():
    pages = {1: [_node(1), _node(2)], 2: [_node(2), _node(3)]}
    server = FakeShopee(
        productOfferV2=lambda v, n: {
            "productOfferV2": {
                "nodes": pages[v["page"]],
                "pageInfo": {"hasNextPage": v["page"] < 2},
            }
        }
    )

    offers = _adapter(server).search_products(limit=10)

    assert [o.external_product_id for o in offers] == ["1", "2", "3"]


def test_search_stops_when_the_api_has_no_more_pages():
    server = FakeShopee(
        productOfferV2=lambda v, n: {
            "productOfferV2": {"nodes": [_node(1)], "pageInfo": {"hasNextPage": False}}
        }
    )

    assert len(_adapter(server).search_products(limit=100)) == 1
    assert len(server.calls) == 1


def test_search_skips_malformed_products_and_omits_an_empty_keyword():
    nodes = [_node(1), {"itemId": None, "productName": "x"}, _node(2)]
    server = FakeShopee(
        productOfferV2=lambda v, n: {
            "productOfferV2": {"nodes": nodes, "pageInfo": {"hasNextPage": False}}
        }
    )

    offers = _adapter(server).search_products(keyword="", limit=10)

    assert [o.external_product_id for o in offers] == ["1", "2"]
    assert "keyword" not in server.calls[0]["variables"]


def test_search_with_a_keyword_sorts_by_sales_on_the_plain_list():
    server = FakeShopee(
        productOfferV2=lambda v, n: {"productOfferV2": {"nodes": [], "pageInfo": {}}}
    )

    _adapter(server).search_products(keyword="fone", limit=5)

    variables = server.calls[0]["variables"]
    assert variables["keyword"] == "fone" and variables["sortType"] == 2
    assert variables["listType"] == 0


def test_search_without_a_keyword_uses_top_performing_and_sends_no_sort():
    server = FakeShopee(
        productOfferV2=lambda v, n: {"productOfferV2": {"nodes": [], "pageInfo": {}}}
    )

    _adapter(server).search_products(limit=5)

    variables = server.calls[0]["variables"]
    assert variables["listType"] == 2 and "sortType" not in variables
    assert "keyword" not in variables


# ---------- links ----------


def test_short_link_mutation_escapes_the_url_and_sends_every_sub_id():
    server = FakeShopee(
        generateShortLink=lambda v, n: {"generateShortLink": {"shortLink": "https://shp.ee/AbC"}}
    )
    url = 'https://shopee.com.br/p-i.1.2?a="x"&b=\\y'

    link = _adapter(server).generate_affiliate_link(origin_url=url, sub_ids=("s-1", 'q"uote'))

    query = server.calls[0]["query"]
    assert json.dumps(url) in query and '"q\\"uote"' in query
    assert link.short_url == "https://shp.ee/AbC" and link.sub_ids == ("s-1", 'q"uote')


def test_short_link_rejects_zero_or_too_many_sub_ids_before_calling_the_api():
    server = FakeShopee(generateShortLink=lambda v, n: {})

    for bad in ((), tuple(f"s{i}" for i in range(6))):
        with pytest.raises(ShopeeError, match="subIds"):
            _adapter(server).generate_affiliate_link(origin_url="https://x", sub_ids=bad)

    assert server.calls == []


def test_short_link_without_a_link_in_the_answer_is_an_error():
    server = FakeShopee(generateShortLink=lambda v, n: {"generateShortLink": {"shortLink": ""}})

    with pytest.raises(ShopeeError, match="shortLink"):
        _adapter(server).generate_affiliate_link(origin_url="https://x", sub_ids=("a",))


# ---------- conversões ----------


def _report_node(order_id: str, when: int = 1788748200) -> dict:
    return {
        "utmContent": "shp-x", "purchaseTime": when, "orderStatus": "COMPLETED",
        "orders": [{"orderId": order_id, "orderStatus": "COMPLETED",
                    "items": [{"actualAmount": "10", "itemTotalCommission": "1.00"}]}],
    }


def _scrolling(pages: list[list[dict]], root: str):
    def handler(variables, n):
        index = 0 if "scrollId" not in variables else int(variables["scrollId"])
        last = index == len(pages) - 1
        return {
            root: {
                "nodes": pages[index],
                "pageInfo": {"hasNextPage": not last, "scrollId": None if last else str(index + 1)},
            }
        }

    return handler


def test_conversions_scroll_through_every_page_in_one_go():
    pages = [[_report_node("A"), _report_node("B")], [_report_node("C")], [_report_node("D")]]
    server = FakeShopee(conversionReport=_scrolling(pages, "conversionReport"))

    records = _adapter(server).fetch_conversions(since=date(2026, 9, 1), until=date(2026, 9, 7))

    assert [r.external_order_id for r in records] == ["A", "B", "C", "D"]
    assert [c["variables"].get("scrollId") for c in server.calls] == [None, "1", "2"]
    # A 1ª página nem declara o argumento (declarado sem valor a API recusa a consulta).
    assert "$scrollId" not in server.calls[0]["query"]
    assert "$scrollId: String" in server.calls[1]["query"]


def test_conversion_window_is_the_brazilian_day_boundaries():
    server = FakeShopee(conversionReport=_scrolling([[]], "conversionReport"))

    _adapter(server).fetch_conversions(since=date(2026, 9, 6), until=date(2026, 9, 6))

    variables = server.calls[0]["variables"]
    # 06/09 00:00 e 23:59:59 em Brasília (UTC-3).
    # Int64 vai como string (medido na API real: como número ela responde "wrong type").
    assert variables["purchaseTimeStart"] == "1788663600"
    assert variables["purchaseTimeEnd"] == str(1788663600 + 86399)
    assert variables["limit"] == 500
    # Na API real as datas são Int64 (com Int a consulta é recusada: erro 10010).
    assert "$purchaseTimeStart: Int64" in server.calls[0]["query"]


def test_expired_scroll_restarts_from_scratch_once_without_duplicating():
    state = {"expired": False}

    def handler(variables, n):
        if variables.get("scrollId") == "1" and not state["expired"]:
            state["expired"] = True
            return error(11001, "Params Error: scrollId expired")
        pages = [[_report_node("A")], [_report_node("B")]]
        return _scrolling(pages, "conversionReport")(variables, n)

    server = FakeShopee(conversionReport=handler)

    records = _adapter(server).fetch_conversions(since=date(2026, 9, 1), until=date(2026, 9, 7))

    assert [r.external_order_id for r in records] == ["A", "B"]  # sem o "A" repetido


def test_a_scroll_that_expires_twice_is_a_real_error():
    def handler(variables, n):
        if variables.get("scrollId"):
            return error(11001, "scrollId expired")
        return {"conversionReport": {"nodes": [_report_node("A")],
                                     "pageInfo": {"hasNextPage": True, "scrollId": "1"}}}

    with pytest.raises(ShopeeInvalidParams):
        _adapter(FakeShopee(conversionReport=handler)).fetch_conversions(
            since=date(2026, 9, 1), until=date(2026, 9, 7)
        )


def test_an_invalid_first_request_is_not_retried_as_an_expired_scroll():
    server = FakeShopee(conversionReport=lambda v, n: error(11001, "bad params"))

    with pytest.raises(ShopeeInvalidParams):
        _adapter(server).fetch_conversions(since=date(2026, 9, 1), until=date(2026, 9, 7))

    assert len(server.calls) == 1


def test_validated_report_is_filtered_to_the_requested_days():
    inside, outside = _report_node("IN", 1788748200), _report_node("OUT", 1767225600)
    server = FakeShopee(validatedReport=_scrolling([[inside, outside]], "validatedReport"))

    records = _adapter(server).fetch_validated_conversions(
        since=date(2026, 9, 1), until=date(2026, 9, 30)
    )

    assert [r.external_order_id for r in records] == ["IN"]
    assert records[0].status == "COMPLETED"


def test_validated_report_is_asked_once_per_validation_id():
    server = FakeShopee(validatedReport=_scrolling([[_report_node("X")]], "validatedReport"))

    _adapter(server, validation_ids=(11, 22)).fetch_validated_conversions(
        since=date(2026, 9, 1), until=date(2026, 9, 30)
    )

    assert [c["variables"]["validationId"] for c in server.calls] == ["11", "22"]
    assert "$validationId: Int64!" in server.calls[0]["query"]


def test_without_validation_ids_there_is_nothing_to_ask_and_nothing_settles():
    server = FakeShopee(validatedReport=_scrolling([[_report_node("X")]], "validatedReport"))

    records = _adapter(server, validation_ids=()).fetch_validated_conversions(
        since=date(2026, 9, 1), until=date(2026, 9, 30)
    )

    assert records == [] and server.calls == []


def test_validation_ids_come_from_the_settings():
    settings = Settings(_env_file=None, shopee_validation_ids=" 101, 202 ,")

    assert settings.validation_ids == (101, 202)
    assert Settings(_env_file=None).validation_ids == ()


# ---------- registro ----------


def test_registry_builds_the_shopee_adapter_when_mock_is_off():
    settings = Settings(
        _env_file=None, mock_marketplace=False, shopee_app_id="1", shopee_secret="s"
    )

    adapter = get_marketplace_adapter(settings)

    assert isinstance(adapter, ShopeeAdapter)


def test_registry_keeps_the_mock_by_default():
    assert get_marketplace_adapter(Settings(_env_file=None)).code == "mock"


def test_real_marketplace_without_credentials_does_not_even_start():
    with pytest.raises(ValueError, match="SHOPEE_APP_ID"):
        Settings(_env_file=None, mock_marketplace=False)


def test_default_endpoint_is_the_one_that_resolves():
    assert Settings(_env_file=None).shopee_api_url.endswith("shopee.com.br/graphql")
