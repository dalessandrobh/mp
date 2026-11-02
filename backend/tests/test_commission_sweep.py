"""Varredura de comissão alta: só entra comissão alta COM venda provada.

O catálogo que a varredura por vendas constrói tem comissão mediana de R$ 3 por venda —
não sustenta meta de receita. A varredura por preço decrescente alcança a cauda, mas
sozinha devolve item caríssimo com zero venda. Estes testes travam as duas pontas.
"""

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.marketplace.base import SORT_PRICE_DESC, SORT_SALES, ProductOffer
from app.adapters.marketplace.mock.adapter import MockAdapter
from app.models.catalog import Category, Product, ProductSnapshot
from app.services import discovery_service

CATEGORY = "100630"

# (id, preço, taxa, vendas) -> comissão por venda
CATALOG = [
    ("caro-sem-venda", Decimal("5000.00"), Decimal("0.03"), 0),       # R$ 150,00 e 0 vendas
    ("caro-com-venda", Decimal("400.00"), Decimal("0.09"), 500),      # R$  36,00 e 500
    ("medio-bom", Decimal("150.00"), Decimal("0.28"), 180),           # R$  42,00 e 180
    ("barato-popular", Decimal("22.00"), Decimal("0.08"), 90000),     # R$   1,76 e muita venda
    ("medio-sem-comissao", Decimal("200.00"), Decimal("0.03"), 800),  # R$   6,00
    ("sem-preco", None, Decimal("0.20"), 300),                        # não dá para julgar
]


class Sweeper(MockAdapter):
    """Catálogo controlado, e que registra a ordenação pedida."""

    code = "mock"

    def __init__(self) -> None:
        self.sorts: list[str | None] = []

    def search_products(self, *, keyword=None, limit=50, category=None, sort=None):
        self.sorts.append(sort)
        offers = [
            ProductOffer(
                external_product_id=ext,
                title=f"Produto {ext}",
                product_url=f"https://example.test/{ext}",
                category_path=(CATEGORY,),
                price=price,
                commission_rate=rate,
                sales_volume=sales,
                rating=Decimal("4.6"),
            )
            for ext, price, rate, sales in CATALOG
        ]
        return offers[:limit]


@pytest.fixture
def category(db: Session) -> None:
    db.add(
        Category(
            marketplace="mock",
            external_id=CATEGORY,
            level=1,
            name="Beleza",
            name_source="inferido",
        )
    )
    db.flush()


def _run(db: Session, adapter, **kwargs):
    defaults = {
        "per_category": 300,
        "min_commission_value": Decimal("15.00"),
        "min_sales": 100,
    }
    return discovery_service.run_commission_discovery(db, adapter, **{**defaults, **kwargs})


def test_keeps_only_high_commission_with_proven_sales(db: Session, category):
    adapter = Sweeper()

    result = _run(db, adapter)

    kept = {p.external_product_id for p in db.execute(select(Product)).scalars()}
    assert kept == {"caro-com-venda", "medio-bom"}
    assert result.fetched == len(CATALOG) and result.kept == 2 and result.new_products == 2


def test_each_rejection_is_counted_by_its_own_reason(db: Session, category):
    result = _run(db, Sweeper())

    assert result.skipped_low_sales == 1, "o caro sem venda não serve"
    assert result.skipped_low_commission == 2, "barato popular e médio sem comissão"
    assert result.skipped_unknown == 1, "sem preço não dá para julgar"
    assert (
        result.skipped_low_sales
        + result.skipped_low_commission
        + result.skipped_unknown
        + result.kept
        == result.fetched
    ), "todo item lido tem um destino explicado"


def test_the_sweep_asks_for_price_descending(db: Session, category):
    """A ordenação por vendas nunca mostra a cauda de comissão alta."""
    adapter = Sweeper()
    _run(db, adapter)
    assert adapter.sorts == [SORT_PRICE_DESC]


def test_sales_sweep_still_asks_for_its_own_ordering(db: Session, category):
    adapter = Sweeper()
    discovery_service.run_discovery(db, adapter, limit=5, category=CATEGORY, sort=SORT_SALES)
    assert adapter.sorts == [SORT_SALES]


def test_a_product_we_already_track_is_refreshed_even_below_the_floor(db: Session, category):
    """A série de snapshots não pode ter buraco: dela saem velocidade e aceleração."""
    discovery_service.run_discovery(db, Sweeper(), limit=len(CATALOG))
    before = db.execute(select(func.count()).select_from(Product)).scalar_one()

    result = _run(db, Sweeper())

    assert db.execute(select(func.count()).select_from(Product)).scalar_one() == before
    assert result.new_products == 0
    assert result.kept == len(CATALOG), "conhecido entra de novo, mesmo abaixo do piso"
    # Nada mudou na oferta, então nenhum snapshot novo foi gravado.
    assert result.snapshots_skipped == len(CATALOG)


def test_a_price_change_on_a_kept_product_writes_a_new_snapshot(db: Session, category):
    _run(db, Sweeper())
    before = db.execute(select(func.count()).select_from(ProductSnapshot)).scalar_one()

    class Cheaper(Sweeper):
        def search_products(self, *, keyword=None, limit=50, category=None, sort=None):
            offers = super().search_products(
                keyword=keyword, limit=limit, category=category, sort=sort
            )
            return [
                ProductOffer(**{**o.__dict__, "price": Decimal("300.00")})
                if o.external_product_id == "caro-com-venda"
                else o
                for o in offers
            ]

    _run(db, Cheaper())

    after = db.execute(select(func.count()).select_from(ProductSnapshot)).scalar_one()
    assert after == before + 1


def test_the_floors_are_configurable(db: Session, category):
    """Piso mais baixo abre a porta; é o parâmetro que calibra a oferta."""
    result = _run(db, Sweeper(), min_commission_value=Decimal("5.00"), min_sales=100)

    kept = {p.external_product_id for p in db.execute(select(Product)).scalars()}
    assert kept == {"caro-com-venda", "medio-bom", "medio-sem-comissao"}
    assert result.skipped_low_commission == 1  # só o barato popular


def test_one_failing_category_does_not_stop_the_others(db: Session, category):
    db.add(
        Category(
            marketplace="mock", external_id="100001", level=1, name="Saúde",
            name_source="inferido",
        )
    )
    db.flush()

    class Flaky(Sweeper):
        def search_products(self, *, keyword=None, limit=50, category=None, sort=None):
            if category == "100001":
                raise RuntimeError("boom")
            return super().search_products(
                keyword=keyword, limit=limit, category=category, sort=sort
            )

    result = _run(db, Flaky())

    assert result.failed == ("100001",) and result.categories == 1 and result.kept == 2


def test_it_sweeps_every_level1_category_when_none_is_given(db: Session, category):
    db.add(
        Category(
            marketplace="mock", external_id="100001", level=1, name="Saúde",
            name_source="inferido",
        )
    )
    # Nível 2 não é varrido: a varredura é por categoria raiz.
    db.add(
        Category(
            marketplace="mock", external_id="100535", level=2, name="Sub",
            name_source="inferido",
        )
    )
    db.flush()

    result = _run(db, Sweeper())

    assert result.categories == 2
