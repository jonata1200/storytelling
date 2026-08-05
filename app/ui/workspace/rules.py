from app.visual_bible.prompts import default_views_for

WORKSPACE_SECTIONS = ("script", "assets", "storyboard", "video", "finalization", "dubbing")
VISUAL_REFERENCE_VIEW_COUNTS = {
    "characters": len(default_views_for("character")),
    "locations": len(default_views_for("location")),
    "props": len(default_views_for("prop")),
}


def expected_visual_reference_count(counts: dict[str, int]) -> int:
    return sum(
        int(counts.get(key, 0) or 0) * view_count
        for key, view_count in VISUAL_REFERENCE_VIEW_COUNTS.items()
    )


def visual_assets_ready(counts: dict[str, int]) -> bool:
    if int(counts.get("characters", 0) or 0) <= 0:
        return False
    if int(counts.get("locations", 0) or 0) <= 0:
        return False
    if int(counts.get("props", 0) or 0) <= 0:
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
        "dubbing": counts.get("dubbing_jobs", 0) > 0,
        "finalization": counts.get("exports", 0) > 0,
        "quality": counts.get("qa_issues", 0) >= 0,
    }
    return readiness[step_key]


def workspace_section_access(section: str, counts: dict[str, int]) -> tuple[bool, str]:
    script_ready = step_ready("script", counts)
    scenes_ready = step_ready("scenes", counts)
    assets_ready = step_ready("visual", counts)
    storyboard_ready = step_ready("storyboard", counts)
    if section == "script":
        return True, ""
    if section == "assets":
        if not script_ready:
            return False, "Crie o roteiro antes de acessar personagens."
        return True, ""
    if section == "storyboard":
        if not script_ready:
            return False, "Crie o roteiro antes de acessar o storyboard."
        if not scenes_ready:
            return False, "Gere as cenas e planos antes de acessar o storyboard."
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
        if not storyboard_ready:
            return False, "Crie o storyboard antes de acessar vídeo."
        return True, ""
    if section == "dubbing":
        allowed, reason = workspace_section_access("video", counts)
        if not allowed:
            return False, reason
        if not step_ready("video", counts):
            return False, "Gere pelo menos um clipe antes de acessar dublagem."
        return True, ""
    if section == "finalization":
        allowed, reason = workspace_section_access("video", counts)
        if not allowed:
            return False, reason
        if not step_ready("video", counts):
            return False, "Gere pelo menos um clipe antes de acessar finalização."
        return True, ""
    return False, "Etapa desconhecida."


def first_available_workspace_section(counts: dict[str, int]) -> str:
    for section in WORKSPACE_SECTIONS:
        allowed, _ = workspace_section_access(section, counts)
        if allowed:
            return section
    return "script"
