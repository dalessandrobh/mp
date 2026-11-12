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
from app.models.catalog import Category, Product
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
        assert parsed.channel == "pin" and parsed.creative_id == package["creative_id"]
        assert link.product_id == package["product_id"] and link.utm_medium == "organic"


def test_package_also_carries_a_separate_paid_ad_link(db, testing_products):
    result = _run(db)

    for package in result.packages:
        assert package["ads_url"] and package["ads_url"] != package["tracked_url"]
        assert "PIN ORGÂNICO" in package["caption"] and "ANÚNCIO PAGO" in package["caption"]
        assert package["ads_url"] in package["caption"]
        ads = db.execute(
            select(AffiliateLink).where(
                AffiliateLink.product_id == package["product_id"],
                AffiliateLink.creative_id == package["creative_id"],
                AffiliateLink.channel == "pinads",
            )
        ).scalar_one()
        parsed = sub_id_format.parse(ads.sub_id)
        assert parsed.channel == "pinads" and parsed.creative_id == package["creative_id"]
        assert ads.utm_medium != "organic"  # canal pago, para a venda não virar orgânica


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
        # Teto padrão de R$ 300: o produto mock de R$ 434 fica de fora.
        assert ok["summary"]["created"] == 2 and len(ok["items"]) == 2
        assert ok["summary"]["excluded_price"] == 1
        assert ok["summary"]["llm_configured"] is False
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------- a marca Shopee nunca aparece (Termos de Afiliados 2.3(a)) ----------


def test_template_package_never_contains_the_marketplace_brand(db, testing_products):
    testing_products[0].title = "Shopee Choice Bicicleta Ergométrica da SHOPEE Premium"
    testing_products[0].category_path = ["Shopee Mall", "Esporte e Lazer"]
    db.flush()
    result = _run(db)

    for package in result.packages:
        assert "shopee" not in package["caption"].lower()
    first = next(p for p in result.packages if p["product_id"] == testing_products[0].id)
    assert "Bicicleta Ergométrica" in first["caption"] and "#esporteelazer" in first["caption"]


def test_llm_text_or_tags_naming_the_brand_are_not_accepted(db, testing_products):
    bad_text = FakeLLM(json.dumps({"hook": "Achado na Shopee", "caption": "Bom.", "hashtags": []}))
    result = _run(db, bad_text, count=1)
    assert result.template_used == 1 and result.llm_used == 0

    bad_tag = FakeLLM(json.dumps({"hook": "Olha", "caption": "Bom.", "hashtags": ["shopeefinds"]}))
    result = _run(db, bad_tag, count=1)
    assert result.llm_used == 1 and "shopee" not in result.packages[0]["caption"].lower()


# ---------- formato do pin (Pinterest) ----------


def _message(db, **kwargs):
    return _run(db, **kwargs).packages[0]["caption"]


def test_the_pack_follows_the_fields_of_the_pin_form(db, testing_products):
    message = _message(db)

    # Título, descrição, link de destino e imagem, nessa ordem.
    positions = [message.index(s) for s in (
        "*Título do pin:*", "*Descrição (copie e cole):*", "*Link de destino", "*Imagem")]
    assert positions == sorted(positions)
    assert "https://img.test/" in message


def test_the_pack_has_no_instagram_leftovers(db, testing_products):
    message = _message(db).lower()

    for word in ("stories", "sticker", "na bio", "instagram", "comentários", "me conta"):
        assert word not in message
    assert "pin" in message


def test_title_and_description_respect_the_pin_limits(db, testing_products):
    for package in _run(db).packages:
        assert 0 < len(package["title"]) <= content_service.MAX_PIN_TITLE
        assert len(package["description"]) <= content_service.MAX_PIN_DESCRIPTION
        assert package["title"] in package["caption"]
        assert package["description"] in package["caption"]


def test_the_description_never_carries_the_link(db, testing_products):
    """O link vai no campo próprio do pin; na descrição ele nem é clicável."""
    for package in _run(db).packages:
        assert "http" not in package["description"]
        assert package["tracked_url"] in package["caption"]


def test_the_disclosure_survives_the_longest_caption_the_model_may_send(db, testing_products):
    long_caption = "Prático para o dia a dia. " * 30  # ~780 caracteres, acima do limite do modelo
    llm = FakeLLM(json.dumps({"hook": "Olha", "caption": long_caption, "hashtags": ["casa"]}))

    first = _run(db, llm, count=1)

    # Legenda acima de MAX_CAPTION é reprovada e cai no modelo de texto: nada estoura.
    assert first.template_used == 1
    description = first.packages[0]["description"]
    assert len(description) <= content_service.MAX_PIN_DESCRIPTION
    assert content_service.DISCLOSURE in description


