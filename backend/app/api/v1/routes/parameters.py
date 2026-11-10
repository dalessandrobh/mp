"""Parâmetros em vigor (tela "Parâmetros" do dashboard). Só leitura: não há como alterar."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import require_dashboard_user
from app.db.session import get_db
from app.services import parameters_service

router = APIRouter(prefix="/parameters", tags=["parameters"])


@router.get("")
def get_parameters(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _user: str = Depends(require_dashboard_user),
) -> dict:
    return {"groups": parameters_service.build(db, settings)}
