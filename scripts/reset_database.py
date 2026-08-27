"""Script para limpar todos os dados da aplicação.

Uso:
    python scripts/reset_database.py
"""
import asyncio
import sys
from pathlib import Path

# Adicionar o diretório raiz ao path
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import text  # noqa: E402

from app.database.session import AsyncSessionLocal  # noqa: E402

# Arquivos JSON do Idea Lab
IDEA_LAB_FILES = [
    ".runtime/idea_lab_saved.json",
    ".runtime/idea_lab_generated.json",
]


async def reset_database() -> None:
    print("Limpando banco de dados...")

    async with AsyncSessionLocal() as session:
        # TRUNCATE todas as tabelas com CASCADE
        await session.execute(text(
            "TRUNCATE TABLE "
            "projects, scripts, story_ideas, artifacts, artifact_versions, "
            "assets, asset_versions, characters, character_versions, "
            "locations, location_versions, visual_references, "
            "prompt_executions, cost_entries, generation_jobs, "
            "approvals, continuous_video_segments, continuous_video_plans, "
            "project_model_settings, project_production_settings "
            "RESTART IDENTITY CASCADE"
        ))
        await session.commit()

    print("Banco de dados limpo com sucesso!")

    # Limpar arquivos JSON do Idea Lab
    for rel_path in IDEA_LAB_FILES:
        idea_file = ROOT_DIR / rel_path
        if idea_file.exists():
            idea_file.unlink()
            print(f"Removido: {rel_path}")

    print("Limpeza concluída!")


if __name__ == "__main__":
    asyncio.run(reset_database())
