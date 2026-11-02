"""Contrato dos provedores de LLM. O MP só pede TEXTO; quem valida é o serviço."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal


class LLMError(Exception):
    """Falha ao falar com o provedor (rede, cota, resposta inválida)."""


@dataclass(frozen=True)
class LLMResult:
    text: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: Decimal | None
    latency_ms: int


class LLMAdapter(ABC):
    provider: str
    model: str

    @abstractmethod
    def generate(self, *, system: str, prompt: str, max_tokens: int) -> LLMResult: ...
