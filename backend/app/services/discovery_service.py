"""Descoberta: traz ofertas do marketplace e as registra no funil.

Produto novo entra em DISCOVERY pela state machine. Produto conhecido ganha
só um novo snapshot — preço e comissão mudam, e a decisão de ontem precisa do
valor de ontem.

Há duas varreduras, e elas procuram coisas diferentes:

* `run_category_discovery` ordena por VENDAS e acha demanda provada. Medido na API real
  (2026-11-02): o topo de cada categoria é barato — comissão mediana de R$ 3 por venda.
* `run_commission_discovery` ordena por PREÇO DECRESCENTE e alcança a cauda de comissão
  alta, que a ordenação por vendas nunca mostra. Sozinha ela é uma armadilha: devolve
  geladeira de R$ 85 mil com ZERO venda. Por isso exige comissão mínima **e** venda
  mínima, as duas. Medido: 5 categorias, 300 itens cada, 338 produtos com ≥ R$ 15 de
  comissão e ≥ 100 vendas — contra 23 em todo o catálogo que a varredura por vendas
  construiu.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.marketplace.base import (
    SORT_PRICE_DESC,
    MarketplaceAdapter,
    ProductOffer,
)
from app.domain import formulas
from app.domain.enums import ProductState
from app.domain.state_machine import transition
from app.models.catalog import Category, Marketplace, Product, ProductSnapshot

ACTOR = "system"


@dataclass(frozen=True)
class DiscoveryResult:
    fetched: int
    new_products: int
    updated_products: int
    # Snapshots que não foram gravados porque nada mudou desde o último.
    snapshots_skipped: int = 0


@dataclass(frozen=True)
class CommissionDiscoveryResult:
    """`fetched` é o que a API devolveu; `kept` o que entrou. A diferença é auditável."""

    categories: int
    fetched: int
    kept: int
    new_products: int
    updated_products: int
    snapshots_skipped: int
    skipped_low_commission: int = 0
    skipped_low_sales: int = 0
    # Preço, comissão ou vendas não informados: não dá para julgar, e "não sei" nunca
    # vira "reprovado por ser ruim".
    skipped_unknown: int = 0
    failed: tuple[str, ...] = ()


@dataclass(frozen=True)
class CategoryDiscoveryResult:
    categories: int
    fetched: int
    new_products: int
    updated_products: int
    snapshots_skipped: int
    failed: tuple[str, ...] = ()


def ensure_marketplace(db: Session, adapter: MarketplaceAdapter) -> Marketplace:
    record = db.execute(
        select(Marketplace).where(Marketplace.code == adapter.code)
    ).scalar_one_or_none()
    unsupported = sorted(adapter.unsupported_fields)
    if record is None:
        record = Marketplace(
            code=adapter.code,
            display_name=adapter.display_name,
            adapter_class=f"{type(adapter).__module__}.{type(adapter).__name__}",
            config={"unsupported_fields": unsupported},
        )
        db.add(record)
        db.flush()
    elif (record.config or {}).get("unsupported_fields") != unsupported:
        # Reatribui o dict inteiro: o JSONB não detecta mutação in-place.
        record.config = {**(record.config or {}), "unsupported_fields": unsupported}
        db.flush()
    return record


def _snapshot_from(product_id: int, offer: ProductOffer) -> ProductSnapshot:
    return ProductSnapshot(
        product_id=product_id,
        price=offer.price,
        original_price=offer.original_price,
        commission_rate=offer.commission_rate,
        commission_value=formulas.commission_value(offer.price, offer.commission_rate),
        rating=offer.rating,
        rating_count=offer.rating_count,
        sales_volume=offer.sales_volume,
        stock=offer.stock,
        data_available=offer.data_available(),
        raw_payload=offer.raw_payload,
    )


def _unchanged(db: Session, product_id: int, offer: ProductOffer) -> bool:
    """O último snapshot já diz exatamente o que a API disse agora?

    Snapshot é append-only: gravar o mesmo valor todo dia só incha a tabela. Preço, comissão,
    vendas e nota são o que as decisões leem; mudou qualquer um, grava.
    """
    last = db.execute(
        select(ProductSnapshot)
        .where(ProductSnapshot.product_id == product_id)
        .order_by(ProductSnapshot.captured_at.desc(), ProductSnapshot.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    return (
        last is not None
        and last.price == offer.price
        and last.commission_rate == offer.commission_rate
        and last.sales_volume == offer.sales_volume
        and last.rating == offer.rating
    )


def _find_product(db: Session, marketplace_id: int, external_id: str) -> Product | None:
    return db.execute(
        select(Product).where(
            Product.marketplace_id == marketplace_id,
            Product.external_product_id == external_id,
        )
    ).scalar_one_or_none()


def _persist(
    db: Session, marketplace: Marketplace, offers: list[ProductOffer], now: datetime
) -> tuple[int, int, int]:
    """(novos, atualizados, snapshots dispensados). Usado pelas duas varreduras."""
    new_count = updated_count = skipped = 0

    for offer in offers:
        product = _find_product(db, marketplace.id, offer.external_product_id)

        if product is None:
            product = Product(
                marketplace_id=marketplace.id,
                external_product_id=offer.external_product_id,
                external_shop_id=offer.external_shop_id,
                title=offer.title,
                category_path=list(offer.category_path) if offer.category_path else None,
                product_url=offer.product_url,
                image_url=offer.image_url,
                raw_payload=offer.raw_payload,
            )
            db.add(product)
            db.flush()
            transition(
                db,
                product_id=product.id,
                to_state=ProductState.DISCOVERY,
                reason_code="DISCOVERED",
                actor=ACTOR,
            )
            new_count += 1
        else:
            product.title = offer.title
            product.product_url = offer.product_url
            product.image_url = offer.image_url
            product.last_seen_at = now
            updated_count += 1
            if _unchanged(db, product.id, offer):
                skipped += 1
                continue

        db.add(_snapshot_from(product.id, offer))

    db.flush()
    return new_count, updated_count, skipped


def register_offer(db: Session, adapter: MarketplaceAdapter, offer: ProductOffer) -> Product:
    """Cadastra um produto trazido à mão (fora das varreduras). Entra em DISCOVERY, como os
    demais, e segue o mesmo funil: ninguém ganha atalho para o portfólio por ter entrado assim."""
    marketplace = ensure_marketplace(db, adapter)
    _persist(db, marketplace, [offer], datetime.now(UTC))
    return _find_product(db, marketplace.id, offer.external_product_id)


def run_discovery(
    db: Session,
    adapter: MarketplaceAdapter,
    *,
    keyword: str | None = None,
    limit: int = 50,
    category: str | None = None,
    sort: str | None = None,
) -> DiscoveryResult:
    marketplace = ensure_marketplace(db, adapter)
    offers = adapter.search_products(keyword=keyword, limit=limit, category=category, sort=sort)
    new_count, updated_count, skipped = _persist(db, marketplace, offers, datetime.now(UTC))
    return DiscoveryResult(
        fetched=len(offers),
        new_products=new_count,
        updated_products=updated_count,
        snapshots_skipped=skipped,
    )


def run_category_discovery(
    db: Session,
    adapter: MarketplaceAdapter,
    *,
    per_category: int,
    category_ids: list[str] | None = None,
) -> CategoryDiscoveryResult:
    """Descobre os mais vendidos de cada categoria nível 1 conhecida.

    Uma categoria que falha não derruba as outras: vai para `failed` e o resto segue.
    """
    ensure_marketplace(db, adapter)
    wanted = category_ids or _level1_categories(db, adapter)
    totals = {"fetched": 0, "new_products": 0, "updated_products": 0, "snapshots_skipped": 0}
    failed: list[str] = []
    done = 0
    for category in wanted:
        try:
            with db.begin_nested():
                res = run_discovery(db, adapter, limit=per_category, category=category)
        except Exception:  # noqa: BLE001 - uma categoria ruim não pode parar as demais
            failed.append(category)
            continue
        done += 1
        totals["fetched"] += res.fetched
        totals["new_products"] += res.new_products
        totals["updated_products"] += res.updated_products
        totals["snapshots_skipped"] += res.snapshots_skipped
    return CategoryDiscoveryResult(categories=done, failed=tuple(failed), **totals)


def _level1_categories(db: Session, adapter: MarketplaceAdapter) -> list[str]:
    return list(
        db.execute(
            select(Category.external_id)
            .where(Category.marketplace == adapter.code, Category.level == 1)
            .order_by(Category.external_id)
        ).scalars()
    )


def _worth_keeping(
    offer: ProductOffer, *, min_commission_value: Decimal, min_sales: int
) -> str:
    """'keep' | 'low_commission' | 'low_sales' | 'unknown'.

    As duas condições juntas, não uma ou outra: comissão alta sem venda é geladeira de
    R$ 85 mil que ninguém compra por um post, e venda alta sem comissão é o catálogo de
    R$ 3 por venda que já temos.
    """
    value = formulas.commission_value(offer.price, offer.commission_rate)
    if value is None or offer.sales_volume is None:
        return "unknown"
    if value < min_commission_value:
        return "low_commission"
    if offer.sales_volume < min_sales:
        return "low_sales"
    return "keep"


def run_commission_discovery(
    db: Session,
    adapter: MarketplaceAdapter,
    *,
    per_category: int,
    min_commission_value: Decimal,
    min_sales: int,
    category_ids: list[str] | None = None,
) -> CommissionDiscoveryResult:
    """Varre cada categoria por PREÇO DECRESCENTE e guarda só comissão alta com venda.

    Produto que já conhecemos é guardado de qualquer jeito, mesmo abaixo do piso: a série
    de snapshots dele não pode ter buraco (é dela que sai velocidade e aceleração, e
    "parou de aparecer" é informação negativa, não dado faltando).

    Uma categoria que falha não derruba as outras.
    """
    marketplace = ensure_marketplace(db, adapter)
    wanted = category_ids or _level1_categories(db, adapter)
    now = datetime.now(UTC)
    totals = dict.fromkeys(
        (
            "fetched", "kept", "new_products", "updated_products", "snapshots_skipped",
            "skipped_low_commission", "skipped_low_sales", "skipped_unknown",
        ),
        0,
    )
    failed: list[str] = []
    done = 0

    for category in wanted:
        try:
            with db.begin_nested():
                offers = adapter.search_products(
                    category=category, limit=per_category, sort=SORT_PRICE_DESC
                )
                keep: list[ProductOffer] = []
                verdicts = {"low_commission": 0, "low_sales": 0, "unknown": 0}
                for offer in offers:
                    verdict = _worth_keeping(
                        offer,
                        min_commission_value=min_commission_value,
                        min_sales=min_sales,
                    )
                    known = (
                        _find_product(db, marketplace.id, offer.external_product_id) is not None
                    )
                    if verdict == "keep" or known:
                        keep.append(offer)
                    else:
                        verdicts[verdict] += 1
                new_count, updated_count, snaps_skipped = _persist(db, marketplace, keep, now)
        except Exception:  # noqa: BLE001 - uma categoria ruim não pode parar as demais
            failed.append(category)
            continue

        done += 1
        totals["fetched"] += len(offers)
        totals["kept"] += len(keep)
        totals["new_products"] += new_count
        totals["updated_products"] += updated_count
        totals["snapshots_skipped"] += snaps_skipped
        totals["skipped_low_commission"] += verdicts["low_commission"]
        totals["skipped_low_sales"] += verdicts["low_sales"]
        totals["skipped_unknown"] += verdicts["unknown"]

    return CommissionDiscoveryResult(categories=done, failed=tuple(failed), **totals)
