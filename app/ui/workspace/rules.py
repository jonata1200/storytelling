from app.video_generation.continuous import CONTINUOUS_VIDEO_MIN_APPROVED_SEGMENTS
from app.visual_bible.prompts import default_views_for

WORKSPACE_SECTIONS = ("script", "assets", "storyboard", "video")
CONTINUOUS_VIDEO_WORKFLOW_MODE = "continuous_fast"
VISUAL_REFERENCE_VIEW_COUNTS = {
    "characters": len(default_views_for("character")),
    "locations": len(default_views_for("location")),
    "props": len(default_views_for("prop")),
}


def expected_visual_reference_count(counts: dict[str, int]) -> int:
    total = 0
    for key, view_count in VISUAL_REFERENCE_VIEW_COUNTS.items():
        count = int(counts.get(key, 0) or 0)
        if key == "props" and count <= 0:
            continue
        total += count * view_count
    return total


def visual_assets_ready(counts: dict[str, int]) -> bool:
    if int(counts.get("characters", 0) or 0) <= 0:
        return False
    if int(counts.get("locations", 0) or 0) <= 0:
        return False
    return int(counts.get("visual_refs", 0) or 0) >= expected_visual_reference_count(counts)


def step_ready(step_key: str, counts: dict[str, int]) -> bool:
    readiness = {
        "briefing": counts.get("briefings", 0) > 0,
        "ideas": counts.get("ideas", 0) > 0,
        "script": counts.get("scripts", 0) > 0,
        "scenes": counts.get("scenes", 0) > 0 and counts.get("shots", 0) > 0,
        "visual": visual_assets_ready(counts),
        "storyboard": counts.get("frames", 0) > 0 and counts.get("animatics", 0) > 0,
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
    approved = int(counts.get("continuous_video_approved_segments", 0) or 0)
    required = continuous_video_required_approved(counts)
    return required > 0 and approved >= required


def workspace_section_access(
    section: str,
    counts: dict[str, int],
    workflow_mode: object = None,
) -> tuple[bool, str]:
    script_ready = step_ready("script", counts)
    assets_ready = step_ready("visual", counts)
    storyboard_ready = step_ready("storyboard", counts)
    continuous_mode = is_continuous_video_workflow(workflow_mode)
    if section == "script":
        return True, ""
    if section == "assets":
        if not script_ready:
            return False, "Crie o roteiro antes de acessar a Biblioteca Visual."
        return True, ""
    if section == "storyboard":
        if not script_ready:
            return False, "Crie o roteiro antes de acessar o storyboard."
        if not assets_ready:
            return (
                False,
                "Gere todas as imagens de personagens, locais e objetos antes do storyboard.",
            )
        return True, ""
    if section == "video":
        if not script_ready:
            return False, "Crie o roteiro antes de acessar vídeo."
        if not assets_ready:
            return (
                False,
                "Gere todas as imagens de personagens, locais e objetos antes de acessar vídeo.",
            )
        if not storyboard_ready and not continuous_mode:
            return False, "Crie o storyboard antes de acessar vídeo."
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
