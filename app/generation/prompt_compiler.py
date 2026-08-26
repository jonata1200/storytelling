import logging
from collections.abc import Mapping

logger = logging.getLogger(__name__)


class SafeDict(dict[str, object]):
    def __missing__(self, key: str) -> str:
        logger.warning("prompt_template_unresolved_placeholder: %s", key)
        return "{" + key + "}"


def compile_prompt(template: str, variables: Mapping[str, object]) -> str:
    return template.format_map(SafeDict(variables))
