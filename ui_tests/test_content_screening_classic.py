# test_content_screening_classic.py
"""
Classic Content Screening policy, hold, review, and remediation workflows.
Version: 0.261.114
Implemented in: 0.261.106
Empty-policy scan feedback implemented in: 0.261.114

Uses the existing local/Azure Playwright connection fixture and a closed,
synthetic API boundary. No application accounts, real documents, secrets,
storage resources, or model inference are used.
"""

import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

# Shared UI fixtures are kept outside functional_tests and imported consistently
# with the existing classic browser suites.
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from content_screening_classic import ClassicScreeningFixture, USER_ID, content_unit
from playwright_connection import connect_options  # noqa: F401


pytestmark = pytest.mark.ui


@pytest.fixture
def classic_screening(page):
    fixture = ClassicScreeningFixture(page)
    yield fixture
    fixture.assert_clean()


def confirm_action(page):
    dialog = page.locator("#screening-confirm-modal")
    expect(dialog).to_be_visible()
    dialog.locator("#screening-confirm-action").click()
    expect(dialog).not_to_be_visible()


def select_secret_text(page):
    page.locator("#screening-unit-text").evaluate("""
        root => {
            const range = document.createRange();
            range.setStart(root.firstChild, 2);
            range.setEnd(root.firstChild, 8);
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            root.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
        }
    """)
    page.locator("#screening-use-selection").click()


def test_classic_policy_prerequisites_fail_closed(classic_screening):
    classic_screening.config.update({"enabled": False, "enhanced_citations_enabled": False})
    classic_screening.global_policy["enabled"] = False
    classic_screening.open_admin()
    page = classic_screening.page
    toggle = page.locator("#enable_content_screening")
    expect(toggle).to_be_disabled()
    expect(toggle).not_to_be_checked()
    expect(page.locator("#screening-admin-policy")).to_contain_text("private storage")
    expect(page.locator("#screening-scan-global")).to_be_disabled()
    assert classic_screening.configuration_writes == []
    assert classic_screening.scan_starts == []


def test_classic_workspace_policy_preserves_mandatory_baseline(classic_screening):
    classic_screening.open_review()
    page = classic_screening.page
    page.locator("#screening-policy-tab").click()
    editor = page.locator("#screening-workspace-policy")
    expect(editor.locator(".screening-policy-baseline")).to_contain_text("cannot remove, disable, or weaken")
    expect(editor.locator(".screening-policy-baseline input")).to_have_count(0)
    expect(editor.get_by_label("Scanner model", exact=True)).to_contain_text("approved-model")
    editor.get_by_label("Workspace additions enabled", exact=True).check()
    editor.get_by_role("button", name="Add literal rule", exact=True).click()
    rule = editor.locator(".screening-rule")
    rule.get_by_label("Rule name", exact=True).fill("Synthetic confidential marker")
    rule.get_by_label("Severity", exact=True).select_option("high")
    rule.get_by_label("Category", exact=True).fill("sensitive")
    rule.get_by_label("Literal values or phrases", exact=True).fill("fixture-private-marker")
    editor.get_by_role("button", name="Save screening policy", exact=True).click()
    expect(editor).to_contain_text("Screening policy saved.")
    assert classic_screening.global_policy["rules"][0]["id"] == "email"
    saved = classic_screening.policy_writes[-1]
    assert saved["etag"] == '"policy-etag-1"'
    assert set(saved) == {"etag", "policy"}
    assert saved["policy"]["allowed_models"] == []
    assert len(saved["policy"]["rules"]) == 1
    assert saved["policy"]["rules"][0]["values"] == ["fixture-private-marker"]
    assert "baseline" not in saved["policy"]