def test_a_caption_at_the_model_limit_still_keeps_disclosure_and_hashtags_whole():
    caption = "a " * (content_service.MAX_CAPTION // 2)
    tags = "#casa #achadinhos #indicacao"

    description = content_service._pin_description(caption, tags)

    assert len(description) <= content_service.MAX_PIN_DESCRIPTION
    assert description.endswith(f"{content_service.DISCLOSURE}\n\n{tags}")


def test_an_oversized_caption_is_cut_in_the_body_not_in_the_disclosure():
    description = content_service._pin_description("palavra " * 400, "#casa")

    assert len(description) <= content_service.MAX_PIN_DESCRIPTION
    assert description.endswith(f"{content_service.DISCLOSURE}\n\n#casa")
    assert "…" in description.split(content_service.DISCLOSURE)[0]


def test_the_model_is_told_to_write_for_pinterest_and_not_to_ask_for_engagement():
    system = content_service.SYSTEM
    assert "Pinterest" in system and "Instagram" not in system
    assert "não peça curtidas" in system


def test_the_template_does_not_ask_for_comments(db, testing_products):
    caption = _run(db).packages[0]["caption"].lower()
    assert "comentários" not in caption and "salve este pin" in caption


def test_a_caption_that_fits_keeps_its_paragraphs(db, testing_products):
    """O corte normaliza espaços; só pode acontecer quando a legenda realmente não cabe."""
    description = _run(db).packages[0]["description"]

    assert "\n\n" in description.split(content_service.DISCLOSURE)[0].strip()
    assert content_service._pin_description("um\n\ndois", "#x").startswith("um\n\ndois")


# ---------- board sugerido ----------


def _categorize(db, products, raw, name=None):
    for p in products:
        p.category_path = [raw]
    if name is not None:
        db.add(Category(marketplace="mock", external_id=raw, level=1, name=name,
                        name_source="inferido"))
    db.flush()


def test_the_pack_suggests_the_board_from_the_category_name(db, testing_products):
    _categorize(db, testing_products, "100011", "Moda Masculina")

    package = _run(db).packages[0]

    assert package["board"] == "Moda Masculina"
    assert "*Board sugerido (onde salvar):*\nModa Masculina" in package["caption"]


def test_the_board_comes_first_because_it_is_where_the_pin_gets_saved(db, testing_products):
    _categorize(db, testing_products, "100011", "Moda Masculina")

    message = _message(db)

    assert message.index("*Board sugerido") < message.index("*Título do pin:*")


def test_products_of_the_same_category_get_the_same_board_every_time(db, testing_products):
    """O nome estável é o que dá tema ao board; por isso vem da categoria, não do produto."""
    _categorize(db, testing_products, "100011", "Moda Masculina")

    boards = {package["board"] for package in _run(db).packages}

    assert boards == {"Moda Masculina"}


def test_a_category_id_without_a_known_name_suggests_nothing(db, testing_products):
    """Sugerir "Categoria 100637" seria pior que não sugerir."""
    _categorize(db, testing_products, "100637")

    package = _run(db).packages[0]

    assert package["board"] is None
    assert "Board sugerido" not in package["caption"]


def test_the_board_name_respects_pinterests_50_character_limit(db, testing_products):
    long_name = "Casa, Cozinha e Utilidades Domésticas para Todos os Cômodos da Residência"
    assert len(long_name) > content_service.MAX_BOARD_NAME
    _categorize(db, testing_products, "100011", long_name)

    board = _run(db).packages[0]["board"]

    assert 0 < len(board) <= content_service.MAX_BOARD_NAME


def test_the_marketplace_brand_never_reaches_the_board_name(db, testing_products):
    _categorize(db, testing_products, "100011", "Ofertas Shopee Casa")

    package = _run(db).packages[0]

    assert "shopee" not in package["board"].lower()
    assert "shopee" not in package["caption"].lower()


def test_the_mock_catalog_already_returns_category_names(db, testing_products):
    """Sem categoria numérica o nome vem direto do caminho de categoria."""
    packages = _run(db).packages

    assert {p["board"] for p in packages} <= {"Casa", "Eletrônicos", "Beleza", "Esporte", "Moda"}
    assert all(p["board"] for p in packages)


# ---------- hashtags: texto, nunca id ----------


def test_hashtags_never_use_numeric_category_ids(db, testing_products):
    """A Shopee devolve o caminho de categoria como ids ("100637"); virar #100637 não significa
    nada para quem busca."""
    for p in testing_products:
        p.category_path = ["100011", "100047", "101295"]
    db.add(Category(marketplace="mock", external_id="100011", level=1, name="Moda Masculina",
                    name_source="inferido"))
    db.flush()

    tags = _run(db).packages[0]["description"]

    assert not any(word.lstrip("#").isdigit() for word in tags.split() if word.startswith("#"))
    assert "#modamasculina" in tags


def test_hashtags_without_a_known_category_name_keep_only_the_fixed_ones(db, testing_products):
    for p in testing_products:
        p.category_path = ["100637", "100725"]
    db.flush()

    tags = [w for w in _run(db).packages[0]["description"].split() if w.startswith("#")]

    assert "#achadinhos" in tags and "#indicacao" in tags
    assert not any(t[1:].isdigit() for t in tags)


# ---------- roteiro de vídeo ----------


def test_the_pack_ends_with_an_optional_video_script(db, testing_products):
    result = _run(db)
    package = result.packages[0]
    message = package["caption"]

    assert "*Roteiro de vídeo" in message
    # Vai depois da imagem, para não atrapalhar os campos do formulário do pin.
    assert message.index("*Imagem") < message.index("*Roteiro de vídeo")
    assert package["video_script"] in message
    assert "9:16" in package["video_script"]


def test_the_video_script_uses_only_known_facts_and_never_names_the_brand(db, testing_products):
    testing_products[0].title = "Shopee Choice Bicicleta Ergométrica Premium"
    db.flush()
    result = _run(db)
    first = next(p for p in result.packages if p["product_id"] == testing_products[0].id)
    script = first["video_script"]

    assert "shopee" not in script.lower()
    assert "Bicicleta Ergométrica" in script
    assert "garantid" not in script.lower() and "frete" not in script.lower()


def test_the_video_script_omits_missing_numbers_instead_of_inventing_them():
    script = content_service._video_script({"produto": "Garrafa térmica"})

    assert "Garrafa térmica" in script
    assert "R$" not in script and "vendidos" not in script and "nota" not in script.lower()


# ---------- intervalo entre repetições do mesmo produto ----------


def _run_on(db, now, days):
    return content_service.generate_daily_package(
        db, MockAdapter(), None, count=3, max_sub_id_length=48, llm_cap_usd=Decimal("1.00"),
        min_days_between=days, now=now,
    )


def test_a_product_does_not_come_back_before_the_interval(db, testing_products):
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    assert _run_on(db, now, 7).created == 3

    assert _run_on(db, now + timedelta(days=1), 7).created == 0
    assert _run_on(db, now + timedelta(days=6), 7).created == 0


def test_the_product_comes_back_exactly_when_the_interval_ends(db, testing_products):
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    _run_on(db, now, 7)

    assert _run_on(db, now + timedelta(days=7), 7).created == 3


def test_zero_days_only_blocks_the_same_day(db, testing_products):
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    assert _run_on(db, now, 0).created == 3
    assert _run_on(db, now, 0).created == 0
    assert _run_on(db, now + timedelta(days=1), 0).created == 3


def test_candidate_products_also_get_a_package_and_both_links(db: Session):
    # Post orgânico não gasta nada: o limite de vagas de TEST é do orçamento de anúncio.
    # Um produto que parou em CANDIDATE tem de poder entrar no pacote.
    from app.services import tracking_service

    discovery_service.run_discovery(db, MockAdapter(), limit=1)
    candidate = db.execute(select(Product).order_by(Product.id).limit(1)).scalar_one()
    candidate.image_url = f"https://img.test/{candidate.id}.jpg"
    for state in (ProductState.QUALIFICATION, ProductState.CANDIDATE):
        transition(db, product_id=candidate.id, to_state=state, reason_code="TEST", actor="system")
    db.flush()

    # O gerador de links "geral" continua sem linkar CANDIDATE (não vira link em massa).
    assert tracking_service.generate_links(
        db, MockAdapter(), channel="pin", max_sub_id_length=48
    ).created == 0

    result = _run(db, count=3)

    assert [p["product_id"] for p in result.packages] == [candidate.id]
    assert result.packages[0]["ads_url"]


def test_branded_products_never_enter_the_package(db, testing_products):
    branded = testing_products[0]
    branded.title = "Smartphone Xiaomi Poco 256GB"
    db.flush()

    result = content_service.generate_daily_package(
        db, MockAdapter(), None, count=3, max_sub_id_length=48, llm_cap_usd=Decimal("1.00")
    )

    assert branded.id not in {p["product_id"] for p in result.packages}
    assert result.excluded_brand == 1 and result.created == 2


def test_price_above_the_ceiling_is_left_out_and_zero_disables_it(db, testing_products):
    def run(max_price):
        return content_service.generate_daily_package(
            db, MockAdapter(), None, count=3, max_sub_id_length=48, llm_cap_usd=Decimal("1.00"),
            max_price=max_price,
        )

    blocked = run(Decimal("0.01"))  # nenhum produto custa menos que 1 centavo
    assert blocked.created == 0 and blocked.excluded_price == 3

    # 0 desliga o teto: aí os três entram.
    assert run(Decimal("0")).created == 3
