from app.generation.prompt_compiler import compile_prompt
from app.generation.service import DEFAULT_TEMPLATES


def test_compile_prompt_keeps_missing_variables_visible() -> None:
    prompt = compile_prompt("Tema: {theme}. Publico: {audience}.", {"theme": "perdao"})

    assert prompt == "Tema: perdao. Publico: {audience}."


def test_default_generation_templates_with_json_examples_compile() -> None:
    variables = {
        "target_duration_minutes": 5,
        "theme": "perdao",
        "audience": "publico geral",
        "primary_emotion": "esperanca",
        "idea_title": "A carta",
        "idea": {"title": "A carta"},
        "language": "pt-BR",
        "target_duration_seconds": 300,
        "story_bible": {"title": "A carta"},
        "script": "Roteiro atual",
        "instruction": "melhore o gancho",
        "project_context": {"project": "A carta"},
        "current_script": "Roteiro atual",
    }

    compiled = {
        task: compile_prompt(template, variables)
        for task, template in DEFAULT_TEMPLATES.items()
    }

    assert '"content":"ROTEIRO COMPLETO AQUI"' in compiled["generate_script"]
    assert '"scenes"' in compiled["generate_scenes_and_shots"]
    assert '"ideas"' in compiled["generate_story_ideas"]