def test_classic_policy_conflict_keeps_draft_and_requires_reload(classic_screening):
    classic_screening.fail_policy = 409
    classic_screening.open_admin()
    page = classic_screening.page
    editor = page.locator("#screening-admin-policy")
    editor.get_by_label("Rule name", exact=True).fill("My unsaved rule name")
    editor.get_by_role("button", name="Save screening policy", exact=True).click()
    expect(editor).to_contain_text("Refresh required")
    expect(editor.get_by_label("Rule name", exact=True)).to_have_value("My unsaved rule name")
    expect(editor.get_by_role("button", name="Save screening policy", exact=True)).to_be_disabled()
    expect(editor).not_to_contain_text("private-provider-diagnostic")


def test_classic_findings_are_inert_and_flags_require_explicit_reason(classic_screening):
    classic_screening.open_review()
    page = classic_screening.page
    expect(page.locator("#screening-unit-text")).to_contain_text("<img src=x")
    expect(page.locator("#screening-findings")).to_contain_text("<script>")
    expect(page.locator("#screening-unit-location")).to_contain_text("Legacy segment")
    expect(page.locator("#screening-review-origin")).to_contain_text("retained indexed knowledge only")
    expect(page.locator("#screening-review-detail img, #screening-review-detail iframe")).to_have_count(0)
    expect(page.locator('#screening-edit-kind option[value="remove_page"]')).to_have_count(0)
    approve = page.locator("#screening-approve-flags")
    expect(approve).to_be_disabled()
    page.locator("#screening-decision-reason").fill("Synthetic false positive reviewed against our policy.")
    expect(approve).to_be_disabled()
    page.locator("#screening-flags-acknowledged").check()
    expect(approve).to_be_enabled()
    approve.click()
    confirm_action(page)
    expect(page.locator("#screening-document-state")).to_contain_text("Approved with flags")
    assert classic_screening.decisions == [{
        "etag": '"review-etag-1"', "action": "approve_with_flags",
        "reason": "Synthetic false positive reviewed against our policy.", "acknowledge_flags": True,
    }]
    expect(page.locator("#screening-recorded-decision")).to_contain_text("Synthetic false positive reviewed")
    expect(page.locator("#screening-review-warning")).to_contain_text("Approved with flags")


@pytest.mark.parametrize("clean", [False, True])
def test_classic_downloads_only_server_authorized_original_and_active_clean(classic_screening, clean):
    classic_screening.enable_downloads(clean=clean)
    classic_screening.open_review()
    page = classic_screening.page
    with page.expect_download() as original:
        page.locator("#screening-download-original").click()
    assert original.value.suggested_filename == "fixture-original.txt"
    if clean:
        with page.expect_download() as derivative:
            page.locator("#screening-download-clean").click()
        assert derivative.value.suggested_filename == "fixture-clean.txt"
    else:
        expect(page.locator("#screening-download-clean")).to_be_disabled()
    assert classic_screening.attachment_requests == [
        f"/api/content-screening/reviews/scan-1/downloads/{kind}"
        for kind in (("original", "clean") if clean else ("original",))
    ]
    expect(page.locator("#screening-review-detail iframe, #screening-review-detail object, #screening-review-detail embed")).to_have_count(0)
    assert page.evaluate("window.evidenceExecuted === true") is False


@pytest.mark.parametrize("url", [
    "javascript:window.evidenceExecuted=true",
    "https://private.invalid/source?signature=untrusted",
    "//private.invalid/source",
    "/api/content-screening/reviews/other-scan/downloads/original",
])
def test_classic_rejects_unsafe_or_wrong_scan_download_urls(classic_screening, url):
    classic_screening.enable_downloads()
    classic_screening.review["downloads"]["original"]["url"] = url
    classic_screening.open_review()
    expect(classic_screening.page.locator("#screening-download-original")).to_be_disabled()
    assert classic_screening.attachment_requests == []


def test_classic_download_requires_action_not_just_retained_source_metadata(classic_screening):
    classic_screening.enable_downloads()
    classic_screening.review["allowed_actions"].remove("download_original")
    classic_screening.open_review()
    expect(classic_screening.page.locator("#screening-download-original")).to_be_disabled()
    assert classic_screening.attachment_requests == []


