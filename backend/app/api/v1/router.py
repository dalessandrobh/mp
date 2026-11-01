from fastapi import APIRouter

from app.api.v1.routes import health, triggers

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(triggers.router)
