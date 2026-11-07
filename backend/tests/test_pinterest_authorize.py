"""Autorização inicial do Pinterest: URL, state, troca do código e o que nunca é impresso."""

import base64
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy.orm import Session

from app.adapters.social.base import SocialAuthError
from app.adapters.social.pinterest.auth import StoredToken
from app.cli import pinterest_authorize as cli
from app.core.config import Settings
from app.models.social import OauthToken
from app.services import oauth_store

SECRET = "segredo-do-mp"
APP_ID = "1634598"
APP_SECRET = "app-secret-que-nunca-aparece"
NOW = 1_800_000_000.0
REDIRECT = cli.DEFAULT_REDIRECT_URI
ACCESS, REFRESH, CODE = "pina_ACESSO_SECRETO", "pinr_REFRESH_SECRETO", "codigo-de-uso-unico"


def _settings(**overrides) -> Settings:
    base = {"jwt_secret": SECRET, "pinterest_app_id": APP_ID, "pinterest_app_secret": APP_SECRET}
    return Settings(_env_file=None, **{**base, **overrides})


def _redirect(state: str, **extra) -> str:
    params = {"code": CODE, "state": state, **extra}
    return f"{REDIRECT}?" + "&".join(f"{k}={v}" for k, v in params.items())


class Out:
    """Captura o que seria impresso."""

    def __init__(self):
        self.lines: list[str] = []

    def __call__(self, text: str = "") -> None:
        self.lines.append(text)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


class FakeClient:
    def __init__(self, routes: dict):
        self.routes = routes

    def get(self, path, params=None):
        result = self.routes[path]
        if isinstance(result, Exception):
            raise result
        return result


ACCOUNT_OK = {
    "/user_account": {"username": "meuperfil", "account_type": "BUSINESS"},
    "/boards": {"items": [{"id": "1234567890", "name": "Achados da semana", "privacy": "PUBLIC"}]},
    "/ad_accounts": {"items": [{"id": "549755885175", "name": "Conta", "currency": "BRL"}]},
}


