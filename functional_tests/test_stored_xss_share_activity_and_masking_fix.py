# test_stored_xss_share_activity_and_masking_fix.py
"""
Functional test for stored XSS sharing, activity, and masking hardening.
Version: 0.241.022
Implemented in: 0.241.020

This test ensures document-sharing modals, group activity rendering, and chat
masking metadata render attacker-controlled values as inert text and derive
masking identity from the authenticated server-side user.
"""

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
CHAT_TOAST_JS = ROOT_DIR / "application" / "single_app" / "static" / "js" / "chat" / "chat-toast.js"
CHAT_MESSAGES_JS = ROOT_DIR / "application" / "single_app" / "static" / "js" / "chat" / "chat-messages.js"
GROUP_MANAGE_JS = ROOT_DIR / "application" / "single_app" / "static" / "js" / "group" / "manage_group.js"
GROUP_SHARE_JS = ROOT_DIR / "application" / "single_app" / "static" / "js" / "workspace" / "group-documents-sharing.js"
WORKSPACE_SHARE_JS = ROOT_DIR / "application" / "single_app" / "static" / "js" / "workspace" / "workspace-documents-sharing.js"
CHAT_ROUTE = ROOT_DIR / "application" / "single_app" / "route_backend_chats.py"
CONFIG_FILE = ROOT_DIR / "application" / "single_app" / "config.py"
FIX_DOC = ROOT_DIR / "docs" / "explanation" / "fixes" / "v0.241.020" / "STORED_XSS_SHARE_ACTIVITY_AND_MASKING_FIX.md"


def read_text(path: Path) -> str:
    """Read a UTF-8 text file from the repository."""
    return path.read_text(encoding="utf-8")


def read_version() -> str:
    """Extract the application version from config.py."""
    for line in read_text(CONFIG_FILE).splitlines():
        if line.strip().startswith('VERSION = '):
            return line.split('"')[1]
    raise AssertionError("VERSION assignment was not found in config.py")


def assert_required_snippets(source: str, required_snippets: list[str], description: str) -> None:
    """Assert that all required snippets exist in the target source text."""
    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f"Missing {description} snippets: {missing}"


def assert_forbidden_snippets(source: str, forbidden_snippets: list[str], description: str) -> None:
    """Assert that forbidden snippets were removed from the target source text."""
    present = [snippet for snippet in forbidden_snippets if snippet in source]
    assert not present, f"Unexpected {description} snippets still present: {present}"


def test_chat_toast_uses_text_nodes_for_messages() -> None:
    """Verify the shared chat toast helper no longer interpolates raw HTML messages."""
    source = read_text(CHAT_TOAST_JS)

    assert_required_snippets(
        source,
        [
            'const toastEl = document.createElement("div");',
            'bodyEl.textContent = String(message ?? "");',
            'container.appendChild(toastEl);',
        ],
        "chat toast hardening",
    )
    assert_forbidden_snippets(
        source,
        [
            'container.insertAdjacentHTML("beforeend", toastHtml);',
            '${message}',
        ],
        "unsafe chat toast rendering",
    )


def test_document_share_modals_use_safe_rendering_and_delegated_clicks() -> None:
    """Verify personal and group share modals no longer rehydrate attacker HTML."""
    workspace_source = read_text(WORKSPACE_SHARE_JS)
    group_source = read_text(GROUP_SHARE_JS)

    assert_required_snippets(
        workspace_source,
        [
            "const userSearchResultsBody = document.querySelector('#userSearchResultsTable tbody');",
            "const sharedUsersList = document.getElementById('sharedUsersList');",
            "const addButton = e.target.closest('.user-search-add-btn');",
            "const removeButton = e.target.closest('.shared-user-remove-btn');",
            "displayNameCell.textContent = user.displayName || '';",
            "emailCell.textContent = user.email || '';",
            "toastBody.textContent = String(message ?? '');",
            "tbody.replaceChildren(...userRows);",
            "sharedUsersList.replaceChildren(...userRows);",
        ],
        "workspace share hardening",
    )
    assert_forbidden_snippets(
        workspace_source,
        [
            'onclick="addUserToDocument(',
            'onclick="removeUserFromDocument(',
            'toast.innerHTML = `',
        ],
        "unsafe workspace share rendering",
    )

    assert_required_snippets(
        group_source,
        [
            "const groupSearchResultsBody = document.querySelector('#groupSearchResultsTable tbody');",
            "const sharedGroupsList = document.getElementById('sharedGroupsList');",
            "const addButton = e.target.closest('.group-search-add-btn');",
            "const removeButton = e.target.closest('.shared-group-remove-btn');",
            "nameCell.textContent = group.name || '';",
            "descriptionCell.textContent = group.description || '';",
            "toastBody.textContent = String(message ?? '');",
            "tbody.replaceChildren(...groupRows);",
            "sharedGroupsList.replaceChildren(...groupRows);",
        ],
        "group share hardening",
    )
    assert_forbidden_snippets(
        group_source,
        [
            'onclick="addGroupToDocument(',
            'onclick="removeGroupFromDocument(',
            'toast.innerHTML = `',
        ],
        "unsafe group share rendering",
    )


