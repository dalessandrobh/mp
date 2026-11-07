"""Fixtures dos testes.

Cada teste roda dentro de uma transação que é revertida no fim, então os testes
compartilham o mesmo banco migrado sem sujar um ao outro. Os testes de
append-only precisam do Postgres real — os triggers vivem lá, não no Python.
"""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.marketplace.mock.adapter import MockAdapter
from app.db.session import engine
from app.domain.enums import ProductState
from app.domain.state_machine import transition
from app.models.catalog import Marketplace, Product
from app.services import content_service, discovery_service

# Base pública usada nos testes de publicação e de anúncio.
BASE = "https://mp.test"


@pytest.fixture
def db() -> Session:
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def marketplace(db: Session) -> Marketplace:
    record = Marketplace(
        code="mock",
        display_name="Mock Marketplace",
        adapter_class="app.adapters.marketplace.mock.adapter.MockAdapter",
    )
    db.add(record)
    db.flush()
    return record


@pytest.fixture
def product(db: Session, marketplace: Marketplace) -> Product:
    record = Product(
        marketplace_id=marketplace.id,
        external_product_id="p-1",
        title="Produto de teste",
        product_url="https://example.test/p-1",
    )
    db.add(record)
    db.flush()
    return record


@pytest.fixture
def set_autonomy(monkeypatch):
    """set_autonomy(4) liga o nível de autonomia só durante o teste."""
    from app.core.config import get_settings

    def _set(level: int) -> None:
        monkeypatch.setattr(get_settings(), "ai_autonomy_level", level)

    return _set


@pytest.fixture
def ready(db: Session):
    """Três produtos em TEST, com imagem, criativo e legenda do dia."""
    discovery_service.run_discovery(db, MockAdapter(), limit=3)
    products = db.execute(select(Product).order_by(Product.id).limit(3)).scalars().all()
    for p in products:
        p.image_url = f"https://img.test/{p.id}.jpg"
        for state in (ProductState.QUALIFICATION, ProductState.CANDIDATE, ProductState.TEST):
            transition(db, product_id=p.id, to_state=state, reason_code="TEST", actor="system")
    db.flush()
    content_service.generate_daily_package(
        db, MockAdapter(), None, count=3, max_sub_id_length=48,
        llm_cap_usd=Decimal("1.00"), public_base=BASE,
    )
    return products
