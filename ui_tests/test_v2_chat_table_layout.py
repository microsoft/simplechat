# test_v2_chat_table_layout.py
"""
Real-component regressions for responsive V2 assistant tables.
Version: 0.261.439
Implemented in: 0.261.425
Native-title serialization regression added in: 0.261.439

Production MessageList, Markdown, stores and CSS run through the existing harness.
Only HTTP is stubbed. Shared fixtures support local and Azure Playwright.
"""

from pathlib import Path
import json
import sys

import pytest
from playwright.sync_api import expect

from test_v2_chat_message_scroll import (
    complete,
    frames,
    message,
    mount,
    push_content,
    root,
    start_stream,
)

# The browser case exercises the bootstrap-free production Python answer serializer.
APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))
from functions_native_audit import build_native_audit, decode_native_audit_answer, native_audit_contract  # noqa: E402

pytest_plugins = ("test_v2_chat_message_scroll",)
pytestmark = pytest.mark.ui
ARTIFACTS = Path(__file__).parent / "artifacts" / "v2-chat-tables"
IDENTIFIER = "catalog_and_tagged_state_" * 8
RECORD = '{"has_struct_tree":false,"is_tagged":false,"mark_info_state":"absent","struct_tree_state":"absent"}'
LONG_URL = "https://example.test/evidence/" + "source_record_" * 30
TABLE = (
    "Native file evidence\n\n"
    "| Location | Field | Source state | Exact value / supported record |\n"
    "| --- | --- | --- | --- |\n"
    f"| SC-C05.pdf; PDF catalog | {IDENTIFIER} | present_value | `{RECORD}` |\n"
    f"| SC-C05.pdf; inspection | reported_issue | present_value | [Source record]({LONG_URL}) |\n"
    f"| SC-C05.pdf; source | URL | present_value | {LONG_URL} |\n"
    "| SC-C05.pdf; page 1 | citation | present_value | "
    "(Source: SC-C05.pdf, Page: 1) [#table-document_1] |\n"
)
CITATIONS = [{
    "file_name": "SC-C05.pdf",
    "document_id": "table-document",
    "citation_id": "table-document_1",
    "page_number": 1,
}]


def prepare(page, api, width, theme="light", preference="wide"):
    page.set_viewport_size({"width": width, "height": 900})
    page.route("**/api/v2/orchestration/questions?*", lambda route: route.fulfill(
        json={"questions": [], "csrf_token": "fixture-token"},
    ))
    for path in ("v2/user-input/pending", "action-credentials/pending"):
        page.route(f"**/api/{path}?*", lambda route: route.fulfill(
            json={"requests": [], "csrf_token": "fixture-token"},
        ))
    page.add_init_script(
        f"localStorage.setItem('simplechat.v2.chat-width', '{preference}');"
    )
    mount(page, api, messages=[
        message("plain", "A short assistant response."),
        message("user", "A short user message.", role="user"),
        message("table", TABLE, hybrid_citations=CITATIONS),
    ])
    page.evaluate(
        "(dark) => document.documentElement.classList.toggle('dark', dark)",
        theme == "dark",
    )
    frames(page)


def table_geometry(page, selector="#message-table"):
    return page.locator(selector).evaluate(
        """(message) => {
            const table = message.querySelector('table');
            const bubble = table.closest('.glass-flat');
            const pane = message.closest('[data-tour="message-list"]');
            const wrapper = table.parentElement;
            const box = element => {
                const rect = element.getBoundingClientRect();
                return {left: rect.left, right: rect.right, width: rect.width};
            };
            const paneBox = box(pane);
            const paneStyle = getComputedStyle(pane);
            return {
                table: box(table), bubble: box(bubble), wrapper: box(wrapper),
                container: box(message.parentElement), pane: paneBox,
                paneContentLeft: paneBox.left + parseFloat(paneStyle.paddingLeft),
                paneContentRight: paneBox.right - parseFloat(paneStyle.paddingRight),
                paneScroll: pane.scrollWidth - pane.clientWidth,
                pageScroll: document.documentElement.scrollWidth - innerWidth,
                tableScroll: wrapper.scrollWidth - wrapper.clientWidth,
                cellOverflow: [...table.querySelectorAll('th,td')].map(cell =>
                    cell.scrollWidth - cell.clientWidth),
                narrowestCell: Math.min(...[...table.querySelectorAll('th,td')].map(cell =>
                    cell.getBoundingClientRect().width)),
                fontSize: getComputedStyle(table).fontSize,
            };
        }"""
    )


