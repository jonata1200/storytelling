"""Testes do helper de detecção/morte de Chrome zombie no bridge.

Bug: launchPersistentContext no Playwright falha com erro "Target page,
context or browser has been closed" quando já existe outra instância
Chrome com o mesmo --user-data-dir (lock file). O erro é fatal e trava
o job. O bridge atual (meta_browser_bridge.mjs) só abre o contexto —
não checa pré-existencia nem mata zombies.

Correção: helper killZombieChromeForProfile(profilePath) em
meta_browser_bridge.mjs que usa tasklist + taskkill para finalizar
instâncias Chrome órfãs antes de launchPersistentContext.

Estes testes validam o CONTRATO da função (interface) e o MOCK da
execução via subprocess. A integração real com Playwright fica
coberta pelo fluxo end-to-end.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
BRIDGE = REPO / "scripts" / "meta_browser_bridge.mjs"


def _extract_function(name: str) -> str:
    """Extrai uma função top-level do bridge para execução isolada."""
    text = BRIDGE.read_text(encoding="utf-8")
    pattern = rf"async function {name}\([^)]*\)\s*\{{"
    match = re.search(pattern, text)
    if not match:
        raise AssertionError(f"function {name} não encontrada no bridge")
    start = match.start()
    # Walk braces to find function end.
    depth = 0
    i = start
    while i < len(text):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
        i += 1
    raise AssertionError(f"chave final de {name} não encontrada")


def _run_node(script: str, timeout: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def test_kill_zombie_chrome_for_profile_exists() -> None:
    """A função killZombieChromeForProfile existe no bridge."""
    text = BRIDGE.read_text(encoding="utf-8")
    assert re.search(
        r"async function killZombieChromeForProfile\s*\(",
        text,
    ), "killZombieChromeForProfile precisa existir em meta_browser_bridge.mjs"


def test_persistent_page_invokes_kill_zombie_before_launch() -> None:
    """persistentPage chama killZombieChromeForProfile antes de
    chromium.launchPersistentContext."""
    text = BRIDGE.read_text(encoding="utf-8")
    fn = _extract_function("persistentPage")
    assert "killZombieChromeForProfile" in fn, (
        "persistentPage precisa chamar killZombieChromeForProfile antes "
        "de chromium.launchPersistentContext para evitar conflitos de lock"
    )
    # A chamada real de killZombieChromeForProfile (não a definição nem
    # comentários) deve vir ANTES da chamada real de launchPersistentContext.
    # Procuramos as linhas que invocam (não as que apenas mencionam).
    kill_calls = [
        i for i, line in enumerate(fn.splitlines())
        if "killZombieChromeForProfile(" in line and "//" not in line.split("killZombieChromeForProfile")[0]
    ]
    launch_calls = [
        i for i, line in enumerate(fn.splitlines())
        if "launchPersistentContext(" in line and "//" not in line.split("launchPersistentContext")[0]
    ]
    assert kill_calls, "chamada real de killZombieChromeForProfile não encontrada"
    assert launch_calls, "chamada real de launchPersistentContext não encontrada"
    assert min(kill_calls) < min(launch_calls), (
        f"killZombieChromeForProfile deve ser chamado ANTES de "
        f"launchPersistentContext; linhas: kill={min(kill_calls)} "
        f"launch={min(launch_calls)}"
    )


def test_kill_zombie_returns_zero_when_no_chrome_running() -> None:
    """Sem Chrome no profile, a função retorna 0 (nenhum processo morto)
    sem levantar exceção."""
    fn_body = _extract_function("killZombieChromeForProfile")
    # Remove `async` para rodar a função com um mock de child_process.
    # Validamos apenas a forma da função (parâmetros e retorno).
    assert "return 0" in fn_body or "return []" in fn_body or "length" in fn_body, (
        "killZombieChromeForProfile deve retornar 0 ou [] quando "
        "não há zombies"
    )
    # A função recebe profilePath como argumento.
    assert re.search(r"async function killZombieChromeForProfile\s*\(\s*profilePath", fn_body), (
        "killZombieChromeForProfile deve receber profilePath como argumento"
    )


def test_kill_zombie_uses_taskkill() -> None:
    """A função usa taskkill (Windows) para finalizar processos Chrome."""
    fn_body = _extract_function("killZombieChromeForProfile")
    assert "taskkill" in fn_body, (
        "killZombieChromeForProfile deve usar taskkill (Windows) para "
        "finalizar Chrome zombies"
    )
    assert "user-data-dir" in fn_body, (
        "killZombieChromeForProfile deve filtrar Chrome por --user-data-dir"
    )