from pydantic import BaseModel, Field

from app.adapters.marketplace.base import SortBy


class DiscoveryRequest(BaseModel):
    keyword: str | None = Field(default=None, max_length=100)
    sort_by: SortBy = SortBy.COMMISSION
    pages: int = Field(default=1, ge=1, le=10)
    limit: int = Field(default=20, ge=1, le=50)


class DiscoveryResponse(BaseModel):
    dry_run: bool
    seen: int
    new_products: int
    snapshots: int


class QualificationRequest(BaseModel):
    limit: int = Field(default=200, ge=1, le=500)


class QualificationResponse(BaseModel):
    dry_run: bool
    evaluated: int
    candidates: list[int]
    rejected: list[int]
    expired: list[int]
    waiting_data: list[int]
