"""Cliente HTTP do Pinterest v5: autentica, respeita o limite de taxa e traduz erros.

O limite que importa para o MP é `org_write`: 300/dia no Trial, 100/min/usuário no
Standard. Publicar 10 pins/dia não chega perto de nenhum dos dois, então o cuidado aqui
não é com volume — é com o 429 que aparece quando outra coisa na conta consome a cota.
O Pinterest informa `x-ratelimit-remaining`, e vale registrar quando a sobra fica baixa:
é o aviso que antecede a falha.

Erro 403 com `PINNER_DATA_ACCESS_DENIED` tem causa específica e mensagem própria: app
registrado a partir de 14/09/2026 exige conta business. Sem isso o pin nunca sai, e a
mensagem genérica de 403 mandaria o operador procurar no lugar errado.
"""

import logging
import random
import time
from collections.abc import Callable
from typing import Any

import httpx

from app.adapters.social.base import (
    SocialAuthError,
    SocialError,
    SocialRateLimited,
    SocialRejected,
)
from app.adapters.social.pinterest.auth import PinterestAuth

logger = logging.getLogger(__name__)

BASE_URL = "https://api.pinterest.com/v5"
SANDBOX_URL = "https://api-sandbox.pinterest.com/v5"
LOW_QUOTA_WARNING = 50


class PinterestClient:
    def __init__(
        self,
        *,
        auth: PinterestAuth,
        base_url: str = BASE_URL,
        timeout: float = 30.0,
        max_retries: int = 3,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._auth = auth
        self._base = base_url.rstrip("/")
        self._http = http or httpx.Client(timeout=timeout)
        self._max_retries = max_retries
        self._sleep = sleep

    def post(self, path: str, payload: Any) -> Any:
        return self._send("POST", path, json=payload)

    def patch(self, path: str, payload: Any) -> Any:
        return self._send("PATCH", path, json=payload)

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._send("GET", path, params=params)

    def _send(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Os endpoints de criação de anúncio recebem uma LISTA no corpo, por isso `Any`.

        Repetir a chamada é seguro aqui só porque a única coisa repetida é a que falhou
        antes de o Pinterest responder (rede, 429, 5xx). Um 4xx nunca é repetido.
        """
        last: Exception | None = None
        for attempt in range(self._max_retries + 1):
            token = self._auth.access_token()
            try:
                response = self._http.request(
                    method,
                    f"{self._base}{path}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json=json,
                    params=params,
                )
            except httpx.HTTPError as exc:
                last = SocialError(f"falha de rede: {exc}")
                self._backoff(attempt)
                continue

            self._log_quota(response)
            if response.status_code == 429:
                last = SocialRateLimited("limite de taxa do Pinterest")
                self._backoff(attempt, response)
                continue
            if response.status_code >= 500:
                last = SocialError(f"Pinterest indisponível (HTTP {response.status_code})")
                self._backoff(attempt)
                continue
            return self._parse(response)

        raise last or SocialError("falha desconhecida ao chamar o Pinterest")

    @staticmethod
    def _parse(response: httpx.Response) -> Any:
        if response.status_code in (200, 201):
            return response.json()

        try:
            body = response.json()
        except ValueError:
            body = {}
        code = str(body.get("code", ""))
        message = body.get("message") or response.text[:200]

        if response.status_code == 401:
            raise SocialAuthError(f"token recusado pelo Pinterest: {message}")
        if response.status_code == 403:
            if "PINNER_DATA_ACCESS_DENIED" in f"{code}{message}":
                raise SocialAuthError(
                    "PINNER_DATA_ACCESS_DENIED: a conta do Pinterest precisa ser business. "
                    "Apps registrados a partir de 14/09/2026 não publicam em conta pessoal."
                )
            raise SocialAuthError(f"acesso negado pelo Pinterest: {message}")
        raise SocialRejected(f"Pinterest recusou (HTTP {response.status_code}): {message}")

    @staticmethod
    def _log_quota(response: httpx.Response) -> None:
        remaining = response.headers.get("x-ratelimit-remaining")
        if remaining is None:
            return
        try:
            left = int(remaining)
        except ValueError:
            return
        if left <= LOW_QUOTA_WARNING:
            logger.warning(
                "cota do Pinterest baixa: %s requisições restantes (limite %s)",
                left,
                response.headers.get("x-ratelimit-limit", "?"),
            )

    def _backoff(self, attempt: int, response: httpx.Response | None = None) -> None:
        if attempt >= self._max_retries:
            return
        retry_after = response.headers.get("retry-after") if response is not None else None
        if retry_after:
            try:
                self._sleep(min(float(retry_after), 60.0))
                return
            except ValueError:
                pass
        self._sleep(min(2.0**attempt + random.random(), 30.0))
