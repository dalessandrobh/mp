"""Gatilhos do n8n para Discovery e Qualification.

Só validam entrada, aplicam idempotência/dry-run e chamam o serviço.
Em dry-run o serviço roda de verdade e a transação é desfeita: o resultado
reflete o que aconteceria, sem deixar rastro.
"""

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.adapters.marketplace.registry import get_marketplace_adapter
from app.core import idempotency
from app.core.config import Settings, get_settings
from app.core.security import require_api_key
from app.db.session import get_db
from app.schemas.pipeline import (
    DiscoveryRequest,
    DiscoveryResponse,
    QualificationRequest,
    QualificationResponse,
)
from app.services.discovery_service import run_discovery
from app.services.qualification_service import run_qualification

router = APIRouter(tags=["pipeline"], dependencies=[Depends(require_api_key)])


def _require_key(key: str | None) -> str:
    if not key:
        raise HTTPException(status_code=400, detail="Header Idempotency-Key é obrigatório")
    return key


def _resolve_dry_run(flag: bool | None, settings: Settings) -> bool:
    # Pedido explícito não pode destravar o que a configuração global trava.
    return settings.dry_run or bool(flag)


@router.post("/discovery/run", response_model=DiscoveryResponse)
def discovery_run(
    body: DiscoveryRequest,
    dry_run: bool | None = Query(default=None),
    idempotency_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    key = _require_key(idempotency_key)
    endpoint = "/discovery/run"
    payload = body.model_dump(mode="json")
    effective_dry = _resolve_dry_run(dry_run, settings)

    cached = idempotency.lookup(db, key=key, endpoint=endpoint, payload=payload)
    if cached is not None:
        return cached

    result = run_discovery(db, get_marketplace_adapter(settings), **body.model_dump())
    response = {
        "dry_run": effective_dry,
        "seen": result.seen,
        "new_products": result.new_products,
        "snapshots": result.snapshots,
    }

    if effective_dry:
        db.rollback()
    else:
        idempotency.store(db, key=key, endpoint=endpoint, payload=payload, response_body=response)
    return response


@router.post("/qualification/run", response_model=QualificationResponse)
def qualification_run(
    body: QualificationRequest,
    dry_run: bool | None = Query(default=None),
    idempotency_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    key = _require_key(idempotency_key)
    endpoint = "/qualification/run"
    payload = body.model_dump(mode="json")
    effective_dry = _resolve_dry_run(dry_run, settings)

    cached = idempotency.lookup(db, key=key, endpoint=endpoint, payload=payload)
    if cached is not None:
        return cached

    result = run_qualification(db, limit=body.limit)
    response = {
        "dry_run": effective_dry,
        "evaluated": result.evaluated,
        "candidates": result.candidates,
        "rejected": result.rejected,
        "expired": result.expired,
        "waiting_data": result.waiting_data,
    }

    if effective_dry:
        db.rollback()
    else:
        idempotency.store(db, key=key, endpoint=endpoint, payload=payload, response_body=response)
    return response
