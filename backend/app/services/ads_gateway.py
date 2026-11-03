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

from app.adapters.ads.base import PAUSED, AdsAdapter, AdsProviderError
from app.domain import autonomy
from app.domain.autonomy import ActionClass
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
    FAILED_PROVIDER = "FAILED_PROVIDER"


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
    # None => o gateway usa o objetivo do adapter (cada provedor tem o seu vocabulário).
    objective: str | None = None
    # Específicos de provedor que promove conteúdo existente (Pinterest promove um pin).
    pin_id: str | None = None
    destination_url: str | None = None
    # Lance máximo por clique. Obrigatório em alguns objetivos do Pinterest.
    bid: Decimal | None = None


@dataclass(frozen=True)
class BundleOutcome:
    status: BundleStatus
    detail: str | None = None
    campaign_id: int | None = None
    external_campaign_id: str | None = None
    # Erro de provedor que vale para o lote todo: quem chama deve parar.
    fatal: bool = False


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

        if not autonomy.permits(self._limits.autonomy_level, ActionClass.CREATE_CAMPAIGN):
            return BundleOutcome(
                BundleStatus.REFUSED_AUTONOMY,
                autonomy.refusal(self._limits.autonomy_level, ActionClass.CREATE_CAMPAIGN),
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
        objective = request.objective or self._adapter.objective
        campaign_payload = {
            "name": request.name,
            "objective": objective,
            "status": PAUSED,
            "daily_budget": str(request.daily_budget),
            "ad_account_id": self._adapter.ad_account_id,
        }
        try:
            external_id = self._adapter.create_campaign(campaign_payload)
        except AdsProviderError as exc:
            # Resultado, não exceção: levantar faria o get_db desfazer as campanhas já
            # criadas neste lote, que existem no provedor mas sumiriam daqui.
            return BundleOutcome(BundleStatus.FAILED_PROVIDER, str(exc), fatal=exc.fatal)

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

        ad_set_payload: dict = {
            "campaign_external_id": external_id,
            "name": f"{request.name} / conjunto",
            "status": PAUSED,
            "daily_budget": str(request.daily_budget),
        }
        if request.bid is not None:
            ad_set_payload["bid"] = str(request.bid)
        ad_payload: dict = {"name": f"{request.name} / anúncio", "status": PAUSED}
        if request.pin_id is not None:
            ad_payload["pin_id"] = request.pin_id
        if request.destination_url is not None:
            ad_payload["destination_url"] = request.destination_url

        try:
            ad_set_id = self._adapter.create_ad_set(ad_set_payload)
            ad_external_id = self._adapter.create_ad(
                {**ad_payload, "ad_set_external_id": ad_set_id}
            )
        except AdsProviderError as exc:
            # A campanha já existe no provedor (pausada, sem gasto), mas não há linha aqui.
            # Sem o alerta ela ficaria invisível: o id externo é o que o operador precisa
            # para apagá-la no Gerenciador.
            alert_service.raise_alert(
                self._db,
                severity="WARNING",
                code="CAMPAIGN_ORPHANED",
                message=(
                    f"Campanha {external_id} criada (PAUSED) sem conjunto/anúncio: {exc}. "
                    "Apague-a no Gerenciador de Anúncios."
                ),
                subject_type="campaign",
                subject_id=external_id,
                details={"product_id": request.product_id, "fatal": exc.fatal},
            )
            return BundleOutcome(
                BundleStatus.FAILED_PROVIDER,
                str(exc),
                external_campaign_id=external_id,
                fatal=exc.fatal,
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
            objective=request.objective or self._adapter.objective,
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
