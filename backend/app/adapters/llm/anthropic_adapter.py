"""Claude pela API de Mensagens, via httpx (sem SDK). A chave vem do ambiente."""

import time
from decimal import Decimal

import httpx

from app.adapters.llm.base import LLMAdapter, LLMError, LLMResult

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
MILLION = Decimal(1_000_000)


class AnthropicAdapter(LLMAdapter):
    provider = "anthropic"

    def __init__(
        self, *, api_key: str, model: str, input_usd_per_mtok: Decimal,
        output_usd_per_mtok: Decimal, timeout: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise LLMError("ANTHROPIC_API_KEY vazia")
        self.model = model
        self._key = api_key
        self._in, self._out = input_usd_per_mtok, output_usd_per_mtok
        self._client = client or httpx.Client(timeout=timeout)

    def generate(self, *, system: str, prompt: str, max_tokens: int) -> LLMResult:
        started = time.monotonic()
        try:
            response = self._client.post(
                API_URL,
                headers={
                    "x-api-key": self._key, "anthropic-version": API_VERSION,
                    "content-type": "application/json",
                },
                json={
                    "model": self.model, "max_tokens": max_tokens, "system": system,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
        except httpx.HTTPError as exc:
            raise LLMError(f"falha de rede: {type(exc).__name__}") from exc
        if response.status_code != 200:
            # O corpo da resposta de erro não leva a chave; mas corta por segurança.
            raise LLMError(f"HTTP {response.status_code}: {response.text[:200]}")
        body = response.json()
        blocks = body.get("content", [])
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        usage = body.get("usage") or {}
        tokens_in, tokens_out = usage.get("input_tokens"), usage.get("output_tokens")
        cost = None
        if tokens_in is not None and tokens_out is not None:
            cost = (Decimal(tokens_in) * self._in + Decimal(tokens_out) * self._out) / MILLION
        return LLMResult(
            text=text, model=body.get("model", self.model), input_tokens=tokens_in,
            output_tokens=tokens_out, cost_usd=cost,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
