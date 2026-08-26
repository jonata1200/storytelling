import asyncio
import shutil
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from app.config.settings import Settings
from app.providers import browser_bridge


def _prepare(monkeypatch: Any, tmp_path: Path, popen: Mock) -> Path:
    monkeypatch.setattr(browser_bridge.subprocess, "Popen", popen)
    monkeypatch.setattr(browser_bridge, "browser_bridge_script", lambda: tmp_path / "bridge.mjs")
    (tmp_path / "authorize-meta-browser.ps1").touch()
    browser_bridge._authorization_processes.clear()
    return tmp_path / "profile"


def test_authorization_console_reuses_running_process(monkeypatch: Any, tmp_path: Path) -> None:
    process = Mock()
    process.poll.return_value = None
    popen = Mock(return_value=process)
    profile = _prepare(monkeypatch, tmp_path, popen)

    assert browser_bridge.launch_authorization_console(profile, "image") is True
    assert browser_bridge.launch_authorization_console(profile, "vibes") is False
    popen.assert_called_once()


def test_authorization_console_restarts_finished_process(monkeypatch: Any, tmp_path: Path) -> None:
    finished = Mock()
    finished.poll.return_value = 0
    popen = Mock(side_effect=[finished, Mock()])
    profile = _prepare(monkeypatch, tmp_path, popen)

    assert browser_bridge.launch_authorization_console(profile, "image") is True
    assert browser_bridge.launch_authorization_console(profile, "image") is True
    assert popen.call_count == 2


def test_image_and_video_keep_independent_browser_profiles() -> None:
    settings = Settings(_env_file=None)

    assert settings.vibes_browser_profile_path != settings.meta_browser_profile_path
    assert settings.vibes_browser_profile_path.name == "vibes"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node não instalado")
async def test_browser_bridge_reuses_same_node_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = tmp_path / "bridge-server.mjs"
    script_source = """
import readline from 'node:readline';
import process from 'node:process';
let count = 0;
const lines = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
for await (const line of lines) {
  const request = JSON.parse(line);
  count += 1;
  process.stdout.write(JSON.stringify({
    id: request.id,
    result: { pid: process.pid, count },
  }) + '\\n');
}
""".strip()
    await asyncio.to_thread(
        script.write_text,
        script_source,
        encoding="utf-8",
    )
    monkeypatch.setattr(browser_bridge, "browser_bridge_script", lambda: script)
    profile = tmp_path / "profile"
    payload = {"profilePath": str(profile)}

    first = await browser_bridge.run_browser_bridge("status", payload, timeout_seconds=5)
    second = await browser_bridge.run_browser_bridge("status", payload, timeout_seconds=5)

    assert first["pid"] == second["pid"]
    assert (first["count"], second["count"]) == (1, 2)

    resolved_profile = await asyncio.to_thread(profile.resolve)
    key = (asyncio.get_running_loop(), resolved_profile)
    client = browser_bridge._persistent_bridge_clients.pop(key)
    await client.stop()


def test_user_closed_browser_error_is_typed_from_marker() -> None:
    client = browser_bridge._PersistentBridgeClient(Path("profile"))

    typed = client._bridge_error(
        "user-closed-browser: o navegador foi fechado manualmente. Fechado em 2026-09-05."
    )
    generic = client._bridge_error("Automação de browser excedeu 60s")

    assert isinstance(typed, browser_bridge.UserClosedBrowserError)
    assert isinstance(typed, browser_bridge.BrowserBridgeError)
    assert not isinstance(generic, browser_bridge.UserClosedBrowserError)


def test_visual_reference_user_error_maps_user_closed_browser() -> None:
    from app.ui.workspace.visual_bible_area import _visual_reference_user_error

    mapped = _visual_reference_user_error(
        "user-closed-browser: o navegador foi fechado manualmente. Fechado em 2026-09-05."
    )

    assert "fechado manualmente" in mapped
    assert "Autorizar Meta" in mapped
    # Erros sem o marcador seguem intocados.
    raw = "Falha genérica de automação"
    assert _visual_reference_user_error(raw) == raw
