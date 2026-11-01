"""Ingestão bruta: Meta Insights e relatórios de conversão do marketplace.

Aqui só se guarda o que veio, do jeito que veio. Nenhuma métrica é calculada —
isso é da consolidação. O bruto de métricas é append-only; as conversões são
atualizadas no lugar porque o MESMO pedido muda de status (PENDING -> COMPLETED).
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime

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


def _upsert_conversion(
    db: Session, *, marketplace_id: int, source: str, settlement: SettlementStatus,
    record: ConversionRecord,
) -> bool:
    """True se criou, False se atualizou."""
    existing = db.execute(
        select(ConversionRaw).where(
            ConversionRaw.marketplace_id == marketplace_id,
            ConversionRaw.source == source,
            ConversionRaw.external_order_id == record.external_order_id,
            ConversionRaw.sub_id.is_not_distinct_from(record.sub_id),
        )
    ).scalar_one_or_none()

    values = {
        "conversion_date": record.conversion_date,
        "commission_value": record.commission_value,
        "order_value": record.order_value,
        "status": record.status,
        "fraud_status": record.fraud_status,
        "settlement": settlement,
        "payload": record.payload or {},
    }
    if existing is None:
        db.add(
            ConversionRaw(
                marketplace_id=marketplace_id,
                source=source,
                external_order_id=record.external_order_id,
                sub_id=record.sub_id,
                **values,
            )
        )
        return True
    for key, value in values.items():
        setattr(existing, key, value)
    return False


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
            if record.sub_id is None and source == SOURCE_CONVERSION:
                result.unattributable += 1
            if source == SOURCE_CONVERSION:
                result.conversions_new += created
                result.conversions_updated += not created
            else:
                result.validated_new += created
                result.validated_updated += not created
    db.flush()
    return result


