"""Regressão das melhorias de prompt aprovadas (2026-09): ideias, roteiro,
extração com candidatos do parser, anti-genérico no design visual, frames e
compilador de vídeo v10."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.generation.service import DEFAULT_TEMPLATES
from app.generation.shot_generation_spec import ShotGenerationSpec
from app.generation.shot_prompt_compiler import (
    VIBES_SHOT_PROMPT_COMPILER_VERSION,
    VibesPromptCompiler,
)
from app.video_generation.continuous_frames import segment_frame_prompts
from app.visual_bible.script_profile_contracts import extraction_prompt, visual_design_prompt
from app.visual_bible.script_profiles import _llm_extract_characters_and_locations


def test_story_ideas_prompt_constrains_cast_and_hook() -> None:
    template = DEFAULT_TEMPLATES["generate_story_ideas"]

    assert "no maximo 3 personagens nomeados" in template
    assert "no maximo 3 locais fisicos" in template
    assert "GANCHO COMO IMAGEM DE ABERTURA" in template
    assert "PRIMEIRA IMAGEM" in template
    assert "CONTINUIDADE DO CONTRATO NARRATIVO" in template
    assert "AUTOAVALIACAO DE COMPLEXIDADE" in template
    assert "0-25" in template and "76-100" in template
    assert "RESTRICAO DE CONTEUDO PARA IMAGENS" in template
    assert "violencia grafica" in template
    assert "marca de faca" in template


def test_generate_script_prompt_balances_scenes_and_locks_visual_identity() -> None:
    template = DEFAULT_TEMPLATES["generate_script"]

    assert "EQUILIBRIO ENTRE CENAS" in template
    assert "RÉGUA DE DIÁLOGO" in template
    assert "no maximo 2 a 3 blocos de dialogo por cena" in template
    assert "CONTINUIDADE PARA REFERENCIAS VISUAIS" in template
    assert "fonte de verdade" in template
    assert "REUTILIZAVEIS" in template
    assert "estados momentaneos vao na acao, nao na slugline" in template
    assert "RESTRICAO DE CONTEUDO PARA IMAGENS" in template
    assert "violencia grafica" in template
    assert "ate a carne" in template


def test_extraction_prompt_lists_parser_candidates_when_given() -> None:
    prompt = extraction_prompt("CENA 1\nINT. CASA - NOITE", 1, 1, "", ["Elias", "Casa"])

    assert "CANDIDATOS DETECTADOS NO ROTEIRO" in prompt
    assert "Elias, Casa" in prompt
    assert "verifique UM A UM" in prompt
    assert "Nao ignore candidatos humanos" in prompt


def test_extraction_prompt_without_hints_has_no_candidates_section() -> None:
    prompt = extraction_prompt("CENA 1\nINT. CASA - NOITE", 1, 1, "")

    assert "CANDIDATOS DETECTADOS NO ROTEIRO" not in prompt
    assert "NENHUM campo textual pode ficar vazio" in prompt


def test_visual_design_prompt_bans_generic_placeholders() -> None:
    prompt = visual_design_prompt([], [], "")

    assert "PROIBIDO CAMPO VAZIO OU GENÉRICO" in prompt
    assert "15 a 40 palavras" in prompt
    assert "um ambiente amplo, usado e com detalhes arquitetônicos bem definidos" in prompt
    assert "roupa discreta" in prompt
    assert "calçados adequados" in prompt


def test_frame_prompt_locks_identity_and_final_pose() -> None:
    segment = SimpleNamespace(
        prompt="A personagem atravessa a sala.",
        metadata_json={
            "characters": ["Clara"],
            "locations": ["Bunker"],
            "shot_generation_spec": {"lighting": "luz azul suave"},
        },
    )

    prompts = segment_frame_prompts(segment)  # type: ignore[arg-type]

    assert "Use as mesmas imagens anteriores" not in prompts["initial"]
    assert "pose final da ação" in prompts["final"]
    # v3 dos frames: a trava de iluminação foi removida — a consistência de
    # luz vem do chat/referências onde todas as imagens são geradas.
    assert "mesma iluminação" not in prompts["final"]
    assert "Iluminação" not in prompts["initial"]
    assert "logo depois dessa ação" not in prompts["final"]


def test_vibes_compiler_v12_omits_camera_and_plans() -> None:
    assert VIBES_SHOT_PROMPT_COMPILER_VERSION == "vibes_shot_v14_action_only"
    spec = ShotGenerationSpec(
        shot_id=uuid4(),
        scene_id=uuid4(),
        scene_title="Corredor",
        scene_summary="A fuga continua",
        duration_seconds=8,
        characters=["Ana"],
        action="Ana atravessa o corredor",
        emotion="urgência",
        visual_composition="Plano médio, Ana centralizada",
        camera_movement="dolly in",
        lighting="luz vermelha de emergência",
   )

    compiled = VibesPromptCompiler().compile(spec)

    # v13: nem planos/enquadramento, nem movimento de câmera, nem iluminação.
    assert "Iluminação" not in compiled.prompt
    assert "luz vermelha" not in compiled.prompt
    assert "Enquadramento" not in compiled.prompt
    assert "câmera" not in compiled.prompt.casefold()
    assert "dolly" not in compiled.prompt.casefold()
    assert len(compiled.prompt) <= 420


def test_vibes_compiler_v11_omits_static_camera() -> None:
    spec = ShotGenerationSpec(
        shot_id=uuid4(),
        scene_id=uuid4(),
        scene_title="Sala",
        scene_summary="Espera",
        duration_seconds=8,
        characters=["Bia"],
        action="Bia observa a porta",
        emotion="tensão",
        visual_composition="Plano fechado em Bia",
        camera_movement="estático",
    )

    compiled = VibesPromptCompiler().compile(spec)

    assert "câmera" not in compiled.prompt.casefold()


def test_vibes_compiler_v11_omits_generic_camera_placeholder() -> None:
    """Placeholder "movimento curto e realista" (38/38 shots iguais) é ruído."""
    spec = ShotGenerationSpec(
        shot_id=uuid4(),
        scene_id=uuid4(),
        scene_title="Rua",
        scene_summary="A caminhada",
        duration_seconds=8,
        characters=["Antônio"],
        action="Antônio empurra o carrinho",
        emotion="urgência",
        visual_composition="Plano centrado em Antônio, no ambiente Rua do Bairro",
        camera_movement="movimento curto e realista",
        lighting="luz amarelada de amanhecer",
        location="Rua do Bairro - Amanhecer",
    )

    compiled = VibesPromptCompiler().compile(spec)

    assert "câmera" not in compiled.prompt.casefold()
    assert "movimento curto" not in compiled.prompt
    # v14: o prompt é só a ação — local não entra mais no texto.
    assert compiled.prompt == "Antônio empurra o carrinho."
    assert "Amanhecer" not in compiled.prompt


def test_vibes_compiler_v12_strips_embedded_enquadramento_label() -> None:
    """Rótulo embutido no composition legado some junto com o próprio bloco."""
    spec = ShotGenerationSpec(
        shot_id=uuid4(),
        scene_id=uuid4(),
        scene_title="Rua",
        scene_summary="A caminhada",
        duration_seconds=8,
        characters=["Antônio"],
        action="Antônio empurra o carrinho",
        emotion="urgência",
        visual_composition=(
            "Plano centrado em Antônio, no ambiente Rua do Bairro. "
            "Enquadramento vertical fiel à ação"
        ),
        camera_movement="",
        location="Rua do Bairro",
    )

    compiled = VibesPromptCompiler().compile(spec)

    # v12: sem bloco de enquadramento, o rótulo embutido também não aparece.
    assert "Enquadramento" not in compiled.prompt
    assert "Enquadramento…" not in compiled.prompt


@pytest.mark.asyncio
async def test_llm_extraction_receives_parser_hints(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured_prompts: list[str] = []

    class Provider:
        async def generate_structured(self, request):  # type: ignore[no-untyped-def]
            captured_prompts.append(request.prompt)
            from app.providers.llm.types import LLMResult

            return LLMResult(
                content={"characters": [], "locations": []},
                model="model",
                provider="provider",
            )

    async def configured_provider(*_args):  # type: ignore[no-untyped-def]
        return Provider(), "model"

    monkeypatch.setattr(
        "app.generation.model_settings.llm_provider_for_task",
        configured_provider,
    )

    await _llm_extract_characters_and_locations(
        SimpleNamespace(),
        uuid4(),
        "CENA 1\nINT. CASA - NOITE\nMÃE\nVolte aqui.\n",
    )

    assert captured_prompts, "esperava ao menos um request de extração"
    assert "CANDIDATOS DETECTADOS NO ROTEIRO" in captured_prompts[0]
    assert "Mãe" in captured_prompts[0]
    assert "Casa" in captured_prompts[0]