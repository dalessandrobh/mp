"""Lista de produtos para montar a vitrine do app da Shopee (exportada em CSV).

A API de afiliados não gerencia a vitrine; quem adiciona os itens é uma pessoa (ou um
navegador) colando a URL do produto. Aqui só se escolhe O QUE entra, com o mesmo critério
do pacote diário: sem marca no título, abaixo do teto de preço, categorias que funcionam
em pin orgânico primeiro (content_fit), depois maior receita esperada por clique.
"""

import csv
import io
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.adapters.marketplace.base import MarketplaceAdapter
from app.domain import brand_risk
from app.services import content_service
from app.services._funnel_queries import latest_snapshot

HEADER = ["posicao", "titulo", "preco", "comissao_pct", "comissao_rs", "url_produto"]


@dataclass(frozen=True)
class ShowcaseRow:
    product_id: int
    title: str
    price: Decimal
    commission_rate: Decimal | None
    commission_value: Decimal | None
    url: str


def rows(
    db: Session,
    adapter: MarketplaceAdapter,
    *,
    limit: int,
    max_price: Decimal | None,
    now: datetime | None = None,
) -> list[ShowcaseRow]:
    now = now or datetime.now(UTC)
    out: list[ShowcaseRow] = []
    # min_days_between=0: a vitrine não é pin, então o intervalo entre posts não importa.
    for product in content_service._eligible(db, adapter, now, min_days_between=0):
        if len(out) >= limit:
            break
        if brand_risk.brands_in(product.title):
            continue
        snapshot = latest_snapshot(db, product.id)
        if snapshot is None or snapshot.price is None:
            continue
        if max_price is not None and snapshot.price > max_price:
            continue
        out.append(
            ShowcaseRow(
                product_id=product.id,
                title=product.title,
                price=snapshot.price,
                commission_rate=snapshot.commission_rate,
                commission_value=snapshot.commission_value,
                url=product.product_url,
            )
        )
    return out


def _num(value: Decimal | None) -> str:
    return "" if value is None else f"{value:.2f}"


def to_csv(items: list[ShowcaseRow]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(HEADER)
    for position, item in enumerate(items, start=1):
        rate = None if item.commission_rate is None else item.commission_rate * 100
        writer.writerow(
            [
                position,
                item.title,
                _num(item.price),
                _num(rate),
                _num(item.commission_value),
                item.url,
            ]
        )
    return buffer.getvalue()


