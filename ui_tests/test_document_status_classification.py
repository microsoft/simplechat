# test_document_status_classification.py
"""
Browser coverage for shared classic document status interpretation.
Version: 0.261.354
Implemented in: 0.261.354

Exercise real group views and personal/public/card status predicates with local
assets and intercepted APIs, including in-progress, failed and completed states.
"""

import re

import pytest
from playwright.sync_api import expect

from test_group_document_filename_xss_rendering import (  # noqa: F401
    APP_ROOT, VIEWS, _document, _render, group_page, group_render_sources,
)
from test_v2_chat_context_selection import connect_options  # noqa: F401


pytestmark = pytest.mark.ui


@pytest.mark.parametrize("view", VIEWS)
@pytest.mark.parametrize("filename", ["error-budget.md", "failed-policy.md", "incomplete-policy.md"])
def test_group_views_do_not_enable_ready_actions_from_filename(group_page, view, filename):
    page, state = group_page
    record = _document(filename, status=f"Processing file {filename}, type: .md", percentage_complete=0)
    rows = _render(group_page, view, [record])
    expect(rows.first.locator("a.dropdown-item").filter(has_text=re.compile(r"^\s*Share"))).to_have_count(0)
    if view == "list":
        assert page.evaluate("window.__pollCallbacks.size") == 1
        state["documents"] = [{**record, "status": "Processing complete", "percentage_complete": 100}]
        page.evaluate("() => window.__pollCallbacks.forEach(callback => callback())")
        expect(rows.first.locator("a.dropdown-item").filter(has_text=re.compile(r"^\s*Share"))).to_have_count(1)


@pytest.mark.parametrize(("relative", "function"), [
    ("static/js/workspace/workspace-documents.js", "getDocumentProcessingState"),
    ("static/js/public/public_workspace.js", "getPublicDocumentProcessingState"),
])
def test_personal_and_public_processing_flags(page, relative, function):
    source = APP_ROOT.joinpath(*relative.split("/")).read_text(encoding="utf-8")
    start = source.index(f"function {function}(")
    end = source.index("\n}", start) + len("\n}")
    page.set_content('<main aria-label="Document status"></main>')
    page.add_script_tag(path=str(APP_ROOT / "static" / "js" / "document-status.js"))
    page.add_script_tag(content=source[start:end])
    for status in [
        "Processing file error-budget.md, type: .md",
        "Processing file failed-checklist.md, type: .md",
        "Processing file processing complete.md, type: .md",
        "Retrying Markdown processing after a transient parser concurrency error (1/3)...",
    ]:
        result = page.evaluate(
            "({name, status}) => window[name]({status, percentage_complete: 0})",
            {"name": function, "status": status},
        )
        assert result["hasError"] is False
        assert result["isComplete"] is False
    failure = page.evaluate(
        "(name) => window[name]({status: 'Error: unavailable', percentage_complete: 100})", function,
    )
    assert failure["hasError"] is True
    assert failure["isComplete"] is True


def test_classic_chat_card_polls_instead_of_completing_from_details(page):
    source = (APP_ROOT / "static" / "js" / "chat" / "chat-messages.js").read_text(encoding="utf-8")
    start = source.index("function getChatWorkspaceProgressValue(")
    end = source.index("function normalizeChatWorkspaceDocumentResponse(")
    page.set_content('<main aria-label="Chat"></main>')
    page.add_script_tag(path=str(APP_ROOT / "static" / "js" / "document-status.js"))
    page.add_script_tag(content=source[start:end])
    for status in [
        "Processing file error-budget.md, type: .md",
        "Processing file incomplete-policy.md, type: .md",
        "Retrying Markdown processing after a transient parser concurrency error (1/3)...",
        "Vision analysis completed (no results)",
    ]:
        result = page.evaluate(
            """(status) => {
                const doc = {status, percentage_complete: 0};
                return [isChatWorkspaceDocumentComplete(doc), isChatWorkspaceDocumentFailure(doc),
                    isChatWorkspaceDocumentSuccessComplete(doc)];
            }""", status,
        )
        assert result == [False, False, False]
