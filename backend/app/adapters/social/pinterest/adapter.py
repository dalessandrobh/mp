"""Publicação de pin de imagem no Pinterest (v5).

    POST /v5/pins
    {"board_id": "...", "title": ..., "description": ..., "link": ...,
     "alt_text": ..., "media_source": {"source_type": "image_url", "url": ...}}

Limites vindos da OpenAPI oficial, não de blog: title 100, description 800, alt_text 500,
link 2048, board_id só dígitos.

`source_type: image_url` faz o Pinterest baixar a imagem do fornecedor — no caso do MP, a
foto do produto hospedada pela Shopee. Isso evita o MP armazenar e servir imagem de
terceiro, e evita o fluxo de duas etapas do upload. O custo é que uma imagem que saia do
ar quebra o pin, mas aí o produto já não serve para divulgar de todo modo.
"""

from app.adapters.social.base import (
    PostDraft,
    PostLimits,
    PublishedPost,
    SocialAdapter,
    SocialRejected,
    fit,
)
from app.adapters.social.pinterest.client import PinterestClient

# Da OpenAPI do Pinterest (components.schemas.PinCreate).
LIMITS = PostLimits(title=100, description=800, alt_text=500, link=2048, per_day=None)


class PinterestAdapter(SocialAdapter):
    code = "pinterest"
    display_name = "Pinterest"

    def __init__(self, *, client: PinterestClient, board_id: str) -> None:
        if not board_id or not board_id.isdigit():
            raise ValueError("PINTEREST_BOARD_ID deve ser o id numérico do board")
        self._client = client
        self._board_id = board_id

    @property
    def limits(self) -> PostLimits:
        return LIMITS

    def publish(self, draft: PostDraft) -> PublishedPost:
        problems = draft.problems(LIMITS)
        if problems:
            raise SocialRejected("; ".join(problems))

        payload = {
            "board_id": self._board_id,
            "title": fit(draft.title, LIMITS.title),
            "description": fit(draft.description, LIMITS.description),
            "link": draft.link,
            "media_source": {"source_type": "image_url", "url": draft.image_url},
        }
        if draft.alt_text:
            payload["alt_text"] = fit(draft.alt_text, LIMITS.alt_text)

        body = self._client.post("/pins", payload)
        pin_id = str(body.get("id") or "")
        if not pin_id:
            raise SocialRejected("Pinterest respondeu sem id do pin")
        return PublishedPost(
            external_post_id=pin_id,
            url=f"https://www.pinterest.com/pin/{pin_id}/",
            raw={"board_id": body.get("board_id"), "created_at": body.get("created_at")},
        )
