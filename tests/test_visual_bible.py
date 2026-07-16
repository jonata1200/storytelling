from app.visual_bible.service import default_views_for


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
