from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class RunResponse(BaseModel):
    """Envelope padrão dos endpoints de gatilho (PLANNING §5)."""

    run_id: int
    status: str
    dry_run: bool
    summary: dict
    items: list = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DiscoveryRequest(BaseModel):
    keyword: str | None = None
    limit: int = Field(default=50, ge=1, le=500)
    # Varre as categorias nível 1 conhecidas (tabela `categories`), `per_category` por uma.
    by_category: bool = False
    per_category: int = Field(default=40, ge=1, le=500)
    category_ids: list[str] | None = None
    # Varredura por PREÇO DECRESCENTE, guardando só comissão alta COM venda provada.
    # Os pisos vazios caem nos de `Settings` (commission_sweep_*).
    by_commission: bool = False
    min_commission_value: Decimal | None = Field(default=None, ge=0)
    min_sales: int | None = Field(default=None, ge=0)

    def sweep_size(self, default: int) -> int:
        """`per_category` só vence o padrão se vier escrito no corpo.

        As duas varreduras têm profundidade natural diferente — 40 por categoria basta
        para pegar os mais vendidos, e a cauda de comissão só aparece com centenas — então
        o padrão de uma não pode virar o da outra por acidente.
        """
        return self.per_category if "per_category" in self.model_fields_set else default


class LinkGenerationRequest(BaseModel):
    channel: str = Field(default="meta", pattern=r"^[a-z0-9]+$", max_length=12)
    campaign_id: int | None = Field(default=None, ge=1)
    creative_id: int | None = Field(default=None, ge=1)


class PerformanceWindowRequest(BaseModel):
    days: int = Field(default=14, ge=1, le=60)


class RejectRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class ReviewRequest(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
