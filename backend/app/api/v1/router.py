from fastapi import APIRouter

from app.api.v1.routes import health, portfolio, products, triggers

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(triggers.router)
api_router.include_router(portfolio.router)
api_router.include_router(products.router)
