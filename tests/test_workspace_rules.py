from app.ui.workspace.rules import visual_assets_ready, workspace_section_access


def test_video_requires_one_reference_per_character_and_location() -> None:
    counts = {"scripts": 1, "characters": 2, "locations": 1, "visual_refs_ready": 2}

    allowed, reason = workspace_section_access("video", counts)

    assert allowed is False
    assert "(2/3 criadas)" in reason


def test_video_unlocks_when_each_visual_target_has_its_reference() -> None:
    counts = {
        "scripts": 1,
        "characters": 2,
        "locations": 1,
        "visual_refs_ready": 3,
        "continuous_video_segments": 2,
        "storyboard_ready_segments": 2,
    }

    assert visual_assets_ready(counts) is True
    assert workspace_section_access("storyboard", counts) == (True, "")
    assert workspace_section_access("video", counts) == (True, "")


def test_video_does_not_require_prebuilt_storyboards() -> None:
    counts = {
        "scripts": 1,
        "characters": 1,
        "locations": 1,
        "visual_refs_ready": 2,
        "continuous_video_segments": 12,
        "storyboard_ready_segments": 3,
        "storyboard_approved_segments": 2,
    }

    assert workspace_section_access("video", counts) == (True, "")


def test_video_remains_available_with_only_two_legacy_storyboards() -> None:
    counts = {
        "scripts": 1,
        "characters": 1,
        "locations": 1,
        "visual_refs_ready": 2,
        "continuous_video_segments": 12,
        "storyboard_ready_segments": 2,
    }

    assert workspace_section_access("video", counts) == (True, "")


def test_extra_obsolete_views_do_not_mask_a_missing_required_reference() -> None:
    counts = {
        "scripts": 1,
        "characters": 1,
        "locations": 1,
        "visual_refs": 5,
        "visual_refs_ready": 1,
    }

    assert visual_assets_ready(counts) is False


def test_finalization_section_is_removed() -> None:
    # A etapa de finalização foi removida: a seção não existe mais e o acesso
    # retorna "Etapa desconhecida" em vez de desbloquear.
    counts = {
        "scripts": 1,
        "continuous_video_segments": 12,
        "continuous_video_generated_segments": 4,
        "continuous_video_selected_segments": 3,
    }

    allowed, reason = workspace_section_access("finalization", counts)

    assert allowed is False
    assert reason == "Etapa desconhecida."
