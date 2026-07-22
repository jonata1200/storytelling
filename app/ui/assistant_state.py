from typing import Any, cast
from uuid import UUID

from nicegui import app as nicegui_app


def assistant_initial_message(
    active: str, assistant_suggestions: dict[str, str]
) -> dict[str, str]:
    return {
        "role": "assistant",
        "content": (
            "Estou acompanhando esta etapa. Posso revisar, propor variações "
            "e orientar a próxima ação mantendo a continuidade do projeto.\n\n"
            f"{assistant_suggestions.get(active, '')}"
        ),
    }


def assistant_chat_store() -> dict[str, list[dict[str, str]]]:
    raw_store = nicegui_app.storage.user.get("project_assistant_messages")
    if not isinstance(raw_store, dict):
        raw_store = {}
    return cast(dict[str, list[dict[str, str]]], raw_store)


def is_legacy_assistant_greeting(role: str, content: str) -> bool:
    return role == "assistant" and content.startswith("Estou acompanhando esta etapa.")


def load_assistant_messages(
    project_id: UUID, active: str, assistant_suggestions: dict[str, str]
) -> list[dict[str, str]]:
    store = assistant_chat_store()
    raw_messages = store.get(str(project_id), [])
    messages: list[dict[str, str]] = []
    for item in raw_messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")
        content = str(item.get("content") or "")
        if role == "assistant_pending":
            continue
        if is_legacy_assistant_greeting(role, content):
            continue
        if role and content:
            message = {"role": role, "content": content}
            event_id = item.get("event_id")
            if event_id:
                message["event_id"] = str(event_id)
            event_action = item.get("event_action")
            if event_action:
                message["event_action"] = str(event_action)
            messages.append(message)
    if not messages:
        messages.append(assistant_initial_message(active, assistant_suggestions))
    store[str(project_id)] = messages
    nicegui_app.storage.user["project_assistant_messages"] = store
    return messages


def save_assistant_messages(project_id: UUID, messages: list[dict[str, str]]) -> None:
    store = assistant_chat_store()
    store[str(project_id)] = [
        item for item in messages[-80:] if item["role"] != "assistant_pending"
    ]
    nicegui_app.storage.user["project_assistant_messages"] = store


def append_assistant_message_to_chat(project_id: UUID, content: str) -> None:
    message = content.strip()
    if not message:
        return
    store = assistant_chat_store()
    raw_messages = store.get(str(project_id), [])
    messages = [
        {"role": str(item.get("role") or ""), "content": str(item.get("content") or "")}
        for item in raw_messages
        if isinstance(item, dict)
    ]
    if (
        messages
        and messages[-1].get("role") == "assistant"
        and messages[-1].get("content") == message
    ):
        return
    messages.append({"role": "assistant", "content": message})
    store[str(project_id)] = messages[-80:]
    nicegui_app.storage.user["project_assistant_messages"] = store


def safe_refresh(refreshable: Any) -> None:
    try:
        refreshable.refresh()
    except RuntimeError as exc:
        if "parent element this slot belongs to has been deleted" not in str(exc).lower():
            raise


def safe_client_navigation(client: Any, target: str | None = None) -> None:
    try:
        if getattr(client, "is_deleted", False):
            return
        if target:
            client.open(target)
        else:
            client.run_javascript("history.go(0)")
    except RuntimeError as exc:
        if "parent element this slot belongs to has been deleted" not in str(exc).lower():
            raise


def sync_ai_action_events_to_chat(project_id: UUID, ai_action: dict[str, Any]) -> None:
    raw_events = ai_action.get("events", [])
    if not isinstance(raw_events, list):
        return
    store = assistant_chat_store()
    raw_messages = store.get(str(project_id), [])
    messages = [item for item in raw_messages if isinstance(item, dict)]
    known_event_ids = {
        str(item.get("event_id"))
        for item in messages
        if item.get("event_id") is not None
    }
    known_event_actions = {
        str(item.get("event_action"))
        for item in messages
        if item.get("event_action") is not None
    }
    changed = False
    for event in raw_events:
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("id") or "")
        event_action = str(event.get("action") or "")
        message = str(event.get("message") or "").strip()
        if (
            not event_id
            or not event_action
            or not message
            or event_id in known_event_ids
            or event_action in known_event_actions
        ):
            continue
        messages.append(
            {
                "role": "assistant",
                "content": message,
                "event_id": event_id,
                "event_action": event_action,
            }
        )
        known_event_ids.add(event_id)
        known_event_actions.add(event_action)
        changed = True
    if changed:
        store[str(project_id)] = cast(list[dict[str, str]], messages[-80:])
        nicegui_app.storage.user["project_assistant_messages"] = store