def _token_http(status=200, body=None, seen=None) -> httpx.Client:
    body = body if body is not None else {
        "access_token": ACCESS, "refresh_token": REFRESH, "expires_in": 2592000,
        "refresh_token_expires_in": 5184000, "scope": ",".join(cli.SCOPES),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


# ---------- URL de autorização ----------


def test_the_authorize_url_carries_everything_pinterest_needs():
    url = cli.build_authorize_url(app_id=APP_ID, redirect_uri=REDIRECT, state="abc")
    parsed = urlparse(url)
    query = {k: v[0] for k, v in parse_qs(parsed.query).items()}

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "https://www.pinterest.com/oauth/"
    assert query["client_id"] == APP_ID
    assert query["redirect_uri"] == REDIRECT
    assert query["response_type"] == "code"
    assert query["state"] == "abc"
    assert query["scope"].split(",") == list(cli.SCOPES)


def test_the_ads_scopes_are_requested_up_front_so_nobody_has_to_reauthorize_later():
    assert {"ads:read", "ads:write", "pins:write", "boards:read"} <= set(cli.SCOPES)


# ---------- state ----------


def test_a_fresh_state_is_accepted():
    cli.check_state(SECRET, cli.make_state(SECRET, now=NOW), now=NOW + 60)


@pytest.mark.parametrize("mutate", [
    lambda s: s[:-1] + ("0" if s[-1] != "0" else "1"),   # assinatura adulterada
    lambda s: "x" + s,                                    # nonce adulterado
    lambda s: "lixo",                                     # formato inválido
    lambda s: "",
])
def test_a_tampered_or_malformed_state_is_refused(mutate):
    state = cli.make_state(SECRET, now=NOW)
    with pytest.raises(cli.AuthorizeError):
        cli.check_state(SECRET, mutate(state), now=NOW + 1)


def test_a_state_signed_with_another_secret_is_refused():
    state = cli.make_state("outro-segredo", now=NOW)
    with pytest.raises(cli.AuthorizeError, match="não confere"):
        cli.check_state(SECRET, state, now=NOW + 1)


def test_an_old_state_expires():
    state = cli.make_state(SECRET, now=NOW)
    with pytest.raises(cli.AuthorizeError, match="15 minutos"):
        cli.check_state(SECRET, state, now=NOW + cli.STATE_MAX_AGE_SECONDS + 1)


# ---------- URL colada ----------


def test_the_code_comes_out_of_the_pasted_url():
    state = cli.make_state(SECRET, now=NOW)
    assert cli.code_from_redirect(_redirect(state), secret=SECRET, now=NOW + 5) == CODE


def test_a_refusal_by_the_user_is_reported_in_plain_words():
    with pytest.raises(cli.AuthorizeError, match="não concluiu"):
        cli.code_from_redirect(
            f"{REDIRECT}?error=access_denied&error_description=O+usuario+recusou",
            secret=SECRET, now=NOW,
        )


def test_a_url_without_code_asks_for_the_whole_url():
    with pytest.raises(cli.AuthorizeError, match="URL INTEIRA"):
        cli.code_from_redirect(REDIRECT, secret=SECRET, now=NOW)
    with pytest.raises(cli.AuthorizeError, match="URL INTEIRA"):
        cli.code_from_redirect(CODE, secret=SECRET, now=NOW)  # só o código, sem state


def test_a_code_with_a_foreign_state_is_refused():
    with pytest.raises(cli.AuthorizeError):
        cli.code_from_redirect(_redirect("forjado.123.abc"), secret=SECRET, now=NOW)


# ---------- troca do código ----------


def test_the_exchange_uses_basic_auth_and_a_form_with_continuous_refresh():
    seen: list[httpx.Request] = []
    token, scope = cli.exchange_code(
        app_id=APP_ID, app_secret=APP_SECRET, code=CODE, redirect_uri=REDIRECT,
        http=_token_http(seen=seen), now=NOW,
    )

    (request,) = seen
    assert str(request.url) == cli.TOKEN_URL
    expected = base64.b64encode(f"{APP_ID}:{APP_SECRET}".encode()).decode()
    assert request.headers["authorization"] == f"Basic {expected}"
    assert request.headers["content-type"].startswith("application/x-www-form-urlencoded")
    form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
    assert form == {
        "grant_type": "authorization_code", "code": CODE, "redirect_uri": REDIRECT,
        "continuous_refresh": "true",
    }
    assert token.refresh_token == REFRESH and token.access_token == ACCESS
    assert token.access_expires_at == NOW + 2592000
    assert token.refresh_expires_at == NOW + 5184000
    assert scope == ",".join(cli.SCOPES)


def test_a_response_without_a_refresh_token_is_an_error():
    with pytest.raises(cli.AuthorizeError, match="sem access_token ou refresh_token"):
        cli.exchange_code(
            app_id=APP_ID, app_secret=APP_SECRET, code=CODE, redirect_uri=REDIRECT,
            http=_token_http(body={"access_token": ACCESS}), now=NOW,
        )


def test_a_refused_exchange_explains_the_usual_causes_and_never_echoes_the_body():
    http = _token_http(status=400, body={"message": "vazou-o-segredo", "code": 2})
    with pytest.raises(cli.AuthorizeError) as err:
        cli.exchange_code(
            app_id=APP_ID, app_secret=APP_SECRET, code=CODE, redirect_uri=REDIRECT,
            http=http, now=NOW,
        )
    message = str(err.value)
    assert "HTTP 400" in message and "idêntico ao cadastrado" in message
    assert "vazou-o-segredo" not in message


# ---------- comandos ----------


def test_start_prints_the_url_and_the_steps_but_never_the_app_secret():
    out = Out()
    cli.run_start(_settings(), redirect_uri=REDIRECT, now=NOW, out=out)

    assert "https://www.pinterest.com/oauth/?" in out.text
    assert f"client_id={APP_ID}" in out.text
    assert "15 minutos" in out.text and "URL INTEIRA" in out.text
    assert APP_SECRET not in out.text


def test_start_needs_the_app_id():
    with pytest.raises(cli.AuthorizeError, match="PINTEREST_APP_ID"):
        cli.run_start(_settings(pinterest_app_id=""), redirect_uri=REDIRECT, now=NOW, out=Out())


def _finish(db, *, routes=None, scope_body=None, settings=None, store=None):
    out = Out()
    state = cli.make_state(SECRET, now=NOW)
    store = store or oauth_store.TokenStore(db, lambda: db)
    cli.run_finish(
        settings or _settings(), _redirect(state), redirect_uri=REDIRECT, store=store,
        http=_token_http(body=scope_body), now=NOW + 30,
        client_factory=lambda settings, store: FakeClient(routes or ACCOUNT_OK), out=out,
    )
    return out, store


def test_finish_saves_the_token_and_shows_what_to_configure(db: Session):
    out, _ = _finish(db)

    row = db.get(OauthToken, "pinterest")
    assert row.refresh_token == REFRESH and row.access_token == ACCESS
    assert row.scope == ",".join(cli.SCOPES)
    assert row.refresh_expires_at is not None
    assert "Token gravado." in out.text
    # O que a pessoa precisa para configurar o MP:
    assert "1234567890" in out.text and "Achados da semana" in out.text
    assert "549755885175" in out.text and "moeda BRL" in out.text
    assert "@meuperfil" in out.text and "BUSINESS" in out.text


def test_nothing_sensitive_is_ever_printed(db: Session):
    out, _ = _finish(db)

    for secret in (ACCESS, REFRESH, CODE, APP_SECRET, SECRET):
        assert secret not in out.text


def test_finish_says_when_it_replaced_an_existing_token(db: Session):
    db.add(OauthToken(provider="pinterest", refresh_token="antigo"))
    db.flush()

    out, _ = _finish(db)

    assert "substituiu o anterior" in out.text
    assert db.get(OauthToken, "pinterest").refresh_token == REFRESH


def test_finish_warns_about_missing_scopes(db: Session):
    body = {"access_token": ACCESS, "refresh_token": REFRESH, "expires_in": 1000,
            "scope": "boards:read,pins:read"}
    out, _ = _finish(db, scope_body=body)

    assert "faltam escopos" in out.text and "pins:write" in out.text and "ads:write" in out.text


def test_finish_warns_when_the_account_is_not_business(db: Session):
    routes = {**ACCOUNT_OK, "/user_account": {"username": "x", "account_type": "PINNER"}}
    out, _ = _finish(db, routes=routes)

    assert "não é BUSINESS" in out.text


def test_each_lookup_fails_on_its_own_without_hiding_the_others(db: Session):
    """Sem escopo de anúncio (ou sem conta de anúncios), boards e conta continuam aparecendo."""
    routes = {**ACCOUNT_OK, "/ad_accounts": SocialAuthError("acesso negado")}
    out, _ = _finish(db, routes=routes)

    assert "1234567890" in out.text
    assert "contas de anúncios: não consegui ler (acesso negado)" in out.text


def test_an_empty_board_list_tells_the_person_what_to_do(db: Session):
    out, _ = _finish(db, routes={**ACCOUNT_OK, "/boards": {"items": []}})
    assert "crie um no Pinterest" in out.text


def test_finish_without_credentials_points_to_the_env_file(db: Session):
    with pytest.raises(cli.AuthorizeError, match=r"\.env\.prod"):
        _finish(db, settings=_settings(pinterest_app_secret=""))


def test_a_failed_exchange_leaves_the_stored_token_untouched(db: Session):
    db.add(OauthToken(provider="pinterest", refresh_token="antigo"))
    db.flush()

    with pytest.raises(cli.AuthorizeError):
        cli.run_finish(
            _settings(), _redirect(cli.make_state(SECRET, now=NOW)), redirect_uri=REDIRECT,
            store=oauth_store.TokenStore(db, lambda: db), http=_token_http(status=400, body={}),
            now=NOW, client_factory=lambda *_: FakeClient(ACCOUNT_OK), out=Out(),
        )

    assert db.get(OauthToken, "pinterest").refresh_token == "antigo"


def test_check_needs_a_stored_token(db: Session):
    with pytest.raises(cli.AuthorizeError, match="rode `start` e `finish`"):
        cli.run_check(
            _settings(), store=oauth_store.TokenStore(db, lambda: db),
            client_factory=lambda *_: FakeClient(ACCOUNT_OK), out=Out(),
        )


def test_check_lists_the_account_with_a_stored_token(db: Session):
    db.add(OauthToken(provider="pinterest", refresh_token="r"))
    db.flush()
    out = Out()

    cli.run_check(
        _settings(), store=oauth_store.TokenStore(db, lambda: db),
        client_factory=lambda *_: FakeClient(ACCOUNT_OK), out=out,
    )

    assert "1234567890" in out.text


# ---------- TokenStore: o escopo não se perde na renovação ----------


def test_a_refresh_does_not_erase_the_granted_scope(db: Session):
    store = oauth_store.TokenStore(db, lambda: db)
    store.save(StoredToken(refresh_token="r1", access_token="a1"), scope="pins:write")

    # A renovação chama save(token) sem escopo.
    store.save(StoredToken(refresh_token="r2", access_token="a2"))

    row = db.get(OauthToken, "pinterest")
    assert row.refresh_token == "r2" and row.scope == "pins:write"


# ---------- ponto de entrada ----------


def test_the_entry_point_prints_the_url_for_start(monkeypatch, capsys):
    monkeypatch.setattr(cli, "get_settings", lambda: _settings())

    assert cli.main(["start"]) == 0

    printed = capsys.readouterr().out
    assert "pinterest.com/oauth" in printed and APP_SECRET not in printed


def test_the_entry_point_reports_errors_on_stderr_with_a_nonzero_exit(monkeypatch, capsys):
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(pinterest_app_id=""))

    assert cli.main(["start"]) == 1
    assert "PINTEREST_APP_ID" in capsys.readouterr().err
