"""Leitura tipada de `config_parameters`."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.control import ConfigParameter


def get_decimal(db: Session, key: str, default: Decimal) -> Decimal:
    raw = db.execute(
        select(ConfigParameter.value).where(ConfigParameter.key == key)
    ).scalar_one_or_none()
    return default if raw is None else Decimal(str(raw))


def get_int(db: Session, key: str, default: int) -> int:
    raw = db.execute(
        select(ConfigParameter.value).where(ConfigParameter.key == key)
    ).scalar_one_or_none()
    return default if raw is None else int(raw)