@pytest.mark.parametrize("failure", ["inline", "revoked"])
def test_classic_download_failure_never_opens_active_source(classic_screening, failure):
    classic_screening.enable_downloads()
    classic_screening.inline_attachment = failure == "inline"
    classic_screening.fail_attachment = 403 if failure == "revoked" else 0
    downloads = []
    classic_screening.page.on("download", lambda download: downloads.append(download))
    classic_screening.open_review()
    page = classic_screening.page
    page.locator("#screening-download-original").click()
    expect(page.locator("#screening-review-message")).to_contain_text(
        "permission" if failure == "revoked" else "could not be completed"
    )
    assert downloads == []
    assert page.evaluate("window.evidenceExecuted === true") is False
    if failure == "revoked":
        expect(page.locator("#screening-review-detail")).not_to_be_visible()
        expect(page.locator("#screening-unit-text")).to_have_text("")


@pytest.mark.parametrize("source_missing", [True, False])
def test_classic_missing_or_unreadable_evidence_keeps_reject_delete(classic_screening, source_missing):
    if source_missing:
        classic_screening.review.update({
            "state": "scan_error", "allowed_actions": ["reject", "delete"],
            "evidence": {"units_available": False, "findings_available": False},
        })
    else:
        classic_screening.fail_evidence = 503
    classic_screening.open_review()
    page = classic_screening.page
    expect(page.locator("#screening-evidence-unavailable")).to_be_visible()
    expect(page.locator("#screening-unit-text")).to_contain_text("not available")
    expect(page.locator("#screening-approve-flags")).to_be_disabled()
    expect(page.locator("#screening-edit-controls")).to_have_js_property("disabled", True)
    expect(page.locator("#screening-add-edit")).to_be_disabled()
    page.locator("#screening-decision-reason").fill("Missing evidence must remain held.")
    expect(page.locator("#screening-reject")).to_be_enabled()
    expect(page.locator("#screening-delete")).to_be_enabled()
    if source_missing:
        assert classic_screening.evidence_requests == []
    page.locator("#screening-reject").click()
    confirm_action(page)
    expect(page.locator("#screening-recorded-decision")).to_contain_text("Missing evidence must remain held.")
    assert classic_screening.decisions[-1]["action"] == "reject"


@pytest.mark.parametrize("outcome", ["pass", "error"])
def test_classic_queued_candidate_polls_until_complete_without_premature_approval(classic_screening, outcome):
    classic_screening.defer_candidate = True
    classic_screening.open_review()
    page = classic_screening.page
    select_secret_text(page)
    page.locator("#screening-add-edit").click()
    page.locator("#screening-preview-edit").click()
    page.locator("#screening-submit-candidate").click()
    confirm_action(page)
    expect(page.locator("#screening-candidate-pending")).to_be_visible()
    expect(page.locator("#screening-approve-clean")).to_be_disabled()
    expect(page.locator("#screening-approve-flags")).to_be_disabled()
    assert not any("candidate-2/findings" in path for path in classic_screening.evidence_requests)
    assert classic_screening.decisions == []
    classic_screening.complete_candidate(outcome)
    expect(page.locator("#screening-candidate-pending")).not_to_be_visible(timeout=10000)
    page.locator("#screening-decision-reason").fill("Reviewed candidate after required checks.")
    if outcome == "pass":
        expect(page.locator("#screening-approve-clean")).to_be_enabled()
    else:
        expect(page.locator("#screening-approve-clean")).to_be_disabled()
        expect(page.locator("#screening-review-coverage")).to_contain_text("incomplete")
    assert classic_screening.decisions == []


