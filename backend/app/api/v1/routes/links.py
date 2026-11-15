"""Link rastreado para divulgação manual (painel). Só pessoas: exige o JWT do painel."""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.adapters.marketplace.registry import get_marketplace_adapter
from app.core.config import Settings, get_settings
from app.core.security import require_dashboard_user
from app.db.session import get_db
from app.services import manual_link_service, showcase_service

router = APIRouter(prefix="/links", tags=["links"])


class ManualLinkRequest(BaseModel):
    ref: str = Field(min_length=1, max_length=500, description="URL do produto ou id do item")
    channel: str = Field(default="wa", description="wa, ig ou pin")


@router.post("/manual")
def create_manual_link(
    body: ManualLinkRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _user: str = Depends(require_dashboard_user),
) -> dict:
    link = manual_link_service.create(
        db,
        get_marketplace_adapter(settings),
        ref=body.ref,
        channel=body.channel,
        public_base=settings.public_base,
        max_sub_id_length=settings.subid_max_length,
    )
    return {
        "product_id": link.product_id, "title": link.title, "channel": link.channel,
        "sub_id": link.sub_id, "tracked_url": link.tracked_url,
    }


@router.get("/showcase.csv")
def showcase_csv(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _user: str = Depends(require_dashboard_user),
) -> Response:
    items = showcase_service.rows(
        db, get_marketplace_adapter(settings), limit=limit, max_price=settings.content_max_price
    )
    return Response(
        content="\ufeff" + showcase_service.to_csv(items),  # BOM: o Excel abre com acento certo
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="vitrine.csv"'},
    )
