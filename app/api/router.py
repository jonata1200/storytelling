from fastapi import APIRouter

from app.api.health import router as health_router
from app.assets.router import router as assets_router
from app.auth.router import router as auth_router
from app.costs.router import router as costs_router
from app.finalization.router import router as finalization_router
from app.projects.router import router as projects_router
from app.quality.router import router as quality_router
from app.quality.router import security_router as quality_security_router
from app.storyboards.router import router as storyboards_router
from app.storytelling.router import router as storytelling_router
from app.video_generation.router import router as video_generation_router
from app.visual_bible.router import router as visual_bible_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(projects_router)
api_router.include_router(assets_router)
api_router.include_router(costs_router)
api_router.include_router(storytelling_router)
api_router.include_router(visual_bible_router)
api_router.include_router(storyboards_router)
api_router.include_router(video_generation_router)
api_router.include_router(finalization_router)
api_router.include_router(quality_router)
api_router.include_router(quality_security_router)