def test_classic_unicode_span_preview_rescan_and_explicit_clean_approval(classic_screening):
    classic_screening.open_review()
    page = classic_screening.page
    select_secret_text(page)
    expect(page.locator("#screening-span-start")).to_have_value("1")
    expect(page.locator("#screening-span-end")).to_have_value("7")
    source_hash = classic_screening.units[0]["content_hash"]
    page.locator("#screening-add-edit").click()
    page.locator("#screening-preview-edit").click()
    expect(page.locator("#screening-preview")).to_be_visible()
    expect(page.locator(".screening-diff-before")).to_contain_text("secret")
    expect(page.locator(".screening-diff-after")).not_to_contain_text("secret")
    assert classic_screening.previews[-1] == {
        "etag": '"review-etag-1"',
        "edits": [{"action": "remove_span", "unit_id": "unit-1", "content_hash": source_hash, "start": 1, "end": 7}],
    }
    assert classic_screening.decisions == []
    page.locator("#screening-submit-candidate").click()
    confirm_action(page)
    page.locator("#screening-decision-reason").fill("Reviewed the fully scanned clean candidate.")
    expect(page.locator("#screening-approve-clean")).to_be_enabled()
    expect(page.locator("#screening-unit-text")).not_to_contain_text("secret")
    assert classic_screening.remediations[-1] == classic_screening.previews[-1]
    assert classic_screening.decisions == []
    page.locator("#screening-approve-clean").click()
    confirm_action(page)
    expect(page.locator("#screening-document-state")).to_contain_text("Screening cleared")
    assert classic_screening.decisions[-1]["etag"] == '"candidate-etag-2"'
    assert classic_screening.decisions[-1]["action"] == "approve_clean"


def test_classic_unicode_selection_adds_canonical_window_offset(classic_screening):
    classic_screening.units[0]["text_offset"] = 40
    classic_screening.units[0]["text_total"] += 40
    classic_screening.findings[0].update({"start": 41, "end": 47})
    classic_screening.open_review()
    page = classic_screening.page
    select_secret_text(page)
    expect(page.locator("#screening-span-start")).to_have_value("41")
    expect(page.locator("#screening-span-end")).to_have_value("47")
    page.locator("#screening-add-edit").click()
    page.locator("#screening-preview-edit").click()
    expect(page.locator("#screening-preview")).to_be_visible()
    assert classic_screening.previews[-1]["edits"][0]["start"] == 41
    assert classic_screening.previews[-1]["edits"][0]["end"] == 47


@pytest.mark.parametrize("incomplete", ["pending", "error", "partial_evidence"])
def test_classic_incomplete_review_disables_approval(classic_screening, incomplete):
    classic_screening.findings = []
    classic_screening.review.update({"finding_count": 0, "allowed_actions": ["approve_clean", "approve_with_flags", "remediate"]})
    if incomplete == "partial_evidence":
        classic_screening.units_continuation = "next-page"
        classic_screening.extra_units = [content_unit("unit-2", "Remaining canonical source")]
    else:
        classic_screening.review["coverage"].update({"complete": False, "status": incomplete})
        classic_screening.review["outcome"] = incomplete
    classic_screening.open_review()
    page = classic_screening.page
    page.locator("#screening-decision-reason").fill("Coverage is not complete.")
    page.locator("#screening-flags-acknowledged").check()
    expect(page.locator("#screening-approve-clean")).to_be_disabled()
    expect(page.locator("#screening-approve-flags")).to_be_disabled()
    assert classic_screening.decisions == []


@pytest.mark.parametrize("status", [403, 409])
def test_classic_forbidden_or_stale_decision_is_not_success(classic_screening, status):
    classic_screening.fail_decision = status
    classic_screening.open_review()
    page = classic_screening.page
    page.locator("#screening-decision-reason").fill("Reviewed synthetic evidence.")
    page.locator("#screening-flags-acknowledged").check()
    page.locator("#screening-approve-flags").click()
    confirm_action(page)
    notice = page.locator("#screening-review-message")
    expect(notice).to_contain_text("permission" if status == 403 else "Refresh required")
    expect(notice).not_to_have_class("alert alert-success mt-3")
    expect(notice).not_to_contain_text("private-provider-diagnostic")
    expect(page.locator("#screening-approve-flags")).to_be_disabled()
    if status == 403:
        expect(page.locator("#screening-review-detail")).not_to_be_visible()
        expect(page.locator("#screening-unit-text")).to_have_text("")


