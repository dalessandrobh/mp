"""Adaptador do Pinterest: OAuth que rotaciona, erros traduzidos, payload do pin."""

import httpx
import pytest
from sqlalchemy.orm import Session

from app.adapters.social.base import PostDraft, SocialAuthError, SocialRateLimited, SocialRejected
from app.adapters.social.pinterest.adapter import PinterestAdapter
from app.adapters.social.pinterest.auth import PinterestAuth, StoredToken
from app.adapters.social.pinterest.client import PinterestClient
from app.models.social import OauthToken
from app.services import oauth_store

BOARD = "1234567890"
DRAFT = PostDraft(
    title="Título do pin", description="Descrição", link="https://mp.test/go/abc",
    image_url="https://img.test/1.jpg", alt_text="alternativo",
)


class Store:
    """Carteira em memória, para ver a rotação acontecer."""

    def __init__(self, token: StoredToken | None):
        self.token, self.saves = token, 0

    def load(self):
        return self.token

    def save(self, token):
        self.token, self.saves = token, self.saves + 1


def _auth(store, handler, clock=lambda: 1000.0):
    return PinterestAuth(
        app_id="app", app_secret="secret", load=store.load, save=store.save,
        http=httpx.Client(transport=httpx.MockTransport(handler)), clock=clock,
    )


# ---------- OAuth ----------


def test_a_fresh_access_token_is_reused_without_calling_the_network():
    chamadas = []

    def handler(request):
        chamadas.append(request)
        return httpx.Response(200, json={})

    store = Store(StoredToken(refresh_token="r1", access_token="a1", access_expires_at=99999.0))
    assert _auth(store, handler).access_token() == "a1"
    assert chamadas == []


def test_an_access_token_about_to_expire_is_renewed_early():
    """Vencer no meio da requisição seria um 401 à toa: renova com margem."""
    def handler(request):
        return httpx.Response(200, json={"access_token": "a2", "expires_in": 3600})

    # Expira em 100s, abaixo da margem de 300s.
    store = Store(StoredToken(refresh_token="r1", access_token="a1", access_expires_at=1100.0))
    assert _auth(store, handler).access_token() == "a2"


def test_the_rotated_refresh_token_is_saved(db):
    """O Pinterest invalida o antigo; não gravar o novo mata a integração."""
    def handler(request):
        assert request.headers["authorization"].startswith("Basic ")
        assert b"grant_type=refresh_token" in request.content
        return httpx.Response(
            200,
            json={
                "access_token": "a2", "expires_in": 3600,
                "refresh_token": "r2", "refresh_token_expires_in": 5184000,
            },
        )

    store = Store(StoredToken(refresh_token="r1"))
    _auth(store, handler).access_token()

    assert store.saves == 1
    assert store.token.refresh_token == "r2"
    assert store.token.refresh_expires_at == 1000.0 + 5184000


def test_a_response_without_a_new_refresh_token_keeps_the_old_one():
    def handler(request):
        return httpx.Response(200, json={"access_token": "a2", "expires_in": 3600})

    store = Store(StoredToken(refresh_token="r1"))
    _auth(store, handler).access_token()

    assert store.token.refresh_token == "r1"


def test_an_expired_refresh_token_fails_loud_and_says_it_needs_a_human():
    def handler(request):  # pragma: no cover - não deve ser chamado
        raise AssertionError("não deveria chamar a rede")

    store = Store(StoredToken(refresh_token="r1", refresh_expires_at=999.0))
    with pytest.raises(SocialAuthError, match="reautorizar"):
        _auth(store, handler).access_token()


def test_no_refresh_token_at_all_is_a_configuration_error():
    store = Store(None)
    with pytest.raises(SocialAuthError, match="refresh token"):
        _auth(store, lambda r: httpx.Response(200, json={})).access_token()


def test_the_token_endpoint_refusing_does_not_leak_the_body_into_the_message():
    def handler(request):
        return httpx.Response(400, json={"message": "refresh_token=r1-secreto inválido"})

    store = Store(StoredToken(refresh_token="r1"))
    with pytest.raises(SocialAuthError) as exc:
        _auth(store, handler).access_token()
    assert "r1-secreto" not in str(exc.value)


def test_days_left_reports_the_refresh_window():
    store = Store(StoredToken(refresh_token="r1", refresh_expires_at=1000.0 + 10 * 86400))
    assert round(_auth(store, lambda r: httpx.Response(200)).refresh_token_days_left()) == 10


# ---------- cliente e adaptador ----------


def _adapter(handler, *, sleeps=None):
    store = Store(StoredToken(refresh_token="r", access_token="a", access_expires_at=99999.0))
    client = PinterestClient(
        auth=_auth(store, lambda r: httpx.Response(200, json={})),
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=(sleeps.append if sleeps is not None else (lambda s: None)),
    )
    return PinterestAdapter(client=client, board_id=BOARD)


