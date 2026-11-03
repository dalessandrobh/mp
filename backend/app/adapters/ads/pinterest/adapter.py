"""Anúncios do Pinterest (API v5): campanha, grupo de anúncios e anúncio, sempre PAUSED.

Mapeamento do vocabulário do gateway (que é neutro) para o do Pinterest:

  campanha     -> campaign       objective_type CONSIDERATION, status PAUSED
  conjunto     -> ad group       billable_event CLICKTHROUGH, orçamento diário, lance máximo
  anúncio      -> ad             promove um PIN que já existe (pin_id), creative_type REGULAR

**Por que CONSIDERATION e não WEB_CONVERSION.** Otimizar por conversão exige a tag do
Pinterest na página de destino, e o destino é a Shopee — não temos como instalá-la. Sem
tag o Pinterest não vê a venda e não tem o que otimizar. CONSIDERATION cobra e otimiza por
clique, que é o único evento que enxergamos. A venda continua vindo do relatório de
conversão da Shopee, atribuída pelo sub_id.

**Por que há um lance.** A especificação v5 diz que `bid_in_micro_currency` é obrigatório
para CONSIDERATION/CLICKTHROUGH. O gateway entrega esse valor já calculado a partir do
piso de receita por clique do produto; este adapter não escolhe lance, só se recusa a
criar sem um.

**Moeda.** Valores vão em micro-unidades da moeda da CONTA de anúncios. Se a conta
estiver em dólar, R$ 20,00 viraria US$ 20,00 sem nenhum erro — então a moeda é conferida
uma vez, antes da primeira criação, e qualquer coisa diferente de BRL recusa tudo.

Nada aqui ativa nada: não existe método de ativação. Status só sai como PAUSED.
"""

from collections.abc import Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.adapters.ads.base import PAUSED, AdInsight, AdsAdapter, AdsProviderError
from app.adapters.social.base import (
    SocialAuthError,
    SocialError,
    SocialRateLimited,
    SocialRejected,
)
from app.adapters.social.pinterest.client import PinterestClient

MICRO = Decimal(1_000_000)
OBJECTIVE = "CONSIDERATION"
BILLABLE_EVENT = "CLICKTHROUGH"
CURRENCY = "BRL"
ANALYTICS_COLUMNS = "IMPRESSION_1,CLICKTHROUGH_1,SPEND_IN_MICRO_DOLLAR"
# Limite da API para `ad_ids` por chamada de analytics.
ANALYTICS_MAX_IDS = 250

# Segmentação: país e idioma. NÃO foi exercitada contra a API real — a especificação traz
# exemplos contraditórios para LOCATION/GEO. Como tudo nasce PAUSED, um erro aqui aparece
# como FAILED_PROVIDER na primeira criação, sem gastar nada; o teste que trava este formato
# existe para que a correção, quando vier, seja uma mudança deliberada.
def targeting_spec(country: str) -> dict:
    return {"GEO": [country], "LOCALE": ["pt"]}


def _micro(value: Decimal) -> int:
    return int((value * MICRO).to_integral_value(rounding=ROUND_HALF_UP))