def test_classic_forbidden_evidence_never_renders(classic_screening):
    classic_screening.fail_review = 403
    classic_screening.open_review()
    page = classic_screening.page
    expect(page.locator("#screening-review-message")).to_contain_text("permission")
    expect(page.locator("#screening-review-detail")).not_to_be_visible()
    expect(page.locator("#screening-unit-text")).to_have_text("")
    expect(page.locator("body")).not_to_contain_text("private-provider-diagnostic")


def test_classic_confirmation_cannot_authorize_a_refreshed_revision(classic_screening):
    classic_screening.open_review()
    page = classic_screening.page
    page.locator("#screening-decision-reason").fill("I reviewed the first revision only.")
    page.locator("#screening-flags-acknowledged").check()
    page.locator("#screening-approve-flags").click()
    expect(page.locator("#screening-confirm-modal")).to_be_visible()
    classic_screening.review["etag"] = '"different-review-revision"'
    page.evaluate("document.getElementById('screening-refresh').click()")
    expect(page.locator("#screening-decision-reason")).to_have_value("")
    confirm_action(page)
    expect(page.locator("#screening-review-message")).to_contain_text("Refresh required")
    expect(page.locator("#screening-approve-flags")).to_be_disabled()
    assert classic_screening.decisions == []


def test_classic_cell_clear_and_real_page_controls(classic_screening):
    classic_screening.units = [content_unit(locator={
        "kind": "table_cell", "sheet_index": 0, "sheet": "Synthetic", "row": 2, "column": "B", "value_type": "string",
    })]
    classic_screening.open_review()
    page = classic_screening.page
    expect(page.locator("#screening-unit-location")).to_contain_text("Sheet Synthetic · row 2 · column B")
    expect(page.locator('#screening-edit-kind option[value="remove_page"]')).to_have_count(0)
    page.locator("#screening-edit-kind").select_option("clear_cell")
    page.locator("#screening-add-edit").click()
    page.locator("#screening-preview-edit").click()
    expect(page.locator("#screening-preview")).to_be_visible()
    edit = classic_screening.previews[-1]["edits"][0]
    assert edit == {"action": "replace_cell", "unit_id": "unit-1", "content_hash": classic_screening.units[0]["content_hash"], "text": ""}


def test_classic_page_removal_expands_only_authoritative_page_units(classic_screening):
    classic_screening.units = [
        content_unit("unit-1", "secret on a real page", {"kind": "page", "page_number": 3}),
        content_unit("unit-2", "figure description", {"kind": "figure", "page_number": 3, "figure_id": "figure-1"}),
        content_unit("unit-3", "surviving legacy segment", {"kind": "legacy_segment", "segment_index": 3}),
    ]
    classic_screening.open_review()
    page = classic_screening.page
    expect(page.locator('#screening-edit-kind option[value="remove_unit"]')).to_have_count(0)
    page.locator("#screening-edit-kind").select_option("remove_page")
    page.locator("#screening-add-edit").click()
    page.locator("#screening-preview-edit").click()
    expect(page.locator("#screening-preview")).to_be_visible()
    edits = classic_screening.previews[-1]["edits"]
    assert [edit["unit_id"] for edit in edits] == ["unit-1", "unit-2"]
    assert all(edit["action"] == "remove_unit" for edit in edits)
    assert all(set(edit) == {"action", "unit_id", "content_hash"} for edit in edits)


def test_classic_paged_units_require_complete_page_mapping(classic_screening):
    classic_screening.units = [content_unit(locator={"kind": "page", "page_number": 3})]
    classic_screening.units_continuation = "remaining-units"
    classic_screening.extra_units = [content_unit("unit-2", "second page unit", {"kind": "page", "page_number": 3})]
    classic_screening.open_review()
    page = classic_screening.page
    expect(page.locator('#screening-edit-kind option[value="remove_page"]')).to_have_count(0)
    expect(page.locator("#screening-approval-blocked")).to_contain_text("Load the remaining")
    page.locator("#screening-more-units").click()
    expect(page.locator("#screening-more-units")).not_to_be_visible()
    expect(page.locator('#screening-edit-kind option[value="remove_page"]')).to_have_count(1)


