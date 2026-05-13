# test_chat_collaboration_invite_toast_button.py
"""
UI test for collaboration invite toast button rendering.
Version: 0.241.153
Implemented in: 0.241.153

This test ensures DOM-based chat toast messages can render a clickable Review
invite button while untrusted conversation title text remains inert.
"""

from pathlib import Path

import pytest
from playwright.sync_api import expect


REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_TOAST_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-toast.js"


@pytest.mark.ui
def test_chat_collaboration_invite_toast_button_renders_safely(page):
    """Validate the chat toast helper renders DOM action content without executing title HTML."""
    toast_source = CHAT_TOAST_JS.read_text(encoding="utf-8")
    toast_source = toast_source.replace(
        "export function showToast(message, variant = \"danger\") {",
        "window.showToast = function showToast(message, variant = \"danger\") {",
    )
    assert "window.showToast = function showToast" in toast_source

    page.set_content(
        """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Collaboration Invite Toast Regression</title>
</head>
<body>
    <div class="toast-container position-fixed top-0 end-0 p-3" id="toast-container"></div>
    <div id="click-count">0</div>
    <script>
        window.bootstrap = {
            Toast: class {
                constructor(element) {
                    this.element = element;
                }

                show() {
                    this.element.classList.add('show');
                }
            }
        };
    </script>
</body>
</html>
""".strip()
    )
    page.add_script_tag(content=toast_source)

    page.evaluate(
        """
        () => {
            window.__xssFired = false;
            const maliciousTitle = '<img src=x onerror="window.__xssFired = true"> Incident Coordination';
            const fragment = document.createDocumentFragment();
            fragment.appendChild(document.createTextNode('You were invited to '));

            const titleEl = document.createElement('strong');
            titleEl.textContent = maliciousTitle;
            fragment.appendChild(titleEl);
            fragment.appendChild(document.createTextNode('. '));

            const actionButton = document.createElement('button');
            actionButton.type = 'button';
            actionButton.className = 'btn btn-sm btn-light ms-2';
            actionButton.textContent = 'Review invite';
            actionButton.addEventListener('click', () => {
                const countEl = document.getElementById('click-count');
                countEl.textContent = String(Number(countEl.textContent) + 1);
            });
            fragment.appendChild(actionButton);

            window.showToast(fragment, 'warning');
        }
        """
    )

    toast = page.locator("#toast-container .toast").last
    expect(toast).to_be_visible()
    expect(toast).to_contain_text("You were invited to")
    expect(toast.locator("strong")).to_have_text('<img src=x onerror="window.__xssFired = true"> Incident Coordination')
    expect(toast.get_by_role("button", name="Review invite")).to_be_visible()
    expect(toast.locator("img")).to_have_count(0)
    assert page.evaluate("window.__xssFired") is False

    toast.get_by_role("button", name="Review invite").click()
    expect(page.locator("#click-count")).to_have_text("1")