"""Cliente GraphQL da Shopee: assina, limita a taxa e traduz erros.

A API responde HTTP 200 mesmo em erro; o erro vem em `errors[].extensions.code`:

  10020  assinatura/timestamp/credencial inválidos
  10030  rate limit  -> backoff exponencial e retry
  10031-10035 acesso negado / conta congelada / sem acesso à API -> falha, sem retry
  11001  parâmetro inválido (inclui scrollId expirado após 30 s)

Tudo que não é rate limit e não é falha de rede/5xx levanta direto: repetir não conserta.
"""

import json
import logging
import random
import time
from collections.abc import Callable
from typing import Any

import httpx

from app.adapters.marketplace.shopee.auth import ShopeeAuth

logger = logging.getLogger(__name__)

RATE_LIMITED = 10030
SIGNATURE_ERROR = 10020
INVALID_PARAMS = 11001


class ShopeeError(Exception):
    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class ShopeeRateLimited(ShopeeError):
    """10030 depois de esgotar as tentativas."""


class ShopeeAuthError(ShopeeError):
    """Credencial/assinatura/permissão: configuração, não retry."""


class ShopeeInvalidParams(ShopeeError):
    """11001. Para scroll, normalmente é o scrollId expirado."""


_AUTH_CODES = {10020, 10031, 10032, 10033, 10034, 10035}


class ShopeeClient:
    def __init__(
        self,
        *,
        url: str,
        auth: ShopeeAuth,
        timeout: float = 30.0,
        min_interval: float = 0.5,
        max_retries: int = 4,
        http: httpx.Client | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._url = url
        self._auth = auth
        self._http = http or httpx.Client(timeout=timeout)
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._clock = clock
        self._sleep = sleep
        self._last_call = 0.0

    def execute(self, query: str, variables: dict | None = None) -> dict[str, Any]:
        """Devolve `data`. Levanta ShopeeError (ou subclasse) em qualquer falha."""
        body = {"query": query}
        if variables:
            body["variables"] = variables
        # Uma serialização só: é esta string que é assinada E enviada.
        payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False)

        attempt = 0
        while True:
            self._throttle()
            try:
                return self._send(payload)
            except ShopeeRateLimited:
                if attempt >= self._max_retries:
                    raise
                delay = min(30.0, 2.0**attempt) * (0.75 + random.random() / 2)
                logger.warning("shopee_rate_limited", extra={"retry_in": round(delay, 2)})
                self._sleep(delay)
                attempt += 1
            except (httpx.TransportError, _ServerError) as exc:
                if attempt >= self._max_retries:
                    raise ShopeeError(f"Shopee indisponível: {exc}") from exc
                self._sleep(min(30.0, 2.0**attempt))
                attempt += 1

    def _throttle(self) -> None:
        wait = self._min_interval - (self._clock() - self._last_call)
        if wait > 0:
            self._sleep(wait)
        self._last_call = self._clock()

    def _send(self, payload: str) -> dict[str, Any]:
        timestamp = int(self._clock())  # assinatura nova a cada tentativa: o timestamp expira
        response = self._http.post(
            self._url,
            content=payload.encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": self._auth.header(payload, timestamp),
            },
        )
        if response.status_code >= 500:
            raise _ServerError(f"HTTP {response.status_code}")
        if response.status_code == 429:
            raise ShopeeRateLimited("HTTP 429", code=RATE_LIMITED)
        if response.status_code >= 400:
            raise ShopeeError(f"HTTP {response.status_code}: {response.text[:200]}")

        document = response.json()
        errors = document.get("errors")
        if errors:
            raise _translate(errors[0])
        return document.get("data") or {}


class _ServerError(Exception):
    pass


def _translate(error: dict) -> ShopeeError:
    code = (error.get("extensions") or {}).get("code")
    message = error.get("message") or "erro desconhecido"
    if code == RATE_LIMITED:
        return ShopeeRateLimited(message, code=code)
    if code in _AUTH_CODES:
        return ShopeeAuthError(message, code=code)
    if code == INVALID_PARAMS:
        return ShopeeInvalidParams(message, code=code)
    return ShopeeError(message, code=code if isinstance(code, int) else None)
