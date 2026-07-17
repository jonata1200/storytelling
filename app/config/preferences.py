import asyncio
import json
import urllib.request
from pathlib import Path

from app.config.settings import get_settings


def save_preferences(values: dict[str, str], env_path: Path = Path(".env")) -> None:
    existing = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    normalized = {key.upper(): value for key, value in values.items()}
    output: list[str] = []
    found: set[str] = set()
    for line in existing:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in normalized:
            output.append(f"{key}={normalized[key]}")
            found.add(key)
        else:
            output.append(line)
    for key, value in normalized.items():
        if key not in found:
            output.append(f"{key}={value}")
    env_path.write_text("\n".join(output) + "\n", encoding="utf-8")
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
    ]