def test_a_non_numeric_board_id_is_refused_at_construction():
    with pytest.raises(ValueError, match="numérico"):
        PinterestAdapter(client=None, board_id="meu-board")


def test_the_pin_payload_matches_the_official_schema():
    visto = {}

    def handler(request):
        import json
        visto.update(json.loads(request.content))
        assert request.url.path.endswith("/pins")
        return httpx.Response(201, json={"id": "999", "board_id": BOARD})

    result = _adapter(handler).publish(DRAFT)

    assert visto["board_id"] == BOARD
    assert visto["media_source"] == {"source_type": "image_url", "url": DRAFT.image_url}
    assert visto["link"] == DRAFT.link
    assert visto["alt_text"] == "alternativo"
    assert result.external_post_id == "999"
    assert result.url == "https://www.pinterest.com/pin/999/"


def test_long_fields_are_truncated_to_the_official_limits():
    visto = {}

    def handler(request):
        import json
        visto.update(json.loads(request.content))
        return httpx.Response(201, json={"id": "1"})

    _adapter(handler).publish(
        PostDraft(
            title="palavra " * 50, description="texto " * 300, link="https://mp.test/go/a",
            image_url="https://i/1.jpg", alt_text="alt " * 300,
        )
    )

    assert len(visto["title"]) <= 100
    assert len(visto["description"]) <= 800
    assert len(visto["alt_text"]) <= 500


def test_alt_text_is_omitted_when_absent():
    visto = {}

    def handler(request):
        import json
        visto.update(json.loads(request.content))
        return httpx.Response(201, json={"id": "1"})

    _adapter(handler).publish(
        PostDraft(title="t", description="d", link="https://mp.test/go/a",
                  image_url="https://i/1.jpg")
    )
    assert "alt_text" not in visto


def test_a_response_without_an_id_is_a_failure_not_a_silent_success():
    def handler(request):
        return httpx.Response(201, json={"board_id": BOARD})

    with pytest.raises(SocialRejected, match="sem id"):
        _adapter(handler).publish(DRAFT)


def test_pinner_data_access_denied_says_the_account_must_be_business():
    """403 genérico mandaria procurar no lugar errado; esta causa tem remédio próprio."""
    def handler(request):
        return httpx.Response(403, json={"code": "PINNER_DATA_ACCESS_DENIED",
                                         "message": "not allowed"})

    with pytest.raises(SocialAuthError, match="business"):
        _adapter(handler).publish(DRAFT)


def test_rate_limit_is_retried_and_then_succeeds():
    tentativas, sleeps = [], []

    def handler(request):
        tentativas.append(1)
        if len(tentativas) == 1:
            return httpx.Response(429, headers={"retry-after": "2"})
        return httpx.Response(201, json={"id": "7"})

    result = _adapter(handler, sleeps=sleeps).publish(DRAFT)

    assert result.external_post_id == "7"
    assert sleeps == [2.0]


def test_rate_limit_that_never_clears_raises_after_the_retries():
    def handler(request):
        return httpx.Response(429)

    with pytest.raises(SocialRateLimited):
        _adapter(handler).publish(DRAFT)


def test_a_400_is_not_retried_because_repeating_does_not_fix_it():
    tentativas = []

    def handler(request):
        tentativas.append(1)
        return httpx.Response(400, json={"message": "image_url inacessível"})

    with pytest.raises(SocialRejected, match="image_url"):
        _adapter(handler).publish(DRAFT)
    assert len(tentativas) == 1


# ---------- armazenamento do token ----------


def test_the_store_seeds_the_first_refresh_token_from_the_environment(db: Session):
    store = oauth_store.TokenStore(db, lambda: db, seed_refresh_token="semente")

    assert store.load().refresh_token == "semente"


def test_the_store_prefers_the_database_over_the_environment_seed(db: Session):
    db.add(OauthToken(provider="pinterest", refresh_token="do-banco"))
    db.flush()

    store = oauth_store.TokenStore(db, lambda: db, seed_refresh_token="semente")

    assert store.load().refresh_token == "do-banco"


def test_an_empty_store_without_a_seed_returns_nothing(db: Session):
    assert oauth_store.TokenStore(db, lambda: db, seed_refresh_token="").load() is None


def test_saving_writes_the_row(db: Session):
    """Em produção a sessão é própria (SessionLocal) para commitar fora da transação de
    quem chamou; aqui ela é a do teste, senão o commit escaparia do rollback."""
    store = oauth_store.TokenStore(db, lambda: db, seed_refresh_token="semente")

    store.save(StoredToken(refresh_token="r2", access_token="a2", access_expires_at=1.0))

    row = db.get(OauthToken, "pinterest")
    assert row.refresh_token == "r2" and row.access_token == "a2"
