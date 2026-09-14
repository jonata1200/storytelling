"""Testes do template generate_script: garante que ele instrui a IA a
devolver o campo 'title' no payload JSON. A remoção do título do roteiro
foi revertida para o fluxo da dashboard; ver skill title-and-prompt-editing."""

# ruff: noqa: F401

from app.generation.service import DEFAULT_TEMPLATES


def test_generate_script_template_requests_title_field_in_json_schema() -> None:
    template = DEFAULT_TEMPLATES["generate_script"]
    assert '"title"' in template, (
        "o template generate_script deve incluir o campo 'title' no schema "
        "JSON de resposta, para que a IA gere o nome do roteiro/projeto."
    )


def test_generate_script_template_instructs_llm_to_invent_short_ptbr_title() -> None:
    template = DEFAULT_TEMPLATES["generate_script"].lower()
    # Instrução explícita para gerar título próprio.
    assert "titulo" in template or "título" in template
    # Não pode mais conter a instrução antiga que proibia a IA de nomear.
    assert "o nome do projeto já é o título da história" not in template