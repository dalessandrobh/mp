"""Provedor de anúncios fictício (MOCK_ADS=true).

Guarda o estado das campanhas em memória e registra cada chamada recebida, para
os testes inspecionarem exatamente o que seria enviado ao Meta. Os parâmetros
`create_as_status` e `ignore_pause` simulam um provedor que desobedece, para
exercitar a releitura pós-criação do gateway.
"""

import itertools

from app.adapters.ads.base import PAUSED, AdsAdapter

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
