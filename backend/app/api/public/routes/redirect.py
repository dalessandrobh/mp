"""Redirect público `/go/{sub_id}`: conta o clique e manda para o link de afiliado.

Regras que não se negociam aqui:

* **O clique nunca custa a venda.** Gravar é best-effort: qualquer falha ao registrar é
  logada e o visitante segue para o produto do mesmo jeito. Analytics perdido se recupera;
  venda perdida, não.
* **O destino sai do banco.** `sub_id` desconhecido ou revogado é 404, nunca redirect.
  Aceitar URL da requisição transformaria o nosso domínio em open redirect.
* **Nada disso é indexável.** `X-Robots-Tag: noindex` em toda resposta: os Termos de
  Afiliados 4.3(k) proíbem indexar URL que carregue o ID de afiliado, e o destino daqui
  carrega.
* **302, nunca 301.** Redirect permanente fica no cache do navegador e o clique seguinte
  não chega a nós: a contagem morreria em silêncio.
"""

import logging

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.services import click_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["public"])

NO_INDEX = {
    "X-Robots-Tag": "noindex, nofollow, noarchive",
    "Cache-Control": "no-store, max-age=0",
    "Referrer-Policy": "no-referrer",
}


def client_ip(request: Request) -> str | None:
    """Atrás do Traefik o IP real vem no X-Forwarded-For; o primeiro item é o cliente."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else None


@router.get("/go/{sub_id}", include_in_schema=False)
def go(
    sub_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    link = click_service.find_link(db, sub_id)
    if link is None:
        logger.info("click_unknown_sub_id", extra={"sub_id": sub_id[:64]})
        return Response(status_code=404, content="Link não encontrado", headers=NO_INDEX)

    destination = link.short_url or link.raw_url

    try:
        record = click_service.record_click(
            db,
            link,
            ip=client_ip(request),
            user_agent=request.headers.get("user-agent"),
            referrer=request.headers.get("referer"),
            salt=settings.click_salt,
        )
        logger.info(
            "click_recorded",
            extra={
                "product_id": record.product_id,
                "channel": record.channel,
                "is_bot": record.is_bot,
                "is_unique": record.is_unique,
            },
        )
    except Exception:
        # O visitante não paga pelo nosso erro de medição.
        db.rollback()
        logger.exception("click_record_failed", extra={"sub_id": sub_id[:64]})

    return RedirectResponse(url=destination, status_code=302, headers=NO_INDEX)


@router.get("/robots.txt", include_in_schema=False)
def robots() -> Response:
    """Reforço do `noindex`: o buscador obediente nem chega a pedir a página."""
    body = "User-agent: *\nDisallow: /go/\nDisallow: /l\nDisallow: /biopinterest\nDisallow: /api/\n"
    return Response(content=body, media_type="text/plain")
