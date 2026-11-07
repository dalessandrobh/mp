"""Fila de aprovação: o MP propõe, a pessoa decide, pin a pin (Diretrizes do Pinterest, 4.3)."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters.social.base import SocialAuthError, SocialRejected
from app.adapters.social.mock.adapter import MockSocialAdapter
from app.core.config import get_settings
from app.core.exceptions import DomainError, NotFound
from app.db.session import get_db
from app.main import app
from app.models.content import Creative
from app.models.social import PublishApproval, SocialPost
from app.services import approval_service
from app.services.publishing_constants import WINDOW_DAYS
from tests.conftest import BASE
from tests.test_publishing import HUMAN, _publish


def _ids(db):
    return [c.id for c in approval_service.candidates(db, now=datetime.now(UTC))]


def _decide(db, ids, decision="APPROVED", actor=HUMAN):
    return approval_service.decide(db, creative_ids=ids, decision=decision, actor=actor)


def _publish_only_approved(db, social=None, **kw):
    return _publish(db, social=social, approve=False, **kw)


# ---------- a trava principal ----------


def test_nothing_is_published_without_a_human_decision(db: Session, ready):
    social = MockSocialAdapter()
    result = _publish_only_approved(db, social)

    assert result.published == 0 and result.considered == 0
    assert social.published == []
    assert result.awaiting_approval == 3


def test_only_the_approved_pins_go_out(db: Session, ready):
    first, *_ = sorted(_ids(db))
    _decide(db, [first])

    result = _publish_only_approved(db)

    assert result.published == 1 and result.awaiting_approval == 2
    posted = db.execute(select(SocialPost.creative_id)).scalars().all()
    assert posted == [first]


def test_a_rejected_pin_is_never_published(db: Session, ready):
    _decide(db, _ids(db), "REJECTED")
    result = _publish_only_approved(db)
    assert result.published == 0 and result.awaiting_approval == 0


def test_the_latest_decision_wins_in_both_directions(db: Session, ready):
    a, b, _ = sorted(_ids(db))
    _decide(db, [a, b], "APPROVED")
    _decide(db, [a], "REJECTED")  # mudou de ideia antes de sair
    _decide(db, [b], "REJECTED")
    _decide(db, [b], "APPROVED")  # e voltou atrás

    _publish_only_approved(db)

    assert db.execute(select(SocialPost.creative_id)).scalars().all() == [b]


def test_approving_does_not_bypass_the_brand_guard(db: Session, ready):
    """A pessoa pode errar o clique; o guarda de réplica não pode."""
    _decide(db, _ids(db))
    categories = frozenset({"Casa", "Eletrônicos", "Beleza", "Esporte", "Moda"})

    result = _publish_only_approved(db, price_ceiling=0.01, brand_categories=categories)

    assert result.published == 0 and result.blocked == 3
    assert {s.status for s in db.execute(select(SocialPost)).scalars()} == {"BLOCKED"}


def test_dry_run_only_drafts_what_was_approved(db: Session, ready):
    first, *_ = sorted(_ids(db))
    _decide(db, [first])

    result = _publish_only_approved(db, dry_run=True)

    assert result.dry_run == 1


# ---------- quem pode decidir ----------


@pytest.mark.parametrize("actor", ["n8n", "system", "", "human"])
def test_only_a_logged_in_person_can_decide(db: Session, ready, actor):
    """O n8n aprovar os próprios pins reintroduziria a automação que a regra proíbe."""
    with pytest.raises(DomainError):
        _decide(db, _ids(db), actor=actor)
    assert db.execute(select(func.count()).select_from(PublishApproval)).scalar_one() == 0


def test_unknown_creative_is_not_found(db: Session, ready):
    with pytest.raises(NotFound):
        _decide(db, [999_999])


def test_invalid_decision_and_empty_list_are_refused(db: Session, ready):
    with pytest.raises(DomainError):
        _decide(db, _ids(db), decision="MAYBE")
    with pytest.raises(DomainError):
        _decide(db, [])


# ---------- histórico ----------


def test_decisions_are_append_only_and_keep_the_history(db: Session, ready):
    cid = sorted(_ids(db))[0]
    _decide(db, [cid], "APPROVED")
    _decide(db, [cid], "REJECTED")

    rows = db.execute(
        select(PublishApproval).where(PublishApproval.creative_id == cid).order_by(
            PublishApproval.id
        )
    ).scalars().all()
    assert [r.decision for r in rows] == ["APPROVED", "REJECTED"]
    assert {r.decided_by for r in rows} == {HUMAN}

    with pytest.raises(IntegrityError):
        db.execute(update(PublishApproval).values(decision="APPROVED"))
        db.flush()


def test_repeating_the_same_decision_records_nothing_new(db: Session, ready):
    cid = sorted(_ids(db))[0]
    assert _decide(db, [cid]).recorded == 1
    again = _decide(db, [cid])
    assert (again.recorded, again.unchanged) == (0, 1)


def test_a_pin_already_posted_cannot_be_decided_again(db: Session, ready):
    cid = sorted(_ids(db))[0]
    _decide(db, [cid])
    _publish_only_approved(db)

    late = _decide(db, [cid], "REJECTED")

    assert late.already_posted == 1 and late.recorded == 0


# ---------- janela ----------


def test_the_queue_keeps_a_few_days_and_forgets_older_creatives(db: Session, ready):
    ids = sorted(_ids(db))
    old = datetime.now(UTC) - timedelta(days=WINDOW_DAYS + 2)
    db.execute(update(Creative).where(Creative.id == ids[0]).values(created_at=old))
    db.flush()

    assert ids[0] not in _ids(db)
    assert len(approval_service.queue(db)) == 2


def test_a_pin_approved_the_next_morning_still_goes_out(db: Session, ready):
    cid = sorted(_ids(db))[0]
    yesterday = datetime.now(UTC) - timedelta(days=1)
    db.execute(update(Creative).where(Creative.id == cid).values(created_at=yesterday))
    db.flush()
    _decide(db, [cid])

    assert _publish_only_approved(db).published == 1


# ---------- falha: passageira não queima o pin aprovado ----------


class Flaky(MockSocialAdapter):
    def __init__(self, error):
        super().__init__()
        self._error = error

    def publish(self, draft):
        raise self._error


def test_a_transient_error_leaves_the_approved_pin_for_the_next_run(db: Session, ready):
    _decide(db, _ids(db))

    down = _publish_only_approved(db, Flaky(SocialAuthError("token recusado")))

    assert down.published == 0 and down.failed == 1
    assert "segue aprovado" in down.warnings[0]
    # Nada gravado e o lote parou: não há 3 tentativas contra um token que não vale.
    assert db.execute(select(func.count()).select_from(SocialPost)).scalar_one() == 0

    back = _publish_only_approved(db)
    assert back.published == 3


def test_a_rejection_by_pinterest_is_final_and_does_not_stop_the_batch(db: Session, ready):
    _decide(db, _ids(db))

    result = _publish_only_approved(db, Flaky(SocialRejected("imagem inválida")))

    assert result.failed == 3
    assert {s.status for s in db.execute(select(SocialPost)).scalars()} == {"FAILED"}
    assert _publish_only_approved(db).published == 0  # definitivo: não insiste


# ---------- API ----------


def _token(email="dono@example.com") -> dict:
    token = jwt.encode({"email": email}, get_settings().jwt_secret, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(db: Session):
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


N8N = {"X-API-Key": "troque-esta-chave"}


def test_the_queue_endpoints_refuse_the_n8n_key(client, db: Session, ready):
    """A decisão é humana: a chave da automação não serve nem para ler nem para aprovar."""
    cid = sorted(_ids(db))[0]
    assert client.get("/api/v1/publishing/queue", headers=N8N).status_code == 401
    refused = client.post(
        "/api/v1/publishing/decisions",
        headers=N8N,
        json={"creative_ids": [cid], "decision": "APPROVED"},
    )
    assert refused.status_code == 401
    assert client.get("/api/v1/publishing/queue").status_code == 401


def test_the_queue_lists_the_proposals_with_what_the_person_needs_to_decide(client, ready):
    body = client.get("/api/v1/publishing/queue", headers=_token()).json()

    assert body["awaiting"] == 3 and body["window_days"] == WINDOW_DAYS
    item = body["items"][0]
    assert {"creative_id", "title", "price", "image_url", "caption", "status",
            "risk_blocked"} <= set(item)
    assert item["status"] == "PENDING"
    assert item["image_url"] and item["caption"]


def test_approving_through_the_api_records_who_decided(client, db: Session, ready):
    cid = sorted(_ids(db))[0]

    response = client.post(
        "/api/v1/publishing/decisions",
        headers=_token("ana@x.com"),
        json={"creative_ids": [cid], "decision": "APPROVED"},
    )

    assert response.status_code == 200 and response.json()["recorded"] == 1
    row = db.execute(select(PublishApproval)).scalar_one()
    assert row.decided_by == "human:ana@x.com"
    queue = client.get("/api/v1/publishing/queue", headers=_token()).json()
    assert queue["awaiting"] == 2
    assert {i["creative_id"]: i["status"] for i in queue["items"]}[cid] == "APPROVED"


def test_the_api_validates_the_request(client, ready):
    url = "/api/v1/publishing/decisions"
    assert client.post(url, headers=_token(), json={"creative_ids": [], "decision": "APPROVED"}
                       ).status_code == 422
    assert client.post(url, headers=_token(), json={"creative_ids": [1], "decision": "X"}
                       ).status_code == 422
    assert client.post(url, headers=_token(), json={"creative_ids": [999999],
                                                    "decision": "APPROVED"}).status_code == 404


def test_the_publish_trigger_reports_what_awaits_approval(client, db: Session, ready):
    # Publicar só roda com autonomia 4; aqui só interessa o resumo.
    from app.core.config import Settings

    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, ai_autonomy_level=4, public_base_url=BASE
    )
    response = client.post(
        "/api/v1/trigger/content/publish?dry_run=false",
        headers={**N8N, "Idempotency-Key": "appr-1"},
    )
    summary = response.json()["summary"]

    assert summary["published"] == 0
    assert summary["awaiting_approval"] == 3
    assert summary["queue_url"] == f"{BASE}/publicacao"
