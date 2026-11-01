"""Consolidação: `*_raw` -> `performance_daily`.

Regras que sustentam o ROI:

* **Ausência não é zero.** Receita só vale 0 quando sabemos que o relatório de
  conversões cobriu aquele dia (`coverage`). Dia não coberto = receita None e
  `revenue_data_available=False`, e o motor de decisão trata como NO_DATA.
* **Maturidade.** Dia liquidado (ValidatedReport cobrindo, e já passada a
  janela de liquidação) usa só comissão final -> SETTLED. Dia coberto pelo
  validado mas ainda dentro da janela mistura final + estimada -> PARTIAL. O
  resto usa a estimada -> PROVISIONAL. Só SETTLED autoriza corte.
* **Fraude e status.** Só pedido COMPLETED e sem fraude vira receita.
* **Granularidade.** Uma linha por (dia, produto, canal), com `campaign_id`
  NULL: o `sub_id` é emitido antes da campanha existir, então a receita só
  atribui com segurança ao produto, e a decisão é por produto.
* **Revisão.** Reprocessar um dia que mudou grava o antes e o depois.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import formulas
from app.domain.enums import RunStatus, SettlementStatus
from app.models.ads import Ad
from app.models.control import WorkflowRun
from app.models.metrics import (
    AdMetricsRaw,
    ConversionRaw,
    PerformanceDaily,
    PerformanceDailyRevision,
)
from app.models.tracking import AffiliateLink
from app.services.ingestion_service import SOURCE_CONVERSION, SOURCE_VALIDATED

CHANNEL = "meta"
SETTLEMENT_LAG_DAYS = 7
SYNC_WORKFLOW = "performance_sync"

_TRACKED_FIELDS = (
    "impressions", "clicks", "ad_spend", "conversions", "revenue", "profit", "ctr", "cpc",
    "cvr", "roi", "roas", "epc", "cost_data_available", "revenue_data_available", "settlement",
)


@dataclass(frozen=True)
class Coverage:
    conversions: frozenset[date]
    validated: frozenset[date]


@dataclass
class ConsolidationResult:
    rows_created: int = 0
    rows_updated: int = 0
    rows_unchanged: int = 0
    revisions: int = 0
    unattributed_conversions: int = 0
    warnings: list[str] = field(default_factory=list)


def _days(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def load_coverage(db: Session) -> Coverage:
    """Dias cobertos por um sync real e bem-sucedido. Dry-run não prova cobertura."""
    runs = db.execute(
        select(WorkflowRun).where(
            WorkflowRun.workflow_name == SYNC_WORKFLOW,
            WorkflowRun.dry_run.is_(False),
            WorkflowRun.status == RunStatus.SUCCESS,
        )
    ).scalars()

    conversions: set[date] = set()
    validated: set[date] = set()
    for run in runs:
        window = (run.summary or {}).get("window")
        if not window:
            continue
        span = list(_days(date.fromisoformat(window["since"]), date.fromisoformat(window["until"])))
        conversions.update(span)
        # O validado atrasa, mas a consulta também cobre o intervalo todo.
        validated.update(span)
    return Coverage(frozenset(conversions), frozenset(validated))


def _snapshot(row: PerformanceDaily) -> dict:
    return {name: _plain(getattr(row, name)) for name in _TRACKED_FIELDS}


def _plain(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, SettlementStatus):
        return value.value
    return value


def consolidate(
    db: Session, *, since: date, until: date, today: date | None = None
) -> ConsolidationResult:
    today = today or datetime.now(UTC).date()
    result = ConsolidationResult()
    coverage = load_coverage(db)

    # --- custo e tráfego: última leitura de cada (anúncio, dia) ---
    ad_product = {
        ad.external_id: ad.product_id
        for ad in db.execute(select(Ad).where(Ad.external_id.is_not(None))).scalars()
    }
    latest_raw: dict[tuple[str, date], AdMetricsRaw] = {}
    for raw in db.execute(
        select(AdMetricsRaw)
        .where(AdMetricsRaw.metric_date >= since, AdMetricsRaw.metric_date <= until)
        .order_by(AdMetricsRaw.ingested_at.desc(), AdMetricsRaw.id.desc())
    ).scalars():
        latest_raw.setdefault((raw.external_ad_id, raw.metric_date), raw)

    cost: dict[tuple[date, int], dict] = {}
    for (ad_id, day), raw in latest_raw.items():
        product_id = ad_product.get(ad_id)
        if product_id is None:
            continue
        bucket = cost.setdefault((day, product_id), {"impressions": 0, "clicks": 0, "spend": 0})
        payload = raw.payload
        bucket["impressions"] += payload.get("impressions") or 0
        bucket["clicks"] += payload.get("clicks") or 0
        bucket["spend"] += Decimal(payload["spend"]) if payload.get("spend") else 0

    # --- receita: conversões atribuídas por sub_id ---
    link_product = dict(db.execute(select(AffiliateLink.sub_id, AffiliateLink.product_id)).all())
    provisional: dict[tuple[date, int], dict[str, Decimal]] = {}
    validated: dict[tuple[date, int], dict[str, Decimal]] = {}
    for conv in db.execute(
        select(ConversionRaw).where(
            ConversionRaw.conversion_date >= since, ConversionRaw.conversion_date <= until
        )
    ).scalars():
        product_id = link_product.get(conv.sub_id) if conv.sub_id else None
        if product_id is None:
            if conv.source == SOURCE_CONVERSION:
                result.unattributed_conversions += 1
            continue
        if conv.status != "COMPLETED" or conv.fraud_status == "FRAUD":
            continue
        bucket = {SOURCE_CONVERSION: provisional, SOURCE_VALIDATED: validated}[conv.source]
        bucket.setdefault((conv.conversion_date, product_id), {})[
            conv.external_order_id or f"row-{conv.id}"
        ] = conv.commission_value or Decimal(0)

    keys = set(cost) | set(provisional) | set(validated)
    for day, product_id in sorted(keys):
        _write_day(
            db, result, day, product_id, today,
            cost=cost.get((day, product_id)),
            provisional=provisional.get((day, product_id), {}),
            validated=validated.get((day, product_id), {}),
            coverage=coverage,
        )

    db.flush()
    return result


def _write_day(db, result, day, product_id, today, *, cost, provisional, validated, coverage):
    conv_covered = day in coverage.conversions
    val_covered = day in coverage.validated
    settled_day = val_covered and day <= today - timedelta(days=SETTLEMENT_LAG_DAYS)

    if settled_day:
        orders, settlement = validated, SettlementStatus.SETTLED
    elif val_covered and validated:
        merged = {**provisional, **validated}  # a liquidada vence a estimada do mesmo pedido
        orders, settlement = merged, SettlementStatus.PARTIAL
    else:
        orders, settlement = provisional, SettlementStatus.PROVISIONAL

    revenue_available = conv_covered or val_covered
    revenue = sum(orders.values(), Decimal(0)) if revenue_available else None
    conversions = len(orders) if revenue_available else None

    impressions = cost["impressions"] if cost else None
    clicks = cost["clicks"] if cost else None
    spend = Decimal(cost["spend"]).quantize(Decimal("0.01")) if cost else None

    values = {
        "impressions": impressions,
        "clicks": clicks,
        "ad_spend": spend,
        "conversions": conversions,
        "revenue": revenue.quantize(Decimal("0.01")) if revenue is not None else None,
        "profit": formulas.profit(revenue, spend),
        "ctr": formulas.ctr(clicks, impressions),
        "cpc": formulas.cpc(spend, clicks),
        "cvr": formulas.cvr(conversions, clicks),
        "roi": formulas.roi(revenue, spend),
        "roas": formulas.roas(revenue, spend),
        "epc": formulas.epc(revenue, clicks),
        "cost_data_available": cost is not None,
        "revenue_data_available": revenue_available,
        "settlement": settlement,
    }

    existing = db.execute(
        select(PerformanceDaily).where(
            PerformanceDaily.metric_date == day,
            PerformanceDaily.product_id == product_id,
            PerformanceDaily.channel == CHANNEL,
            PerformanceDaily.campaign_id.is_(None),
        )
    ).scalar_one_or_none()

    if existing is None:
        db.add(
            PerformanceDaily(
                metric_date=day, product_id=product_id, channel=CHANNEL, campaign_id=None,
                **values,
            )
        )
        result.rows_created += 1
        return

    before = _snapshot(existing)
    after = {k: _plain(v) for k, v in values.items()}
    if before == after:
        result.rows_unchanged += 1
        return

    db.add(
        PerformanceDailyRevision(
            performance_daily_id=existing.id,
            previous_values=before,
            new_values=after,
            reason="reprocess",
        )
    )
    for key, value in values.items():
        setattr(existing, key, value)
    existing.computed_at = datetime.now(UTC)
    result.rows_updated += 1
    result.revisions += 1