def test_classic_delete_requires_confirmation_and_clears_evidence(classic_screening):
    classic_screening.open_review()
    page = classic_screening.page
    page.locator("#screening-decision-reason").fill("Remove this synthetic test document.")
    page.locator("#screening-delete").click()
    page.locator("#screening-confirm-modal").get_by_role("button", name="Cancel", exact=True).click()
    expect(page.locator("#screening-confirm-modal")).not_to_be_visible()
    assert classic_screening.decisions == []
    page.locator("#screening-delete").click()
    confirm_action(page)
    expect(page.locator("#screening-review-detail")).not_to_be_visible()
    expect(page.locator("#screening-unit-text")).to_have_text("")
    assert classic_screening.decisions[-1]["action"] == "delete"


def test_classic_held_indicators_survive_disabled_scanning(classic_screening):
    classic_screening.config["enabled"] = False
    classic_screening.open_workspace()
    page = classic_screening.page
    expect(page.locator("#fixture-documents")).to_contain_text("Needs review — held")
    expect(page.locator("#fixture-documents")).to_contain_text("Approved with flags")
    expect(page.locator("#fixture-documents")).not_to_contain_text("private-abstract-must-not-appear")
    expect(page.locator("#fixture-documents img")).to_have_count(0)
    page.locator(".document-checkbox").check()
    expect(page.locator("#chat-selected-btn")).to_be_disabled()
    expect(page.locator("#download-selected-btn")).to_be_disabled()
    expect(page.locator("[data-screening-scan-selected]")).to_be_disabled()
    expect(page.locator("[data-screening-review-link]")).to_be_visible()
    page.locator("[data-screening-filter]").select_option("approved_with_flags")
    expect(page.locator("#fixture-documents tbody tr")).to_have_count(1)


def test_classic_selected_scan_progress_cancel_and_resume(classic_screening):
    classic_screening.open_workspace()
    page = classic_screening.page
    page.locator(".document-checkbox").check()
    scan = page.locator("[data-screening-scan-selected]")
    expect(scan).to_be_enabled()
    scan.click()
    confirm_action(page)
    jobs = page.locator("[data-screening-workspace-jobs]")
    expect(jobs).to_contain_text("1 completed")
    assert classic_screening.scan_starts == [{
        "scope_type": "personal", "scope_id": USER_ID, "document_ids": ["held-document"],
    }]
    jobs.get_by_role("button", name="Cancel scan", exact=True).click()
    confirm_action(page)
    expect(jobs.get_by_role("button", name="Resume scan", exact=True)).to_be_visible()
    jobs.get_by_role("button", name="Resume scan", exact=True).click()
    confirm_action(page)
    expect(jobs).to_contain_text("Scanning")
    assert classic_screening.scan_actions == ["cancel", "resume"]


def test_classic_cancel_request_waits_for_durable_worker_state(classic_screening):
    classic_screening.defer_cancel = True
    classic_screening.open_workspace()
    page = classic_screening.page
    page.locator("[data-screening-scan-workspace]").click()
    confirm_action(page)
    jobs = page.locator("[data-screening-workspace-jobs]")
    jobs.get_by_role("button", name="Cancel scan", exact=True).click()
    confirm_action(page)
    expect(jobs).to_contain_text("Cancellation requested")
    expect(jobs.get_by_role("button", name="Cancel scan", exact=True)).to_be_disabled()
    expect(jobs.get_by_role("button", name="Resume scan", exact=True)).to_have_count(0)
    assert classic_screening.scan_actions == ["cancel"]


