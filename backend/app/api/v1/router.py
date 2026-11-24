from fastapi import APIRouter

from app.api.v1.routes import (
    auth,
    health,
    links,
    parameters,
    pins,
    portfolio,
    products,
    publishing,
    triggers,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(triggers.router)
api_router.include_router(portfolio.router)
api_router.include_router(products.router)
api_router.include_router(publishing.router)
api_router.include_router(parameters.router)
api_router.include_router(links.router)
api_router.include_router(pins.router)
