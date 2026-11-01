"""Contrato do provedor de anúncios.

Não existe método de ativação, de propósito: a plataforma só cria estrutura
pausada e a ativação é feita por um humano no Gerenciador de Anúncios. Um
adapter que não sabe ativar não pode ser usado para ativar.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

PAUSED = "PAUSED"


@dataclass(frozen=True)
class AdInsight:
    """Linha diária do Insights. Campo que o Meta não devolveu fica None."""

    external_ad_id: str
    metric_date: date
    impressions: int | None
    clicks: int | None
    spend: Decimal | None
    payload: dict | None = None


class AdsAdapter(ABC):
    ad_account_id: str

    @abstractmethod
    def create_campaign(self, payload: dict) -> str:
        """Cria a campanha e devolve o id externo. O payload já vem com status=PAUSED."""

    @abstractmethod
    def create_ad_set(self, payload: dict) -> str: ...

    @abstractmethod
    def create_ad(self, payload: dict) -> str: ...

    @abstractmethod
    def get_campaign_status(self, external_id: str) -> str:
        """Relê o estado REAL da campanha no provedor, não o que foi enviado."""

    @abstractmethod
    def pause_campaign(self, external_id: str) -> None:
        """Única mutação de estado permitida: levar a campanha para PAUSED."""

    @abstractmethod
    def fetch_insights(
        self, *, external_ad_ids: Sequence[str], since: date, until: date
    ) -> list[AdInsight]:
        """Métricas diárias por anúncio. Somente leitura."""