@pytest.mark.parametrize("single_document", [True, False])
def test_classic_single_and_workspace_scan_targets(classic_screening, single_document):
    classic_screening.open_workspace()
    page = classic_screening.page
    if single_document:
        page.locator("[data-screening-scan-document]").first.click()
    else:
        page.locator("[data-screening-scan-workspace]").click()
    confirm_action(page)
    expect(page.locator("[data-screening-workspace-jobs]")).to_contain_text("Scanning")
    target = {"scope_type": "personal", "scope_id": USER_ID}
    if single_document:
        target["document_ids"] = ["held-document"]
    assert classic_screening.scan_starts == [target]


@pytest.mark.parametrize("dirty_policy", [False, True])
def test_classic_disable_new_scans_preserves_review_holds(classic_screening, dirty_policy):
    classic_screening.open_admin()
    page = classic_screening.page
    if dirty_policy:
        page.get_by_label("Rule name", exact=True).fill("Keep my policy edits")
    with page.expect_response(
        lambda response: response.request.method == "PUT"
        and response.url.endswith("/api/content-screening/configuration")
    ) as configuration, page.expect_response(
        lambda response: response.request.method == "GET"
        and response.url.endswith("/api/content-screening/policies/global/global")
    ) as refreshed_policy:
        page.locator("#enable_content_screening").uncheck()
    assert configuration.value.status == 200 and configuration.value.json()["enabled"] is False
    assert refreshed_policy.value.status == 200
    expect(page.locator("#screening-admin-policy")).to_contain_text("New scans are disabled")
    if dirty_policy:
        expect(page.get_by_label("Rule name", exact=True)).to_have_value("Keep my policy edits")
    assert not classic_screening.policy_writes
    assert classic_screening.configuration_writes == [{"enabled": False}]
    assert classic_screening.review["state"] == "pending_review"
    assert classic_screening.decisions == []
    classic_screening.open_workspace()
    expect(page.locator("#fixture-documents")).to_contain_text("Needs review — held")


def test_classic_global_scan_is_explicit_admin_operation(classic_screening):
    classic_screening.open_admin()
    page = classic_screening.page
    page.locator("#screening-scan-global").click()
    expect(page.locator("#screening-confirm-description")).to_contain_text("all workspaces")
    confirm_action(page)
    expect(page.locator("#screening-admin-jobs")).to_contain_text("Scanning")
    assert classic_screening.scan_starts == [{"all_workspaces": True}]


def test_classic_global_scan_requires_server_capability(classic_screening):
    classic_screening.config["can_scan_all"] = False
    classic_screening.open_admin()
    expect(classic_screening.page.locator("#screening-scan-global")).not_to_be_visible()
    assert classic_screening.scan_starts == []


def test_classic_empty_policy_scan_error_explains_checks_without_blocking_settings(classic_screening):
    ui = classic_screening
    ui.open_workspace()

    def reject_empty_scan(route):
        if route.request.method == "POST":
            route.fulfill(status=400, json={"error": "No active checks.", "code": "screening_policy_empty"})
        else:
            route.fallback()

    ui.page.route("**/api/content-screening/scans", reject_empty_scan)
    ui.page.locator("[data-screening-scan-workspace]").click()
    confirm_action(ui.page)
    message = ui.page.locator("[data-screening-workspace-message]")
    expect(message).to_contain_text("No active checks are configured for this workspace.")
    expect(message).to_contain_text("An empty policy can stay enabled")
    expect(message).to_contain_text("existing holds are unchanged")
    assert not ui.scan_starts and not ui.configuration_writes


def test_classic_admin_scan_capability_does_not_grant_private_review(classic_screening):
    classic_screening.can_review = False
    classic_screening.open_workspace()
    page = classic_screening.page
    expect(page.locator("#fixture-documents")).to_contain_text("Needs review — held")
    page.wait_for_load_state("networkidle")
    expect(page.locator("#fixture-documents a")).to_have_count(0)
    assert classic_screening.config["can_scan_all"] is True


