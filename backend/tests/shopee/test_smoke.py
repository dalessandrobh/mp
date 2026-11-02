from app.adapters.marketplace.shopee.smoke import run
from tests.shopee.fakes import FakeShopee, error
from tests.shopee.test_adapter import _adapter, _node, _report_node, _scrolling


def _server(**overrides) -> FakeShopee:
    handlers = {
        "productOfferV2": lambda v, n: {
            "productOfferV2": {"nodes": [_node(1), _node(2)], "pageInfo": {"hasNextPage": False}}
        },
        "conversionReport": _scrolling([[_report_node("A")]], "conversionReport"),
        "validatedReport": _scrolling([[_report_node("B")]], "validatedReport"),
        "generateShortLink": lambda v, n: {"generateShortLink": {"shortLink": "https://shp.ee/x"}},
    }
    return FakeShopee(**{**handlers, **overrides})


def test_smoke_passes_when_everything_answers():
    lines: list[str] = []

    code = run(_adapter(_server()), short_link=True, out=lines.append)

    text = "\n".join(lines)
    assert code == 0 and "PASSOU" in text and "https://shp.ee/x" in text


def test_smoke_does_not_create_a_link_unless_asked():
    server = _server()

    run(_adapter(server), short_link=False, out=lambda s: None)

    assert all(c["operation"] != "generateShortLink" for c in server.calls)


def test_smoke_reports_each_failing_step_and_keeps_going():
    lines: list[str] = []
    server = _server(conversionReport=lambda v, n: error(10035, "No access to Shopee Affiliate"))

    code = run(_adapter(server), short_link=False, out=lines.append)

    text = "\n".join(lines)
    assert code == 1 and "[10035]" in text and "validatedReport" in text and "1 etapa" in text


def test_smoke_never_prints_credentials():
    lines: list[str] = []

    run(_adapter(_server()), short_link=True, out=lines.append)

    assert "segredo-de-teste" not in "\n".join(lines)
