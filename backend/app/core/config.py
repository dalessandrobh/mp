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
    # E-mails (separados por vírgula) que podem usar o dashboard. O Supabase self-hosted
    # pode ter usuários de outros apps: o JWT válido não basta para aprovar recomendação.
    dashboard_allowed_emails: str = ""

    # ---------- Modo de operação ----------
    mock_marketplace: bool = True
    mock_ads: bool = True
    # Qual rede recebe os anúncios quando MOCK_ADS=false.
    ads_provider: Literal["meta", "pinterest"] = "pinterest"
    # Publicação orgânica. Padrão true de propósito: no Trial access do Pinterest o pin
    # criado é visível SÓ para o dono da conta, então publicar de verdade antes do
    # Standard access gasta cota e não entrega alcance nenhum.
    mock_social: bool = True
    dry_run: bool = True
    ai_autonomy_level: int = Field(default=1, ge=1, le=5)

    # ---------- Orçamento e portfólio ----------
    max_daily_ad_spend: Decimal = Decimal("100.00")
    min_daily_test_budget: Decimal = Decimal("10.00")
    min_active_products: int = Field(default=3, ge=1)
    max_active_products: int = Field(default=15, ge=1)
    exploration_percentage: int = Field(default=30, ge=0, le=100)
    # Fatia máxima do portfólio que uma única categoria nível 1 pode ocupar.
    max_category_share_pct: int = Field(default=40, ge=1, le=100)

    # ---------- Varredura de comissão alta ----------
    # Quantos itens por categoria a varredura por preço decrescente lê (teto da API: 500).
    commission_sweep_per_category: int = Field(default=300, ge=20, le=500)
    # Pisos para guardar o produto. Os DOIS valem: comissão alta sem venda não serve.
    commission_sweep_min_value: Decimal = Decimal("15.00")
    commission_sweep_min_sales: int = Field(default=100, ge=0)
    exploitation_percentage: int = Field(default=70, ge=0, le=100)

    # ---------- Maturidade de dado ----------
    min_test_duration_days: int = Field(default=3, ge=1)
    min_clicks_for_decision: int = Field(default=50, ge=1)
    min_impressions_for_decision: int = Field(default=1000, ge=1)
    min_data_for_decision: int = Field(default=1, ge=1)

    # ---------- Guardrails de anúncios ----------
    max_unreviewed_campaigns: int = Field(default=10, ge=1)
    max_campaigns_per_execution: int = Field(default=2, ge=1)

    # Teto de mudanças de portfólio por execução do /portfolio/apply.
    max_decisions_per_execution: int = Field(default=3, ge=1)

    # ---------- Tracking ----------
    # UNKNOWN-4 (medido na API real): a Shopee aceita até 48 caracteres e recusa 56; o limite
    # exato fica entre 49 e 55. 48 é o maior valor verificado. Acima dele o link falha alto —
    # truncar em silêncio quebraria a atribuição.
    subid_max_length: int = Field(default=48, ge=20)

    # ---------- Página pública e cliques ----------
    # Base das URLs /go/{sub_id} e /l que entram em post e pin. Sem isso o conteúdo sai
    # com o link de afiliado cru, que os Termos 4.3(k) não deixam indexar.
    public_base_url: str = ""
    # Sal do hash do visitante. Vazio cai no JWT_SECRET: o importante é não ser constante
    # entre instalações, senão o mesmo IP produz o mesmo hash em qualquer lugar.
    click_hash_salt: str = ""
    bio_page_title: str = "Achadinhos da vez"
    # Não afirmar "testei": são produtos selecionados por dados (preço, vendas, nota), não
    # testados. Afirmação não verificável é conteúdo enganoso (Termos da Shopee 4.3(j)).
    bio_page_subtitle: str = "Seleção diária de achadinhos, com preço e nota à vista."
    # E-mail público de contato na política de privacidade (/privacidade). Vazio => a página
    # manda o visitante falar pelo perfil do Pinterest. É publicado: não use um e-mail que
    # não deva ser público.
    privacy_contact_email: str = ""

    # ---------- Publicação orgânica (Pinterest) ----------
    pinterest_app_id: str = ""
    pinterest_app_secret: str = ""
    # Semente da primeira autorização. A partir da primeira renovação quem vale é a
    # tabela oauth_tokens: o refresh token do Pinterest ROTACIONA, e o valor daqui
    # envelhece (app/adapters/social/pinterest/auth.py).
    pinterest_refresh_token: str = ""
    # Id numérico do board que recebe os pins.
    pinterest_board_id: str = ""
    pinterest_base_url: str = "https://api.pinterest.com/v5"
    # ---------- Anúncios do Pinterest ----------
    # Id NUMÉRICO da conta de anúncios (ads.pinterest.com). Moeda BRL é conferida na API.
    pinterest_ad_account_id: str = ""
    # Teto do lance por clique. O lance efetivo é o MENOR entre este teto e o piso de
    # receita por clique do produto: nunca se paga mais por clique do que ele rende.
    pinterest_ads_max_cpc: Decimal = Decimal("0.30")
    pinterest_ads_country: str = "BR"
    # Quantos posts por execução. O limite do Pinterest (org_write) é 300/dia no Trial;
    # o gargalo aqui é editorial, não técnico.
    publish_max_per_run: int = Field(default=10, ge=1, le=50)
    # Guarda provisório contra réplica: acima deste preço, categoria ou marca de risco
    # no título barram a publicação (app/domain/brand_risk.py).
    publish_price_ceiling: Decimal = Decimal("800.00")
    # Ids de categoria onde falsificação é lucrativa, separados por vírgula.
    publish_brand_categories: str = ""

    # ---------- LLM ----------
    opportunity_use_llm: bool = False
    llm_provider: Literal["null", "anthropic", "gemini"] = "null"
    llm_model: str = ""
    llm_daily_cost_cap_usd: Decimal = Decimal("1.00")
    anthropic_api_key: str = ""
    # Preço por milhão de tokens, só para ESTIMAR o custo e aplicar o teto diário. Conservador
    # de propósito: confira na tabela de preços do modelo escolhido.
    llm_input_usd_per_mtok: Decimal = Decimal("1.00")
    llm_output_usd_per_mtok: Decimal = Decimal("5.00")
    # Quantos produtos recebem pacote de conteúdo por dia (o dono publica à mão).
    content_daily_count: int = Field(default=3, ge=1, le=10)
    # Dias mínimos até o mesmo produto voltar a ganhar pacote (0 = só não repete no mesmo dia).
    # Teto de preço do produto no pacote diário (R$). Acima dele o item não entra: ticket alto
    # converte pouco em pin orgânico. 0 desliga o teto. Produto com marca no título nunca entra.
    content_max_price: Decimal = Field(default=Decimal("300"), ge=0)
    content_min_days_between: int = Field(default=7, ge=0, le=60)
    gemini_api_key: str = ""

    # ---------- Shopee ----------
    shopee_api_url: str = "https://open-api.affiliate.shopee.com.br/graphql"
    shopee_app_id: str = ""
    shopee_secret: str = ""
    shopee_timeout_seconds: float = Field(default=30.0, gt=0)
    # UNKNOWN-5: o limite de requisições não é documentado. Intervalo mínimo conservador
    # entre chamadas + backoff exponencial no erro 10030.
    shopee_min_interval_seconds: float = Field(default=0.5, ge=0)
    shopee_max_retries: int = Field(default=4, ge=0, le=10)
    # IDs dos lotes de liquidação (painel de afiliado > Billing), separados por vírgula. A API
    # exige um `validationId` por consulta e não tem como listá-los.
    shopee_validation_ids: str = ""

    # ---------- Meta ----------
    meta_api_version: str = "v21.0"
    meta_ad_account_id: str = ""
    meta_access_token: str = ""

    @property
    def validation_ids(self) -> tuple[int, ...]:
        return tuple(int(p) for p in self.shopee_validation_ids.replace(" ", "").split(",") if p)

    @property
    def click_salt(self) -> str:
        return self.click_hash_salt or self.jwt_secret

    @property
    def public_base(self) -> str:
        return self.public_base_url.rstrip("/")

    @property
    def brand_categories(self) -> frozenset[str]:
        return frozenset(
            part.strip() for part in self.publish_brand_categories.split(",") if part.strip()
        )

    @property
    def allowed_emails(self) -> frozenset[str]:
        return frozenset(
            e.strip().lower() for e in self.dashboard_allowed_emails.split(",") if e.strip()
        )

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
            if not self.allowed_emails:
                raise ValueError(
                    "DASHBOARD_ALLOWED_EMAILS precisa listar quem pode usar o dashboard em produção"
                )

        if self.opportunity_use_llm and self.llm_provider == "null":
            raise ValueError("OPPORTUNITY_USE_LLM=true exige LLM_PROVIDER diferente de 'null'")

        if not self.mock_marketplace and not (self.shopee_app_id and self.shopee_secret):
            raise ValueError("MOCK_MARKETPLACE=false exige SHOPEE_APP_ID e SHOPEE_SECRET")

        if (
            not self.mock_ads
            and self.ads_provider == "meta"
            and not (self.meta_access_token and self.meta_ad_account_id)
        ):
            raise ValueError("MOCK_ADS=false exige META_ACCESS_TOKEN e META_AD_ACCOUNT_ID")

        if not self.mock_ads and self.ads_provider == "pinterest":
            if not (
                self.pinterest_app_id
                and self.pinterest_app_secret
                and self.pinterest_ad_account_id
            ):
                raise ValueError(
                    "MOCK_ADS=false com ADS_PROVIDER=pinterest exige PINTEREST_APP_ID, "
                    "PINTEREST_APP_SECRET e PINTEREST_AD_ACCOUNT_ID"
                )
            if not self.public_base_url:
                raise ValueError(
                    "MOCK_ADS=false com ADS_PROVIDER=pinterest exige PUBLIC_BASE_URL: o "
                    "anúncio aponta para /go/, não para o link de afiliado cru"
                )

        if not self.mock_social and not (
            self.pinterest_app_id and self.pinterest_app_secret and self.pinterest_board_id
        ):
            raise ValueError(
                "MOCK_SOCIAL=false exige PINTEREST_APP_ID, PINTEREST_APP_SECRET e "
                "PINTEREST_BOARD_ID"
            )

        if not self.mock_social and not self.public_base_url:
            raise ValueError(
                "MOCK_SOCIAL=false exige PUBLIC_BASE_URL: o pin aponta para /go/, não "
                "para o link de afiliado cru (Termos 4.3k)"
            )

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
