# test_terms_of_use_activity_logs.py
"""
Terms of Use revision visibility in Activity Logs (#1616).
Version: 0.261.051
Implemented in: 0.261.050

Exercises the real Control Center module with offline API fixtures and local
assets. Reuses the Terms UI suite's Azure Playwright/local Chromium fixture.
"""

import ast
import csv
import io
import mimetypes
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, unquote, urlsplit

from playwright.sync_api import expect
import pytest

from test_terms_of_use_ui import terms_browser


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from functions_terms_of_use_config import format_terms_of_use_version
ORIGIN = "http://simplechat.test"
pytestmark = pytest.mark.ui
OLD_REVISION = "a" * 64
NEW_REVISION = "b" * 64


@pytest.fixture
def activity_page(terms_browser):
    context = terms_browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    errors = []
    external = []
    filters = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_init_script("window.appSettings = {};")
    records = [
        {
            "id": f"terms-{index}", "activity_type": activity_type,
            "terms_hash": revision, "frequency": "once", "source": "post_auth",
            "terms_version": version,
            "user_id": "reader", "timestamp": "2026-10-02T12:00:00Z",
        }
        for index, (activity_type, revision, version) in enumerate([
            ("terms_of_use_accepted", OLD_REVISION, 1),
            ("terms_of_use_accepted", NEW_REVISION, 2),
            ("terms_of_use_declined", NEW_REVISION, 2),
        ])
    ]
    template = (APP_ROOT / "templates" / "control_center.html").read_text(encoding="utf-8")
    selector = re.search(r'<select\b[^>]*id="activityTypeFilterSelect".*?</select>', template, re.DOTALL).group()
    html = f"""<!DOCTYPE html><html lang="en"><head>
        <link rel="stylesheet" href="/static/css/bootstrap.min.css">
        <script src="/static/js/bootstrap/bootstrap.bundle.min.js"></script>
        </head><body>
        {selector}
        <button id="exportActivityLogsBtn">Export</button>
        <table><tbody id="activityLogsTableBody"></tbody></table>
        <div id="activityLogsPaginationInfo"></div><div id="activityLogsPagination"></div>
        <div class="modal fade" id="rawLogModal" tabindex="-1">
            <div class="modal-dialog modal-xl"><div class="modal-content">
                <div class="modal-header"><h2 id="rawLogModalTitle"></h2>
                    <button type="button" data-bs-dismiss="modal">Close</button>
                </div><div id="rawLogModalBody" class="modal-body"></div>
            </div></div>
        </div></body></html>"""
    tree = ast.parse((APP_ROOT / "route_backend_control_center.py").read_text(encoding="utf-8"))
    formatter = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "format_activity_log_details_for_csv")
    namespace = {"format_terms_of_use_version": format_terms_of_use_version}
    exec(compile(ast.Module(body=[formatter], type_ignores=[]), "activity_csv", "exec"), namespace)

    def route_request(route):
        url = urlsplit(route.request.url)
        if f"{url.scheme}://{url.netloc}" != ORIGIN:
            external.append(route.request.url)
            route.abort()
            return
        if url.path.startswith("/static/"):
            asset = (APP_ROOT / unquote(url.path.lstrip("/"))).resolve()
            assert asset.is_relative_to(APP_ROOT) and asset.is_file()
            body = asset.read_bytes()
            if url.path == "/static/js/control-center.js":
                # Expose the real class for the fixture without changing its implementation.
                body += b"\nexport { ControlCenter };\n"
            route.fulfill(body=body, content_type=mimetypes.guess_type(asset.name)[0] or "application/octet-stream")
        elif url.path.endswith("/activity-logs") or url.path.endswith("/activity-logs/export"):
            kind = parse_qs(url.query).get("activity_type_filter", ["all"])[0]
            filters.append(kind)
            selected = [item for item in records if kind == "all" or item["activity_type"] == kind]
            if url.path.endswith("/export"):
                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerow(["Activity", "Details"])
                for item in selected:
                    writer.writerow([item["activity_type"], namespace["format_activity_log_details_for_csv"](item)])
                route.fulfill(body=output.getvalue(), content_type="text/csv")
            else:
                route.fulfill(json={
                    "logs": selected, "user_map": {"reader": {"display_name": "Reader"}},
                    "pagination": {
                        "page": 1, "per_page": 50, "total_items": len(selected),
                        "total_pages": 1, "has_next": False, "has_prev": False,
                    },
                })
        elif url.path.endswith("/token-filters"):
            route.fulfill(json={"success": True, "filters": {
                key: [] for key in ("users", "groups", "public_workspaces", "models", "workspace_types", "token_types")
            }})
        elif url.path.endswith("/activity-trends"):
            route.fulfill(json={"success": True, "activity_data": {
                key: {} for key in ("logins", "chats", "documents", "personal_documents", "group_documents", "public_documents", "tokens")
            }})
        elif url.path == "/admin/control-center":
            route.fulfill(body=html, content_type="text/html")
        else:
            route.fulfill(status=404, body="")

    page.route("**/*", route_request)
    page.goto(f"{ORIGIN}/admin/control-center", wait_until="networkidle")
    page.evaluate("""async () => {
        const { ControlCenter } = await import('/static/js/control-center.js');
        window.controlCenter = new ControlCenter();
        await window.controlCenter.loadActivityLogs();
    }""")
    yield page, records, filters
    context.close()
    assert not errors
    assert not external


