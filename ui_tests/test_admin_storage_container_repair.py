# test_admin_storage_container_repair.py
"""V1/V2 browser regressions for explicit, saved-settings-only storage repair.

Version: 0.261.396
Implemented in: 0.261.396

The real built SPA and classic handler run over intercepted APIs. The shared
connect_options fixture supports local or configured Azure Playwright.
No live settings or containers are changed.
"""

from pathlib import Path
import re
import sys

import pytest
from playwright.sync_api import expect


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
from v2_admin_settings import AdminSettingsFixture, connect_options  # noqa: E402,F401


pytestmark = pytest.mark.ui
REPAIR = "/api/admin/settings/storage/repair-containers"
TEST = "/api/admin/settings/test_connection"


def storage_result(page):
    return page.get_by_role("region", name="Enhanced", exact=True).get_by_role("status")


@pytest.fixture
def storage_ui(page):
    fixture = AdminSettingsFixture(page, sections={"chat": ("enhanced-citations-section",)})
    fixture.settings.update({
        "enable_enhanced_citations": True,
        "office_docs_authentication_type": "managed_identity",
        "office_docs_storage_account_blob_endpoint": "https://fixture.blob.core.windows.net",
    })
    yield fixture
    fixture.assert_clean()


@pytest.mark.parametrize("theme,width", [("light", 1440), ("dark", 390)])
def test_v2_repair_is_explicit_and_coalesces_browser_submissions(storage_ui, theme, width):
    held = []
    storage_ui.extra_routes[("POST", REPAIR)] = lambda route: held.append(route)
    storage_ui.open(theme=theme, width=width, ready_region="Enhanced")
    page = storage_ui.page
    assert held == []
    repair = page.get_by_role("button", name="Create missing containers", exact=True)
    test = page.get_by_role("button", name="Test storage connection", exact=True)
    repair.focus()
    repair.press("Enter")
    expect(page.get_by_role("button", name="Creating", exact=False)).to_be_disabled()
    expect(test).to_be_disabled()
    assert len(held) == 1 and held[0].request.post_data_json == {}
    held.pop().fulfill(json={
        "success": True, "message": "Storage is ready.",
        "details": ["personal-chat: created", "user-documents: already exists"],
        "guidance": ["Retry the failed analysis when you are ready."],
    })
    expect(storage_result(page)).to_contain_text("personal-chat: created")
    expect(repair).to_be_enabled()
    assert storage_ui.patches == []


def test_v2_storage_draft_requires_save_but_read_only_test_still_works(storage_ui):
    tests = []

    def tested(route):
        tests.append(route.request.post_data_json)
        route.fulfill(json={"success": True, "message": "Connection tested without creating containers."})

    storage_ui.extra_routes[("POST", TEST)] = tested
    storage_ui.open(ready_region="Enhanced")
    page = storage_ui.page
    page.get_by_role("combobox", name="Storage Account Authentication Type").select_option("key")
    expect(page.get_by_role("button", name="Create missing containers", exact=True)).to_be_disabled()
    expect(page.get_by_text("Save storage settings before creating containers.", exact=True)).to_be_visible()
    page.get_by_role("button", name="Test storage connection", exact=True).click()
    expect(storage_result(page)).to_contain_text("without creating containers")
    assert len(tests) == 1 and tests[0]["authentication_type"] == "key"
    assert storage_ui.patches == []


@pytest.mark.parametrize("status", [200, 503])
def test_v2_partial_repair_keeps_failed_container_and_recovery_visible(storage_ui, status):
    storage_ui.extra_routes[("POST", REPAIR)] = lambda route: route.fulfill(status=status, json={
        "success": False, "error": "Some storage containers could not be prepared.",
        "details": ["user-documents: already exists", "personal-chat: failed"],
        "guidance": ["Check the app's storage permissions, then try again."],
    })
    storage_ui.open(ready_region="Enhanced")
    page = storage_ui.page
    page.get_by_role("button", name="Create missing containers", exact=True).click()
    expect(storage_result(page)).to_contain_text("personal-chat: failed")
    expect(storage_result(page)).to_contain_text("storage permissions")
    expect(storage_result(page).locator("p").first).to_have_class(re.compile(r"\btext-danger\b"))
    expect(page.get_by_role("button", name="Create missing containers", exact=True)).to_be_enabled()
    expected_error = "Failed to load resource: the server responded with a status of 503 (Service Unavailable)"
    if status == 503:
        assert storage_ui.errors.count(expected_error) == 1, storage_ui.errors
        storage_ui.errors.remove(expected_error)


def test_classic_repair_handler_uses_saved_settings_and_safe_inline_feedback(page):
    """Run the production classic handler with its unrelated page helpers isolated."""
    source = (ROOT / "application" / "single_app" / "static" / "js" / "admin" / "admin_settings.js").read_text(
        encoding="utf-8",
    )
    handler = source.split("    const testEnhancedCitationsStorageBtn =", 1)[1].split(
        "    const testGptBtn =", 1,
    )[0]
    script = r'''
const getFieldValue = (id) => document.getElementById(id).value;
const buildEnhancedCitationsStoragePayload = () => ({
    authentication_type: getFieldValue('office_docs_authentication_type'),
    connection_string: getFieldValue('office_docs_storage_account_url'),
    blob_endpoint: getFieldValue('office_docs_storage_account_blob_endpoint')
});
const setButtonBusy = (button, busy) => { button.disabled = busy; };
const renderAdminTestLoading = (target, message) => { target.textContent = message; };
const renderAdminTestResult = (target, result) => {
    target.textContent = [result.message, ...(result.details || []), ...(result.guidance || [])].join('\n');
};
const runEnhancedCitationsStorageTest = () => {};
const testEnhancedCitationsStorageBtn = __HANDLER__
'''.replace("__HANDLER__", handler)
    page.route("http://simplechat.test/classic-storage", lambda route: route.fulfill(
        content_type="text/html", body="""
        <select id="office_docs_authentication_type"><option value="key">Key</option><option value="managed_identity">Identity</option></select>
        <input id="office_docs_storage_account_url" value="saved-placeholder">
        <input id="office_docs_storage_account_blob_endpoint" value="">
        <button id="test_enhanced_citations_storage_button">Test Enhanced Citations Storage</button>
        <button id="repair_enhanced_citations_storage_button">Create missing containers</button>
        <p id="repair_enhanced_citations_storage_help"></p>
        <div id="test_enhanced_citations_storage_result" role="status"></div>
        """,
    ))
    held = []
    page.route(f"**{REPAIR}", lambda route: held.append(route))
    page.goto("http://simplechat.test/classic-storage")
    page.add_script_tag(content=script)
    repair = page.get_by_role("button", name="Create missing containers")
    repair.click()
    expect(repair).to_be_disabled()
    expect(page.get_by_role("button", name="Test Enhanced Citations Storage")).to_be_disabled()
    assert len(held) == 1 and held[0].request.post_data_json == {}
    held.pop().fulfill(json={
        "success": True, "message": "Storage is ready.", "details": ["personal-chat: created"],
    })
    expect(page.get_by_role("status")).to_contain_text("personal-chat: created")
    expect(repair).to_be_enabled()
    page.locator("#office_docs_storage_account_url").fill("unsaved")
    expect(repair).to_be_disabled()
    expect(page.locator("#repair_enhanced_citations_storage_help")).to_contain_text("Save storage settings")
