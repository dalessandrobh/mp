"""Monta o cliente do Pinterest a partir das configurações.

Publicação (social) e anúncios (ads) usam a MESMA autenticação: um app, um refresh token
que rotaciona, uma linha em `oauth_tokens`. Dois lugares montando `PinterestAuth` por conta
própria seriam dois leitores do mesmo token rotativo — e é exatamente assim que um deles
acaba segurando um token que o outro acabou de invalidar.
"""

from app.adapters.social.pinterest.auth import PinterestAuth
from app.adapters.social.pinterest.client import PinterestClient
from app.core.config import Settings


def build_client(settings: Settings, *, token_store) -> PinterestClient:
    if token_store is None:
        raise ValueError("adaptador real do Pinterest exige um token_store para persistir")
    auth = PinterestAuth(
        app_id=settings.pinterest_app_id,
        app_secret=settings.pinterest_app_secret,
        load=token_store.load,
        save=token_store.save,
    )
    return PinterestClient(auth=auth, base_url=settings.pinterest_base_url)
