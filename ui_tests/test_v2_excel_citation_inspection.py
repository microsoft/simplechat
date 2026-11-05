# test_v2_excel_citation_inspection.py
"""
UI tests for table-aware Excel citation previews and stable source evidence.
Version: 0.261.405
Implemented in: 0.261.405

The real V2 viewer runs through real HTTP fetches against synthetic API transport.
The shared Azure Playwright connection fixture uses Entra authentication when
configured and the existing local browser otherwise.
"""

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.orchestration import harness_build
from ui_tests.fixtures.playwright_connection import connect_options


__all__ = ["connect_options"]
PASSAGE = "Saved reviewer evidence: Budget!B4 contains 15000; the reviewer requests 19500."
ROOT = Path(__file__).resolve().parents[1]


def load_harness(page, origin):
    styles = list((ROOT / "application" / "single_app" / "static" / "v2" / "assets").glob("*.css"))
    assert len(styles) == 1, "Build the V2 UI before running styled citation tests."
    response = page.goto(f"{origin}/{harness_build.HARNESS_HTML_REL}")
    assert response is not None and response.ok
    page.add_style_tag(url=f"{origin}/application/single_app/static/v2/assets/{styles[0].name}")


def install_transport(page, *, identical=False):
    requests, failures, errors = [], {"Delivery": False}, []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def transport(route):
        parsed = urlparse(route.request.url)
        if parsed.path == "/api/get_citation":
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"cited_text": PASSAGE}))
            return
        if parsed.path != "/api/enhanced_citations/tabular_preview":
            route.fulfill(status=200, content_type="application/json", body="{}")
            return
        query = parse_qs(parsed.query)
        requests.append(query)
        sheet = query.get("sheet_name", ["Budget"])[0]
        if failures.get(sheet):
            route.fulfill(status=500, content_type="application/json", body=json.dumps({"error": "Preview temporarily unavailable."}))
            return
        table_id = query.get("table_id", [f"{sheet.lower()}-1"])[0]
        table_number = int(table_id.rsplit("-", 1)[-1])
        start = int(query.get("start_row", ["0"])[0])
        count = min(200, 50000 - start)
        tables = [
            {"id": f"{sheet.lower()}-{index}", "name": f"Review {index}", "range": f"A{index * 10}:B{50000 + index * 10}",
             "origin": "inferred", "header_row": 2, "header_status": "inferred", "row_count": 50000}
            for index in range(1, 6 if sheet == "Budget" else 2)
        ]
        rows = [
            ["North", "15000"] if identical else [f"{sheet}-{table_number}-{index + 1}", str(index + 1)]
            for index in range(start, start + count)
        ]
        payload = {
            "filename": "review.xlsx", "selected_sheet": sheet, "sheet_names": ["Budget", "Delivery"],
            "sheet_count": 2, "tables": tables, "table_count": len(tables),
            "table_id": table_id, "table_name": f"Review {table_number}", "table_range": tables[table_number - 1]["range"],
            "header_row": 2, "header_status": "inferred", "total_rows": 50000,
            "columns": ["Site", "Amount"], "rows": rows,
            "row_numbers": list(range(start + 3, start + 3 + count)), "start_row": start,
            "has_more": start + count < 50000, "truncated": start + count < 50000,
            "next_start_row": start + count if start + count < 50000 else None,
        }
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

    page.route("**/api/**", transport)
    return requests, failures, errors


def mount_viewer(page):
    page.wait_for_function("() => Boolean(window.OrchHarness)")
    page.evaluate("""() => {
        const H = window.OrchHarness;
        H.reset();
        window.viewerFallbacks = [];
        H.mount('mount-a', 'EnhancedCitationViewer', {
            type: 'tabular', docId: 'workbook', location: '1', locationLabel: 'Page',
            metadata: {file_name: 'review.xlsx', enhanced_citations: true},
            citationId: 'workbook_2', onClose: () => H.unmount('mount-a'),
            onFallback: (message) => window.viewerFallbacks.push(message),
        });
    }""")
    dialog = page.get_by_role("dialog", name="Cited source", exact=True)
    expect(dialog.get_by_role("tab", name="Budget", exact=True)).to_have_attribute("aria-selected", "true")
    expect(dialog.get_by_role("tabpanel")).to_have_attribute("aria-busy", "false")
    return dialog


