"""Fila de aprovação de pins (dashboard). Só pessoas: a chave do n8n é recusada aqui.

Regra 4.3 das Diretrizes de Desenvolvedor do Pinterest: cada pin publicado precisa ter sido
escolhido pela pessoa. Estes endpoints são onde essa escolha acontece. Exigem o JWT do
painel (`require_dashboard_user`), e NÃO `require_reader`: se o n8n pudesse aprovar, o
workflow aprovaria os próprios pins.
"""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import require_dashboard_user
from app.db.session import get_db
from app.services import approval_service
from app.services.publishing_constants import WINDOW_DAYS

router = APIRouter(prefix="/publishing", tags=["publishing"])


class DecisionRequest(BaseModel):
    creative_ids: list[int] = Field(min_length=1, max_length=100)
    decision: Literal["APPROVED", "REJECTED"]


@router.get("/queue")
def get_queue(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _user: str = Depends(require_dashboard_user),
) -> dict:
    items = approval_service.queue(
        db,
        price_ceiling=float(settings.publish_price_ceiling),
        brand_categories=settings.brand_categories,
    )
    return {
        "window_days": WINDOW_DAYS,
        "awaiting": sum(1 for i in items if i.status == approval_service.PENDING),
        "items": [
            {
                **{k: v for k, v in i.__dict__.items() if k != "created_at"},
                "created_at": i.created_at,
            }
            for i in items
        ],
    }


@router.post("/decisions")
def post_decisions(
    body: DecisionRequest,
    db: Session = Depends(get_db),
    actor: str = Depends(require_dashboard_user),
) -> dict:
    result = approval_service.decide(
        db, creative_ids=body.creative_ids, decision=body.decision, actor=actor
    )
    return {
        "decision": body.decision,
        "recorded": result.recorded,
        "unchanged": result.unchanged,
        "already_posted": result.already_posted,
    }