def assert_contained(page, selector="#message-table", *, scrolls=False):
    measured = table_geometry(page, selector)
    assert measured["bubble"]["left"] >= measured["paneContentLeft"] - 1, measured
    assert measured["bubble"]["right"] <= measured["paneContentRight"] + 1, measured
    assert measured["wrapper"]["right"] <= measured["bubble"]["right"] - 15, measured
    if scrolls:
        assert measured["tableScroll"] > 1, measured
    else:
        assert measured["table"]["right"] <= measured["bubble"]["right"] - 15, measured
        assert measured["tableScroll"] <= 1, measured
    assert max(measured["cellOverflow"]) <= 1, measured
    assert measured["narrowestCell"] >= 56, measured
    assert measured["paneScroll"] <= 1 and measured["pageScroll"] <= 1, measured
    assert measured["fontSize"] == "14px", measured
    return measured


@pytest.mark.parametrize("width", [393, 1440])
def test_native_title_with_pipe_remains_in_one_finding_cell(scroll_ui, width):
    page, api = scroll_ui
    title = "NASA-16 | Orbit-1 shift handover"
    report = {
        "document": {"id": "native-title", "file_name": "handover.pptx", "version": 1},
        "accessibility_metadata": {
            "format": "pptx", "schema_version": "2.0", "source_sha256": "c" * 64,
            "native_properties": {"title": {"state": "present_value", "value": title}},
        },
    }
    report["native_audit"] = build_native_audit(report)
    contract = native_audit_contract({"inspection": {"value": {
        "capability_id": "action_invoke",
        "citations": [{"function_name": "get_document_accessibility_report", "function_result": report}],
    }}})
    response = {
        "native_claims": {"scope": "all_returned", "fact_set_sha256": contract["fact_set_sha256"]},
        "answer": (
            f"| Property | Finding |\n| --- | --- |\n| Native title | `{title}` |\n"
            f"# Next: `{title}`"
        ),
    }
    _decoded, rendered = decode_native_audit_answer(json.dumps(response), contract, require_answer=True)
    prepare(page, api, width)
    page.evaluate(
        "(content) => window.OrchHarness.stores.chat.useChatStore.setState(state => "
        "({messages: state.messages.map(item => item.id === 'table' ? {...item, content} : item)}))",
        rendered,
    )
    finding = page.locator("#message-table table").first.locator("tbody tr").first
    expect(finding.locator("td")).to_have_count(2)
    expect(finding.locator("td").nth(1).locator("code")).to_have_text(title)
    expect(finding.locator("td").nth(0)).to_have_text("Native title")
    expect(page.locator("#message-table h1 code")).to_have_text(title)


@pytest.mark.parametrize("width,theme,preference,scrolls", [
    (320, "light", "wide", True),
    (393, "dark", "comfortable", False),
    (768, "light", "comfortable", False),
    (1280, "dark", "comfortable", False),
    (1920, "light", "wide", False),
])
def test_evidence_table_expands_and_wraps_inside_its_bubble(scroll_ui, width, theme, preference, scrolls):
    page, api = scroll_ui
    prepare(page, api, width, theme, preference)
    measured = assert_contained(page, scrolls=scrolls)
    assert measured["bubble"]["width"] == pytest.approx(measured["container"]["width"], abs=1)
    table = page.locator("#message-table table")
    expect(table.locator("tbody tr")).to_have_count(4)
    expect(table.locator("code")).to_have_text(RECORD)
    expect(table.get_by_role("link", name="Source record", exact=True)).to_have_attribute("href", LONG_URL)
    expect(table.get_by_title("SC-C05.pdf — Page 1", exact=True)).to_be_visible()
    assert page.locator("#message-plain .glass-flat").bounding_box()["width"] < measured["bubble"]["width"]
    assert page.locator("#message-user .bg-accent").bounding_box()["width"] < measured["bubble"]["width"]
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    root(page).evaluate(
        """pane => {
            pane.scrollTop += pane.querySelector('#message-table').getBoundingClientRect().top
                - pane.getBoundingClientRect().top;
        }"""
    )
    root(page).screenshot(path=str(ARTIFACTS / f"evidence-{width}-{theme}-{preference}.png"))


