from fastapi import APIRouter, Depends

from app.auth.dependencies import require_basic_auth

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me")
async def me(username: str = Depends(require_basic_auth)) -> dict[str, str]:
    return {"username": username}
