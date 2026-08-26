import asyncio
import json
import logging
import shutil
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path
from typing import Any
from uuid import uuid4


class BrowserBridgeError(RuntimeError):
    pass


class UserClosedBrowserError(BrowserBridgeError):
    """O usuário fechou manualmente a janela do navegador da automação.

    O fechamento manual é DEFINITIVO: a automação não reabre o navegador por
    conta própria. Quem decide retomar é o usuário (Autorizar Meta/Vibes ou
    disparar uma nova geração) — handlers de job devem tratar este erro como
    terminal, sem retry automático.
    """


logger = logging.getLogger(__name__)


class _PersistentBridgeClient:
    """Cliente JSON-lines para uma ponte Node persistente por perfil de navegador."""

    def __init__(self, profile_path: Path) -> None:
        self.profile_path = profile_path
        self.process: asyncio.subprocess.Process | None = None
        self._start_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._stderr_lines: deque[str] = deque(maxlen=20)

    async def _ensure_started(self, node: str, script: Path) -> asyncio.subprocess.Process:
        async with self._start_lock:
            if self.process is not None and self.process.returncode is None:
                return self.process
            process = await asyncio.create_subprocess_exec(
                node,
                str(script),
                "serve",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self.process = process
            self._stderr_lines.clear()
            self._reader_task = asyncio.create_task(self._read_responses(process))
            self._stderr_task = asyncio.create_task(self._read_stderr(process))
            return process

    async def _read_responses(self, process: asyncio.subprocess.Process) -> None:
        # Qual-04: assert some com python -O — invariantes de pipeline usam
        # exceção explícita para que a falha continue verificada em runtime.
        if process.stdout is None:
            raise RuntimeError("Browser bridge sem stdout para ler respostas.")
        try:
            while line := await process.stdout.readline():
                try:
                    response = json.loads(line.decode("utf-8", errors="replace"))
                    request_id = str(response.get("id") or "")
                except (json.JSONDecodeError, AttributeError):
                    logger.warning("browser_bridge_invalid_response")
                    continue
                future = self._pending.pop(request_id, None)
                if future is None or future.done():
                    continue
                error = str(response.get("error") or "").strip()
                if error:
                    future.set_exception(self._bridge_error(error))
                    continue
                result = response.get("result")
                if not isinstance(result, dict):
                    future.set_exception(
                        BrowserBridgeError("Backend Playwright retornou resposta inesperada")
                    )
                    continue
                future.set_result(result)
        finally:
            if self.process is process:
                self.process = None
            message = self._bridge_exit_message(process)
            for future in list(self._pending.values()):
                if not future.done():
                    future.set_exception(BrowserBridgeError(message))
            self._pending.clear()

    async def _read_stderr(self, process: asyncio.subprocess.Process) -> None:
        if process.stderr is None:
            raise RuntimeError("Browser bridge sem stderr para capturar diagnósticos.")
        while line := await process.stderr.readline():
            text = line.decode("utf-8", errors="replace").strip()
            if text:
                self._stderr_lines.append(text)
                logger.warning(
                    "browser_bridge_stderr profile=%s message=%s", self.profile_path, text
                )

    def _bridge_exit_message(self, process: asyncio.subprocess.Process) -> str:
        detail = self._stderr_lines[-1] if self._stderr_lines else ""
        if detail:
            return detail
        code = process.returncode
        return f"Automação de browser encerrou inesperadamente (código {code})"

    async def request(
        self,
        node: str,
        script: Path,
        action: str,
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        process = await self._ensure_started(node, script)
        if process.stdin is None:
            raise BrowserBridgeError("Ponte Playwright iniciou sem canal de entrada")
        request_id = str(uuid4())
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        message = json.dumps(
            {"id": request_id, "action": action, "payload": payload}, ensure_ascii=False
        ).encode("utf-8") + b"\n"
        try:
            async with self._write_lock:
                process.stdin.write(message)
                await process.stdin.drain()
            return await asyncio.wait_for(future, timeout=max(1.0, timeout_seconds))
        except TimeoutError:
            self._pending.pop(request_id, None)
            await self.stop()
            raise BrowserBridgeError(
                f"Automação de browser excedeu {timeout_seconds:.0f}s"
            ) from None
        except (BrokenPipeError, ConnectionError) as exc:
            self._pending.pop(request_id, None)
            await self.stop()
            raise BrowserBridgeError("Ponte Playwright perdeu a conexão") from exc

    def _bridge_error(self, error: str) -> BrowserBridgeError:
        # Fechamento manual do navegador vira exceção tipada: os handlers de
        # job a tratam como terminal (sem retry automático que reabra o
        # navegador contra a vontade do usuário).
        if "user-closed-browser" in error:
            return UserClosedBrowserError(error)
        return BrowserBridgeError(error)

    async def stop(self) -> None:
        async with self._start_lock:
            process = self.process
            self.process = None
            if process is None or process.returncode is not None:
                return
            if process.stdin is not None:
                process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                process.kill()
                await process.wait()


_persistent_bridge_clients: dict[
    tuple[asyncio.AbstractEventLoop, Path], _PersistentBridgeClient
] = {}


_authorization_processes: dict[Path, subprocess.Popen[Any]] = {}
_authorization_processes_lock = threading.Lock()


def browser_bridge_script() -> Path:
    return Path(__file__).resolve().parents[2] / "scripts" / "meta_browser_bridge.mjs"


def browser_bridge_available() -> bool:
    return shutil.which("node") is not None and browser_bridge_script().is_file()


async def run_browser_bridge(
    action: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    node = shutil.which("node")
    script = browser_bridge_script()
    if node is None or not script.is_file():
        raise BrowserBridgeError(
            "Backend Playwright local indisponível. Instale as dependências Node com npm ci."
        )
    raw_profile_path = payload.get("profilePath")
    if not raw_profile_path:
        raise BrowserBridgeError("Perfil de navegador não informado para a automação")
    profile_path = await asyncio.to_thread(
        lambda: Path(str(raw_profile_path)).resolve(strict=False)
    )
    loop_key = asyncio.get_running_loop()
    client_key = (loop_key, profile_path)
    client = _persistent_bridge_clients.get(client_key)
    if client is None:
        client = _PersistentBridgeClient(profile_path)
        _persistent_bridge_clients[client_key] = client
    return await client.request(node, script, action, payload, timeout_seconds)


async def authorize_meta_profile(profile_path: Path, destination: str) -> None:
    await run_browser_bridge(
        "authorize",
        {"profilePath": str(profile_path), "destination": destination},
        timeout_seconds=600,
    )


async def resume_after_user_browser_close(profile_path: Path) -> bool:
    """Limpa o estado de fechamento manual do navegador de um perfil.

    Chamado quando o usuário toma uma ação explícita de retomada (Autorizar
    Meta/Vibes ou nova geração). Retorna True se havia um flag a limpar.
    """
    await run_browser_bridge(
        "resume-after-close",
        {"profilePath": str(profile_path)},
        timeout_seconds=30,
    )
    return True


def launch_authorization_console(profile_path: Path, destination: str) -> bool:
    """Start at most one authorization console per persistent browser profile."""
    script = browser_bridge_script().with_name("authorize-meta-browser.ps1")
    if not script.is_file():
        raise BrowserBridgeError("Script de autorização Meta não encontrado.")
    target = "vibes" if destination == "vibes" else "image"
    resolved_profile_path = profile_path.resolve(strict=False)
    command = [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-Target",
        target,
        "-ProfilePath",
        str(resolved_profile_path),
    ]
    creation_flags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
    with _authorization_processes_lock:
        existing = _authorization_processes.get(resolved_profile_path)
        if existing is not None and existing.poll() is None:
            return False
        process = subprocess.Popen(  # noqa: S603
            command,
            cwd=browser_bridge_script().parents[1],
            creationflags=creation_flags,
            close_fds=True,
        )
        _authorization_processes[resolved_profile_path] = process
    return True
