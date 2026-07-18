from app.visual_bible.service import (
    default_views_for,
    initial_view_for,
    visual_reference_prompt,
)


def test_default_character_views_include_required_reference_sheet_items() -> None:
    views = default_views_for("character")

    assert "front_portrait" in views
    assert "left_profile" in views
    assert "right_profile" in views
    assert "back_view" in views
    assert "full_body" in views
    assert "expression_sheet" in views
    assert "pose_sheet" in views
    assert "scale_reference" in views


def test_initial_visual_reference_is_single_canonical_view() -> None:
    assert initial_view_for("character") == "front_portrait"
    assert initial_view_for("location") == "establishing"
    assert initial_view_for("prop") == "front"

    for target_kind in ["character", "location", "prop"]:
        assert initial_view_for(target_kind) in default_views_for(target_kind)


def test_visual_reference_prompt_uses_canonical_profile_prompt() -> None:
    profile = {
        "name": "Helena",
        "canonical_prompt": "Helena, 35, expressive detective, rainy noir lighting",
    }

    assert (
        visual_reference_prompt(profile, "front_portrait")
        == "Helena, 35, expressive detective, rainy noir lighting. View: front_portrait."
    )
