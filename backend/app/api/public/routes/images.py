"""Imagem do pin em `/img/{creative_id}.jpg`, pública: quem a busca é o Pinterest.

A URL de origem sai do banco, nunca da requisição, e só vale para criativo de pin: o
endpoint não é um proxy de imagem genérico.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.catalog import Product
from app.models.content import Creative
from app.services import content_service, pin_image_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["public"])


@router.get("/img/{creative_id}.jpg", include_in_schema=False)
def pin_image(creative_id: int, db: Session = Depends(get_db)) -> Response:
    creative = db.get(Creative, creative_id)
    product = db.get(Product, creative.product_id) if creative else None
    if (
        creative is None
        or creative.format != content_service.FORMAT
        or product is None
        or not product.image_url
    ):
        raise HTTPException(status_code=404, detail="imagem não encontrada")
    try:
        body = pin_image_service.pin_image(product.image_url)
    except pin_image_service.ImageUnavailable as exc:
        logger.warning("imagem do criativo %s indisponível: %s", creative_id, exc)
        raise HTTPException(status_code=404, detail="imagem indisponível") from exc
    return Response(
        content=body,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )
