"""Provedor de anúncios fictício (MOCK_ADS=true).

Guarda o estado das campanhas em memória e registra cada chamada recebida, para
os testes inspecionarem exatamente o que seria enviado ao Meta. Os parâmetros
`create_as_status` e `ignore_pause` simulam um provedor que desobedece, para
exercitar a releitura pós-criação do gateway.
"""

import itertools
import random
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal

from app.adapters.ads.base import PAUSED, AdInsight, AdsAdapter

# Global ao processo: cada requisição cria um adapter novo, e ids externos repetidos
# violariam o UNIQUE de campaigns.external_id como o Meta real nunca faria.
_ids = itertools.count(1)


class MockAdsAdapter(AdsAdapter):
    ad_account_id = "act_mock"

    def __init__(self, *, create_as_status: str | None = None, ignore_pause: bool = False) -> None:
        self._create_as_status = create_as_status
        self._ignore_pause = ignore_pause
        self._statuses: dict[str, str] = {}
        self.calls: list[tuple[str, dict]] = []

    def create_campaign(self, payload: dict) -> str:
        self.calls.append(("create_campaign", payload))
        external_id = f"mock-cmp-{next(_ids)}"
        self._statuses[external_id] = self._create_as_status or payload["status"]
        return external_id

    def create_ad_set(self, payload: dict) -> str:
        self.calls.append(("create_ad_set", payload))
        return f"mock-adset-{next(_ids)}"

    def create_ad(self, payload: dict) -> str:
        self.calls.append(("create_ad", payload))
        return f"mock-ad-{next(_ids)}"

    def get_campaign_status(self, external_id: str) -> str:
        return self._statuses[external_id]

    def pause_campaign(self, external_id: str) -> None:
        self.calls.append(("pause_campaign", {"external_id": external_id}))
        if not self._ignore_pause:
            self._statuses[external_id] = PAUSED

    def fetch_insights(
        self, *, external_ad_ids: Sequence[str], since: date, until: date
    ) -> list[AdInsight]:
        insights: list[AdInsight] = []
        for ad_id in external_ad_ids:
            day = since
            while day <= until:
                rng = random.Random(f"{ad_id}|{day.isoformat()}")
                impressions = rng.randint(800, 2300)
                clicks = round(impressions * rng.uniform(0.005, 0.025))
                spend = (Decimal(clicks) * Decimal(str(round(rng.uniform(0.3, 0.9), 2)))).quantize(
                    Decimal("0.01")
                )
                insights.append(
                    AdInsight(
                        external_ad_id=ad_id,
                        metric_date=day,
                        impressions=impressions,
                        clicks=clicks,
                        spend=spend,
                        payload={"source": "mock"},
                    )
                )
                day += timedelta(days=1)
        return insights
