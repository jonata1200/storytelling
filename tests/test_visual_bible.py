from app.visual_bible.service import (
    _character_profile,
    _location_profile,
    _profile_items,
    _prop_profile,
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


def test_visual_profiles_accept_text_items_from_story_bible() -> None:
    character = _character_profile("Clara")
    location = _location_profile("Casa da familia")
    prop = _prop_profile("Carta azul")

    assert character["name"] == "Clara"
    assert character["role"] == "personagem"
    assert location["name"] == "Casa da familia"
    assert prop["name"] == "Carta azul"


def test_profile_items_accepts_mapping_sections_from_story_bible() -> None:
    items = _profile_items(
        {
            "protagonist": {"nome": "Clara", "funcao": "filha"},
            "mentor": "Mae de Clara",
        }
    )

    assert items == [
        {"nome": "Clara", "funcao": "filha", "name": "Clara"},
        {"name": "Mae de Clara", "description": "Mae de Clara"},
    ]
