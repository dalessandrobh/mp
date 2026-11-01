"""AdsGateway: CHOKE POINT de criação de estrutura de anúncios.

Nada cria Campaign/AdSet/Ad fora daqui. As verificações rodam na ordem do
PLANNING §7.1, e cada uma existe por um motivo:

  1. dry-run          — simula, não chama o provedor
  2. UNREVIEWED alto  — fila de revisão humana cheia: aborta e alerta
  3. limite/execução  — para de criar, não recusa o resto em silêncio
  4. BudgetGuard      — orçamento não cabe: recusa
  5. status=PAUSED    — forçado no payload, qualquer status recebido é ignorado
  6. releitura        — confia no estado REAL do provedor, não no que enviamos

Aborto e recusa viram resultado, não exceção: levantar faria o get_db desfazer a
transação inteira e o alerta CRITICAL sumiria junto com ela.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.ads.base import PAUSED, AdsAdapter
from app.domain.enums import CampaignReviewStatus, PortfolioTier
from app.models.ads import Ad, AdSet, Campaign
from app.services import alert_service
from app.services.budget_guard import BudgetGuard


class BundleStatus(StrEnum):
    CREATED = "CREATED"
    SIMULATED = "SIMULATED"
    REFUSED_BUDGET = "REFUSED_BUDGET"
    REFUSED_AUTONOMY = "REFUSED_AUTONOMY"
    STOPPED_LIMIT = "STOPPED_LIMIT"
    ABORTED = "ABORTED"


@dataclass(frozen=True)
class GatewayLimits:
    max_unreviewed: int
    max_per_execution: int
    dry_run: bool
    # Abaixo do nível 4 a criação de campanha é sempre humana (PLANNING §7.3).
    autonomy_level: int


@dataclass
class ExecutionContext:
    """Estado de UMA execução do workflow; é ele que conta as campanhas criadas."""

    run_id: int | None = None
    campaigns_created: int = 0


@dataclass(frozen=True)
class BundleRequest:
    product_id: int
    affiliate_link_id: int
    name: str
    daily_budget: Decimal
    tier: PortfolioTier
    creative_id: int | None = None
    objective: str = "OUTCOME_SALES"


@dataclass(frozen=True)
class BundleOutcome:
    status: BundleStatus
    detail: str | None = None
    campaign_id: int | None = None
    external_campaign_id: str | None = None


class AdsGateway:
    def __init__(
        self,
        db: Session,
        adapter: AdsAdapter,
        guard: BudgetGuard,
        limits: GatewayLimits,
        context: ExecutionContext,
    ) -> None:
        self._db = db
        self._adapter = adapter
        self._guard = guard
        self._limits = limits
        self._context = context

    def create_campaign_bundle(self, request: BundleRequest) -> BundleOutcome:
        # 1. Dry-run: nada sai daqui.
        if self._limits.dry_run:
            return BundleOutcome(BundleStatus.SIMULATED, "dry-run: nada foi criado")

        if self._limits.autonomy_level < 4:
            return BundleOutcome(
                BundleStatus.REFUSED_AUTONOMY,
                f"AI_AUTONOMY_LEVEL={self._limits.autonomy_level}: criar campanha exige nível 4+",
            )

        # 2. Fila de revisão cheia.
        unreviewed = self._db.execute(
            select(func.count())
            .select_from(Campaign)
            .where(Campaign.review_status == CampaignReviewStatus.UNREVIEWED)
        ).scalar_one()
        if unreviewed > self._limits.max_unreviewed:
            alert_service.raise_alert(
                self._db,
                severity="CRITICAL",
                code="UNREVIEWED_THRESHOLD_EXCEEDED",
                message=(
                    f"{unreviewed} campanhas sem revisão "
                    f"(limite {self._limits.max_unreviewed})"
                ),
                details={"unreviewed": unreviewed, "limit": self._limits.max_unreviewed},
            )
            return BundleOutcome(BundleStatus.ABORTED, "campanhas UNREVIEWED acima do limite")

        # 3. Limite por execução.
        if self._context.campaigns_created >= self._limits.max_per_execution:
            return BundleOutcome(
                BundleStatus.STOPPED_LIMIT,
                f"limite de {self._limits.max_per_execution} campanhas por execução",
            )

        # 4. Orçamento.
        verdict = self._guard.check(request.daily_budget, request.tier)
        if not verdict.allowed:
            return BundleOutcome(BundleStatus.REFUSED_BUDGET, verdict.reason)

        # 5. PAUSED forçado: o status do request nem existe, e este é o único payload.
        campaign_payload = {
            "name": request.name,
            "objective": request.objective,
            "status": PAUSED,
            "daily_budget": str(request.daily_budget),
            "ad_account_id": self._adapter.ad_account_id,
        }
        external_id = self._adapter.create_campaign(campaign_payload)

        # 6. Releitura do estado real.
        observed = self._adapter.get_campaign_status(external_id)
        if observed != PAUSED:
            self._adapter.pause_campaign(external_id)
            observed = self._adapter.get_campaign_status(external_id)
            alert_service.raise_alert(
                self._db,
                severity="CRITICAL",
                code="CAMPAIGN_CREATED_NOT_PAUSED",
                message=f"Campanha {external_id} nasceu fora de PAUSED; pausa forçada",
                subject_type="campaign",
                subject_id=external_id,
                details={"still_not_paused": observed != PAUSED},
            )
            if observed != PAUSED:
                # Não conseguimos pausar: dinheiro pode estar saindo. Registra e aborta.
                self._persist_campaign(request, external_id, observed, None)
                return BundleOutcome(
                    BundleStatus.ABORTED,
                    "campanha ativa e a pausa forçada falhou — intervenção humana urgente",
                    external_campaign_id=external_id,
                )

        ad_set_id = self._adapter.create_ad_set(
            {
                "campaign_external_id": external_id,
                "name": f"{request.name} / conjunto",
                "status": PAUSED,
                "daily_budget": str(request.daily_budget),
            }
        )
        ad_external_id = self._adapter.create_ad(
            {
                "ad_set_external_id": ad_set_id,
                "name": f"{request.name} / anúncio",
                "status": PAUSED,
            }
        )

        campaign = self._persist_campaign(request, external_id, observed, ad_external_id, ad_set_id)
        self._guard.commit(
            request.daily_budget,
            request.tier,
            product_id=request.product_id,
            campaign_id=campaign.id,
        )
        self._context.campaigns_created += 1
        return BundleOutcome(
            BundleStatus.CREATED,
            campaign_id=campaign.id,
            external_campaign_id=external_id,
        )

    def _persist_campaign(
        self,
        request: BundleRequest,
        external_id: str,
        status: str,
        ad_external_id: str | None,
        ad_set_external_id: str | None = None,
    ) -> Campaign:
        campaign = Campaign(
            external_id=external_id,
            ad_account_id=self._adapter.ad_account_id,
            name=request.name,
            objective=request.objective,
            status=status,
            created_paused=True,
            review_status=CampaignReviewStatus.UNREVIEWED,
            daily_budget=request.daily_budget,
            created_by_run_id=self._context.run_id,
            dry_run=False,
        )
        self._db.add(campaign)
        self._db.flush()

        if ad_external_id is not None:
            ad_set = AdSet(
                campaign_id=campaign.id,
                external_id=ad_set_external_id,
                name=f"{request.name} / conjunto",
                status=PAUSED,
                daily_budget=request.daily_budget,
            )
            self._db.add(ad_set)
            self._db.flush()
            self._db.add(
                Ad(
                    ad_set_id=ad_set.id,
                    product_id=request.product_id,
                    creative_id=request.creative_id,
                    affiliate_link_id=request.affiliate_link_id,
                    external_id=ad_external_id,
                    status=PAUSED,
                )
            )
            self._db.flush()
        return campaign
