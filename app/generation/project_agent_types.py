from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

ProjectChatAction = Literal[
    "chat",
    "generate_ideas",
    "generate_script",
    "revise_script",
    "generate_assets",
    "approve_visual_prompt",
    "approve_storyboard_prompt",
    "generate_storyboard",
    "generate_video",
    "generate_dubbing",
    "generate_finalization",
    "run_quality",
]


REVISION_TERMS = (
    "ajuste",
    "ajustar",
    "altere",
    "alterar",
    "corrija",
    "corrigir",
    "edicao",
    "edição",
    "edite",
    "editar",
    "melhore",
    "melhorar",
    "mude",
    "mudar",
    "modifique",
    "modificar",
    "refaça",
    "refazer",
    "reescreva",
    "reescrever",
    "revise",
    "revisar",
)


@dataclass(frozen=True)
class ProjectChatResult:
    message: str
    action: ProjectChatAction
    changed: bool = False
    failed: bool = False


@dataclass(frozen=True)
class ProjectChatIntent:
    action: ProjectChatAction
    confidence: float
    reason: str = ""


ProgressCallback = Callable[[str], Awaitable[None]]


ACTION_PROGRESS_MESSAGES: dict[ProjectChatAction, str] = {
    "generate_ideas": "Criando ideias.",
    "generate_script": "Criando roteiro.",
    "revise_script": "Revisando roteiro.",
    "generate_assets": "Criando ativos visuais.",
    "approve_visual_prompt": "Aprovando prompt visual.",
    "approve_storyboard_prompt": "Aprovando prompts de storyboard.",
    "generate_storyboard": "Criando storyboard.",
    "generate_video": "Preparando video.",
    "generate_dubbing": "Preparando dublagem.",
    "generate_finalization": "Finalizando projeto.",
    "run_quality": "Rodando controle de qualidade.",
    "chat": "Analisando projeto.",
}


async def _emit_progress(progress: ProgressCallback | None, message: str) -> None:
    if progress is not None:
        await progress(message)
