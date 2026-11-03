"""OAuth 2.0 do Pinterest, com o detalhe que decide o desenho: o token ROTACIONA.

A resposta de `POST /v5/oauth/token` traz `refresh_token` novo, e o refresh token é
"continuous refresh": **expira em 60 dias, renovável indefinidamente** (docs oficiais do
Pinterest, nota de 25/09/2025). Duas consequências que não são opcionais:

1. Guardar o refresh token só em variável de ambiente QUEBRA. Na primeira renovação o
   valor do ambiente fica velho e a próxima chamada falha com 401. Por isso aqui há
   `load`/`save` injetados: quem instancia decide onde persistir (no MP, tabela
   `oauth_tokens`), e o ambiente serve apenas de semente na primeira vez.
2. Sessenta dias sem renovar mata a integração e exige reautorização MANUAL no navegador
   — não há como o sistema se recuperar sozinho. Então `refresh_expires_at` é dado de
   alerta, não só de controle interno: quem publica todo dia renova de sobra, mas uma
   pausa longa (feriado, workflow desligado) precisa avisar antes de virar incidente.

A autenticação do endpoint de token é Basic com app_id:app_secret, e o corpo é
form-urlencoded — não JSON.
"""

import base64
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, replace

import httpx

from app.adapters.social.base import SocialAuthError

logger = logging.getLogger(__name__)

TOKEN_URL = "https://api.pinterest.com/v5/oauth/token"
# Renova com folga: um access token que vence durante a requisição vira 401 à toa.
REFRESH_MARGIN_SECONDS = 300
# Abaixo disso o refresh token está perto demais do fim para confiar no automático.
REFRESH_TOKEN_WARN_DAYS = 10


@dataclass(frozen=True)
class StoredToken:
    refresh_token: str
    access_token: str | None = None
    access_expires_at: float | None = None
    refresh_expires_at: float | None = None

    def access_is_fresh(self, now: float) -> bool:
        return bool(
            self.access_token
            and self.access_expires_at
            and self.access_expires_at - REFRESH_MARGIN_SECONDS > now
        )


class PinterestAuth:
    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        load: Callable[[], StoredToken | None],
        save: Callable[[StoredToken], None],
        http: httpx.Client | None = None,
        clock: Callable[[], float] = time.time,
        timeout: float = 30.0,
    ) -> None:
        if not app_id or not app_secret:
            raise ValueError("PINTEREST_APP_ID e PINTEREST_APP_SECRET são obrigatórios")
        self._app_id = app_id
        self._app_secret = app_secret
        self._load = load
        self._save = save
        self._http = http or httpx.Client(timeout=timeout)
        self._clock = clock

    def _basic(self) -> str:
        raw = f"{self._app_id}:{self._app_secret}".encode()
        return "Basic " + base64.b64encode(raw).decode()

    def access_token(self) -> str:
        stored = self._load()
        if stored is None or not stored.refresh_token:
            raise SocialAuthError(
                "sem refresh token do Pinterest: autorize o app no navegador uma vez e "
                "semeie PINTEREST_REFRESH_TOKEN"
            )
        now = self._clock()
        if stored.access_is_fresh(now):
            return stored.access_token  # type: ignore[return-value]
        return self._refresh(stored, now)

    def _refresh(self, stored: StoredToken, now: float) -> str:
        if stored.refresh_expires_at and stored.refresh_expires_at <= now:
            raise SocialAuthError(
                "refresh token do Pinterest expirou (60 dias sem renovar). É preciso "
                "reautorizar o app no navegador — o sistema não se recupera sozinho."
            )
        try:
            response = self._http.post(
                TOKEN_URL,
                headers={
                    "Authorization": self._basic(),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"grant_type": "refresh_token", "refresh_token": stored.refresh_token},
            )
        except httpx.HTTPError as exc:
            raise SocialAuthError(f"falha de rede ao renovar token: {exc}") from exc

        if response.status_code >= 400:
            # O corpo do erro do Pinterest pode citar o token; não vai para o log.
            raise SocialAuthError(
                f"Pinterest recusou a renovação do token (HTTP {response.status_code})"
            )

        body = response.json()
        access = body.get("access_token")
        if not access:
            raise SocialAuthError("resposta de token sem access_token")

        expires_in = int(body.get("expires_in") or 0)
        fresh = replace(
            stored,
            access_token=access,
            access_expires_at=now + expires_in if expires_in else None,
        )
        # O Pinterest devolve refresh token novo; o antigo deixa de valer.
        if body.get("refresh_token"):
            refresh_in = int(body.get("refresh_token_expires_in") or 0)
            fresh = replace(
                fresh,
                refresh_token=body["refresh_token"],
                refresh_expires_at=now + refresh_in if refresh_in else None,
            )
        self._save(fresh)
        logger.info(
            "token do Pinterest renovado; access expira em %ss, refresh em %s dias",
            expires_in or "?",
            round((fresh.refresh_expires_at - now) / 86400) if fresh.refresh_expires_at else "?",
        )
        return access

    def refresh_token_days_left(self) -> float | None:
        """Dias até o refresh token expirar. None quando a validade é desconhecida."""
        stored = self._load()
        if stored is None or stored.refresh_expires_at is None:
            return None
        return (stored.refresh_expires_at - self._clock()) / 86400
