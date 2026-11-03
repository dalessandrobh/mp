"""Rede social fictícia e determinística (MOCK_SOCIAL=true).

Serve a dois propósitos: teste sem rede, e ensaio do fluxo completo antes de o Pinterest
conceder Standard access — enquanto ele não concede, o pin real só é visível para o dono
da conta, então publicar de verdade não entrega nada.

O id devolvido é hash do rascunho: duas chamadas com o mesmo conteúdo devolvem o mesmo
id, o que deixa o teste de idempotência honesto.
"""

import hashlib

from app.adapters.social.base import (
    PostDraft,
    PostLimits,
    PublishedPost,
    SocialAdapter,
    SocialRejected,
)

_LIMITS = PostLimits(title=100, description=800, alt_text=500, link=2048, per_day=100)


class MockSocialAdapter(SocialAdapter):
    code = "mock_social"
    display_name = "Mock Social"

    def __init__(self) -> None:
        self.published: list[PostDraft] = []

    @property
    def limits(self) -> PostLimits:
        return _LIMITS

    def publish(self, draft: PostDraft) -> PublishedPost:
        problems = draft.problems(_LIMITS)
        if problems:
            raise SocialRejected("; ".join(problems))
        digest = hashlib.sha256(
            "|".join((draft.title, draft.description, draft.link, draft.image_url)).encode()
        ).hexdigest()[:16]
        self.published.append(draft)
        return PublishedPost(
            external_post_id=f"mock-{digest}",
            url=f"https://mock.social/p/{digest}",
            raw={"source": "mock", "title": draft.title},
        )
