"""Imagem do pin: foto do produto num quadro vertical 2:3, servida pelo nosso domínio.

Por que existe: o Pinterest distribui melhor o formato vertical, e buscar a foto direto do
CDN do marketplace falha quando ele bloqueia ou troca o endereço. Servida daqui, a URL é
estável — e é a mesma que a publicação pela API vai usar quando o acesso Standard sair.

Só busca imagem cujo endereço está no banco (nunca um parâmetro da requisição) e cujo
domínio é do marketplace: sem isso o endpoint viraria um proxy aberto para qualquer URL.
"""

import io
from functools import lru_cache
from urllib.parse import urlparse

import httpx
from PIL import Image, ImageOps

CANVAS = (1000, 1500)
MAX_BYTES = 8_000_000
ALLOWED_DOMAINS = ("shopee.com.br", "shopee.com", "susercontent.com", "shopeemobile.com")


class ImageUnavailable(Exception):
    """A foto não pôde ser obtida ou lida."""


def is_allowed(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(
        host == domain or host.endswith(f".{domain}") for domain in ALLOWED_DOMAINS
    )


def fetch(url: str) -> bytes:
    if not is_allowed(url):
        raise ImageUnavailable("domínio da imagem não permitido")
    try:
        # Sem seguir redirect: um redirect poderia levar a um destino fora da lista.
        response = httpx.get(url, timeout=10.0, follow_redirects=False)
    except httpx.HTTPError as exc:
        raise ImageUnavailable(f"falha ao buscar a imagem: {exc}") from exc
    if response.status_code != 200:
        raise ImageUnavailable(f"o CDN respondeu {response.status_code}")
    if len(response.content) > MAX_BYTES:
        raise ImageUnavailable("imagem grande demais")
    return response.content


def render(raw: bytes) -> bytes:
    """Foto inteira (sem cortar o produto), centralizada em fundo branco 1000x1500."""
    try:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(raw)))
        if image.mode in ("RGBA", "LA", "P"):
            image = image.convert("RGBA")
            flat = Image.new("RGB", image.size, "white")
            flat.paste(image, mask=image.getchannel("A"))
            image = flat
        else:
            image = image.convert("RGB")
    except Exception as exc:  # Pillow levanta vários tipos para arquivo inválido
        raise ImageUnavailable(f"imagem ilegível: {exc}") from exc

    fitted = ImageOps.contain(image, CANVAS)
    canvas = Image.new("RGB", CANVAS, "white")
    canvas.paste(fitted, ((CANVAS[0] - fitted.width) // 2, (CANVAS[1] - fitted.height) // 2))
    out = io.BytesIO()
    canvas.save(out, format="JPEG", quality=88, optimize=True)
    return out.getvalue()


@lru_cache(maxsize=64)
def pin_image(url: str) -> bytes:
    return render(fetch(url))
