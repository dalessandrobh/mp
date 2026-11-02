"""Pacote diário de conteúdo orgânico."""

import json
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.llm.base import LLMAdapter, LLMError, LLMResult
from app.adapters.marketplace.mock.adapter import MockAdapter
from app.domain import sub_id as sub_id_format
from app.domain.enums import ProductState
from app.domain.state_machine import transition
from app.models.ai import LlmCall
from app.models.catalog import Product
from app.models.content import Creative
from app.models.tracking import AffiliateLink
from app.services import content_service, discovery_service


class FakeLLM(LLMAdapter):
    provider, model = "fake", "fake-1"

    def __init__(self, text: str | None = None, error: str | None = None, cost="0.001"):
        self.text, self.error, self.cost, self.calls = text, error, Decimal(cost), 0

    def generate(self, *, system, prompt, max_tokens):
        self.calls += 1
        if self.error:
            raise LLMError(self.error)
        return LLMResult(self.text, self.model, 100, 80, self.cost, 5)


def _good(db_prompt_facts=None) -> str:
    return json.dumps(
        {"hook": "Você precisa conhecer esse achado", "caption": "Prático para o dia a dia.",
         "hashtags": ["casa", "organização", "achados"]}
    )


@pytest.fixture
def testing_products(db: Session):
    discovery_service.run_discovery(db, MockAdapter(), limit=3)
    products = db.execute(select(Product).order_by(Product.id).limit(3)).scalars().all()
    for p in products:
        p.image_url = f"https://img.test/{p.id}.jpg"
        for state in (ProductState.QUALIFICATION, ProductState.CANDIDATE, ProductState.TEST):
            transition(db, product_id=p.id, to_state=state, reason_code="TEST", actor="system")
    db.flush()
    return products


def _run(db, llm=None, count=3, cap="1.00"):
    return content_service.generate_daily_package(
        db, MockAdapter(), llm, count=count, max_sub_id_length=48, llm_cap_usd=Decimal(cap)
    )


def _count(db, model) -> int:
    return db.execute(select(func.count()).select_from(model)).scalar_one()


def test_without_llm_the_template_makes_a_complete_package(db, testing_products):
    result = _run(db)

    assert result.created == 3 and result.template_used == 3 and result.llm_used == 0
    package = result.packages[0]
    assert package["image_url"].startswith("https://img.test/")
    assert "#publi" in package["caption"] and "Link de afiliado" in package["caption"]
    assert "http" in package["caption"]  # o link rastreado vai na mensagem
    assert _count(db, LlmCall) == 0


def test_each_post_has_its_own_tracked_link_for_attribution(db, testing_products):
    result = _run(db)

    for package in result.packages:
        link = db.execute(
            select(AffiliateLink).where(AffiliateLink.sub_id == package["sub_id"])
        ).scalar_one()
        parsed = sub_id_format.parse(link.sub_id)
        assert parsed.channel == "ig" and parsed.creative_id == package["creative_id"]
        assert link.product_id == package["product_id"] and link.utm_medium == "organic"


def test_second_run_the_same_day_makes_nothing_new(db, testing_products):
    _run(db)
    again = _run(db)

    assert again.created == 0
    assert _count(db, Creative) == 3


def test_daily_count_limits_the_package(db, testing_products):
    assert _run(db, count=2).created == 2


def test_products_without_photo_or_outside_the_portfolio_are_left_out(db, testing_products):
    testing_products[0].image_url = None
    db.flush()
    result = _run(db)

    assert {p["product_id"] for p in result.packages} == {p.id for p in testing_products[1:]}


def test_valid_llm_text_is_used_and_logged(db, testing_products):
    llm = FakeLLM(_good())
    result = _run(db, llm)

    assert result.llm_used == 3 and llm.calls == 3
    creative = db.get(Creative, result.packages[0]["creative_id"])
    assert creative.generated_by == "llm:fake-1" and creative.llm_call_id is not None
    assert _count(db, LlmCall) == 3
    assert "Você precisa conhecer esse achado" in result.packages[0]["caption"]
    assert "#publi" in result.packages[0]["caption"]  # o aviso é do código


@pytest.mark.parametrize(
    "caption",
    [
        "Só R$ 19,90 hoje!",                     # número que não está nos fatos
        "Garantido: resolve tudo.",              # promessa
        "Compre em https://x.com agora",         # link na legenda
        "Linda #oferta",                         # hashtag na legenda
    ],
)
def test_llm_text_that_breaks_the_rules_falls_back_to_the_template(db, testing_products, caption):
    llm = FakeLLM(json.dumps({"hook": "Olha", "caption": caption, "hashtags": ["a1b"]}))
    result = _run(db, llm, count=1)

    assert result.template_used == 1 and result.llm_used == 0
    assert any("reprovada" in w for w in result.warnings)
    call = db.execute(select(LlmCall)).scalar_one()
    assert call.success is False and "reprovado" in call.error