def test_classic_approval_request_links_protected_content_review(classic_screening):
    classic_screening.open_approvals()
    page = classic_screening.page
    table = page.locator("#approvalsTableBody")
    expect(table).to_contain_text("Content Screening")
    expect(table.locator("img")).to_have_count(0)
    expect(table).not_to_contain_text("private-approval-reason-must-not-appear")
    table.get_by_role("link", name="Open content review", exact=True).click()
    expect(page.locator("#screening-review-detail")).to_be_visible()
    expect(page.locator("#screening-unit-text")).to_contain_text("secret")
    assert classic_screening.generic_approval_writes == []


@pytest.mark.parametrize("unsafe_url", ["javascript:window.evidenceExecuted=true", "https://untrusted.example.test/content-review?scan_id=scan-1"])
def test_classic_approval_review_link_rejects_untrusted_destinations(classic_screening, unsafe_url):
    classic_screening.approval["metadata"]["review_url"] = unsafe_url
    classic_screening.open_approvals()
    link = classic_screening.page.locator("#approvalsTableBody").get_by_role("link", name="Open content review", exact=True)
    expect(link).to_have_attribute("href", "/content-review")
    assert classic_screening.generic_approval_writes == []


def test_classic_screening_modal_never_uses_generic_decisions(classic_screening):
    classic_screening.open_approvals()
    page = classic_screening.page
    page.evaluate("""approval => {
        const modal = document.getElementById('approvalActionModal');
        modal.dataset.approvalId = approval.id;
        modal.dataset.groupId = approval.group_id;
        window.ApprovalManager.populateApprovalDetails(approval, 'view');
        bootstrap.Modal.getOrCreateInstance(modal).show();
    }""", classic_screening.approval)
    expect(page.locator("#approvalActionModal")).to_be_visible()
    expect(page.locator("#approvalApproveBtn")).not_to_be_visible()
    expect(page.locator("#approvalDenyBtn")).not_to_be_visible()
    expect(page.locator("#approvalDetailReason")).not_to_contain_text("private-approval-reason-must-not-appear")
    page.evaluate("async () => { await ApprovalManager.handleApprove(); await ApprovalManager.handleDeny(); }")
    assert classic_screening.generic_approval_writes == []
    page.evaluate("""() => ApprovalManager.populateApprovalDetails({
        request_type: 'delete_user_documents', status: 'pending',
        requester_name: 'Synthetic requester', created_at: '2026-09-08T12:00:00Z',
        reason: 'Ordinary approval remains unchanged', can_approve: false, can_deny: true
    }, 'view')""")
    expect(page.locator("#approvalApproveBtn")).not_to_be_visible()
    expect(page.locator("#approvalDenyBtn")).to_be_visible()


def test_classic_publication_retry_does_not_approve_an_incomplete_scan(classic_screening):
    classic_screening.review.update({
        "state": "publishing", "allowed_actions": ["retry_publication"],
        "decision": {
            "action": "approve_with_flags", "actor_id": USER_ID,
            "reason": "Previously approved exact revision.", "decided_at": "2026-09-16T15:00:00Z",
        },
    })
    classic_screening.open_review()
    page = classic_screening.page
    expect(page.locator("#screening-approve-clean")).to_be_disabled()
    expect(page.locator("#screening-approve-flags")).to_be_disabled()
    page.locator("#screening-retry-publication").click()
    confirm_action(page)
    expect(page.locator("#screening-review-message")).to_contain_text("Decision accepted")
    assert classic_screening.decisions[-1]["reason"] == "Previously approved exact revision."
    assert classic_screening.decisions[-1]["action"] == "retry_publication"


def test_classic_review_mobile_layout_and_keyboard_findings(classic_screening):
    classic_screening.page.set_viewport_size({"width": 390, "height": 844})
    classic_screening.open_review()
    page = classic_screening.page
    finding = page.locator("#screening-findings button").first
    finding.focus()
    finding.press("Enter")
    expect(page.locator("#screening-unit-text")).to_be_focused()
    expect(page.locator("#screening-unit-text mark")).to_have_text("secret")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
