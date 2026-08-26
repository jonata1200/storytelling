from app.storytelling.normalization_common import (
    GenerationOutputError,
    _required_list,
    _required_mapping,
    _required_str,
)

STORY_HOOK_MIN_COUNT = 5
STORY_HOOK_MAX_COUNT = 8
STORY_HOOK_MAX_TITLE_LENGTH = 120
STORY_HOOK_MAX_DESCRIPTION_LENGTH = 500


def _hook_similarity_key(value: str) -> str:
    text = str(value or "").casefold().strip()
    tokens = [token for token in text.split() if token]
    return " ".join(tokens[:14])


def normalize_story_hooks_payload(content: dict) -> list[dict]:
    """Valida a resposta da IA para a tarefa ``generate_story_hooks``.

    Exige pelo menos ``STORY_HOOK_MIN_COUNT`` ganchos com ``title`` e
    ``description`` preenchidos, remove duplicatas por título e limita o
    tamanho dos campos para não inchar o prompt do roteiro.
    """
    raw_hooks = _required_list(content, "hooks", "generate_story_hooks")
    errors: list[str] = []
    hooks: list[dict] = []
    seen: set[str] = set()
    for index, raw_hook in enumerate(raw_hooks, 1):
        context = f"generate_story_hooks.hooks[{index}]"
        try:
            hook = _required_mapping(raw_hook, context)
        except GenerationOutputError as exc:
            errors.append(str(exc))
            continue
        title = _required_str(hook, "title", context).strip()
        description = _required_str(hook, "description", context).strip()
        if not title or not description:
            errors.append(f"{context}: title e description precisam estar preenchidos")
            continue
        key = _hook_similarity_key(title)
        if key in seen:
            continue
        seen.add(key)
        hooks.append(
            {
                "title": title[:STORY_HOOK_MAX_TITLE_LENGTH],
                "description": description[:STORY_HOOK_MAX_DESCRIPTION_LENGTH],
            }
        )
    if len(hooks) < STORY_HOOK_MIN_COUNT:
        errors.append(
            f"generate_story_hooks: esperado pelo menos {STORY_HOOK_MIN_COUNT} "
            f"ganchos válidos, recebidos {len(hooks)}"
        )
    if len(hooks) > STORY_HOOK_MAX_COUNT:
        hooks = hooks[:STORY_HOOK_MAX_COUNT]
    if errors:
        raise GenerationOutputError("; ".join(errors))
    return hooks