def test_llm_failure_or_garbage_never_blocks_the_package(db, testing_products):
    assert _run(db, FakeLLM(error="HTTP 529"), count=1).template_used == 1
    assert _run(db, FakeLLM("isto não é json"), count=1).template_used == 1


def test_daily_cost_cap_stops_the_llm_but_not_the_package(db, testing_products):
    llm = FakeLLM(_good(), cost="0.60")
    result = _run(db, llm, cap="1.00")

    # 1ª e 2ª chamadas gastam 1,20 >= teto; a 3ª já cai no template sem chamar o LLM.
    assert llm.calls == 2 and result.llm_used == 2 and result.template_used == 1
    assert any("teto" in w for w in result.warnings)


def test_llm_numbers_that_are_in_the_facts_are_accepted(db, testing_products):
    facts_price = content_service._facts(testing_products[0], None)  # sem snapshot: só título
    digits = "".join(c for c in facts_price["produto"] if c.isdigit())
    if not digits:
        pytest.skip("título do mock sem número")
    parsed = {"hook": "Olha", "caption": f"Modelo {digits}", "hashtags": []}
    content_service._validate(parsed, facts_price)


def test_a_failed_link_skips_the_product_not_a_post_without_attribution(db, testing_products):
    result = content_service.generate_daily_package(
        db, MockAdapter(), None, count=3, max_sub_id_length=20, llm_cap_usd=Decimal("1")
    )

    assert result.created == 0 and result.skipped == 3
    assert _count(db, Creative) == 0


# ---------- adaptador Claude e endpoint ----------


def _anthropic(handler):
    import httpx

    from app.adapters.llm.anthropic_adapter import AnthropicAdapter

    return AnthropicAdapter(
        api_key="sk-test", model="claude-haiku-5-5", input_usd_per_mtok=Decimal("1"),
        output_usd_per_mtok=Decimal("5"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_anthropic_adapter_parses_text_and_estimates_cost():
    import httpx

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"], seen["body"] = request.headers["x-api-key"], json.loads(request.content)
        return httpx.Response(200, json={
            "model": "claude-haiku-5-5", "content": [{"type": "text", "text": "oi"}],
            "usage": {"input_tokens": 1000, "output_tokens": 200},
        })

    result = _anthropic(handler).generate(system="s", prompt="p", max_tokens=50)

    assert result.text == "oi" and seen["key"] == "sk-test"
    assert seen["body"]["max_tokens"] == 50 and seen["body"]["system"] == "s"
    assert result.cost_usd == Decimal("0.002")  # 1000*1/1M + 200*5/1M


def test_anthropic_adapter_error_never_leaks_the_key():
    import httpx

    adapter = _anthropic(lambda r: httpx.Response(401, json={"error": "invalid x-api-key"}))
    with pytest.raises(LLMError) as exc:
        adapter.generate(system="s", prompt="p", max_tokens=5)

    assert "401" in str(exc.value) and "sk-test" not in str(exc.value)


def test_registry_gives_no_llm_without_key_or_provider():
    from app.adapters.llm.registry import get_llm_adapter
    from app.core.config import Settings

    assert get_llm_adapter(Settings(llm_provider="null")) is None
    assert get_llm_adapter(Settings(llm_provider="anthropic", anthropic_api_key="")) is None
    assert get_llm_adapter(Settings(llm_provider="anthropic", anthropic_api_key="k")) is not None


def test_endpoint_needs_idempotency_key_and_respects_autonomy(db, testing_products, set_autonomy):
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.db.session import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        headers = {"X-API-Key": get_settings().n8n_api_key}
        assert client.post("/api/v1/trigger/content/generate", headers=headers).status_code == 400

        set_autonomy(2)
        low = client.post(
            "/api/v1/trigger/content/generate?dry_run=false",
            headers={**headers, "Idempotency-Key": "c-1"},
        ).json()
        assert low["items"] == [] and _count(db, Creative) == 0

        set_autonomy(3)
        ok = client.post(
            "/api/v1/trigger/content/generate?dry_run=false",
            headers={**headers, "Idempotency-Key": "c-2"},
        ).json()
        assert ok["summary"]["created"] == 3 and len(ok["items"]) == 3
        assert ok["summary"]["llm_configured"] is False
    finally:
        app.dependency_overrides.pop(get_db, None)
