from fastapi import APIRouter, Depends

from app.api.health import router as health_router
from app.assets.router import router as assets_router
from app.auth.dependencies import require_authenticated_user
from app.auth.router import router as auth_router
from app.costs.router import router as costs_router
from app.finalization.router import router as finalization_router
from app.jobs.router import router as jobs_router
from app.projects.router import router as projects_router
from app.quality.router import router as quality_router
from app.quality.router import security_router as quality_security_router
from app.storyboards.router import router as storyboards_router
from app.storytelling.router import router as storytelling_router
from app.video_generation.router import router as video_generation_router
from app.visual_bible.router import router as visual_bible_router

api_router = APIRouter(prefix="/api/v1")
private_api_router = APIRouter(dependencies=[Depends(require_authenticated_user)])

api_router.include_router(health_router)
private_api_router.include_router(auth_router)
private_api_router.include_router(projects_router)
private_api_router.include_router(assets_router)
private_api_router.include_router(costs_router)
private_api_router.include_router(storytelling_router)
private_api_router.include_router(visual_bible_router)
private_api_router.include_router(storyboards_router)
private_api_router.include_router(video_generation_router)
private_api_router.include_router(finalization_router)
private_api_router.include_router(quality_router)
private_api_router.include_router(quality_security_router)
private_api_router.include_router(jobs_router)
api_router.include_router(private_api_router)
