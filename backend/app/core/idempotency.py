"""Idempotência para os endpoints que o n8n chama.

O n8n faz retry automático. Sem isso, um retry de "criar campanha" cria duas
campanhas. A chave é enviada pelo cliente no header `Idempotency-Key`; a mesma
chave com o mesmo corpo devolve a resposta guardada, e com corpo diferente é
conflito — nunca um segundo efeito.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import IdempotencyConflict
from app.models.control import IdempotencyKey

DEFAULT_TTL = timedelta(hours=24)


def hash_request(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def lookup(db: Session, *, key: str, endpoint: str, payload: object) -> dict | None:
    """Devolve a resposta guardada se esta chave já foi usada com o mesmo corpo.

    None significa "pode executar". Chave repetida com corpo diferente levanta
    IdempotencyConflict.
    """
    record = db.execute(
        select(IdempotencyKey).where(IdempotencyKey.key == key)
    ).scalar_one_or_none()

    if record is None:
        return None

    if record.expires_at <= datetime.now(UTC):
        db.delete(record)
        db.flush()
        return None

    if record.request_hash != hash_request(payload):
        raise IdempotencyConflict(
            "Idempotency-Key reutilizada com corpo diferente",
            details={"key": key, "endpoint": record.endpoint},
        )

    return record.response_body or {}


def store(
    db: Session,
    *,
    key: str,
    endpoint: str,
    payload: object,
    response_body: dict,
    status_code: int = 200,
    ttl: timedelta = DEFAULT_TTL,
) -> None:
    db.add(
        IdempotencyKey(
            key=key,
            endpoint=endpoint,
            request_hash=hash_request(payload),
            response_body=response_body,
            status_code=status_code,
            expires_at=datetime.now(UTC) + ttl,
        )
    )
    db.flush()
