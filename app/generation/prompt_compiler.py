from collections.abc import Mapping


class SafeDict(dict[str, object]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def compile_prompt(template: str, variables: Mapping[str, object]) -> str:
    return template.format_map(SafeDict(variables))
