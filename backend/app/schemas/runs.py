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
