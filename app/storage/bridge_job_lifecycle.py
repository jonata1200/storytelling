"""Ciclo de vida dos artefatos intermediários do browser (ARQ-02).

Os jobs do bridge de vídeo acumulam por diretório de job: variantes baixadas
(`result-*.mp4`), frames enviados (`start-frame.png`), o checkpoint
`job-state.json` e screenshots de diagnóstico. O vídeo final é copiado para o
Asset e os intermediários ficam. Frames de QA (`<video>.qa/<segment>/`) idem.

Este módulo concentra as regras de limpeza (puras, testáveis):
- jobs com checkpoint em estado terminal E sem atividade há RETENTION_DAYS
  são removidos por completo;
- frames `.qa` de segmentos cujo QA terminou são removidos;
- screenshots de diagnóstico são limitados aos KEEP_RECENT_DIAGNOSTICS mais
  recentes, em todo o storage.
"""

import logging
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Jobs terminados são mantidos por N dias para diagnóstico; depois, o diretório
# inteiro (checkpoint + variantes + frames) pode ser removido.
BRIDGE_JOB_TERMINAL_RETENTION_DAYS = 7
DIAGNOSTIC_KEEP_RECENT = 20
_DIAGNOSTIC_PREFIXES = (
    "meta-timeout-",
    "meta-refusal-",
    "editor-timeout-",
    "upload-error-",
    "poll-error-",
)
_CHECKPOINT_NAME = "job-state.json"
_TERMINAL_STATUSES = {"completed", "failed"}
_JOB_DIRNAME_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def _checkpoint_age_days(path: Path) -> float | None:
    try:
        return max(0.0, (time.time() - path.stat().st_mtime) / 86400)
    except OSError:
        return None


def _checkpoint_status(path: Path) -> str | None:
    try:
        import json as _json

        data = _json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    status = data.get("status") if isinstance(data, dict) else None
    return str(status).lower() if isinstance(status, str) else None


@dataclass
class BridgeJobCleanupReport:
    removed_job_dirs: list[str] = field(default_factory=list)
    removed_bytes: int = 0
    kept_pending_jobs: int = 0
    removed_qa_dirs: list[str] = field(default_factory=list)
    removed_diagnostics: list[str] = field(default_factory=list)


def _is_terminal_expired_job_dir(job_dir: Path) -> bool:
    checkpoint = job_dir / _CHECKPOINT_NAME
    if not checkpoint.is_file():
        return False
    status = _checkpoint_status(checkpoint)
    if status not in _TERMINAL_STATUSES:
        return False
    age_days = _checkpoint_age_days(checkpoint)
    if age_days is None:
        return False
    return age_days >= BRIDGE_JOB_TERMINAL_RETENTION_DAYS


def prune_finished_bridge_jobs(root: Path, *, dry_run: bool = True) -> BridgeJobCleanupReport:
    """Remove diretórios de job terminal + expirados sob um root de jobs do bridge."""
    report = BridgeJobCleanupReport()
    if not root.is_dir():
        return report
    for job_dir in sorted(root.iterdir()):
        if not job_dir.is_dir() or not _JOB_DIRNAME_RE.fullmatch(job_dir.name):
            continue
        checkpoint = job_dir / _CHECKPOINT_NAME
        if checkpoint.is_file():
            status = _checkpoint_status(checkpoint)
            if status not in _TERMINAL_STATUSES:
                report.kept_pending_jobs += 1
                continue
        if not _is_terminal_expired_job_dir(job_dir):
            continue
        size = sum(1 for _ in ()) or _dir_size_bytes(job_dir)
        if dry_run:
            report.removed_job_dirs.append(job_dir.name)
            report.removed_bytes += size
            continue
        try:
            shutil.rmtree(job_dir)
        except OSError:
            logger.warning("bridge_job_cleanup_failed dir=%s", job_dir)
            continue
        report.removed_job_dirs.append(job_dir.name)
        report.removed_bytes += size
    return report


def _dir_size_bytes(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total


def prune_qa_frame_dirs(
    video_path: Path,
    segment_id: object,
    *,
    dry_run: bool = True,
) -> BridgeJobCleanupReport:
    """Remove o diretório de frames `.qa/<segment>` de um vídeo já avaliado.

    Chamado pelo handler de QA após persistir o resultado: os frames serviram
    ao propósito e são regeneráveis a qualquer momento com FFmpeg.
    """
    report = BridgeJobCleanupReport()
    frame_dir = video_path.parent / ".qa" / str(segment_id)
    if not frame_dir.is_dir():
        return report
    size = _dir_size_bytes(frame_dir)
    if dry_run:
        report.removed_qa_dirs.append(str(frame_dir))
        report.removed_bytes += size
        return report
    try:
        shutil.rmtree(frame_dir)
    except OSError:
        logger.warning("qa_frames_cleanup_failed dir=%s", frame_dir)
        return report
    report.removed_qa_dirs.append(str(frame_dir))
    report.removed_bytes += size
    return report


def _is_diagnostic_file(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith((".png", ".txt", ".html")) and any(
        name.startswith(prefix) for prefix in _DIAGNOSTIC_PREFIXES
    )


def prune_old_diagnostics(
    roots: list[Path],
    *,
    keep_recent: int = DIAGNOSTIC_KEEP_RECENT,
    dry_run: bool = True,
) -> BridgeJobCleanupReport:
    """Limita screenshots/dumps de diagnóstico aos `keep_recent` mais recentes."""
    report = BridgeJobCleanupReport()
    diagnostics: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.is_file() and _is_diagnostic_file(path):
                diagnostics.append(path)
    diagnostics.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    for path in diagnostics[keep_recent:]:
        size = 0
        try:
            size = path.stat().st_size
            if not dry_run:
                path.unlink()
        except OSError:
            continue
        report.removed_diagnostics.append(path.name)
        report.removed_bytes += size
    return report