@pytest.mark.ui
@pytest.mark.parametrize("viewport", [{"width": 1440, "height": 900}, {"width": 390, "height": 844}], ids=["desktop", "mobile"])
def test_real_sheets_five_tables_and_original_evidence(page, viewport):
    harness_build.ensure_bundle()
    page.set_viewport_size(viewport)
    requests, _, errors = install_transport(page)
    with harness_build.start_static_server() as origin:
        load_harness(page, origin)
        dialog = mount_viewer(page)
        expect(dialog.get_by_role("columnheader", name="Site", exact=True)).to_be_visible()
        expect(dialog.get_by_role("cell", name="Budget-1-1", exact=True)).to_be_visible()
        expect(dialog.get_by_text("Cited workbook evidence", exact=True)).to_be_visible()
        expect(dialog.get_by_text("What was extracted from this image", exact=True)).to_have_count(0)
        expect(dialog.get_by_text(PASSAGE, exact=True)).to_be_visible()
        dialog.get_by_label("Table", exact=True).select_option("budget-5")
        expect(dialog.get_by_role("cell", name="Budget-5-1", exact=True)).to_be_visible()
        expect(dialog.get_by_role("cell", name="Budget-1-1", exact=True)).to_have_count(0)
        dialog.get_by_role("tab", name="Delivery", exact=True).click()
        expect(dialog.get_by_role("tab", name="Delivery", exact=True)).to_have_attribute("aria-selected", "true")
        expect(dialog.get_by_role("cell", name="Delivery-1-1", exact=True)).to_be_visible()
        expect(dialog.get_by_text(PASSAGE, exact=True)).to_be_visible()
        assert any(request.get("table_id") == ["budget-5"] for request in requests)
        assert any(request.get("sheet_name") == ["Delivery"] for request in requests)
        assert dialog.evaluate("(element) => element.scrollWidth <= element.clientWidth")
    assert errors == []


@pytest.mark.ui
def test_identical_source_sheets_still_have_correct_selected_identity_and_keyboard_navigation(page):
    harness_build.ensure_bundle()
    requests, _, errors = install_transport(page, identical=True)
    with harness_build.start_static_server() as origin:
        load_harness(page, origin)
        dialog = mount_viewer(page)
        budget = dialog.get_by_role("tab", name="Budget", exact=True)
        budget.focus()
        budget.press("ArrowRight")
        delivery = dialog.get_by_role("tab", name="Delivery", exact=True)
        expect(delivery).to_have_attribute("aria-selected", "true")
        expect(delivery).to_be_focused()
        expect(dialog.get_by_role("tabpanel")).to_have_attribute("aria-label", "Delivery data preview")
        expect(dialog.get_by_role("cell", name="North", exact=True).first).to_be_visible()
        delivery.press("Home")
        expect(budget).to_have_attribute("aria-selected", "true")
        budget.click()
        expect(dialog.get_by_role("tabpanel")).to_have_attribute("aria-busy", "false")
        assert any(request.get("sheet_name") == ["Delivery"] for request in requests)
    assert errors == []


@pytest.mark.ui
def test_fifty_thousandth_record_is_loaded_without_rendering_fifty_thousand_rows(page):
    harness_build.ensure_bundle()
    requests, _, errors = install_transport(page)
    with harness_build.start_static_server() as origin:
        load_harness(page, origin)
        dialog = mount_viewer(page)
        dialog.get_by_label("Go to record", exact=True).fill("50000")
        dialog.get_by_role("button", name="Go", exact=True).click()
        expect(dialog.get_by_role("cell", name="Budget-1-50000", exact=True)).to_be_visible()
        expect(dialog.get_by_role("rowheader", name="50002", exact=True)).to_be_visible()
        expect(dialog.get_by_text("Records 50000–50000 of 50000", exact=True)).to_be_visible()
        assert len(dialog.get_by_role("row").all()) <= 201
        assert any(request.get("start_row") == ["49999"] for request in requests)
        dialog.get_by_role("button", name="Previous records", exact=True).click()
        expect(dialog.get_by_role("cell", name="Budget-1-1", exact=True)).to_be_visible()
        dialog.get_by_label("Go to record", exact=True).fill("1")
        dialog.get_by_role("button", name="Go", exact=True).click()
        expect(dialog.get_by_role("tabpanel")).to_have_attribute("aria-busy", "false")
    assert errors == []


@pytest.mark.ui
def test_failed_switch_does_not_mislabel_previous_data_and_can_retry(page):
    harness_build.ensure_bundle()
    _, failures, errors = install_transport(page)
    with harness_build.start_static_server() as origin:
        load_harness(page, origin)
        dialog = mount_viewer(page)
        failures["Delivery"] = True
        dialog.get_by_role("tab", name="Delivery", exact=True).click()
        expect(dialog.get_by_role("alert")).to_contain_text("Preview temporarily unavailable.")
        expect(dialog.get_by_role("tab", name="Budget", exact=True)).to_have_attribute("aria-selected", "true")
        expect(dialog.get_by_role("cell", name="Budget-1-1", exact=True)).to_be_visible()
        failures["Delivery"] = False
        dialog.get_by_role("button", name="Retry preview", exact=True).click()
        expect(dialog.get_by_role("tab", name="Delivery", exact=True)).to_have_attribute("aria-selected", "true")
        expect(dialog.get_by_role("cell", name="Delivery-1-1", exact=True)).to_be_visible()
        assert page.evaluate("window.viewerFallbacks") == []
    assert errors == []
