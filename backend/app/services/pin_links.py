"""Endereços que levam um pin pronto ao Pinterest com um toque.

O "Pin It" do Pinterest (`/pin/create/button/`) recebe link de destino, imagem e descrição
pela URL: a pessoa só escolhe o quadro e salva. Ela continua decidindo cada pin (regra 4.3
das Diretrizes de Desenvolvedor), mas sem baixar imagem nem colar campos.

Módulo sem dependências do resto do MP para o `content_service` poder usá-lo sem import
circular.
"""

from urllib.parse import quote

PIN_IT = "https://www.pinterest.com/pin/create/button/"


def image_url(public_base: str, creative_id: int) -> str:
    """Imagem do pin servida pelo nosso domínio (2:3), não pelo CDN do marketplace."""
    return f"{public_base}/img/{creative_id}.jpg"


def pin_it_url(*, link: str, image: str, description: str) -> str:
    return (
        f"{PIN_IT}?url={quote(link, safe='')}&media={quote(image, safe='')}"
        f"&description={quote(description, safe='')}"
    )
