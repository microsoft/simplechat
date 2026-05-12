# test_collaboration_invite_toast_button_fix.py
"""
Functional test for collaboration invite toast button rendering.
Version: 0.241.153
Implemented in: 0.241.153

This test ensures pending collaboration invite toasts build their Review invite
button with DOM APIs and keep conversation titles out of executable HTML sinks.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_COLLABORATION_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-collaboration.js"
CHAT_TOAST_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-toast.js"


def read_text(path):
    """Read a source file as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def test_collaboration_invite_toast_uses_safe_dom_button():
    """Validate invite toast button rendering uses DOM APIs instead of HTML strings."""
    collaboration_content = read_text(CHAT_COLLABORATION_JS)
    toast_content = read_text(CHAT_TOAST_JS)

    assert "const messageFragment = document.createDocumentFragment();" in collaboration_content, (
        "Expected pending invite toast content to be assembled as a DOM fragment."
    )
    assert "titleEl.textContent = conversation.title || 'a collaborative conversation';" in collaboration_content, (
        "Expected collaboration conversation titles to be assigned with textContent."
    )
    assert "const actionButton = document.createElement('button');" in collaboration_content, (
        "Expected the Review invite action to be a DOM button element."
    )
    assert "actionButton.addEventListener('click', async event =>" in collaboration_content, (
        "Expected the Review invite button to bind its click handler directly."
    )
    assert "showToast(messageFragment, 'warning');" in collaboration_content, (
        "Expected pending invite toasts to pass the DOM fragment to the toast helper."
    )
    assert "You were invited to <strong>" not in collaboration_content, (
        "Did not expect invite toast markup to be interpolated into an HTML string."
    )
    assert "bodyEl.appendChild(message);" in toast_content, (
        "Expected the shared chat toast helper to render DOM Node messages."
    )
    assert "bodyEl.textContent = String(message ?? \"\");" in toast_content, (
        "Expected plain string toast messages to continue rendering as inert text."
    )

    print("✅ Collaboration invite toast button rendering verified.")


if __name__ == "__main__":
    test_collaboration_invite_toast_uses_safe_dom_button()
    sys.exit(0)