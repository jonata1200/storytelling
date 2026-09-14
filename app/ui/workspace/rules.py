from app.video_generation.continuous import CONTINUOUS_VIDEO_MIN_APPROVED_SEGMENTS
from app.visual_bible.reference_planning import VISUAL_REFERENCE_VIEW_COUNTS

WORKSPACE_SECTIONS = ("script", "visual", "storyboard")
CONTINUOUS_VIDEO_WORKFLOW_MODE = "continuous_fast"


def visual_assets_ready(counts: dict[str, int]) -> bool:
    expected = sum(
        int(counts.get(key, 0) or 0) * view_count
        for key, view_count in VISUAL_REFERENCE_VIEW_COUNTS.items()
    )
    generated = int(counts.get("visual_refs_ready", counts.get("visual_refs", 0)) or 0)
    return expected > 0 and generated >= expected


def pending_visual_assets(counts: dict[str, int]) -> tuple[int, int]:
    expected = sum(
        int(counts.get(key, 0) or 0) * view_count
        for key, view_count in VISUAL_REFERENCE_VIEW_COUNTS.items()
    )
    generated = min(
        int(counts.get("visual_refs_ready", counts.get("visual_refs", 0)) or 0), expected
    )
    return max(expected - generated, 0), expected


def step_ready(step_key: str, counts: dict[str, int]) -> bool:
    readiness = {
        "briefing": counts.get("briefings", 0) > 0,
        "ideas": counts.get("ideas", 0) > 0,
        "script": counts.get("scripts", 0) > 0,
        "scenes": counts.get("scenes", 0) > 0 and counts.get("shots", 0) > 0,
        "visual": visual_assets_ready(counts),
        "storyboard": continuous_video_ready(counts),
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
            return False, "Crie o roteiro antes de acessar a Bíblia Visual."
        return True, ""
    if section == "video":
        return workspace_section_access("storyboard", counts, workflow_mode)
    if section == "storyboard":
        if not script_ready:
            return False, "Crie o roteiro antes de acessar os Storyboards."
        if not visual_assets_ready(counts):
            pending, expected = pending_visual_assets(counts)
            if expected > 0:
                return (
                    False,
                    "Gere todas as imagens de referência antes de acessar os "
                    f"Storyboards ({expected - pending}/{expected} criadas).",
                )
            return (
                False,
                "Crie os perfis e todas as imagens de referência na Bíblia Visual antes de "
                "acessar os Storyboards.",
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
