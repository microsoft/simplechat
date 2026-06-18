# test_chat_model_icon_avatar.py
#!/usr/bin/env python3
"""
Functional test for chat model icon avatars.
Version: 0.242.071
Implemented in: 0.242.070

This test ensures saved model endpoint icons flow into chat assistant message
metadata and the chat renderer can use them as model avatars when no agent icon
is present, without replacing agent avatars on agent responses.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = REPO_ROOT / "application" / "single_app" / "config.py"
CHAT_ROUTE_FILE = REPO_ROOT / "application" / "single_app" / "route_backend_chats.py"
CHAT_MESSAGES_FILE = REPO_ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-messages.js"


def read_text(path: Path) -> str:
    """Read a UTF-8 repository file."""
    return path.read_text(encoding="utf-8")


def read_config_version() -> str:
    """Return the current app version from config.py."""
    for line in read_text(CONFIG_FILE).splitlines():
        if line.strip().startswith("VERSION = "):
            return line.split("=", 1)[1].strip().strip('"')
    raise AssertionError("VERSION assignment not found in config.py")


def test_backend_resolves_and_persists_model_icon_metadata() -> None:
    """Verify backend chat paths use saved model icons, not only agent icons."""
    source = read_text(CHAT_ROUTE_FILE)

    assert "def _normalize_model_icon_payload" in source
    assert "model_icon = _normalize_model_icon_payload(model_cfg.get('icon'))" in source
    assert source.count("'model_icon': gpt_model_icon") >= 6
    assert "'model_endpoint_id': gpt_endpoint_id or data.get('model_endpoint_id')" in source
    assert "'model_id': gpt_model_id or data.get('model_id')" in source
    assert read_config_version() == "0.242.071"


def test_frontend_uses_model_icon_for_assistant_avatar() -> None:
    """Verify chat rendering falls back to model icons for model-only replies."""
    source = read_text(CHAT_MESSAGES_FILE)

    assert "function resolveAssistantModelIcon" in source
    assert "fullMessageObject?.metadata?.model_selection?.model_icon" in source
    assert "findModelIconFromChatOptions" in source
    assert "function hasAssistantAgentIdentity" in source
    assert "hasAssistantAgentIdentity(fullMessageObject) ? null : resolveAssistantModelIcon(fullMessageObject)" in source
    assert "window.chatModelOptions" in source
    assert "model_icon: modelIcon" in source
    assert "model_icon: Object.keys(parsedIcon).length" in source
    assert "model-avatar" in source


def run_tests() -> bool:
    """Run standalone checks with readable output."""
    tests = [
        test_backend_resolves_and_persists_model_icon_metadata,
        test_frontend_uses_model_icon_for_assistant_avatar,
    ]
    results = []
    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            print("PASS")
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {exc}")
            results.append(False)
    return all(results)


if __name__ == "__main__":
    raise SystemExit(0 if run_tests() else 1)