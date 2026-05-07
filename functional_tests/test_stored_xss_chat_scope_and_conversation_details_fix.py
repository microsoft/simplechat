# test_stored_xss_chat_scope_and_conversation_details_fix.py
"""
Functional test for chat scope-lock and conversation-details XSS hardening.
Version: 0.241.022
Implemented in: 0.241.019

This test ensures stored workspace and conversation metadata values are encoded
before the scope-lock modal and conversation-details modal render HTML.
"""

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
CHAT_DOCUMENTS_JS = ROOT_DIR / "application" / "single_app" / "static" / "js" / "chat" / "chat-documents.js"
CHAT_CONVERSATION_DETAILS_JS = ROOT_DIR / "application" / "single_app" / "static" / "js" / "chat" / "chat-conversation-details.js"
CONFIG_FILE = ROOT_DIR / "application" / "single_app" / "config.py"
FIX_DOC = ROOT_DIR / "docs" / "explanation" / "fixes" / "v0.241.020" / "CHAT_SCOPE_LOCK_AND_CONVERSATION_DETAILS_XSS_FIX.md"


def read_text(path: Path) -> str:
    """Read a UTF-8 text file from the repository."""
    return path.read_text(encoding="utf-8")


def read_version() -> str:
    """Extract the application version from config.py."""
    for line in read_text(CONFIG_FILE).splitlines():
        if line.strip().startswith('VERSION = '):
            return line.split('"')[1]
    raise AssertionError("VERSION assignment was not found in config.py")


def test_scope_lock_modal_renders_workspace_names_with_text_nodes() -> None:
    """Verify the scope-lock modal no longer interpolates workspace names into HTML."""
    source = read_text(CHAT_DOCUMENTS_JS)

    required_snippets = [
        "workspaceItems.push({ icon, name });",
        "nameEl.textContent = name;",
        "listItemEl.appendChild(nameEl);",
        "listGroupEl.appendChild(listItemEl);",
    ]
    forbidden_snippets = [
        "workspaceItems.push(`<li class=\"list-group-item\"><i class=\"bi ${icon} me-2\"></i>${name}</li>`);",
        "listEl.innerHTML = `<p class=\"small text-muted mb-2\">${listLabel}</p><ul class=\"list-group list-group-flush\">${workspaceItems.join('')}</ul>`;",
    ]

    for snippet in required_snippets:
        assert snippet in source, f"Expected safe scope-lock rendering snippet: {snippet}"

    for snippet in forbidden_snippets:
        assert snippet not in source, f"Unexpected unsafe scope-lock rendering snippet: {snippet}"


def test_conversation_details_modal_escapes_untrusted_metadata_fields() -> None:
    """Verify the conversation-details renderer escapes the user-controlled fields in this fix."""
    source = read_text(CHAT_CONVERSATION_DETAILS_JS)

    required_snippets = [
        "const safeConversationTitle = escapeHtml(metadata.title || 'Conversation Details');",
        "escapeHtml(error.message || 'Unknown error')",
        "const safeConversationId = escapeHtml(conversationId);",
        "const safeDisplayName = escapeHtml(displayName);",
        "const safeParticipantName = escapeHtml(participant.name || 'Unknown User');",
        "const safeDocumentTitle = escapeHtml(documentTitle);",
        "const safeClassification = escapeHtml(doc.classification || 'None');",
        "const safeSourceUrl = sanitizeHttpUrl(sourceValue);",
        "href=\"${escapeHtml(safeSourceUrl)}\"",
        "names.map(name => escapeHtml(name)).join(', ')",
    ]
    forbidden_snippets = [
        "${metadata.title || 'Conversation Details'}",
        "<span class=\"fw-bold\">${displayName}</span>",
        "<div class=\"fw-semibold\">${participant.name || 'Unknown User'}</div>",
        "title=\"${documentTitle}\">${documentTitle}</div>",
        "${doc.scope?.type} scope: <strong>${scopeName}</strong>",
        "<span class=\"badge bg-dark\">${tag.value}</span>",
        "<a href=\"${source.value}\" target=\"_blank\" rel=\"noopener noreferrer\" class=\"text-decoration-none\">",
        "names.join(', ')",
    ]

    for snippet in required_snippets:
        assert snippet in source, f"Expected safe conversation-details snippet: {snippet}"

    for snippet in forbidden_snippets:
        assert snippet not in source, f"Unexpected unsafe conversation-details snippet: {snippet}"


def test_fix_documentation_and_version_are_in_sync() -> None:
    """Verify the version bump and fix documentation were added together."""
    version = read_version()
    assert version == "0.241.022", f"Expected config.py version 0.241.022, found {version}"
    assert FIX_DOC.exists(), f"Expected fix documentation file at {FIX_DOC}"

    fix_doc = read_text(FIX_DOC)
    assert "Fixed in version: **0.241.019**" in fix_doc
    assert "functional_tests/test_stored_xss_chat_scope_and_conversation_details_fix.py" in fix_doc
    assert "ui_tests/test_chat_scope_lock_and_conversation_details_escaping.py" in fix_doc


if __name__ == "__main__":
    tests = [
        test_scope_lock_modal_renders_workspace_names_with_text_nodes,
        test_conversation_details_modal_escapes_untrusted_metadata_fields,
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