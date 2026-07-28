import asyncio
import json
import urllib.request

from app.config.model_policy import is_mock_model, is_openrouter_free_model
from app.config.runtime_preferences import save_runtime_preferences
from app.config.settings import get_settings


def save_preferences(values: dict[str, str]) -> None:
    save_runtime_preferences(values)
    get_settings.cache_clear()


async def openrouter_models(api_key: str, kind: str) -> list[dict[str, str]]:
    return await asyncio.to_thread(_fetch_models, api_key, kind)


def _fetch_models(api_key: str, kind: str) -> list[dict[str, str]]:
    settings = get_settings()
    endpoint = "videos/models" if kind == "video" else "models"
    url = f"{settings.openrouter_base_url.rstrip('/')}/{endpoint}"
    if kind == "image":
        url += "?output_modalities=image"
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return [
        {"id": str(item["id"]), "name": str(item.get("name") or item["id"])}
        for item in payload.get("data", [])
        if item.get("id")
        and not is_openrouter_free_model(item.get("id"))
        and not is_mock_model(item.get("id"))
    ]
