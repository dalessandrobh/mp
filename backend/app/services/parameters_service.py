"""Parâmetros em vigor, para a tela de acompanhamento. Só leitura, nunca segredo.

Cada linha traz o valor que o código USA agora e de onde ele vem:
- `banco`: linha em `config_parameters` (vence o ambiente, só vale para os parâmetros do
  portfólio, ver `portfolio_service.load_params`);
- `ambiente`: variável de ambiente do backend (precisa de deploy para mudar).

Chaves, tokens e senhas não entram: onde a informação útil é "está configurado?", a linha
mostra só sim/não.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.control import ConfigParameter
from app.services import portfolio_service

DB = "banco"
ENV = "ambiente"


@dataclass(frozen=True)
class Param:
    key: str
    label: str
    value: str
    source: str
    note: str | None = None


def _yes(flag: bool) -> str:
    return "sim" if flag else "não"


def _brl(value: Decimal) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _db_rows(db: Session) -> dict[str, object]:
    return dict(db.execute(select(ConfigParameter.key, ConfigParameter.value)).all())


def build(db: Session, settings: Settings) -> list[dict]:
    rows = _db_rows(db)
    live = portfolio_service.load_params(db, settings)

    def portfolio(key: str, label: str, value: str, note: str | None = None) -> Param:
        return Param(key, label, value, DB if key in rows else ENV, note)

    autonomy_note = None
    if "AI_AUTONOMY_LEVEL" in rows and str(rows["AI_AUTONOMY_LEVEL"]) != str(
        settings.ai_autonomy_level
    ):
        autonomy_note = (
            f"o banco tem {rows['AI_AUTONOMY_LEVEL']}, mas o código lê só o ambiente: "
            "a linha do banco não é usada"
        )

    groups = [
        (
            "Segurança e automação",
            [
                Param("AI_AUTONOMY_LEVEL", "Nível de autonomia", str(settings.ai_autonomy_level),
                      ENV, autonomy_note),
                Param("DRY_RUN", "Simulação (DRY_RUN)", _yes(settings.dry_run), ENV,
                      "ligado = decide mas não grava"),
                Param("MOCK_SOCIAL", "Pinterest simulado", _yes(settings.mock_social), ENV,
                      "sim = nada é publicado de verdade"),
                Param("MOCK_ADS", "Anúncios simulados", _yes(settings.mock_ads), ENV,
                      "sim = nenhuma campanha é criada de verdade"),
            ],
        ),
        (
            "Orçamento e portfólio",
            [
                portfolio("MAX_DAILY_AD_SPEND", "Gasto diário máximo em anúncios",
                          _brl(live.max_daily_ad_spend)),
                portfolio("MIN_DAILY_TEST_BUDGET", "Orçamento mínimo por teste",
                          _brl(live.min_daily_test_budget)),
                portfolio("EXPLORATION_PERCENTAGE", "Parte do orçamento para explorar",
                          f"{live.exploration_percentage}%"),
                portfolio("MIN_ACTIVE_PRODUCTS", "Mínimo de produtos ativos",
                          str(live.min_active_products)),
                portfolio("MAX_ACTIVE_PRODUCTS", "Máximo de produtos ativos",
                          str(live.max_active_products)),
                portfolio("MAX_CATEGORY_SHARE_PCT", "Máximo por categoria",
                          f"{live.max_category_share_pct}%"),
                Param("MAX_DECISIONS_PER_EXECUTION", "Promoções por execução",
                      str(settings.max_decisions_per_execution), ENV,
                      "o excedente fica para a próxima execução"),
            ],
        ),
        (
            "Quando cortar ou promover",
            [
                portfolio("MIN_CLICKS_FOR_DECISION", "Cliques mínimos para decidir",
                          str(live.min_clicks_for_decision)),
                portfolio("MIN_IMPRESSIONS_FOR_DECISION", "Impressões mínimas para decidir",
                          str(live.min_impressions_for_decision)),
                portfolio("MIN_TEST_DURATION_DAYS", "Duração mínima do teste",
                          f"{live.min_test_duration_days} dias"),
            ],
        ),
        (
            "Pinterest",
            [
                Param("CONTENT_DAILY_COUNT", "Pacotes por dia", str(settings.content_daily_count),
                      ENV),
                Param("CONTENT_MIN_DAYS_BETWEEN", "Dias até o mesmo produto voltar ao pacote",
                      f"{settings.content_min_days_between} dias", ENV),
                Param("PUBLISH_MAX_PER_RUN", "Pins por rodada (publicação automática)",
                      str(settings.publish_max_per_run), ENV),
                Param("PUBLISH_PRICE_CEILING", "Teto de preço para publicar",
                      _brl(settings.publish_price_ceiling), ENV),
                Param("PINTEREST_ADS_MAX_CPC", "Teto de lance por clique (anúncio)",
                      _brl(settings.pinterest_ads_max_cpc), ENV),
                Param("PINTEREST_BOARD_ID", "Board configurado",
                      _yes(bool(settings.pinterest_board_id)), ENV,
                      "só para a publicação automática"),
                Param("ADS_PROVIDER", "Plataforma de anúncios", settings.ads_provider, ENV),
            ],
        ),
        (
            "Texto e links",
            [
                Param("LLM_PROVIDER", "Modelo de texto", settings.llm_provider, ENV,
                      "null = o pacote usa o texto-modelo"),
                Param("LLM_DAILY_COST_CAP_USD", "Teto diário do modelo",
                      f"US$ {settings.llm_daily_cost_cap_usd}", ENV),
                Param("PUBLIC_BASE_URL", "Endereço público dos links", settings.public_base or "—",
                      ENV),
            ],
        ),
    ]
    return [
        {
            "title": title,
            "items": [
                {"key": p.key, "label": p.label, "value": p.value, "source": p.source,
                 "note": p.note}
                for p in params
            ],
        }
        for title, params in groups
    ]
