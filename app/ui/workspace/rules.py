from app.video_generation.continuous import CONTINUOUS_VIDEO_MIN_APPROVED_SEGMENTS

WORKSPACE_SECTIONS = ("script", "visual", "video", "finalization")
CONTINUOUS_VIDEO_WORKFLOW_MODE = "continuous_fast"


def visual_assets_ready(counts: dict[str, int]) -> bool:
    if int(counts.get("characters", 0) or 0) <= 0:
        return False
    if int(counts.get("locations", 0) or 0) <= 0:
        return False
    return True


def step_ready(step_key: str, counts: dict[str, int]) -> bool:
    readiness = {
        "briefing": counts.get("briefings", 0) > 0,
        "ideas": counts.get("ideas", 0) > 0,
        "script": counts.get("scripts", 0) > 0,
        "scenes": counts.get("scenes", 0) > 0 and counts.get("shots", 0) > 0,
        "visual": visual_assets_ready(counts),
        "video": counts.get("clips", 0) > 0,
    }
    return readiness[step_key]


def is_continuous_video_workflow(workflow_mode: object) -> bool:
    mode = str(workflow_mode or "").strip()
    return not mode or mode == CONTINUOUS_VIDEO_WORKFLOW_MODE


def continuous_video_required_approved(counts: dict[str, int]) -> int:
    total = int(counts.get("continuous_video_segments", 0) or 0)
    if total <= 0:
        return 0
    return min(CONTINUOUS_VIDEO_MIN_APPROVED_SEGMENTS, total)


def continuous_video_ready(counts: dict[str, int]) -> bool:
    done = int(counts.get("continuous_video_done_segments", 0) or 0)
    required = continuous_video_required_approved(counts)
    return required > 0 and done >= required


MIN_GENERATED_SEGMENTS_FOR_FINALIZATION = 3


def workspace_section_access(
    section: str,
    counts: dict[str, int],
    workflow_mode: object = None,
) -> tuple[bool, str]:
    script_ready = step_ready("script", counts)
    _ = is_continuous_video_workflow(workflow_mode)
    if section == "script":
        return True, ""
    if section == "visual":
        if not script_ready:
            return False, "Crie o roteiro antes de acessar a Visual Bible."
        return True, ""
    if section == "video":
        if not script_ready:
            return False, "Crie o roteiro antes de acessar vídeo."
        return True, ""
    if section == "finalization":
        if not script_ready:
            return False, "Crie o roteiro antes de acessar a finalização."
        generated_videos = int(
            counts.get("continuous_video_generated_segments", 0)
            or counts.get("continuous_video_done_segments", 0)
            or 0
        )
        if generated_videos < MIN_GENERATED_SEGMENTS_FOR_FINALIZATION:
            return (
                False,
                f"Gere pelo menos {MIN_GENERATED_SEGMENTS_FOR_FINALIZATION} vídeos de "
                f"segmentos antes de acessar a finalização "
                f"({generated_videos}/{MIN_GENERATED_SEGMENTS_FOR_FINALIZATION} gerados).",
            )
        total_segments = int(counts.get("continuous_video_segments", 0) or 0)
        if total_segments > 0 and generated_videos < total_segments:
            return (
                False,
                "Gere os vídeos de todos os segmentos antes de acessar a finalização "
                f"({generated_videos}/{total_segments} gerados).",
            )
        return True, ""
    return False, "Etapa desconhecida."


def first_available_workspace_section(
    counts: dict[str, int],
    workflow_mode: object = None,
) -> str:
    for section in WORKSPACE_SECTIONS:
        allowed, _ = workspace_section_access(section, counts, workflow_mode)
        if allowed:
            return section
    return "script"