def test_group_activity_timeline_uses_safe_text_rendering() -> None:
    """Verify activity rows and the raw-activity modal no longer use unsafe HTML sinks."""
    source = read_text(GROUP_MANAGE_JS)

    assert_required_snippets(
        source,
        [
            'const safeDescription = escapeHtml(description);',
            "const activityTimeline = $('#activityTimeline');",
            "activityTimeline.find('.activity-item').each(function(index) {",
            "$(this).data('activity', activities[index]);",
            '<div class="activity-item" role="button" tabindex="0">',
            "code.textContent = JSON.stringify(activity ?? {}, null, 2) || '{}';",
            'modalBody.replaceChildren(pre);',
        ],
        "group activity hardening",
    )
    assert_forbidden_snippets(
        source,
        [
            'data-activity=\'${activityJson.replace(/\'/g, "&apos;")}\'',
            'onclick="showRawActivity(this)"',
            'modalBody.innerHTML = `<pre><code>${JSON.stringify(activity, null, 2)}</code></pre>`;',
            '<p class="mb-0 text-muted small">${description}</p>',
        ],
        "unsafe group activity rendering",
    )


def test_masking_renderer_and_backend_identity_are_hardened() -> None:
    """Verify masked spans render safely and the backend ignores client-supplied display names."""
    chat_messages_source = read_text(CHAT_MESSAGES_JS)
    chat_route_source = read_text(CHAT_ROUTE)

    assert_required_snippets(
        chat_messages_source,
        [
            "const fragment = document.createDocumentFragment();",
            "fragment.appendChild(document.createTextNode(content.substring(lastIndex, range.start)));",
            "const maskedSpan = document.createElement('span');",
            "maskedSpan.setAttribute('data-display-name', String(range.display_name ?? ''));",
            "maskedSpan.title = `Masked by ${String(range.display_name ?? 'Unknown User')} on ${timestamp}`;",
            'messageText.replaceChildren(fragment);',
        ],
        "chat masking renderer hardening",
    )
    assert_forbidden_snippets(
        chat_messages_source,
        [
            'messageText.innerHTML = htmlContent;',
            'data-display-name="${range.display_name}"',
            'title="Masked by ${range.display_name} on ${timestamp}"',
        ],
        "unsafe chat masking rendering",
    )

    assert_required_snippets(
        chat_route_source,
        [
            'current_user = get_current_user_info() or {}',
            "current_user.get('displayName')",
            "current_user.get('email')",
            "current_user.get('userPrincipalName')",
        ],
        "masking backend identity hardening",
    )
    assert_forbidden_snippets(
        chat_route_source,
        [
            "user_display_name = data.get('display_name', 'Unknown User')",
        ],
        "client-controlled masking display name",
    )


def test_fix_documentation_and_version_are_in_sync() -> None:
    """Verify the version bump and fix documentation landed together."""
    version = read_version()
    assert version == "0.241.022", f"Expected config.py version 0.241.022, found {version}"
    assert FIX_DOC.exists(), f"Expected fix documentation file at {FIX_DOC}"

    fix_doc = read_text(FIX_DOC)
    assert "Fixed in version: **0.241.020**" in fix_doc
    assert "functional_tests/test_stored_xss_share_activity_and_masking_fix.py" in fix_doc
    assert "ui_tests/test_document_share_modal_escaping.py" in fix_doc


if __name__ == "__main__":
    tests = [
        test_chat_toast_uses_text_nodes_for_messages,
        test_document_share_modals_use_safe_rendering_and_delegated_clicks,
        test_group_activity_timeline_uses_safe_text_rendering,
        test_masking_renderer_and_backend_identity_are_hardened,
        test_fix_documentation_and_version_are_in_sync,
    ]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            print("PASS")
            results.append(True)
        except Exception as error:
            print(f"FAIL: {error}")
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)