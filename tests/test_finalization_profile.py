from app.finalization.service import export_profile


def test_export_profile_defaults_to_vertical_social_video() -> None:
    profile = export_profile()

    assert profile["aspect_ratio"] == "9:16"
    assert profile["resolution"] == "1080x1920"
    assert profile["fps"] == 30
    assert profile["safe_area"]["bottom_percent"] == 18
