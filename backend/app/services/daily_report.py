"""Resumo do dia: o que aconteceu, o que mudou e o que espera por você.

Só leitura. É o que o n8n manda por WhatsApp às 21h e o que `GET /report/daily` devolve.
Três regras de honestidade:

* Número estimado é dito estimado. Comissão de pedido PENDING não é a comissão final.
* Ausência não é zero: "sem pedidos" e "sem dado de vendas" são frases diferentes.
* O dia é o dia no Brasil (America/Sao_Paulo), o mesmo do orçamento e do dashboard.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.domain.enums import CampaignReviewStatus, RunStatus
from app.models.ads import Campaign
from app.models.ai import AiDecision, AiRecommendation
from app.models.catalog import Product
from app.models.control import Alert, WorkflowRun
from app.models.funnel import ProductCurrentState, ProductStateTransition
from app.models.metrics import ConversionRaw
from app.models.tracking import AffiliateLink
from app.services import portfolio_service
from app.services.budget_guard import BudgetGuard
from app.services.consolidation_service import SYNC_WORKFLOW

TZ = ZoneInfo("America/Sao_Paulo")
WEEKDAYS = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")
STATE_LABEL = {
    "DISCOVERY": "descoberto", "QUALIFICATION": "qualificado", "CANDIDATE": "candidato",
    "TEST": "em teste", "ACTIVE": "ativo", "WINNER": "vencedor", "REJECTED": "rejeitado",
    "PAUSED": "pausado", "UNDER_REVIEW": "em revisão", "REPLACED": "substituído",
    "EXPIRED": "expirado",
}
STATE_ORDER = list(STATE_LABEL)
REASON_LABEL = {
    "OUT_OF_STOCK": "sem estoque", "PRICE_TOO_LOW": "preço baixo",
    "COMMISSION_TOO_LOW": "comissão baixa", "LOW_RATING": "nota baixa",
}
ORDER_STATUS = {
    "COMPLETED": ("concluído", "concluídos"), "PENDING": ("pendente", "pendentes"),
    "CANCELLED": ("cancelado", "cancelados"), "UNPAID": ("não pago", "não pagos"),
}
MAX_LIST = 8
STALE_AFTER = timedelta(hours=12)


def day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, TZ)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def brl(value: Decimal | float | None) -> str:
    if value is None:
        return "—"
    text = f"{float(value):,.2f}"
    return "R$ " + text.replace(",", "#").replace(".", ",").replace("#", ".")


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


@dataclass
class DailyReport:
    day: date
    data: dict = field(default_factory=dict)
    message: str = ""


def build(db: Session, settings: Settings, params: portfolio_service.PortfolioParams,
          *, day: date | None = None, now: datetime | None = None) -> DailyReport:
    now = now or datetime.now(UTC)
    day = day or now.astimezone(TZ).date()
    start, end = day_bounds(day)
    data: dict = {"date": day.isoformat()}

    # ---- funil: o que mudou de estado hoje
    rows = db.execute(
        select(ProductStateTransition, Product.title)
        .join(Product, Product.id == ProductStateTransition.product_id)
        .where(ProductStateTransition.created_at >= start, ProductStateTransition.created_at < end)
        .order_by(ProductStateTransition.id)
    ).all()
    entered: dict[str, int] = {}
    rejected_reasons: dict[str, int] = {}
    changes: list[dict] = []
    for transition, title in rows:
        state = transition.to_state.value
        entered[state] = entered.get(state, 0) + 1
        if state == "REJECTED":
            rejected_reasons[transition.reason_code] = rejected_reasons.get(
                transition.reason_code, 0) + 1
        # Descobrir e qualificar são em lote: viram contagem. O resto vira linha própria.
        if state not in ("DISCOVERY", "QUALIFICATION", "REJECTED", "CANDIDATE"):
            changes.append({
                "product": title, "to": state, "actor": transition.actor,
                "reason": transition.reason_code,
            })
    data["funnel_today"] = {"entered": entered, "rejected_reasons": rejected_reasons}
    data["changes"] = changes

    totals = dict(
        db.execute(
            select(ProductCurrentState.state, func.count()).group_by(ProductCurrentState.state)
        ).all()
    )
    data["funnel_total"] = {s.value: n for s, n in totals.items()}

    # ---- decisões e o que espera por você
    decisions = db.execute(
        select(AiDecision).where(AiDecision.created_at >= start, AiDecision.created_at < end)
    ).scalars().all()
    pending = db.execute(
        select(AiRecommendation).where(AiRecommendation.status == "PENDING")
        .order_by(AiRecommendation.id)
    ).scalars().all()
    unreviewed = db.execute(
        select(func.count()).select_from(Campaign)
        .where(Campaign.review_status == CampaignReviewStatus.UNREVIEWED)
    ).scalar_one()
    open_alerts = db.execute(
        select(Alert).where(Alert.acknowledged_at.is_(None)).order_by(Alert.id.desc()).limit(20)
    ).scalars().all()
    data["decisions_today"] = {
        "executed": sum(1 for d in decisions if not d.dry_run),
        "simulated": sum(1 for d in decisions if d.dry_run),
        "by_human": sum(1 for d in decisions if not d.dry_run and d.payload.get("human_approved")),
    }
    data["needs_you"] = {
        "pending_recommendations": len(pending),
        "unreviewed_campaigns": unreviewed,
        "open_alerts": [{"severity": a.severity, "code": a.code} for a in open_alerts],
    }

    # ---- portfólio e links
    entries = portfolio_service.active_entries(db)
    links_today = db.execute(
        select(func.count()).select_from(AffiliateLink)
        .where(AffiliateLink.generated_at >= start, AffiliateLink.generated_at < end)
    ).scalar_one()
    budget = BudgetGuard(db, params).status(day)
    data["portfolio"] = {
        "active": len(entries),
        "allocated_per_day": str(sum((e.allocated_daily_budget for e in entries), Decimal(0))),
        "links_created_today": links_today,
        "budget_used": budget["used"], "budget_cap": budget["cap"],
    }

    # ---- vendas (Shopee), pelo dia da compra
    conversions = db.execute(
        select(ConversionRaw).where(
            ConversionRaw.conversion_date == day, ConversionRaw.source == "conversion_report"
        )
    ).scalars().all()
    link_product = dict(db.execute(select(AffiliateLink.sub_id, AffiliateLink.product_id)).all())
    by_status: dict[str, int] = {}
    commission: dict[str, Decimal] = {"COMPLETED": Decimal(0), "PENDING": Decimal(0)}
    per_product: dict[int, Decimal] = {}
    unattributed = 0
    for c in conversions:
        if c.fraud_status == "FRAUD":
            continue
        by_status[c.status or "UNKNOWN"] = by_status.get(c.status or "UNKNOWN", 0) + 1
        if c.status in commission and c.commission_value is not None:
            commission[c.status] += c.commission_value
        product_id = link_product.get(c.sub_id) if c.sub_id else None
        if product_id is None:
            unattributed += 1
        elif c.status in ("COMPLETED", "PENDING") and c.commission_value is not None:
            per_product[product_id] = per_product.get(product_id, Decimal(0)) + c.commission_value
    top: list[dict] = []
    for product_id, value in sorted(per_product.items(), key=lambda kv: -kv[1])[:3]:
        product = db.get(Product, product_id)
        name = product.title if product else str(product_id)
        top.append({"product": name, "commission": str(value)})
    data["sales"] = {
        "orders": sum(by_status.values()), "by_status": by_status,
        "commission_completed": str(commission["COMPLETED"]),
        "commission_pending": str(commission["PENDING"]),
        "unattributed": unattributed, "top_products": top,
    }

    # ---- saúde da operação
    last_sync = db.execute(
        select(func.max(WorkflowRun.finished_at)).where(
            WorkflowRun.workflow_name == SYNC_WORKFLOW,
            WorkflowRun.dry_run.is_(False), WorkflowRun.status == RunStatus.SUCCESS,
        )
    ).scalar_one()
    failed = db.execute(
        select(WorkflowRun.workflow_name).where(
            WorkflowRun.started_at >= start, WorkflowRun.started_at < end,
            WorkflowRun.status.in_([RunStatus.FAILED, RunStatus.ABORTED]),
        )
    ).scalars().all()
    data["health"] = {
        "last_performance_sync": last_sync.isoformat() if last_sync else None,
        "stale": bool(entries) and (last_sync is None or now - last_sync > STALE_AFTER),
        "failed_runs_today": failed,
    }
    data["mode"] = {
        "marketplace": "mock" if settings.mock_marketplace else "Shopee real",
        "paid_ads": "desligados" if settings.mock_ads else "ligados",
        "autonomy_level": settings.ai_autonomy_level,
        "writing": not settings.dry_run,
    }

    return DailyReport(day=day, data=data, message=_message(data, day, now, pending, open_alerts))


def _message(data: dict, day: date, now: datetime, pending: list, alerts: list) -> str:
    funnel, mode = data["funnel_today"], data["mode"]
    entered = funnel["entered"]
    lines = [f"📊 *MP — resumo de {WEEKDAYS[day.weekday()]}, {day:%d/%m}*"]
    lines.append(
        f"{mode['marketplace']} · anúncios {mode['paid_ads']} · autonomia {mode['autonomy_level']}"
        + ("" if mode["writing"] else " · ⚠️ SOMENTE LEITURA (DRY_RUN)")
    )

    lines += ["", "*Funil de hoje*"]
    if not entered:
        lines.append("• nada novo no funil")
    else:
        found = entered.get("DISCOVERY", 0)
        parts = []
        if found:
            parts.append(_plural(found, "produto novo", "produtos novos"))
        if entered.get("QUALIFICATION"):
            parts.append(_plural(entered["QUALIFICATION"], "qualificado", "qualificados"))
        if entered.get("REJECTED"):
            reasons = ", ".join(
                f"{n} {REASON_LABEL.get(code, code.lower())}"
                for code, n in sorted(funnel["rejected_reasons"].items(), key=lambda kv: -kv[1])
            )
            parts.append(f"{_plural(entered['REJECTED'], 'rejeitado', 'rejeitados')} ({reasons})")
        if parts:
            lines.append("• " + " · ".join(parts))
        if entered.get("CANDIDATE"):
            n = entered["CANDIDATE"]
            lines.append(f"• {n} virou candidato" if n == 1 else f"• {n} viraram candidatos")
    total = data["funnel_total"]
    lines.append(
        "• no funil: " + " · ".join(
            f"{total[s]} {STATE_LABEL[s]}" for s in STATE_ORDER if total.get(s)
        )
        if total else "• funil vazio"
    )

    lines += ["", "*Mudanças de hoje*"]
    if not data["changes"]:
        lines.append("• nenhuma mudança de portfólio")
    for change in data["changes"][:MAX_LIST]:
        who = "você" if change["actor"].startswith("human:") else "motor"
        state = STATE_LABEL.get(change["to"], change["to"])
        lines.append(f"• {change['product'][:42]} → {state} ({who})")
    if len(data["changes"]) > MAX_LIST:
        lines.append(f"• … e mais {len(data['changes']) - MAX_LIST}")
    portfolio = data["portfolio"]
    if portfolio["links_created_today"]:
        n_links = portfolio["links_created_today"]
        lines.append(f"• {_plural(n_links, 'link gerado', 'links gerados')}")

    sales = data["sales"]
    lines += ["", "*Vendas (pela data da compra)*"]
    if sales["orders"] == 0:
        lines.append("• nenhum pedido hoje")
    else:
        status = " · ".join(
            f"{n} {ORDER_STATUS.get(s, (s.lower(), s.lower()))[0 if n == 1 else 1]}"
            for s, n in sales["by_status"].items()
        )
        lines.append(f"• {_plural(sales['orders'], 'pedido', 'pedidos')} ({status})")
        lines.append(
            f"• comissão: {brl(Decimal(sales['commission_completed']))} concluída"
            f" + {brl(Decimal(sales['commission_pending']))} pendente _(estimativa, não liquidado)_"
        )
        for item in sales["top_products"]:
            lines.append(f"  – {item['product'][:40]}: {brl(Decimal(item['commission']))}")
        if sales["unattributed"]:
            lines.append(f"• {sales['unattributed']} sem identificação de produto")

    lines += ["", "*Aguardando você*"]
    needs = data["needs_you"]
    waiting = []
    if needs["pending_recommendations"]:
        titles = [r.rationale.get("what", "") for r in pending[:3]]
        waiting.append(
            f"{_plural(needs['pending_recommendations'], 'recomendação', 'recomendações')} "
            f"em Inteligência" + (f": {titles[0]}" if len(pending) == 1 and titles[0] else "")
        )
    if needs["unreviewed_campaigns"]:
        waiting.append(f"{needs['unreviewed_campaigns']} campanhas para revisar")
    crit = [a for a in alerts if a.severity in ("CRITICAL", "ABORT")]
    if crit:
        waiting.append(f"{len(crit)} alerta(s) crítico(s): {', '.join(a.code for a in crit[:3])}")
    lines += [f"• {w}" for w in waiting] or ["• nada — está tudo em dia"]

    health = data["health"]
    lines += ["", "*Saúde*"]
    sync = health["last_performance_sync"]
    if sync:
        hours = (now - datetime.fromisoformat(sync)).total_seconds() / 3600
        warn = " ⚠️" if health["stale"] else ""
        ago = "menos de 1h" if hours < 1 else f"{hours:.0f}h"
        lines.append(f"• último sync de vendas: há {ago}{warn}")
    else:
        lines.append("• sync de vendas: ainda não rodou" + (" ⚠️" if health["stale"] else ""))
    failed = health["failed_runs_today"]
    names = f" ({', '.join(sorted(set(failed)))})" if failed else ""
    lines.append(f"• falhas hoje: {len(failed)}{names} · alertas abertos: {len(alerts)}")
    lines += ["", "🔗 https://mp.dsearch.com.br"]
    return "\n".join(lines)
