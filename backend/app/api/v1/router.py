from fastapi import APIRouter

from app.api.v1.routes import (
    health,
    links,
    parameters,
    portfolio,
    products,
    publishing,
    triggers,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(triggers.router)
api_router.include_router(portfolio.router)
api_router.include_router(products.router)
api_router.include_router(publishing.router)
api_router.include_router(parameters.router)
api_router.include_router(links.router)
