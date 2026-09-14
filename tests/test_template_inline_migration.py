"""Testes da migração inline do template generate_script persistido.

A skill title-and-prompt-editing alerta: templates persistidos em
prompt_templates não são sobrescritos por DEFAULT_TEMPLATES. Para que a
mudança do campo 'title' chegue aos projetos existentes, fazemos um
update inline no startup que detecta a presença da instrução antiga
(proibia a IA de nomear) e substitui pela nova.

Só atualizamos se o template persistido ainda contém a instrução antiga
— customizações do operador ficam intactas.
"""

# ruff: noqa: F401, I001

from types import SimpleNamespace
from typing import Any

import pytest

from app.generation import service as generation_service

OLD_INSTRUCTION = "o nome do projeto já é o título da história"


@pytest.mark.asyncio
async def test_inline_migrate_updates_persisted_template_with_old_instruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRow:
        def __init__(self, text: str) -> None:
            self.template_text = text

        task = "generate_script"
        version = 1

    old_text = "algum texto " + OLD_INSTRUCTION + " mais coisa"
    new_text = generation_service.DEFAULT_TEMPLATES["generate_script"]
    fake_row = FakeRow(old_text)

    class FakeSession:
        def __init__(self) -> None:
            self.commits = 0
            self.last_set: str | None = None

        async def execute(self, query: Any, params: Any = None) -> Any:
            # Primeira chamada: lookup do template.
            class FakeResult:
                def scalars(self) -> "FakeResult":
                    return self

                def first(self) -> FakeRow:
                    return fake_row

            return FakeResult()

        async def commit(self) -> None:
            self.commits += 1

    session = FakeSession()  # type: ignore[arg-type]

    # Importa a função de migração; será implementada em seguida.
    from app.generation.service import migrate_persisted_generate_script_template

    await migrate_persisted_generate_script_template(session)  # type: ignore[arg-type]

    assert fake_row.template_text == new_text, (
        "o template persistido com a instrução antiga deve ser atualizado "
        "para o DEFAULT_TEMPLATES atual."
    )
    assert session.commits == 1


@pytest.mark.asyncio
async def test_inline_migrate_does_not_overwrite_custom_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Template persistido que NÃO contém a instrução antiga foi editado pelo
    operador — não podemos sobrescrever."""

    class FakeRow:
        task = "generate_script"
        version = 1
        template_text = "template customizado pelo operador, sem instrucao antiga"

    custom_text = "template customizado pelo operador, sem instrucao antiga"
    fake_row = FakeRow()

    class FakeSession:
        async def execute(self, query: Any, params: Any = None) -> Any:
            class FakeResult:
                def scalars(self) -> "FakeResult":
                    return self

                def first(self) -> FakeRow:
                    return fake_row

            return FakeResult()

        async def commit(self) -> None:
            pass

    session = FakeSession()  # type: ignore[arg-type]
    from app.generation.service import migrate_persisted_generate_script_template

    await migrate_persisted_generate_script_template(session)  # type: ignore[arg-type]

    assert fake_row.template_text == custom_text, (
        "templates sem a instrução antiga não devem ser sobrescritos "
        "(possível customização do operador)."
    )