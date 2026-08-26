import asyncio
import base64
import json
import subprocess
import urllib.request
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.provider_policy import ensure_provider_api_key
from app.config.settings import get_settings
from app.generation.shot_generation_spec import ShotGenerationSpec
from app.observability.redaction import redact_secrets
from app.providers.media_utils import resolve_ffmpeg_path
from app.video_generation.models import QAResult

QA_DIMENSIONS = (
    "characters",
    "location",
    "character_state",
    "critical_prop",
    "primary_action",
    "continuity",
)
OBJECTIVE_QA_FAILURES = {"missing_video", "unreadable_video", "missing_required_character"}


class QAAssessment(BaseModel):
    dimension_scores: dict[str, int]
    reasons: list[str] = Field(default_factory=list)
    objective_failures: list[str] = Field(default_factory=list)


def _structured_json_content(raw: object) -> str:
    content = str(raw or "").strip()
    if content.startswith("```"):
        lines = content.splitlines()
        if lines and lines[0].strip().lower() in {"```", "```json"}:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines).strip()
    return content


QAAnalyzer = Callable[[ShotGenerationSpec, list[Path]], Awaitable[QAAssessment]]


async def analyze_with_ollama_cloud(spec: ShotGenerationSpec, frames: list[Path]) -> QAAssessment:
    """Compara frames com o Shot usando o endpoint multimodal oficial do Ollama Cloud."""
    settings = get_settings()
    if not settings.qa_ollama_multimodal_enabled:
        return conservative_qa_assessment(spec)
    base_url = str(settings.ollama_cloud_base_url or "").rstrip("/")
    if not base_url:
        raise RuntimeError("OLLAMA_CLOUD_BASE_URL não configurada para QA multimodal")
    api_key = ensure_provider_api_key(
        settings.ollama_cloud_api_key, "ollama_cloud", "OLLAMA_API_KEY"
    )
    schema = QAAssessment.model_json_schema()
    prompt = (
        "Evaluate these keyframes against the ShotGenerationSpec. Score every dimension "
        "from 0 to 100. Only report objective_failures from: "
        f"{sorted(OBJECTIVE_QA_FAILURES)}. Return JSON matching this schema: "
        f"{json.dumps(schema)}. ShotGenerationSpec: {spec.model_dump_json()}"
    )
    images = [base64.b64encode(frame.read_bytes()).decode("ascii") for frame in frames]
    payload = json.dumps(
        {
            "model": settings.ollama_cloud_vision_model,
            "messages": [{"role": "user", "content": prompt, "images": images}],
            "format": schema,
            "stream": False,
            "options": {"temperature": 0},
        }
    ).encode("utf-8")

    def request() -> QAAssessment:
        invalid_response: Exception | None = None
        for _attempt in range(2):
            req = urllib.request.Request(
                f"{base_url}/chat",
                data=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(
                    req, timeout=settings.qa_ollama_timeout_seconds
                ) as response:
                    body = json.loads(response.read().decode("utf-8"))
                raw = _structured_json_content(body["message"]["content"])
                return QAAssessment.model_validate_json(raw)
            except (json.JSONDecodeError, KeyError, TypeError, ValidationError) as exc:
                invalid_response = exc
                continue
            except Exception as exc:
                raise RuntimeError(
                    f"Falha no QA multimodal Ollama Cloud: {redact_secrets(exc)}"
                ) from exc
        return conservative_qa_assessment(
            spec,
            reason=(
                "O QA multimodal retornou uma resposta inválida após duas tentativas; "
                f"revisão humana obrigatória ({redact_secrets(invalid_response)})."
            ),
        )

    return await asyncio.to_thread(request)


def conservative_qa_assessment(
    spec: ShotGenerationSpec, *, reason: str | None = None
) -> QAAssessment:
    """Fallback explícito: não aprova nem rejeita conteúdo sem análise visual."""
    return QAAssessment(
        dimension_scores={dimension: 50 for dimension in QA_DIMENSIONS},
        reasons=[reason or "QA multimodal desativado; revisão humana obrigatória"],
    )


async def extract_video_keyframes(video_path: Path, output_dir: Path) -> list[Path]:
    ffmpeg = resolve_ffmpeg_path()
    if not ffmpeg:
        raise RuntimeError("FFmpeg não encontrado para QA")
    output_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
    pattern = output_dir / "qa-%02d.jpg"
    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-vf",
        "fps=3/10",
        "-frames:v",
        "3",
        str(pattern),
    ]
    process = await asyncio.create_subprocess_exec(
        *command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    _stdout, stderr = await process.communicate()
    if process.returncode != 0:
        detail = stderr.decode(errors="replace")[:400]
        raise RuntimeError(f"Falha ao extrair frames de QA: {detail}")
    frames = sorted(output_dir.glob("qa-*.jpg"))  # noqa: ASYNC240
    if not frames:
        raise RuntimeError("Vídeo não produziu frames-chave para QA")
    return frames


async def persist_qa_result(
    session: AsyncSession,
    *,
    project_id: Any,
    shot_id: Any,
    segment_id: Any,
    generation_job_id: Any,
    assessment: QAAssessment,
    compiler_version: str,
    auto_reject_objective_failures: bool = True,
) -> QAResult:
    scores = {
        dimension: max(0, min(100, int(assessment.dimension_scores.get(dimension, 0))))
        for dimension in QA_DIMENSIONS
    }
    total = round(sum(scores.values()) / len(QA_DIMENSIONS))
    objective = [item for item in assessment.objective_failures if item in OBJECTIVE_QA_FAILURES]
    decision = "objective_failure" if objective and auto_reject_objective_failures else "review"
    result = QAResult(
        project_id=project_id,
        shot_id=shot_id,
        segment_id=segment_id,
        generation_job_id=generation_job_id,
        total_score=total,
        dimension_scores=scores,
        reasons=list(assessment.reasons),
        objective_failures=objective,
        decision=decision,
        needs_human_review=not bool(objective and auto_reject_objective_failures),
        compiler_version=compiler_version,
        metadata_json={"raw_assessment": json.loads(assessment.model_dump_json())},
    )
    session.add(result)
    await session.flush()
    return result


def qa_correction_instruction(result: QAResult) -> str:
    weak = [name for name, score in result.dimension_scores.items() if int(score) < 70]
    reasons = "; ".join(str(item) for item in result.reasons[:3])
    return (
        "Correct the failed QA dimensions without changing approved identities: "
        f"{', '.join(weak) or 'objective failure'}. {reasons}"
    ).strip()
