"""Script para limpar todos os dados da aplicação.

Uso:
    python scripts/reset_database.py
"""
import asyncio
import logging
import sys
from pathlib import Path

# Adicionar o diretório raiz ao path
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import text  # noqa: E402

from app.database.session import AsyncSessionLocal  # noqa: E402
from app.projects.service import _validated_table_identifiers  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("reset_database")

# Arquivos JSON do Idea Lab
IDEA_LAB_FILES = [
    ".runtime/idea_lab_saved.json",
    ".runtime/idea_lab_generated.json",
]

RESET_TABLES = (
    "projects",
    "scripts",
    "story_ideas",
    "artifacts",
    "artifact_versions",
    "assets",
    "asset_versions",
    "characters",
    "locations",
    "visual_references",
    "prompt_executions",
    "cost_entries",
    "generation_jobs",
    "approvals",
    "continuous_video_segments",
    "continuous_video_plans",
    "project_model_settings",
    "project_production_settings",
)


async def reset_database() -> None:
    logger.info("Limpando banco de dados...")

    # Nomes de tabela validados contra o metadata antes de concatenar no SQL.
    table_list = ", ".join(_validated_table_identifiers(RESET_TABLES))
    async with AsyncSessionLocal() as session:
        await session.execute(
            text(f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE")
        )
        await session.commit()

    logger.info("Banco de dados limpo com sucesso!")

    # Limpar arquivos JSON do Idea Lab
    for rel_path in IDEA_LAB_FILES:
        idea_file = ROOT_DIR / rel_path
        if idea_file.exists():
            idea_file.unlink()
            logger.info("Removido: %s", rel_path)

    logger.info("Limpeza concluída!")


if __name__ == "__main__":
    asyncio.run(reset_database())
