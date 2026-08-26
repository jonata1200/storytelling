import os
import tempfile
from pathlib import Path

import pytest
from _pytest.nodes import Item

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTEST_RUNTIME_DIR = PROJECT_ROOT / ".runtime" / "pytest"
PYTEST_TMP_ROOT = PYTEST_RUNTIME_DIR / "runs" / f"run-{os.getpid()}"

PYTEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ["TMP"] = str(PYTEST_TMP_ROOT)
os.environ["TEMP"] = str(PYTEST_TMP_ROOT)
os.environ["TMPDIR"] = str(PYTEST_TMP_ROOT)
tempfile.tempdir = str(PYTEST_TMP_ROOT)

PROVIDER_ENV_VARS = (
    "AI_PROVIDER",
    "TEXT_PROVIDER",
    "VIDEO_PROVIDER",
)


@pytest.fixture(autouse=True)
def _clean_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Torna os testes independentes de variáveis de ambiente do provedor.

    O ambiente de desenvolvimento local pode exportar VIDEO_PROVIDER,
    e essas variáveis sobrescreveriam os defaults do Settings dentro dos testes.
    """
    for key in PROVIDER_ENV_VARS:
        monkeypatch.delenv(key, raising=False)

SECURITY_TEST_FILES = {
    "test_production_settings.py",
    "test_security_regressions.py",
    "test_storage_governance.py",
}

PROVIDER_TEST_FILES = {
    "test_mock_providers.py",
    "test_prompt_compiler.py",
    "test_visual_bible.py",
    "test_visual_bible_script_profiles.py",
}

SMOKE_TEST_FILES = {
    "test_text_provider_smoke.py",
}

UI_TEST_FILES = {
    "test_idea_lab.py",
    "test_project_creation_assets.py",
    "test_project_creation_storyboard.py",
    "test_project_creation_ui.py",
    "test_project_creation_workspace.py",
}

INTEGRATION_TEST_FILES = {
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
    "test_storage_governance.py",
    "test_storyboard_timeline.py",
    "test_video_retry.py",
    "test_visual_bible_script_profiles.py",
}

MARKER_BY_FILE = {
    "integration": INTEGRATION_TEST_FILES,
    "provider": PROVIDER_TEST_FILES,
    "smoke": SMOKE_TEST_FILES,
    "security": SECURITY_TEST_FILES,
    "ui": UI_TEST_FILES,
}


def pytest_collection_modifyitems(items: list[Item]) -> None:
    for item in items:
        filename = Path(item.path).name
        markers = {
            marker_name
            for marker_name, filenames in MARKER_BY_FILE.items()
            if filename in filenames
        }
        if not markers:
            markers.add("unit")
        for marker_name in sorted(markers):
            item.add_marker(getattr(pytest.mark, marker_name))
        if filename in SMOKE_TEST_FILES and os.getenv("RUN_PROVIDER_SMOKE_TESTS") != "1":
            item.add_marker(
                pytest.mark.skip(
                    reason="Defina RUN_PROVIDER_SMOKE_TESTS=1 para executar smokes reais."
                )
            )
