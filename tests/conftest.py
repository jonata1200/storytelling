from pathlib import Path

import pytest
from _pytest.nodes import Item

SECURITY_TEST_FILES = {
    "test_auth.py",
    "test_production_settings.py",
    "test_quality_security.py",
    "test_reference_upload.py",
    "test_script_upload.py",
    "test_security_regressions.py",
    "test_storage_governance.py",
}

PROVIDER_TEST_FILES = {
    "test_mock_image_provider.py",
    "test_mock_llm_provider.py",
    "test_mock_speech_provider.py",
    "test_mock_video_provider.py",
    "test_omniroute_provider.py",
    "test_omniroute_smoke.py",
    "test_omniroute_video_speech_smoke.py",
    "test_omniroute_video_speech.py",
    "test_openrouter_media_providers.py",
    "test_openrouter_provider.py",
    "test_prompt_compiler.py",
    "test_speech_provider.py",
    "test_visual_bible.py",
    "test_visual_bible_script_profiles.py",
}

UI_TEST_FILES = {
    "test_auth.py",
    "test_idea_lab.py",
    "test_project_creation_assets.py",
    "test_project_creation_storyboard.py",
    "test_project_creation_ui.py",
    "test_project_creation_workspace.py",
}

INTEGRATION_TEST_FILES = {
    "test_auth.py",
    "test_dependencies.py",
    "test_idea_lab.py",
    "test_initial_script_pipeline.py",
    "test_observability_middleware.py",
    "test_project_agent_routing.py",
    "test_project_agent_script.py",
    "test_project_agent_storyboard_video.py",
    "test_project_agent_visual.py",
    "test_project_bulk_delete.py",
    "test_project_creation_storyboard.py",
    "test_project_creation_workspace.py",
    "test_reference_upload.py",
    "test_storage_governance.py",
    "test_storyboard_timeline.py",
    "test_video_retry.py",
    "test_visual_bible_script_profiles.py",
}

MARKER_BY_FILE = {
    "integration": INTEGRATION_TEST_FILES,
    "provider": PROVIDER_TEST_FILES,
    "security": SECURITY_TEST_FILES,
    "ui": UI_TEST_FILES,
}


def pytest_collection_modifyitems(items: list[Item]) -> None:
    for item in items:
        filename = Path(str(item.path)).name
        markers = {
            marker_name
            for marker_name, filenames in MARKER_BY_FILE.items()
            if filename in filenames
        }
        if not markers:
            markers.add("unit")
        for marker_name in sorted(markers):
            item.add_marker(getattr(pytest.mark, marker_name))
