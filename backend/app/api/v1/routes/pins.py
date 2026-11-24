"""Pins do dia no painel. Só pessoas: exige o JWT do painel."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import DomainError
from app.core.security import require_dashboard_user
from app.db.session import get_db
from app.services import pin_service

router = APIRouter(prefix="/pins", tags=["pins"])


@router.get("/today")
def pins_today(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _user: str = Depends(require_dashboard_user),
) -> dict:
    if not settings.public_base:
        raise DomainError("PUBLIC_BASE_URL não configurada: sem ela o pin não tem link nem imagem")
    cards = pin_service.recent(db, public_base=settings.public_base)
    return {
        "items": [
            {
                "creative_id": c.creative_id, "product_id": c.product_id, "title": c.title,
                "board": c.board, "description": c.description, "link": c.link,
                "image_url": c.image_url, "pin_it_url": c.pin_it_url, "posted": c.posted,
                "created_at": c.created_at.isoformat(),
            }
            for c in cards
        ],
        "pending": sum(1 for c in cards if not c.posted),
    }


@router.post("/{creative_id}/posted")
def mark_posted(
    creative_id: int,
    db: Session = Depends(get_db),
    _user: str = Depends(require_dashboard_user),
) -> dict:
    try:
        created = pin_service.mark_posted(db, creative_id)
    except pin_service.PinError as exc:
        raise DomainError(str(exc)) from exc
    return {"creative_id": creative_id, "marked": created}