class PinterestAdsAdapter(AdsAdapter):
    objective = OBJECTIVE

    def __init__(self, *, client: PinterestClient, ad_account_id: str, country: str = "BR") -> None:
        if not ad_account_id or not ad_account_id.isdigit():
            raise ValueError("PINTEREST_AD_ACCOUNT_ID deve ser o id numérico da conta de anúncios")
        self.ad_account_id = ad_account_id
        self._client = client
        self._country = country
        self._currency_ok = False

    # ---------- criação ----------

    def create_campaign(self, payload: dict) -> str:
        self._ensure_currency()
        body = [
            {
                "name": payload["name"],
                "objective_type": OBJECTIVE,
                "status": PAUSED,
            }
        ]
        return self._created_id("campanha", self._call("POST", "/campaigns", body))

    def create_ad_set(self, payload: dict) -> str:
        bid = payload.get("bid")
        if bid is None:
            raise AdsProviderError(
                "lance máximo por clique é obrigatório em CONSIDERATION/CLICKTHROUGH"
            )
        body = [
            {
                "name": payload["name"],
                "campaign_id": payload["campaign_external_id"],
                "status": PAUSED,
                "billable_event": BILLABLE_EVENT,
                "budget_type": "DAILY",
                "budget_in_micro_currency": _micro(Decimal(payload["daily_budget"])),
                "bid_strategy_type": "MAX_BID",
                "bid_in_micro_currency": _micro(Decimal(bid)),
                "pacing_delivery_type": "STANDARD",
                "targeting_spec": targeting_spec(self._country),
            }
        ]
        return self._created_id("grupo de anúncios", self._call("POST", "/ad_groups", body))

    def create_ad(self, payload: dict) -> str:
        pin_id = payload.get("pin_id")
        if not pin_id:
            raise AdsProviderError("anúncio do Pinterest promove um pin: pin_id ausente")
        body: dict[str, Any] = {
            "name": payload["name"][:255],
            "ad_group_id": payload["ad_set_external_id"],
            "pin_id": pin_id,
            "creative_type": "REGULAR",
            "status": PAUSED,
        }
        # O destino próprio (/go/ com canal `pinads`) é o que separa o clique pago do
        # orgânico: sem ele o anúncio herdaria o link do pin e o clique entraria como `pin`.
        if payload.get("destination_url"):
            body["destination_url"] = payload["destination_url"]
        return self._created_id("anúncio", self._call("POST", "/ads", [body]))

    # ---------- leitura e pausa ----------

    def get_campaign_status(self, external_id: str) -> str:
        body = self._call("GET", f"/campaigns/{external_id}")
        status = body.get("status")
        if not status:
            raise AdsProviderError(f"Pinterest não informou o status da campanha {external_id}")
        return str(status)

    def pause_campaign(self, external_id: str) -> None:
        self._call("PATCH", "/campaigns", [{"id": external_id, "status": PAUSED}])

    def fetch_insights(
        self, *, external_ad_ids: Sequence[str], since: date, until: date
    ) -> list[AdInsight]:
        insights: list[AdInsight] = []
        ids = list(external_ad_ids)
        for start in range(0, len(ids), ANALYTICS_MAX_IDS):
            chunk = ids[start : start + ANALYTICS_MAX_IDS]
            rows = self._call(
                "GET",
                "/ads/analytics",
                params={
                    "start_date": since.isoformat(),
                    "end_date": until.isoformat(),
                    "ad_ids": ",".join(chunk),
                    "columns": ANALYTICS_COLUMNS,
                    "granularity": "DAY",
                },
            )
            for row in rows or []:
                insights.append(self._insight(row))
        return insights

    # ---------- internos ----------

    @staticmethod
    def _insight(row: dict) -> AdInsight:
        # Coluna ausente é None, não zero: "o Pinterest não informou" não é "custou nada".
        micro = row.get("SPEND_IN_MICRO_DOLLAR")
        spend = None
        if micro is not None:
            spend = (Decimal(str(micro)) / MICRO).quantize(Decimal("0.01"), ROUND_HALF_UP)
        return AdInsight(
            external_ad_id=str(row["AD_ID"]),
            metric_date=date.fromisoformat(str(row["DATE"])),
            impressions=_int_or_none(row.get("IMPRESSION_1")),
            clicks=_int_or_none(row.get("CLICKTHROUGH_1")),
            spend=spend,
            payload={"source": "pinterest", "raw": row},
        )

    def _ensure_currency(self) -> None:
        if self._currency_ok:
            return
        account = self._client_call(lambda: self._client.get(f"/ad_accounts/{self.ad_account_id}"))
        currency = account.get("currency")
        if currency != CURRENCY:
            raise AdsProviderError(
                f"a conta de anúncios {self.ad_account_id} está em {currency!r}, não em "
                f"{CURRENCY}: os valores em reais seriam lidos como outra moeda",
                fatal=True,
            )
        self._currency_ok = True

    def _call(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        url = f"/ad_accounts/{self.ad_account_id}{path}"
        if method == "GET":
            return self._client_call(lambda: self._client.get(url, params))
        if method == "PATCH":
            return self._client_call(lambda: self._client.patch(url, body))
        return self._client_call(lambda: self._client.post(url, body))

    @staticmethod
    def _client_call(call) -> Any:
        try:
            return call()
        except (SocialAuthError, SocialRateLimited) as exc:
            raise AdsProviderError(str(exc), fatal=True) from exc
        except SocialRejected as exc:
            # Recusa de um item (400/422) é do produto, não do lote.
            raise AdsProviderError(str(exc)) from exc
        except SocialError as exc:
            # Rede e 5xx já esgotaram as tentativas do cliente: valem para o lote.
            raise AdsProviderError(str(exc), fatal=True) from exc

    @staticmethod
    def _created_id(what: str, body: dict) -> str:
        """Os endpoints de criação respondem `{"items": [{"data": {...}, "exceptions": [...]}]}`.

        Um item pode falhar com HTTP 200 e a falha vir em `exceptions`; olhar só o status
        HTTP trataria como criado algo que não existe.
        """
        items = body.get("items") or []
        if not items:
            raise AdsProviderError(f"Pinterest respondeu sem itens ao criar {what}")
        item = items[0]
        exceptions = item.get("exceptions") or []
        if exceptions:
            detail = "; ".join(str(e.get("message", e)) for e in exceptions)
            raise AdsProviderError(f"Pinterest recusou {what}: {detail}")
        created = (item.get("data") or {}).get("id")
        if not created:
            raise AdsProviderError(f"Pinterest respondeu sem id ao criar {what}")
        return str(created)


def _int_or_none(value: Any) -> int | None:
    return None if value is None else int(value)
