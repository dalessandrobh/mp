"""Locks de execução: impedem que o mesmo workflow rode duas vezes em paralelo.

Um lock expirado é tomado de volta — senão um worker que morreu no meio
travaria o workflow para sempre.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.exceptions import LockUnavailable
from app.models.control import ExecutionLock

DEFAULT_LEASE = timedelta(minutes=30)


def acquire(db: Session, *, lock_name: str, owner: str, lease: timedelta = DEFAULT_LEASE) -> None:
    now = datetime.now(UTC)

    # Um único statement: toma o lock se estiver livre ou vencido.
    # O RETURNING é o sinal de sucesso — não vem linha quando o WHERE barra o
    # update, e rowcount não é confiável nesse formato de statement.
    statement = (
        insert(ExecutionLock)
        .values(
            lock_name=lock_name,
            acquired_by=owner,
            acquired_at=now,
            expires_at=now + lease,
        )
        .on_conflict_do_update(
            index_elements=[ExecutionLock.lock_name],
            set_={"acquired_by": owner, "acquired_at": now, "expires_at": now + lease},
            where=ExecutionLock.expires_at <= now,
        )
        .returning(ExecutionLock.lock_name)
    )

    if db.execute(statement).scalar_one_or_none() is None:
        raise LockUnavailable(
            f"Workflow '{lock_name}' já está em execução", details={"lock_name": lock_name}
        )
    db.flush()


def release(db: Session, *, lock_name: str, owner: str) -> None:
    db.execute(
        delete(ExecutionLock).where(
            ExecutionLock.lock_name == lock_name, ExecutionLock.acquired_by == owner
        )
    )
    db.flush()


@contextmanager
def execution_lock(
    db: Session, *, lock_name: str, owner: str, lease: timedelta = DEFAULT_LEASE
) -> Iterator[None]:
    acquire(db, lock_name=lock_name, owner=owner, lease=lease)
    try:
        yield
    finally:
        release(db, lock_name=lock_name, owner=owner)
