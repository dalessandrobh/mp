"""Ingestão bruta: Meta Insights e relatórios de conversão do marketplace.

Aqui só se guarda o que veio, do jeito que veio. Nenhuma métrica é calculada —
isso é da consolidação. O bruto de métricas é append-only; as conversões são
atualizadas no lugar porque o MESMO pedido muda de status (PENDING -> COMPLETED).
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.ads.base import AdsAdapter
from app.adapters.marketplace.base import ConversionRecord, MarketplaceAdapter
from app.domain.enums import SettlementStatus
from app.models.ads import Ad
from app.models.catalog import Marketplace
from app.models.metrics import AdMetricsRaw, ConversionRaw
from app.models.tracking import AffiliateLink

SOURCE_INSIGHTS = "meta_insights"
SOURCE_CONVERSION = "conversion_report"
SOURCE_VALIDATED = "validated_report"


@dataclass
class IngestionResult:
    conversions_new: int = 0
    conversions_updated: int = 0
    validated_new: int = 0
    validated_updated: int = 0
    unattributable: int = 0


def sync_ad_metrics(db: Session, adapter: AdsAdapter, *, since: date, until: date) -> int:
    external_ids = list(
        db.execute(select(Ad.external_id).where(Ad.external_id.is_not(None))).scalars()
    )
    if not external_ids:
        return 0

    insights = adapter.fetch_insights(external_ad_ids=external_ids, since=since, until=until)
    for item in insights:
        db.add(
            AdMetricsRaw(
                source=SOURCE_INSIGHTS,
                # Relógio da aplicação, não now() do Postgres: este é fixo na transação e
                # duas leituras no mesmo commit colidiriam na UNIQUE com ingested_at.
                ingested_at=datetime.now(UTC),
                metric_date=item.metric_date,
                external_ad_id=item.external_ad_id,
                # None permanece None: o Meta não informar não é gasto zero.
                payload={
                    "impressions": item.impressions,
                    "clicks": item.clicks,
                    "spend": str(item.spend) if item.spend is not None else None,
                    "raw": item.payload,
                },
            )
        )
    db.flush()
    return len(insights)


def latest_conversions(db: Session, *where) -> list[ConversionRaw]:
    """Só a versão mais recente de cada pedido (a tabela guarda todas as revisões)."""
    rows = db.execute(
        select(ConversionRaw).where(*where).order_by(ConversionRaw.revision, ConversionRaw.id)
    ).scalars()
    latest: dict[tuple, ConversionRaw] = {}
    for row in rows:
        key = (row.marketplace_id, row.source, row.external_order_id, row.sub_id)
        latest[key] = row
    return list(latest.values())


def _cents(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(Decimal("0.01"))


def _same(existing: ConversionRaw, values: dict) -> bool:
    """Compara como o banco guarda (2 casas); `payload` não conta como mudança."""
    return (
        existing.conversion_date == values["conversion_date"]
        and _cents(existing.commission_value) == _cents(values["commission_value"])
        and _cents(existing.order_value) == _cents(values["order_value"])
        and existing.status == values["status"]
        and existing.fraud_status == values["fraud_status"]
        and existing.settlement == values["settlement"]
    )


def _upsert_conversion(
    db: Session, *, marketplace_id: int, source: str, settlement: SettlementStatus,
    record: ConversionRecord,
) -> str:
    """'new' (pedido novo), 'revised' (mudou: nova revisão) ou 'same' (nada a gravar).

    Nunca faz UPDATE: conversions_raw é append-only.
    """
    existing = db.execute(
        select(ConversionRaw)
        .where(
            ConversionRaw.marketplace_id == marketplace_id,
            ConversionRaw.source == source,
            ConversionRaw.external_order_id == record.external_order_id,
            ConversionRaw.sub_id.is_not_distinct_from(record.sub_id),
        )
        .order_by(ConversionRaw.revision.desc())
        .limit(1)
    ).scalar_one_or_none()

    values = {
        "conversion_date": record.conversion_date,
        "commission_value": record.commission_value,
        "order_value": record.order_value,
        "status": record.status,
        "fraud_status": record.fraud_status,
        "settlement": settlement,
    }
    if existing is not None and _same(existing, values):
        return "same"
    db.add(
        ConversionRaw(
            marketplace_id=marketplace_id,
            source=source,
            external_order_id=record.external_order_id,
            sub_id=record.sub_id,
            revision=1 if existing is None else existing.revision + 1,
            payload=record.payload or {},
            **values,
        )
    )
    db.flush()  # a próxima consulta do mesmo pedido já enxerga esta revisão
    return "new" if existing is None else "revised"


def sync_conversions(
    db: Session,
    adapter: MarketplaceAdapter,
    *,
    marketplace: Marketplace,
    since: date,
    until: date,
) -> IngestionResult:
    result = IngestionResult()
    hints = list(db.execute(select(AffiliateLink.sub_id)).scalars())

    batches = (
        (SOURCE_CONVERSION, SettlementStatus.PROVISIONAL,
         adapter.fetch_conversions(since=since, until=until, hint_sub_ids=hints)),
        (SOURCE_VALIDATED, SettlementStatus.SETTLED,
         adapter.fetch_validated_conversions(since=since, until=until, hint_sub_ids=hints)),
    )
    for source, settlement, records in batches:
        for record in records:
            created = _upsert_conversion(
                db, marketplace_id=marketplace.id, source=source, settlement=settlement,
                record=record,
            )
            if record.sub_id is None and source == SOURCE_CONVERSION and created != "same":
                result.unattributable += 1
            if source == SOURCE_CONVERSION:
                result.conversions_new += created == "new"
                result.conversions_updated += created == "revised"
            else:
                result.validated_new += created == "new"
                result.validated_updated += created == "revised"
    db.flush()
    return result


