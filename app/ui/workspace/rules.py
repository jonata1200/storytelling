WORKSPACE_SECTIONS = ("script", "assets", "storyboard", "video")


def step_ready(step_key: str, counts: dict[str, int]) -> bool:
    readiness = {
        "briefing": counts["briefings"] > 0,
        "ideas": counts["ideas"] > 0,
        "script": counts["scripts"] > 0,
        "visual": counts["characters"] > 0,
        "storyboard": counts["frames"] > 0 and counts["animatics"] > 0,
        "video": counts["clips"] > 0,
        "finalization": counts["exports"] > 0,
        "quality": counts["qa_issues"] >= 0,
    }
    return readiness[step_key]


def workspace_section_access(section: str, counts: dict[str, int]) -> tuple[bool, str]:
    script_ready = step_ready("script", counts)
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
        if not assets_ready:
            return False, "Crie os personagens antes de acessar o storyboard."
        return True, ""
    if section == "video":
        if not script_ready:
            return False, "Crie o roteiro antes de acessar vídeo."
        if not assets_ready:
            return False, "Crie os personagens antes de acessar vídeo."
        if not storyboard_ready:
            return False, "Crie o storyboard antes de acessar vídeo."
        return True, ""
    return False, "Etapa desconhecida."


def first_available_workspace_section(counts: dict[str, int]) -> str:
    for section in WORKSPACE_SECTIONS:
        allowed, _ = workspace_section_access(section, counts)
        if allowed:
            return section
    return "script"
