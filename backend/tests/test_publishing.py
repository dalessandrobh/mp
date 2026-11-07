"""Publicação orgânica: adaptador, truncamento, guarda de risco e idempotência."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters.marketplace.mock.adapter import MockAdapter
from app.adapters.social.base import PostDraft, PostLimits, SocialRejected, fit
from app.adapters.social.mock.adapter import MockSocialAdapter
from app.models.social import SocialPost
from app.models.tracking import AffiliateLink
from app.services import approval_service, content_service, publishing_service
from tests.conftest import BASE

LIMITS = PostLimits(title=100, description=800, alt_text=500, link=2048)


HUMAN = "human:dono@example.com"


def approve_all(db: Session) -> list[int]:
    """Aprova toda a fila pelo caminho real: o que a pessoa faria no painel."""
    ids = [c.id for c in approval_service.candidates(db, now=datetime.now(UTC))]
    approval_service.decide(db, creative_ids=ids, decision="APPROVED", actor=HUMAN)
    return ids


def _publish(db, social=None, approve=True, **kwargs):
    if approve:
        approve_all(db)
    options = {
        "public_base": BASE, "max_sub_id_length": 48, "max_per_run": 10,
        "dry_run": False, "price_ceiling": 100000.0,
    }
    options.update(kwargs)
    return publishing_service.publish_pending(
        db, social or MockSocialAdapter(), MockAdapter(), **options
    )


# ---------- truncamento ----------


def test_fit_never_exceeds_the_limit():
    for limit in range(1, 40):
        assert len(fit("palavra " * 20, limit)) <= limit


def test_fit_cuts_on_a_word_boundary_and_marks_the_cut():
    assert fit("um dois tres quatro cinco seis", 20) == "um dois tres quatro…"
    # Limite que cairia no meio de 'quatro': recua para a palavra inteira.
    assert fit("um dois tres quatro cinco", 17) == "um dois tres…"


def test_fit_falls_back_to_a_hard_cut_when_one_word_is_longer_than_the_limit():
    # Sem fronteira de palavra alcançável não há escolha; o que importa é não estourar.
    out = fit("a" * 50, 10)
    assert len(out) == 10 and out.endswith("…")


def test_fit_leaves_short_text_untouched():
    assert fit("curto", 100) == "curto"


def test_fit_collapses_whitespace():
    assert fit("a    b\n\nc", 100) == "a b c"


# ---------- adaptador mock ----------


def test_mock_adapter_publishes_and_is_deterministic():
    adapter = MockSocialAdapter()
    draft = PostDraft(title="t", description="d", link=f"{BASE}/go/x", image_url="https://i/1.jpg")
    first, second = adapter.publish(draft), adapter.publish(draft)
    assert first.external_post_id == second.external_post_id


def test_adapter_refuses_a_draft_without_image():
    with pytest.raises(SocialRejected):
        MockSocialAdapter().publish(
            PostDraft(title="t", description="d", link=f"{BASE}/go/x", image_url="")
        )


def test_a_link_longer_than_the_limit_is_a_problem_not_a_truncation():
    # Link truncado é link quebrado: tem de reprovar, nunca encurtar.
    draft = PostDraft(
        title="t", description="d", link="https://x/" + "a" * 3000, image_url="https://i/1.jpg"
    )
    assert any("link" in p for p in draft.problems(LIMITS))


# ---------- publicação ----------


def test_publishes_the_creatives_of_the_day(db: Session, ready):
    result = _publish(db)

    assert result.published == 3 and result.failed == 0 and result.blocked == 0
    rows = db.execute(select(SocialPost)).scalars().all()
    assert len(rows) == 3
    assert all(r.status == "PUBLISHED" and r.external_post_id for r in rows)
    assert all(r.published_at is not None for r in rows)


def test_the_pin_points_at_our_own_redirect(db: Session, ready):
    result = _publish(db)

    for post in result.posts:
        assert post["link"].startswith(f"{BASE}/go/")


def test_the_link_gets_its_own_channel_so_clicks_are_not_credited_to_instagram(
    db: Session, ready
):
    _publish(db)

    channels = set(db.execute(select(AffiliateLink.channel)).scalars())
    assert "pin" in channels and "ig" in channels
    pin_links = db.execute(
        select(AffiliateLink).where(AffiliateLink.channel == "pin")
    ).scalars().all()
    assert len(pin_links) == 3
    assert all(link.sub_id.endswith("pin") for link in pin_links)


def test_running_twice_does_not_republish(db: Session, ready):
    first = _publish(db)
    second = _publish(db)

    assert first.published == 3
    assert second.published == 0 and second.considered == 0
    assert db.execute(select(func.count()).select_from(SocialPost)).scalar_one() == 3


def test_the_unique_constraint_is_the_real_guard_against_double_posting(db: Session, ready):
    _publish(db)
    post = db.execute(select(SocialPost)).scalars().first()

    db.add(
        SocialPost(
            product_id=post.product_id, creative_id=post.creative_id,
            channel=post.channel, status="PUBLISHED",
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_dry_run_records_the_draft_without_touching_the_network(db: Session, ready):
    social = MockSocialAdapter()

    result = _publish(db, social=social, dry_run=True)

    assert result.dry_run == 3 and result.published == 0
    assert social.published == []  # a rede não foi chamada
    assert all(r.status == "DRY_RUN" for r in db.execute(select(SocialPost)).scalars())


def test_max_per_run_caps_the_batch(db: Session, ready):
    result = _publish(db, max_per_run=2)

    assert result.published == 2


def test_without_public_base_nothing_is_published(db: Session, ready):
    result = _publish(db, public_base="")

    assert result.published == 0
    assert db.execute(select(func.count()).select_from(SocialPost)).scalar_one() == 0
    assert any("PUBLIC_BASE_URL" in w for w in result.warnings)


# ---------- guarda de risco ----------


def test_a_risky_product_is_blocked_and_the_reason_is_recorded(db: Session, ready):
    risky = ready[0]
    risky.title = "Celular iPhone 17 Pro Max 256GB Lacrado"
    db.flush()

    result = _publish(db, price_ceiling=10.0)

    blocked = db.execute(
        select(SocialPost).where(SocialPost.status == "BLOCKED")
    ).scalars().all()
    assert result.blocked >= 1
    assert any(r.reason_code == "RISK_HIGH_TICKET_BRAND" for r in blocked)
    # Bloqueado não publica, mas fica registrado: o motivo é auditável.
    assert all(r.external_post_id is None for r in blocked)


def test_a_blocked_product_does_not_consume_the_daily_slot_silently(db: Session, ready):
    for p in ready:
        p.title = "iPhone 17 Pro"
    db.flush()

    result = _publish(db, price_ceiling=10.0)

    assert result.published == 0 and result.blocked == 3


# ---------- divulgação de afiliado ----------


def test_the_affiliate_disclosure_survives_truncation(db: Session, ready):
    """A divulgação é o fim do texto — é justamente o que um truncamento ingênuo come."""
    enorme = "palavra " * 500
    out = publishing_service._description(enorme, 800)

    assert len(out) <= 800
    assert content_service.DISCLOSURE in out


def test_the_disclosure_is_present_even_with_a_tiny_budget():
    out = publishing_service._description("qualquer coisa", len(content_service.DISCLOSURE) + 5)
    assert content_service.DISCLOSURE in out


def test_published_today_counts_only_published(db: Session, ready):
    _publish(db, max_per_run=2)

    assert publishing_service.published_today(db) == 2
