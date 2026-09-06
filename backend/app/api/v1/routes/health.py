from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Estado da app + em que trilhos ela está rodando.

    Os flags de modo aparecem aqui de propósito: em produção é a forma mais
    rápida de confirmar que a plataforma não está tocando sistema externo.
    """
    try:
        db.execute(text("SELECT 1"))
        database = "up"
    except Exception:
        database = "down"

    return {
        "status": "ok" if database == "up" else "degraded",
        "environment": settings.app_env,
        "database": database,
        "mode": {
            "mock_marketplace": settings.mock_marketplace,
            "mock_ads": settings.mock_ads,
            "dry_run": settings.dry_run,
            "ai_autonomy_level": settings.ai_autonomy_level,
            "llm_enabled": settings.opportunity_use_llm,
        },
    }
