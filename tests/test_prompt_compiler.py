from app.generation.prompt_compiler import compile_prompt


def test_compile_prompt_keeps_missing_variables_visible() -> None:
    prompt = compile_prompt("Tema: {theme}. Publico: {audience}.", {"theme": "perdao"})

    assert prompt == "Tema: perdao. Publico: {audience}."
