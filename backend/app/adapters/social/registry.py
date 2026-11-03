"""Resolve o adaptador de rede social a partir das configurações.

Enquanto `MOCK_SOCIAL=true` (o padrão), nada sai para a rede. Isso é deliberado: no Trial
access do Pinterest o pin criado é visível **só para o dono da conta**, então publicar de
verdade antes do Standard access gasta cota e não entrega alcance nenhum.
"""

from app.adapters.social.base import SocialAdapter
from app.adapters.social.mock.adapter import MockSocialAdapter
from app.adapters.social.pinterest.adapter import PinterestAdapter
from app.adapters.social.pinterest.factory import build_client
from app.core.config import Settings


def get_social_adapter(settings: Settings, *, token_store=None) -> SocialAdapter:
    if settings.mock_social:
        return MockSocialAdapter()
    client = build_client(settings, token_store=token_store)
    return PinterestAdapter(client=client, board_id=settings.pinterest_board_id)
