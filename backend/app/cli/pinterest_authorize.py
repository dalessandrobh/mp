"""Autorização inicial do app no Pinterest (OAuth 2.0, fluxo "authorization code").

Roda UMA vez, depois que o Pinterest aprova o acesso Trial do app e libera a chave secreta.
Sem isto o MP não fala com a sua conta: o Pinterest só entrega o refresh token depois que a
pessoa aprova o app no navegador. Depois da primeira vez, `PinterestAuth` renova sozinho.

    docker exec -it -w /srv mp-backend python -m app.cli.pinterest_authorize start
    docker exec -it -w /srv mp-backend python -m app.cli.pinterest_authorize finish
    docker exec -it -w /srv mp-backend python -m app.cli.pinterest_authorize check

Três decisões que não são óbvias:

**Sem servidor local.** O fluxo clássico sobe um servidor em `localhost:8085` para receber o
código. Aqui o MP roda num servidor remoto e quem aprova usa o navegador de outra máquina
(um iPad, por exemplo): o redirecionamento para `localhost` cairia no aparelho de quem aprova,
não no servidor. Então o navegador vai mostrar "não foi possível conectar" — esperado — e a
pessoa cola a URL inteira da barra de endereço. É nessa URL que vêm o `code` e o `state`.

**`state` sem arquivo nem tabela.** O `state` é um HMAC (nonce + hora, assinado com o segredo
do MP). `finish` confere a assinatura e a idade (15 min), então `start` e `finish` podem rodar
em processos diferentes sem guardar nada. Ele protege contra aceitar um código que não saiu
de um `start` nosso.

**Nada sensível é impresso.** Nem o App secret, nem o código, nem os tokens. O que aparece é
o que a pessoa precisa decidir: tipo de conta, boards, conta de anúncios e escopos concedidos.
"""

import argparse
import base64
import getpass
import hashlib
import hmac
import secrets
import sys
import time
from collections.abc import Callable
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from app.adapters.social.base import SocialError
from app.adapters.social.pinterest.auth import TOKEN_URL, StoredToken
from app.core.config import Settings, get_settings

AUTHORIZE_URL = "https://www.pinterest.com/oauth/"
DEFAULT_REDIRECT_URI = "http://localhost:8085/"
# boards/pins: publicar; ads: criar e acompanhar campanhas; user_accounts: tipo de conta.
# Pedir os de anúncio já agora evita reautorizar depois: o escopo vai dentro do token.
SCOPES = (
    "boards:read",
    "boards:write",
    "pins:read",
    "pins:write",
    "ads:read",
    "ads:write",
    "user_accounts:read",
)
STATE_MAX_AGE_SECONDS = 15 * 60


class AuthorizeError(Exception):
    """Erro com mensagem pronta para a pessoa ler. Nunca carrega segredo."""


# ---------- state (anti-CSRF, sem armazenamento) ----------


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]


def make_state(secret: str, *, now: float) -> str:
    nonce = secrets.token_urlsafe(12)
    stamp = str(int(now))
    return f"{nonce}.{stamp}.{_sign(secret, f'{nonce}.{stamp}')}"


def check_state(
    secret: str, state: str, *, now: float, max_age: int = STATE_MAX_AGE_SECONDS
) -> None:
    parts = (state or "").split(".")
    if len(parts) != 3 or not parts[1].isdigit():
        raise AuthorizeError(
            "o `state` da URL não é o que o `start` gerou: refaça desde o `start`."
        )
    nonce, stamp, signature = parts
    if not hmac.compare_digest(signature, _sign(secret, f"{nonce}.{stamp}")):
        raise AuthorizeError(
            "o `state` da URL não confere (assinatura inválida): esta URL não saiu de um "
            "`start` deste servidor. Refaça desde o `start`."
        )
    if now - int(stamp) > max_age:
        raise AuthorizeError("o `start` tem mais de 15 minutos: refaça desde o `start`.")


# ---------- passos do fluxo ----------


