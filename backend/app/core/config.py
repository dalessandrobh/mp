from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuração validada na subida. Se algo essencial faltar, a app não sobe."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    # ---------- Aplicação ----------
    app_env: Literal["local", "staging", "production"] = "local"
    log_level: str = "INFO"
    timezone: str = "America/Sao_Paulo"
    api_prefix: str = "/api/v1"

    # ---------- Banco ----------
    database_url: str = "postgresql+psycopg://mp:mp@localhost:5432/mp"

    # ---------- Autenticação ----------
    n8n_api_key: str = "troque-esta-chave"
    jwt_secret: str = "troque-este-segredo"
    jwt_algorithm: str = "HS256"

    # ---------- Modo de operação ----------
    mock_marketplace: bool = True
    mock_ads: bool = True
    dry_run: bool = True
    ai_autonomy_level: int = Field(default=1, ge=1, le=5)

    # ---------- Orçamento e portfólio ----------
    max_daily_ad_spend: Decimal = Decimal("100.00")
    min_daily_test_budget: Decimal = Decimal("10.00")
    min_active_products: int = Field(default=3, ge=1)
    max_active_products: int = Field(default=15, ge=1)
    exploration_percentage: int = Field(default=30, ge=0, le=100)
    exploitation_percentage: int = Field(default=70, ge=0, le=100)

    # ---------- Maturidade de dado ----------
    min_test_duration_days: int = Field(default=3, ge=1)
    min_clicks_for_decision: int = Field(default=50, ge=1)
    min_impressions_for_decision: int = Field(default=1000, ge=1)
    min_data_for_decision: int = Field(default=1, ge=1)

    # ---------- LLM ----------
    opportunity_use_llm: bool = False
    llm_provider: Literal["null", "anthropic", "gemini"] = "null"
    llm_model: str = ""
    llm_daily_cost_cap_usd: Decimal = Decimal("1.00")
    anthropic_api_key: str = ""
    gemini_api_key: str = ""

    # ---------- Shopee ----------
    shopee_api_url: str = "https://open-api.affiliate.shopee.br/graphql"
    shopee_app_id: str = ""
    shopee_secret: str = ""

    # ---------- Meta ----------
    meta_api_version: str = "v21.0"
    meta_ad_account_id: str = ""
    meta_access_token: str = ""

    @model_validator(mode="after")
    def _check_invariants(self) -> "Settings":
        if self.exploration_percentage + self.exploitation_percentage != 100:
            raise ValueError(
                "EXPLORATION_PERCENTAGE + EXPLOITATION_PERCENTAGE deve somar 100, "
                f"recebido {self.exploration_percentage} + {self.exploitation_percentage}"
            )
        if self.min_active_products > self.max_active_products:
            raise ValueError("MIN_ACTIVE_PRODUCTS não pode ser maior que MAX_ACTIVE_PRODUCTS")
        if self.min_daily_test_budget > self.max_daily_ad_spend:
            raise ValueError("MIN_DAILY_TEST_BUDGET não pode ser maior que MAX_DAILY_AD_SPEND")

        if self.app_env == "production":
            if self.n8n_api_key == "troque-esta-chave":
                raise ValueError("N8N_API_KEY precisa ser trocada em produção")
            if self.jwt_secret == "troque-este-segredo":
                raise ValueError("JWT_SECRET precisa ser trocado em produção")

        if self.opportunity_use_llm and self.llm_provider == "null":
            raise ValueError("OPPORTUNITY_USE_LLM=true exige LLM_PROVIDER diferente de 'null'")

        if not self.mock_marketplace and not (self.shopee_app_id and self.shopee_secret):
            raise ValueError("MOCK_MARKETPLACE=false exige SHOPEE_APP_ID e SHOPEE_SECRET")

        if not self.mock_ads and not (self.meta_access_token and self.meta_ad_account_id):
            raise ValueError("MOCK_ADS=false exige META_ACCESS_TOKEN e META_AD_ACCOUNT_ID")

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
