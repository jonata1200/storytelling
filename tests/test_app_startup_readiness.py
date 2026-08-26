from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.factory import create_app
from app.observability import service as observability_service
from app.observability.schemas import ReadinessComponentRead


def test_create_app_without_ui_starts_api_routes() -> None:
    app = create_app(include_ui=False)
    client = TestClient(app)

    assert app.title == "Storytelling"
    assert len(app.routes) >= 2
    response = client.get("/static/widget.js")
    assert response.status_code == 200
    assert response.text == ""
    assert response.headers["content-type"].startswith("application/javascript")


class _ReadySession:
    async def execute(self, _statement: Any) -> None:
        return None


@pytest.mark.asyncio
async def test_readiness_dashboard_degrades_without_redis_and_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def degraded_redis(name: str, _url: str) -> ReadinessComponentRead:
        return ReadinessComponentRead(
            name=name,
            status="degraded",
            message=f"{name} indisponivel no teste",
        )

    monkeypatch.setattr(observability_service, "_redis_check", degraded_redis)
    monkeypatch.setattr(observability_service, "resolve_ffmpeg_path", lambda _configured=None: None)

    dashboard = await observability_service.readiness_dashboard(
        _ReadySession(),  # type: ignore[arg-type]
        Settings(ai_provider="ollama_cloud", ollama_cloud_api_key=None),
    )

    statuses = {component.name: component.status for component in dashboard.components}
    assert dashboard.status == "degraded"
    assert statuses["database"] == "ready"
    assert statuses["redis"] == "degraded"
    assert "worker" not in statuses
    assert statuses["text_provider"] == "degraded"
    assert statuses["video_provider"] == "degraded"
