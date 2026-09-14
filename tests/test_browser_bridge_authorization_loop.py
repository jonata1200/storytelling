"""Testes da proteção contra múltiplas janelas na autorização do browser.

Quando o usuário clica "Autorizar Vibes" na página de Ajustes, o sistema
abre um Chrome dedicado via PowerShell (Start-Process --user-data-dir=X).
Se já existe um Chrome usando o mesmo user-data-dir (Playwright zombie
de uma geração anterior, ou Chrome que ficou aberto após autorização
prévia), abrir nova instância com o mesmo perfil gera conflito:
Chrome abre em modo "Recuperando sessão", fica instável, e quando
morre reabre uma nova janela — o usuário vê "não parar de abrir
novas janelas".

Correção: `launch_authorization_console` deve detectar se já existe
Chrome usando o profile_path e, em caso afirmativo, não abrir nova
instância. Retornar False.
"""

# ruff: noqa: F401, I001

from pathlib import Path
from typing import Any

import pytest

from app.providers import browser_bridge


@pytest.fixture
def fake_profile(tmp_path: Path) -> Path:
    profile = tmp_path / "vibes-profile"
    profile.mkdir()
    return profile


def _chrome_proc(command_line: str, pid: int = 1234) -> dict[str, Any]:
    return {"ProcessId": pid, "CommandLine": command_line}


def test_launch_authorization_console_skips_when_chrome_already_uses_profile(
    monkeypatch: pytest.MonkeyPatch,
    fake_profile: Path,
) -> None:
    """Se já há Chrome rodando com o mesmo user-data-dir, o launch
    não deve abrir nova instância."""

    popen_calls: list[Any] = []

    class FakePopen:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            popen_calls.append((args, kwargs))

        def poll(self) -> int | None:
            return None

    monkeypatch.setattr(browser_bridge.subprocess, "Popen", FakePopen)

    fake_running = [
        _chrome_proc(
            f"chrome.exe --user-data-dir={fake_profile.resolve()} --type=renderer ..."
        )
    ]

    monkeypatch.setattr(
        browser_bridge, "_iter_chrome_processes", lambda: fake_running
    )

    result = browser_bridge.launch_authorization_console(fake_profile)

    assert result is False, (
        "launch_authorization_console deve retornar False (no-op) quando já "
        "existe Chrome usando o mesmo user-data-dir."
    )
    assert popen_calls == [], (
        f"launch_authorization_console não deve iniciar novo PowerShell quando "
        f"há Chrome concorrente. Popen foi chamado {len(popen_calls)} vezes."
    )


def test_launch_authorization_console_opens_when_no_chrome_running(
    monkeypatch: pytest.MonkeyPatch,
    fake_profile: Path,
) -> None:
    """Quando NÃO há Chrome usando o user-data-dir, o launch abre
    normalmente (caminho feliz atual)."""

    popen_calls: list[Any] = []

    class FakePopen:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            popen_calls.append((args, kwargs))

        def poll(self) -> int | None:
            return None

    monkeypatch.setattr(browser_bridge.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(browser_bridge, "_iter_chrome_processes", lambda: [])

    result = browser_bridge.launch_authorization_console(fake_profile)

    assert result is True
    assert len(popen_calls) == 1


def test_launch_authorization_console_ignores_unrelated_chrome_processes(
    monkeypatch: pytest.MonkeyPatch,
    fake_profile: Path,
) -> None:
    """Chrome rodando com OUTRO user-data-dir não bloqueia a abertura."""

    fake_running = [
        _chrome_proc(
            "chrome.exe --user-data-dir=C:\\Other\\Profile --type=renderer"
        ),
        _chrome_proc("chrome.exe --no-process-singleton-dialog"),
    ]

    class FakePopen:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def poll(self) -> int | None:
            return None

    monkeypatch.setattr(browser_bridge.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(
        browser_bridge, "_iter_chrome_processes", lambda: fake_running
    )

    result = browser_bridge.launch_authorization_console(fake_profile)

    assert result is True, (
        "Chrome rodando com outro user-data-dir não deve bloquear a abertura."
    )


def test_chrome_uses_profile_detection_normalizes_paths(
    monkeypatch: pytest.MonkeyPatch,
    fake_profile: Path,
) -> None:
    """A detecção deve comparar caminhos normalizados (resolve) — slash
    style e case-insensitivity não devem causar falso negativo."""

    upper_path = str(fake_profile).replace("\\", "/").upper()
    fake_running = [
        _chrome_proc(f"chrome.exe --user-data-dir={upper_path} --foo")
    ]

    monkeypatch.setattr(
        browser_bridge, "_iter_chrome_processes", lambda: fake_running
    )

    detected = browser_bridge._chrome_uses_profile(  # noqa: SLF001
        fake_profile.resolve(), fake_running
    )

    assert detected is True


def test_chrome_uses_profile_detection_handles_quoted_path(
    monkeypatch: pytest.MonkeyPatch,
    fake_profile: Path,
) -> None:
    """Chrome passa --user-data-dir entre aspas quando há espaços no
    caminho — o parser deve extrair o valor corretamente."""

    quoted_path = f'"{fake_profile.resolve()}"'
    fake_running = [
        _chrome_proc(f"chrome.exe --user-data-dir={quoted_path} --foo")
    ]

    monkeypatch.setattr(
        browser_bridge, "_iter_chrome_processes", lambda: fake_running
    )

    detected = browser_bridge._chrome_uses_profile(  # noqa: SLF001
        fake_profile.resolve(), fake_running
    )

    assert detected is True


def test_chrome_uses_profile_detection_returns_false_on_empty(
    monkeypatch: pytest.MonkeyPatch,
    fake_profile: Path,
) -> None:
    """Sem Chrome rodando, retorna False (caminho normal)."""
    monkeypatch.setattr(browser_bridge, "_iter_chrome_processes", lambda: [])

    detected = browser_bridge._chrome_uses_profile(  # noqa: SLF001
        fake_profile.resolve()
    )

    assert detected is False


def test_iter_chrome_processes_returns_empty_on_non_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Em plataformas não-Windows, retorna [] (não tenta chamar
    PowerShell)."""
    monkeypatch.setattr(browser_bridge.sys, "platform", "linux")
    assert browser_bridge._iter_chrome_processes() == []  # noqa: SLF001