from fastapi import APIRouter

from app.api.health import router as health_router
from app.assets.router import router as assets_router
from app.auth.router import router as auth_router
from app.costs.router import router as costs_router
from app.projects.router import router as projects_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(projects_router)
api_router.include_router(assets_router)
api_router.include_router(costs_router)
