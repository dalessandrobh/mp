"""Fixtures dos testes.

Cada teste roda dentro de uma transação que é revertida no fim, então os testes
compartilham o mesmo banco migrado sem sujar um ao outro. Os testes de
append-only precisam do Postgres real — os triggers vivem lá, não no Python.
"""

import pytest
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.catalog import Marketplace, Product


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