def build_authorize_url(*, app_id: str, redirect_uri: str, state: str) -> str:
    query = urlencode(
        {
            "client_id": app_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": ",".join(SCOPES),
            "state": state,
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def code_from_redirect(redirect_url: str, *, secret: str, now: float) -> str:
    """Extrai o `code` da URL colada, depois de conferir o `state`."""
    query = parse_qs(urlparse((redirect_url or "").strip()).query)
    if "error" in query:
        reason = query.get("error_description", query["error"])[0]
        raise AuthorizeError(f"o Pinterest não concluiu a autorização: {reason}")
    if "code" not in query:
        raise AuthorizeError(
            "não achei `code` na URL. Cole a URL INTEIRA da barra de endereço, a que começa "
            "com o endereço de retorno e tem `?code=...&state=...` no fim."
        )
    check_state(secret, query.get("state", [""])[0], now=now)
    return query["code"][0]


def exchange_code(
    *,
    app_id: str,
    app_secret: str,
    code: str,
    redirect_uri: str,
    http: httpx.Client,
    now: float,
) -> tuple[StoredToken, str | None]:
    basic = base64.b64encode(f"{app_id}:{app_secret}".encode()).decode()
    response = http.post(
        TOKEN_URL,
        headers={"Authorization": f"Basic {basic}"},
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            # Refresh token "contínuo": renovável sem prazo final, rotacionando a cada uso.
            "continuous_refresh": "true",
        },
    )
    if response.status_code != 200:
        # O corpo do erro não é impresso: não há motivo para arriscar um segredo na tela.
        hint = (
            " O código vale uma vez e expira em minutos, e o endereço de retorno precisa "
            "ser idêntico ao cadastrado no app. Refaça desde o `start`."
            if response.status_code in (400, 401)
            else ""
        )
        raise AuthorizeError(
            f"o Pinterest recusou a troca do código (HTTP {response.status_code}).{hint}"
        )

    body = response.json()
    if not body.get("access_token") or not body.get("refresh_token"):
        raise AuthorizeError("o Pinterest respondeu sem access_token ou refresh_token.")

    access_in = body.get("expires_in")
    refresh_in = body.get("refresh_token_expires_in")
    token = StoredToken(
        refresh_token=body["refresh_token"],
        access_token=body["access_token"],
        access_expires_at=(now + float(access_in)) if access_in else None,
        refresh_expires_at=(now + float(refresh_in)) if refresh_in else None,
    )
    return token, body.get("scope")


# ---------- o que mostrar depois de autorizar ----------


def describe_account(client, out: Callable[[str], None]) -> None:
    """Lista o que a pessoa precisa para configurar o MP. Cada chamada falha sozinha."""

    def attempt(label: str, call: Callable[[], None]) -> None:
        try:
            call()
        except SocialError as exc:
            out(f"  {label}: não consegui ler ({exc})")

    def account() -> None:
        data = client.get("/user_account")
        kind = data.get("account_type", "?")
        out(f"  conta: @{data.get('username', '?')} · tipo {kind}")
        if kind != "BUSINESS":
            out("  ATENÇÃO: a conta não é BUSINESS; apps novos não publicam em conta pessoal.")

    def boards() -> None:
        items = client.get("/boards", {"page_size": 50}).get("items", [])
        out(f"  boards ({len(items)}): use o id numérico em PINTEREST_BOARD_ID")
        for board in items:
            out(f"    {board.get('id')}  {board.get('name')}  [{board.get('privacy', '?')}]")
        if not items:
            out("    nenhum board encontrado: crie um no Pinterest e rode `check` de novo.")

    def ad_accounts() -> None:
        items = client.get("/ad_accounts").get("items", [])
        out(f"  contas de anúncios ({len(items)}): use o id em PINTEREST_AD_ACCOUNT_ID")
        for acc in items:
            out(f"    {acc.get('id')}  {acc.get('name')}  moeda {acc.get('currency', '?')}")
        if not items:
            out("    nenhuma conta de anúncios (normal se ainda não criou).")

    attempt("conta", account)
    attempt("boards", boards)
    attempt("contas de anúncios", ad_accounts)


# ---------- comandos ----------


def _require_credentials(settings: Settings) -> None:
    if not (settings.pinterest_app_id and settings.pinterest_app_secret):
        raise AuthorizeError(
            "PINTEREST_APP_ID e PINTEREST_APP_SECRET não estão configurados neste container. "
            "Ponha-os no deploy/.env.prod e recrie o backend (`up -d backend`): o container "
            "só lê o .env na criação."
        )


def run_start(settings: Settings, *, redirect_uri: str, now: float, out=print) -> None:
    if not settings.pinterest_app_id:
        raise AuthorizeError("PINTEREST_APP_ID não está configurado neste container.")
    state = make_state(settings.jwt_secret, now=now)
    url = build_authorize_url(
        app_id=settings.pinterest_app_id, redirect_uri=redirect_uri, state=state
    )
    out("1. Abra este endereço no navegador, logado na conta business do Pinterest:\n")
    out(f"   {url}\n")
    out("2. Confira os acessos pedidos e clique em permitir.")
    out(f"3. O navegador vai tentar abrir {redirect_uri} e mostrar um erro de conexão.")
    out("   É ESPERADO. Copie a URL INTEIRA da barra de endereço (no iPad, toque nela para")
    out("   ver o endereço completo).")
    out("4. Rode: python -m app.cli.pinterest_authorize finish")
    out("   e cole a URL quando ela pedir. Você tem 15 minutos.")


def run_finish(
    settings: Settings,
    redirect_url: str,
    *,
    redirect_uri: str,
    store,
    http: httpx.Client,
    now: float,
    client_factory: Callable[[Settings, object], object],
    out=print,
) -> None:
    _require_credentials(settings)
    code = code_from_redirect(redirect_url, secret=settings.jwt_secret, now=now)
    token, scope = exchange_code(
        app_id=settings.pinterest_app_id,
        app_secret=settings.pinterest_app_secret,
        code=code,
        redirect_uri=redirect_uri,
        http=http,
        now=now,
    )
    replaced = store.load() is not None
    store.save(token, scope=scope)
    out("Autorizado. Token gravado" + (" (substituiu o anterior)." if replaced else "."))
    granted = set((scope or "").replace(",", " ").split())
    out(f"  escopos concedidos: {', '.join(sorted(granted)) or '(o Pinterest não informou)'}")
    missing = [s for s in SCOPES if granted and s not in granted]
    if missing:
        out(f"  ATENÇÃO: faltam escopos ({', '.join(missing)}). Funcionalidades que dependem")
        out("  deles não vão funcionar; reautorize depois de ajustar o app.")
    if token.refresh_expires_at:
        days = int((token.refresh_expires_at - now) // 86400)
        out(f"  o refresh token vale {days} dias e é renovado a cada uso.")
    out("\nO que o Pinterest mostra para esta conta:")
    describe_account(client_factory(settings, store), out)


def run_check(settings: Settings, *, store, client_factory, out=print) -> None:
    _require_credentials(settings)
    if store.load() is None:
        raise AuthorizeError("ainda não há token gravado: rode `start` e `finish` primeiro.")
    out("O que o Pinterest mostra para esta conta:")
    describe_account(client_factory(settings, store), out)


# ---------- ligação com o ambiente real ----------


def _default_client(settings: Settings, store):
    from app.adapters.social.pinterest.factory import build_client

    return build_client(settings, token_store=store)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Autoriza o MP na conta do Pinterest.")
    parser.add_argument("command", choices=("start", "finish", "check"))
    parser.add_argument("--redirect-uri", default=DEFAULT_REDIRECT_URI)
    parser.add_argument(
        "--redirect-url",
        help="URL colada do navegador (finish). Se omitida, é pedida sem eco no terminal.",
    )
    args = parser.parse_args(argv)
    settings = get_settings()
    now = time.time()

    try:
        if args.command == "start":
            run_start(settings, redirect_uri=args.redirect_uri, now=now)
            return 0

        from app.db.session import SessionLocal
        from app.services.oauth_store import TokenStore

        with SessionLocal() as db:
            store = TokenStore(db, SessionLocal)
            if args.command == "check":
                run_check(settings, store=store, client_factory=_default_client)
                return 0
            url = args.redirect_url or getpass.getpass("Cole a URL de retorno: ")
            with httpx.Client(timeout=30.0) as http:
                run_finish(
                    settings,
                    url,
                    redirect_uri=args.redirect_uri,
                    store=store,
                    http=http,
                    now=now,
                    client_factory=_default_client,
                )
        return 0
    except AuthorizeError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
