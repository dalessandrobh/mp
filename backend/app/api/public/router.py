"""Rotas públicas: sem API key e sem JWT, porque quem as acessa é o visitante.

Ficam fora do `api_prefix` de propósito — `/go/{sub_id}` entra em post e em pin, e
precisa ser curto. Nenhuma delas lê ou escreve dado de decisão: o redirect só grava
clique, e a página só lê produto que já está publicado.
"""

from fastapi import APIRouter

from app.api.public.routes import catalog, images, privacy, redirect

public_router = APIRouter()
public_router.include_router(redirect.router)
public_router.include_router(catalog.router)
public_router.include_router(privacy.router)
public_router.include_router(images.router)