def test_terms_revision_visible_in_rows_modal_and_filtered_export(activity_page, tmp_path):
    page, _, filters = activity_page
    rows = page.locator("#activityLogsTableBody tr")
    expect(rows).to_have_count(3)
    expect(rows.nth(0)).to_contain_text("Terms version: v1")
    expect(rows.nth(1)).to_contain_text("Terms version: v2")
    expect(rows).not_to_contain_text([OLD_REVISION, NEW_REVISION, NEW_REVISION])
    rows.nth(0).click()
    modal = page.locator("#rawLogModal")
    expect(modal).to_be_visible()
    expect(modal.locator(".activity-log-detail-value").filter(has_text=re.compile(r"^v1$"))).to_be_visible()
    expect(modal.locator(".activity-log-detail-value").filter(has_text=re.compile(r"^v2$"))).to_have_count(0)
    expect(modal.locator("#rawLogJsonCollapse")).not_to_be_visible()
    assert OLD_REVISION in modal.locator("#rawLogModalJson").text_content()
    modal.get_by_role("button", name="Close", exact=True).click()
    expect(modal).not_to_be_visible()

    page.locator("#activityTypeFilterSelect").select_option("terms_of_use_declined")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("Terms of Use Declined")
    with page.expect_download() as download_info:
        page.locator("#exportActivityLogsBtn").click()
    path = tmp_path / "terms.csv"
    download_info.value.save_as(path)
    exported = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig"))))
    assert len(exported) == 1
    assert "Terms version: v2" in exported[0]["Details"]
    assert NEW_REVISION not in exported[0]["Details"]
    assert OLD_REVISION not in exported[0]["Details"]
    assert filters[-1] == "terms_of_use_declined"

    page.locator("#activityTypeFilterSelect").select_option("terms_of_use_accepted")
    expect(rows).to_have_count(2)
    assert filters[-1] == "terms_of_use_accepted"


def test_legacy_and_hostile_revision_fields_are_not_fabricated_or_executed(activity_page):
    page, records, _ = activity_page
    records[0].pop("terms_version")
    hostile = '<img src=x onerror="window.auditInjected=true">'
    records[1]["terms_hash"] = hostile
    records[1]["terms_version"] = hostile
    records[1]["frequency"] = hostile
    records[1]["source"] = hostile
    page.evaluate("async () => window.controlCenter.loadActivityLogs()")
    rows = page.locator("#activityLogsTableBody tr")
    expect(rows.nth(0)).to_contain_text("Terms version: Legacy")
    expect(rows.nth(1)).to_contain_text("Terms version: Legacy")
    expect(rows.locator("img")).to_have_count(0)
    rows.nth(1).click()
    modal = page.locator("#rawLogModal")
    expect(modal).to_be_visible()
    expect(modal.locator(".activity-log-detail-value").filter(has_text=re.compile(r"^Legacy$"))).to_be_visible()
    expect(modal.locator("img")).to_have_count(0)
    assert page.evaluate("window.auditInjected === undefined")