def test_text_and_code_wrap_without_scrolling_at_320_pixels(scroll_ui):
    page, api = scroll_ui
    prepare(page, api, 320)
    # The citation chip has a non-wrapping label; ordinary cell text does not.
    content = TABLE.split("\n| SC-C05.pdf; page 1", 1)[0]
    page.evaluate(
        "(content) => window.OrchHarness.stores.chat.useChatStore.setState(state => "
        "({messages: state.messages.map(item => item.id === 'table' ? {...item, content} : item)}))",
        content,
    )
    expect(page.locator("#message-table tbody tr")).to_have_count(3)
    assert_contained(page)


def test_resizing_preserves_table_content_and_normal_message_widths(scroll_ui):
    page, api = scroll_ui
    prepare(page, api, 1920)
    plain = page.locator("#message-plain .glass-flat").bounding_box()["width"]
    user = page.locator("#message-user .bg-accent").bounding_box()["width"]
    for width in (393, 768, 1920):
        page.set_viewport_size({"width": width, "height": 900})
        frames(page)
        assert_contained(page)
        expect(page.locator("#message-table table")).to_contain_text(IDENTIFIER)
        expect(page.locator("#message-table table code")).to_have_text(RECORD)
    assert page.locator("#message-plain .glass-flat").bounding_box()["width"] == pytest.approx(plain)
    assert page.locator("#message-user .bg-accent").bounding_box()["width"] == pytest.approx(user)


def test_streaming_finalized_and_reloaded_tables_use_the_same_layout(scroll_ui):
    page, api = scroll_ui
    prepare(page, api, 1280)
    start_stream(page)
    push_content(page, "Native file evidence\n\n| Location | Field |")
    push_content(page, TABLE)
    expect(page.locator("[data-scroll-live-reply] table")).to_be_visible()
    assert_contained(page, "[data-scroll-live-reply]")
    complete(page, TABLE, message_id="finished-table")
    expect(page.locator("[data-scroll-live-reply]")).to_have_count(0)
    finished = assert_contained(page, "#message-finished-table")
    mount(page, api, messages=[message("finished-table", TABLE)])
    reloaded = assert_contained(page, "#message-finished-table")
    assert reloaded["bubble"]["width"] == pytest.approx(finished["bubble"]["width"])


def test_unavoidably_wide_table_scrolls_locally_by_keyboard(scroll_ui):
    page, api = scroll_ui
    prepare(page, api, 393)
    columns = 30
    content = (
        "| " + " | ".join(f"Column {index}" for index in range(columns)) + " |\n"
        "| " + " | ".join("---" for _ in range(columns)) + " |\n"
        "| " + " | ".join(f"Value {index}" for index in range(columns)) + " |\n"
    )
    page.evaluate(
        "(content) => window.OrchHarness.stores.chat.useChatStore.setState(state => "
        "({messages: state.messages.map(item => item.id === 'table' ? {...item, content} : item)}))",
        content,
    )
    wrapper = page.locator("#message-table").get_by_role("region", name="Table", exact=True)
    expect(wrapper).to_be_visible()
    measured = table_geometry(page)
    assert measured["tableScroll"] > 0, measured
    assert measured["wrapper"]["right"] <= measured["bubble"]["right"] - 15, measured
    assert measured["paneScroll"] <= 1 and measured["pageScroll"] <= 1, measured
    wrapper.focus()
    expect(wrapper).to_be_focused()
    for _ in range(columns * 2):
        wrapper.press("ArrowRight")
    page.wait_for_function(
        """() => {
            const wrapper = document.querySelector('#message-table [role="region"]');
            return wrapper.scrollLeft > 0 &&
                wrapper.scrollWidth - wrapper.clientWidth - wrapper.scrollLeft <= 1;
        }"""
    )
    last_cell = wrapper.locator("tbody td").last.bounding_box()
    bounds = wrapper.bounding_box()
    assert last_cell["x"] + last_cell["width"] <= bounds["x"] + bounds["width"] + 1
