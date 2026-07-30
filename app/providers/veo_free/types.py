from typing import Any, Literal

from pydantic import BaseModel, Field

VeoFreeSessionStatus = Literal["connected", "expired", "blocked", "unknown"]


class VeoFreeCookie(BaseModel):
    name: str = Field(min_length=1)
    value: str = Field(min_length=1, repr=False)
    domain: str | None = None
    path: str | None = "/"
    expires: float | int | None = None
    httpOnly: bool | None = None
    secure: bool | None = None
    sameSite: str | None = None


class VeoFreeSessionBundle(BaseModel):
    cookies: list[VeoFreeCookie] = Field(default_factory=list)
    user_agent: str | None = None
    csrf_token: str | None = Field(default=None, repr=False)
    local_storage: dict[str, Any] = Field(default_factory=dict, repr=False)
    saved_at: str | None = None
    source: str = "manual"


class VeoFreeSessionValidation(BaseModel):
    status: VeoFreeSessionStatus
    message: str
    details: dict[str, str] = Field(default_factory=dict)
