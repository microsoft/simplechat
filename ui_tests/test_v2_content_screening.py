# test_v2_content_screening.py
"""
Production V2 browser regressions for screening-controlled documents and review.
Version: 0.261.108
Implemented in: 0.261.106

Runs the real SPA with the existing closed workspace fixture and its Azure
Playwright/DefaultAzureCredential connection support or explicit local fallback.
All API data is synthetic. No credentials, scanner calls, or service writes are
needed, and unexpected requests or browser errors fail the test.
"""

import ast
import copy
import re
import sys
from functools import lru_cache
from pathlib import Path

import pytest
from playwright.sync_api import expect

# The existing shared connection fixture uses a top-level import for standalone runs.
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
from ui_tests.fixtures.workspace_authoring import (
    OWNER_ID,
    SPA_INDEX,
    WorkspaceAuthoringFixture,
    connect_options,  # noqa: F401
)

APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))
from content_screening.policies import AI_STARTER_CRITERIA, STARTER_PACKS, STARTER_RULE_TEMPLATES, default_policy, normalize_policy


pytestmark = pytest.mark.ui
SOURCE_SCAN = "scan-held"
CANDIDATE_SCAN = "scan-candidate"
UNTRUSTED_TEXT = '😀SECRET <script>window.screeningEvidenceExecuted=true</script><img src=x onerror=alert(1)>'
EARLIER_TEXT = ("Earlier canonical text. " * 5)[:100]


@lru_cache
def screening_admin_schema():
    """Use the shipped declaration, including visibility and component wiring."""
    tree = ast.parse((APP_ROOT / "admin_settings_fields.py").read_text(encoding="utf-8"))
    declaration = next(
        node.value for node in tree.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "ADMIN_SETTINGS_FIELDS" for target in node.targets)
    )
    screening = next(
        ast.literal_eval(value) for key, value in zip(declaration.keys, declaration.values)
        if isinstance(key, ast.Constant) and key.value == "content-screening-section"
    )
    return {"content-screening-section": screening}


def evidence_unit(identifier, text, locator, content_hash):
    return {
        "unit_id": identifier, "text": text, "locator": locator,
        "content_hash": content_hash, "offset_encoding": "unicode_codepoints",
        "normalization_version": 1, "text_offset": 0, "text_total": len(text),
    }


def review_record(identifier=SOURCE_SCAN, **overrides):
    record = {
        "id": identifier,
        "subject": {
            "scope_type": "personal", "scope_id": OWNER_ID,
            "document_id": "held", "source_revision": "revision-1",
        },
        "state": "pending_review",
        "etag": f'"{identifier}-etag"',
        "content_fingerprint": f"{identifier}-fingerprint",
        "policy_fingerprint": "policy-fingerprint",
        "outcome": "findings",
        "coverage": {"complete": True, "units_total": 2},
        "finding_count": 1,
        "review_required": True,
        "candidate_of": None,
        "original_retained": True,
        "sanitized": False,
        "evidence": {"units_available": True, "findings_available": True},
        "downloads": {"original": None, "clean": None},
        "allowed_actions": ["remediate", "approve_with_flags", "reject", "delete"],
        "warning": None, "decision": None,
    }
    record.update(overrides)
    return record


def screened_document(identifier, state, available=False):
    return {
        "id": identifier,
        "file_name": f"{identifier}.txt",
        "title": f"Protected extracted title for {identifier}" if not available else identifier,
        "abstract": "Reviewer-only extracted evidence" if not available else "",
        "percentage_complete": 100,
        "status": "completed",
        "tags": [],
        "content_screening": {
            "state": state,
            "available": available,
            "finding_count": 1 if state in {"pending_review", "approved_with_flags"} else 0,
            "review_id": f"review-{identifier}",
            "scan_id": f"scan-{identifier}",
            "updated_at": "2026-09-08T18:00:00Z",
        },
    }


class ScreeningUiFixture(WorkspaceAuthoringFixture):
    """Reuse the real-SPA fixture; specialize only this feature's HTTP responses."""

    def __init__(self, page):
        super().__init__(page)
        self.documents = [
            {"id": "legacy", "file_name": "legacy.txt", "status": "completed", "tags": []},
            screened_document("held", "pending_review"),
            screened_document("scanning", "scanning"),
            screened_document("failed", "scan_error"),
            screened_document("incomplete", "incomplete"),
            screened_document("flagged", "approved_with_flags", True),
        ]
        self.preferences["v2DocumentsPrefs"] = {"detailsPaneOpen": False}
        self.admin = False
        self.reviews = {SOURCE_SCAN: review_record()}
        self.source_units = [
            evidence_unit(
                "source-unit", EARLIER_TEXT + UNTRUSTED_TEXT,
                {"kind": "legacy_segment", "segment": 3}, "source-hash",
            ),
            evidence_unit(
                "cell-unit", "private cell",
                {"kind": "table_cell", "sheet_index": 0, "sheet": "Budget",
                 "row": 2, "column": "A", "value_type": "text"},
                "cell-hash",
            ),
        ]
        self.candidate_units = []
        self.defer_candidate = False
        self.inline_attachment = False
        self.attachment_requests = []
        self.screening_writes = []
        self.scan_enabled = False
        self.enhanced_citations_enabled = True
        self.content_safety_enabled = True
        self.can_scan_all = False
        self.can_manage_scope = True
        self.scan_jobs = {}
        self.scan_writes = []
        self.policy = default_policy()
        self.policy.update({"enabled": True, "rules": [{
            "id": "local-check", "name": "Local check", "type": "literal",
            "enabled": True, "severity": "high", "category": "custom",
            "values": ["fixture-value"], "case_sensitive": False, "whole_word": False,
        }]})
        self.policy_etag = '"policy-etag"'
        self.policy_writes = []
        self.policy_samples = []
        self.settings_writes = []
        self.reject_policy_save = None
        self.reject_settings_save = False
        self.model_catalog = []
        self.allowed_models = []
        self.templates = copy.deepcopy({
            "rules": STARTER_RULE_TEMPLATES, "packs": STARTER_PACKS, "ai": AI_STARTER_CRITERIA,
        })
        self.baseline_summary = {
            "schema_version": 1, "enabled": True, "rule_count": 2, "ai_check_count": 1,
            "rule_types": ["pii", "regex"], "pii_types": ["email"], "severities": ["high"],
            "fingerprint": "baseline-fingerprint",
        }

    def _bootstrap(self):
        payload = super()._bootstrap()
        payload["features"].update({
            "enable_content_screening": self.scan_enabled,
            "enable_file_sharing": True,
            "enable_extract_meta_data": True,
        })
        payload["catalogs"]["models"] = copy.deepcopy(self.model_catalog)
        payload["user"]["is_admin"] = self.admin
        if self.admin:
            payload["user"]["roles"] = ["Admin"]
        return payload

    def _dispatch(self, route, entry):
        if entry.path in {"/v2/content-review", "/v2/admin"} and entry.method == "GET":
            route.fulfill(path=str(SPA_INDEX), content_type="text/html")
        elif entry.path == "/api/v2/admin/settings" and entry.method == "GET":
            self._json(route, {
                "settings": {
                    "enable_content_screening": self.scan_enabled,
                    "enable_enhanced_citations": self.enhanced_citations_enabled,
                    "enable_content_safety": self.content_safety_enabled,
                },
                "admin_nav": [{"id": "security", "label": "Security", "tabs": [{
                    "id": "content-screening", "label": "Content Screening", "sections": [{
                        "id": "content-screening-section", "label": "Content Screening",
                    }],
                }]}],
                "field_schema": copy.deepcopy(screening_admin_schema()),
                "section_status": {}, "runtime_flags": {}, "suppressed_capabilities": [],
            })
        elif entry.path == "/api/v2/admin/settings" and entry.method == "PATCH":
            self.settings_writes.append(copy.deepcopy(entry.body))
            updates = entry.body["settings"]
            if self.reject_settings_save:
                self._json(route, {"error": "Settings were not saved. Reload the current settings and try again.", "success": False}, 503)
            elif updates.get("enable_content_screening") is True and not self.policy["enabled"]:
                self._json(route, {
                    "error": "Save an enabled screening policy first.",
                    "field_errors": {"enable_content_screening": "Save an enabled screening policy first."},
                }, 400)
            else:
                self.scan_enabled = updates.get("enable_content_screening", self.scan_enabled)
                self._json(route, {
                    "success": True, "updated_keys": list(updates), "settings": updates, "warnings": {},
                })
        elif entry.path == "/api/content-screening/configuration" and entry.method == "GET":
            self._json(route, {
                "enabled": self.scan_enabled, "enhanced_citations_enabled": self.enhanced_citations_enabled,
                "can_manage_global": self.admin, "can_scan_all": self.can_scan_all,
                "templates": self.templates,
            })
        elif entry.path.startswith("/api/content-screening/policies/") and entry.method == "GET":
            scope_type, scope_id = entry.path.rsplit("/", 2)[-2:]
            if not self.can_manage_scope or (scope_type == "global" and not self.admin):
                self._json(route, {"error": "Not authorized.", "code": "screening_forbidden"}, 403)
            else:
                self._json(route, {
                    "scope_type": scope_type, "scope_id": scope_id, "policy": copy.deepcopy(self.policy),
                    "etag": self.policy_etag, "templates": self.templates,
                    "allowed_models": self.allowed_models,
                    "inherited_summary": copy.deepcopy(self.baseline_summary) if scope_type != "global" else None,
                })
        elif entry.path.startswith("/api/content-screening/policies/") and entry.method == "PUT":
            self.policy_writes.append(copy.deepcopy(entry.body))
            if self.reject_policy_save:
                self._json(route, {"error": "The saved policy changed or access was revoked."}, self.reject_policy_save)
            elif entry.body["etag"] != self.policy_etag:
                self._json(route, {"error": "The policy changed."}, 409)
            else:
                scope_type, scope_id = entry.path.rsplit("/", 2)[-2:]
                self.policy = normalize_policy(entry.body["policy"], scope_type=scope_type)
                self.policy_etag = f'"policy-{len(self.policy_writes) + 1}"'
                self._json(route, {
                    "scope_type": scope_type, "scope_id": scope_id, "policy": copy.deepcopy(self.policy),
                    "etag": self.policy_etag, "templates": self.templates,
                    "allowed_models": self.allowed_models,
                    "inherited_summary": copy.deepcopy(self.baseline_summary) if scope_type != "global" else None,
                })
        elif entry.path.startswith("/api/content-screening/policies/") and entry.path.endswith("/test") and entry.method == "POST":
            self.policy_samples.append(copy.deepcopy(entry.body))
            self._json(route, {
                "status": "findings", "complete": True, "finding_count": 1,
                "findings": [{"evidence": entry.body["sample_text"], "reason": "Matched sample"}],
                "findings_truncated": False, "error_code": None,
            })
        elif entry.path == "/api/content-screening/scans" and entry.method == "GET":
            self._json(route, {"items": list(self.scan_jobs.values()), "continuation": None})
        elif entry.path == "/api/content-screening/scans" and entry.method == "POST":
            if entry.body.get("all_workspaces"):
                assert self.admin and self.can_scan_all
                assert entry.body == {"all_workspaces": True}
            else:
                assert entry.body["scope_type"] == "personal" and entry.body["scope_id"] == OWNER_ID
                assert set(entry.body).issubset({"scope_type", "scope_id", "document_ids"})
            self.scan_writes.append(copy.deepcopy(entry))
            job = {
                "id": f"scan-job-{len(self.scan_jobs) + 1}", "state": "queued",
                "counters": {"queued": 2, "completed": 0, "findings": 0, "failed": 0},
                "allowed_actions": ["cancel"], "enumeration_complete": False, "cancel_requested": False,
            }
            self.scan_jobs[job["id"]] = job
            self._json(route, copy.deepcopy(job))
        elif entry.path.startswith("/api/content-screening/scans/"):
            parts = entry.path.removeprefix("/api/content-screening/scans/").split("/")
            job = self.scan_jobs[parts[0]]
            if entry.method == "GET" and len(parts) == 1:
                self._json(route, copy.deepcopy(job))
            else:
                assert entry.method == "POST" and parts[1] == "actions"
                assert set(entry.body) == {"action"}
                action = entry.body["action"]
                assert action in job["allowed_actions"]
                self.scan_writes.append(copy.deepcopy(entry))
                if action == "cancel":
                    job.update({"state": "cancelled", "cancel_requested": True, "allowed_actions": ["resume", "retry"]})
                else:
                    assert action in {"resume", "retry"}
                    job.update({"state": "queued", "cancel_requested": False, "allowed_actions": ["cancel"]})
                self._json(route, copy.deepcopy(job))
        elif entry.path == "/api/content-screening/reviews" and entry.method == "GET":
            self._json(route, {"items": list(self.reviews.values()), "continuation": None})
        elif entry.path.startswith("/api/content-screening/reviews/"):
            self._review_request(route, entry)
        elif entry.method == "GET" and entry.path == "/api/documents":
            needle = entry.query.get("search", [""])[0].casefold()
            documents = [
                copy.deepcopy(document)
                for document in self.documents
                if needle in document["file_name"].casefold()
            ]
            self._json(route, {
                "documents": documents,
                "total_count": len(documents),
                "file_downloads_enabled": True,
            })
        elif entry.method == "GET" and entry.path == "/api/documents/tags":
            self._json(route, {"tags": []})
        elif entry.method == "GET" and entry.path == "/api/documents/facets":
            self._json(route, {
                "total": len(self.documents), "untagged": len(self.documents),
                "processing": 1, "errors": 2, "recent": len(self.documents),
                "shared_with_me": 0, "by_tag": {}, "by_classification": {},
            })
        elif entry.method == "GET" and entry.path.startswith("/api/documents/"):
            identifier = entry.path.rsplit("/", 1)[-1]
            document = next((item for item in self.documents if item["id"] == identifier), None)
            if document is not None:
                self._json(route, copy.deepcopy(document))
            else:
                super()._dispatch(route, entry)
        else:
            super()._dispatch(route, entry)

    def _review_request(self, route, entry):
        parts = entry.path.removeprefix("/api/content-screening/reviews/").split("/")
        identifier, operation = parts[0], parts[1] if len(parts) > 1 else ""
        review = self.reviews.get(identifier)
        if not review:
            self._json(route, {"error": "Review not available.", "code": "screening_not_found"}, 404)
            return
        if entry.method == "GET" and not operation:
            if identifier == CANDIDATE_SCAN and review["state"] == "pending_scan" and not self.defer_candidate:
                self.complete_candidate()
            self._json(route, copy.deepcopy(review))
        elif entry.method == "GET" and operation == "downloads":
            kind = parts[2]
            assert kind in {"original", "clean"}
            assert review["downloads"][kind]["url"] == entry.path
            assert f"download_{kind}" in review["allowed_actions"]
            self.attachment_requests.append(entry.path)
            route.fulfill(body=UNTRUSTED_TEXT if kind == "original" else "Released clean derivative",
                          content_type="application/octet-stream", headers={
                              "Content-Disposition": f'{"inline" if self.inline_attachment else "attachment"}; filename="fixture-{kind}.txt"',
                              "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
                          })
        elif entry.method == "GET" and operation == "units":
            if review["state"] == "deleted":
                items, continuation = [], None
            elif identifier == SOURCE_SCAN:
                first = copy.deepcopy(self.source_units[0])
                if entry.query.get("continuation") == ["second-window"]:
                    first["text"] = UNTRUSTED_TEXT
                    first["text_offset"] = len(EARLIER_TEXT)
                    items, continuation = [first], None
                else:
                    first["text"] = EARLIER_TEXT
                    items = [first, copy.deepcopy(self.source_units[1])]
                    continuation = "second-window"
            else:
                items, continuation = copy.deepcopy(self.candidate_units), None
            self._json(route, {"items": items, "continuation": continuation, "total": 2})
        elif entry.method == "GET" and operation == "findings":
            self._json(route, {
                "items": [{
                    "rule_id": "global:literal", "unit_id": "source-unit",
                    "severity": "high", "category": "sensitive",
                    "evidence": UNTRUSTED_TEXT,
                }] if review["outcome"] == "findings" else [],
                "continuation": None, "total": review["finding_count"],
            })
        elif entry.method == "POST" and operation in {"preview", "remediate"}:
            assert entry.body["etag"] == review["etag"]
            assert set(entry.body) == {"etag", "edits"}
            self.screening_writes.append(copy.deepcopy(entry))
            units = copy.deepcopy(self.source_units)
            for edit in entry.body["edits"]:
                unit = next(item for item in units if item["unit_id"] == edit["unit_id"])
                assert edit["content_hash"] == unit["content_hash"]
                if edit["action"] == "remove_span":
                    assert set(edit) == {"action", "unit_id", "content_hash", "start", "end"}
                    unit["text"] = unit["text"][:edit["start"]] + unit["text"][edit["end"]:]
                elif edit["action"] == "replace_cell":
                    assert set(edit) == {"action", "unit_id", "content_hash", "text"}
                    unit["text"] = edit["text"]
                else:
                    assert edit["action"] == "remove_unit"
                    units.remove(unit)
            for unit in units:
                unit["text_total"] = len(unit["text"])
            if operation == "preview":
                self._json(route, {
                    "units": units, "total_units": len(units), "preview_truncated": False,
                    "content_fingerprint": "candidate-fingerprint", "removed_unit_ids": [],
                    "removed_unit_count": 2 - len(units), "warnings": [],
                })
            else:
                for unit in units:
                    unit["content_hash"] = f"candidate-{unit['content_hash']}"
                self.candidate_units = units
                candidate = review_record(
                    CANDIDATE_SCAN, candidate_of=SOURCE_SCAN, outcome=None, finding_count=0,
                    state="pending_scan", sanitized=True,
                    coverage={"complete": False, "units_total": len(units)},
                    evidence={"units_available": True, "findings_available": False},
                    allowed_actions=[],
                )
                self.reviews[CANDIDATE_SCAN] = candidate
                self._json(route, copy.deepcopy(candidate), 202)
        elif entry.method == "POST" and operation == "decision":
            assert entry.body["etag"] == review["etag"]
            assert entry.body["reason"].strip()
            action = entry.body["action"]
            assert action in review["allowed_actions"]
            self.screening_writes.append(copy.deepcopy(entry))
            if action == "approve_with_flags":
                assert entry.body["acknowledge_flags"] is True
            if action == "approve_clean":
                assert review["coverage"]["complete"] and review["outcome"] == "pass" and review["candidate_of"]
            review["decision"] = {
                "action": action, "actor_id": OWNER_ID, "reason": entry.body["reason"],
                "decided_at": "2026-09-16T15:00:00Z",
            }
            if action == "approve_with_flags":
                review["warning"] = "Approved with flags. Review the recorded findings before use."
            review["state"] = {
                "approve_with_flags": "approved_with_flags", "approve_clean": "cleared",
                "reject": "rejected", "delete": "deleted",
            }[action]
            review["allowed_actions"] = ["delete"] if action == "reject" else []
            review["etag"] = f'"{identifier}-decided"'
            self._json(route, copy.deepcopy(review))
        else:
            super()._dispatch(route, entry)

    def complete_candidate(self, outcome="pass"):
        self.reviews[CANDIDATE_SCAN].update({
            "state": "scan_error" if outcome == "error" else "pending_review", "outcome": outcome,
            "coverage": {"complete": outcome != "error", "units_total": len(self.candidate_units)},
            "evidence": {"units_available": True, "findings_available": True},
            "allowed_actions": ["remediate", "reject", "delete"] + (["approve_clean"] if outcome == "pass" else []),
        })

    def enable_downloads(self, *, clean=False):
        review = self.reviews[SOURCE_SCAN]
        kinds = ["original", "clean"] if clean else ["original"]
        if clean:
            review.update({"state": "cleared", "sanitized": True, "allowed_actions": []})
        review["allowed_actions"].extend(f"download_{kind}" for kind in kinds)
        review["downloads"] = {
            kind: {
                "url": f"/api/content-screening/reviews/{SOURCE_SCAN}/downloads/{kind}",
                "file_name": f"fixture-{kind}.txt",
            } if kind in kinds else None for kind in ("original", "clean")
        }


@pytest.fixture
def screening_ui(page):
    fixture = ScreeningUiFixture(page)
    yield fixture
    fixture.assert_clean()


@pytest.mark.parametrize("theme,width,height", [("light", 1440, 900), ("dark", 390, 844)])
def test_persisted_holds_remain_visible_and_unselectable_when_scanning_is_disabled(
    screening_ui, theme, width, height
):
    """Rows/cards cannot treat a held record with 100% extraction as ready."""
    ui = screening_ui
    if width < 1024:
        ui.preferences["v2DocumentsPrefs"]["viewMode"] = "tiles"
    ui.open("/workspace/documents", theme=theme, width=width, height=height)
    page = ui.page
    for identifier in ("held", "scanning", "failed", "incomplete"):
        expect(page.get_by_role("checkbox", name=f"Select {identifier}.txt", exact=True)).to_be_disabled()
    expect(page.get_by_role("checkbox", name="Select legacy.txt", exact=True)).to_be_enabled()
    expect(page.get_by_role("checkbox", name="Select flagged", exact=True)).to_be_enabled()
    expect(page.get_by_test_id("screening-status").filter(has_text="Review needed")).to_be_visible()
    expect(page.get_by_test_id("screening-status").filter(has_text="Scanning")).to_be_visible()
    expect(page.get_by_test_id("screening-status").filter(has_text="Scan failed")).to_be_visible()
    expect(page.get_by_test_id("screening-status").filter(has_text="Incomplete coverage")).to_be_visible()
    expect(page.get_by_test_id("screening-status").filter(has_text="Approved with flags")).to_be_visible()
    expect(page.get_by_text("Protected extracted title", exact=False)).to_have_count(0)
    expect(page.get_by_text("Reviewer-only extracted evidence", exact=True)).to_have_count(0)
    ui.assert_no_overflow()


def test_select_all_and_details_do_not_offer_ordinary_actions_for_held_content(screening_ui):
    ui = screening_ui
    ui.open("/workspace/documents")
    page = ui.page
    page.get_by_role("checkbox", name="Select all documents on this page", exact=True).check()
    expect(page.get_by_role("checkbox", name="Select legacy.txt", exact=True)).to_be_checked()
    expect(page.get_by_role("checkbox", name="Select flagged", exact=True)).to_be_checked()
    expect(page.get_by_role("checkbox", name="Select held.txt", exact=True)).not_to_be_checked()

    page.get_by_role("button", name="Details for held.txt", exact=True).click()
    details = page.locator("aside").filter(
        has=page.get_by_role("heading", name="Details", exact=True)
    )
    expect(details).to_be_visible()
    expect(details.get_by_text("Held sources cannot be selected", exact=False)).to_be_visible()
    for label in ("Chat", "Download", "Extract", "Share", "Edit", "Delete"):
        expect(details.get_by_role("button", name=label, exact=True)).to_have_count(0)
    expect(details.get_by_text("Reviewer-only extracted evidence", exact=True)).to_have_count(0)

    page.get_by_role("button", name="Details for legacy.txt", exact=True).click()
    expect(details.get_by_role("button", name="Chat", exact=True)).to_be_visible()
    expect(details.get_by_role("button", name="Download", exact=True)).to_be_visible()
    assert not any(
        entry.method == "POST" and entry.path != "/api/user/settings"
        for entry in ui.requests
    )


def test_document_picker_explains_held_sources_without_selecting_them(screening_ui):
    ui = screening_ui
    ui.open("/chat")
    page = ui.page
    toolbar = page.get_by_title(re.compile(r"^Documents(?: · \d+)?$"))
    if not toolbar.is_visible():
        page.get_by_title("Manual controls", exact=True).click()
    toolbar.click()
    expect(page.get_by_role("searchbox", name="Search documents", exact=True)).to_be_visible()
    for identifier in ("held", "scanning", "failed", "incomplete"):
        candidate = page.get_by_role(
            "button", name=re.compile(rf"^{identifier}\.txt")
        ).and_(page.locator("button[aria-pressed]"))
        expect(candidate).to_be_disabled()
        expect(candidate).to_have_attribute("aria-pressed", "false")
    approved = page.get_by_role("button", name=re.compile("^flagged")).and_(
        page.locator("button[aria-pressed]")
    )
    expect(approved).to_be_enabled()
    expect(approved.get_by_test_id("screening-status")).to_contain_text("Approved with flags")
    approved.click()
    expect(approved).to_have_attribute("aria-pressed", "true")
    page.get_by_role("button", name="Done", exact=True).click()
    expect(page.get_by_role("button", name="Remove flagged", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Remove held.txt", exact=True)).to_have_count(0)
    ui.assert_no_secret_storage("Reviewer-only extracted evidence")


def open_review(ui, **layout):
    ui.open(f"/content-review?scan_id={SOURCE_SCAN}", **layout)
    expect(ui.page.get_by_role("heading", name="Document held", exact=True)).to_be_visible()


def accept_flags(page):
    page.get_by_label("Decision reason", exact=True).fill("Reviewed this exact source revision.")
    page.get_by_role("checkbox", name=re.compile("^I have reviewed the findings")).check()
    page.get_by_role("button", name="Approve with flags", exact=True).click()


@pytest.mark.parametrize("theme,width,height", [("light", 1440, 900), ("dark", 390, 844)])
def test_review_edits_unicode_window_and_cell_then_requires_explicit_clean_approval(
    screening_ui, theme, width, height
):
    ui = screening_ui
    open_review(ui, theme=theme, width=width, height=height)
    page = ui.page
    page.get_by_role("button", name="Load more evidence", exact=True).click()
    page.get_by_role("button", name=re.compile(r"Legacy indexed segment.*offset 100")).click()
    source = page.get_by_label("Protected source text", exact=True)
    expect(source).to_have_value(UNTRUSTED_TEXT)
    assert page.evaluate("window.screeningEvidenceExecuted === true") is False
    expect(page.locator("iframe")).to_have_count(0)
    source.evaluate("""element => {
        element.focus();
        const start = element.value.indexOf('SECRET');
        element.setSelectionRange(start, start + 'SECRET'.length);
    }""")
    source.dispatch_event("mouseup")
    page.get_by_role("button", name="Remove selected span", exact=True).click()
    expect(page.get_by_text("Selected code points 101–107 (end exclusive).", exact=True)).to_be_visible()

    page.get_by_role("button", name=re.compile(r"^Table cell")).click()
    page.get_by_label("Replacement cell value", exact=True).fill("safe cell")
    page.get_by_role("button", name="Replace cell", exact=True).click()
    page.get_by_role("button", name="Validate edit preview", exact=True).click()
    expect(page.get_by_test_id("screening-server-preview")).to_be_visible()
    preview = ui.screening_writes[-1].body
    assert preview["etag"] == f'"{SOURCE_SCAN}-etag"'
    assert preview["edits"] == [
        {"action": "remove_span", "unit_id": "source-unit", "content_hash": "source-hash", "start": 101, "end": 107},
        {"action": "replace_cell", "unit_id": "cell-unit", "content_hash": "cell-hash", "text": "safe cell"},
    ]
    page.get_by_role("button", name="Create candidate and rescan", exact=True).click()
    expect(page).to_have_url(re.compile(f"scan_id={CANDIDATE_SCAN}"))
    clean = page.get_by_role("button", name="Approve clean candidate", exact=True)
    expect(clean).to_be_disabled()
    expect(page.get_by_test_id("screening-status")).to_contain_text("Held")
    assert not any(entry.path.endswith("/decision") for entry in ui.screening_writes)
    page.get_by_label("Decision reason", exact=True).fill("Complete candidate scan is clean.")
    clean.click()
    expect(page.get_by_test_id("screening-status")).to_contain_text("Screened")
    assert ui.screening_writes[-1].body["etag"] == f'"{CANDIDATE_SCAN}-etag"'
    assert ui.screening_writes[-1].body["action"] == "approve_clean"
    ui.assert_no_secret_storage(UNTRUSTED_TEXT, "private cell")
    ui.assert_no_overflow()


def test_flagged_approval_requires_reason_and_explicit_acknowledgment(screening_ui):
    ui = screening_ui
    open_review(ui)
    page = ui.page
    approve = page.get_by_role("button", name="Approve with flags", exact=True)
    expect(approve).to_be_disabled()
    page.get_by_label("Decision reason", exact=True).fill("Accepted after scoped review.")
    expect(approve).to_be_disabled()
    page.get_by_role("checkbox", name=re.compile("^I have reviewed the findings")).check()
    approve.click()
    expect(page.get_by_test_id("screening-status")).to_contain_text("Approved with flags")
    assert ui.screening_writes[-1].body["acknowledge_flags"] is True
    expect(page.get_by_text("Recorded decision:", exact=False)).to_contain_text("Accepted after scoped review.")


@pytest.mark.parametrize("clean", [False, True])
def test_v2_downloads_exact_authorized_original_and_released_derivative(screening_ui, clean):
    ui = screening_ui
    ui.enable_downloads(clean=clean)
    open_review(ui)
    page = ui.page
    with page.expect_download() as original:
        page.get_by_role("button", name="Download reviewer-only original", exact=True).click()
    assert original.value.suggested_filename == "fixture-original.txt"
    if clean:
        with page.expect_download() as derivative:
            page.get_by_role("button", name="Download clean derivative", exact=True).click()
        assert derivative.value.suggested_filename == "fixture-clean.txt"
    else:
        expect(page.get_by_role("button", name="Download clean derivative", exact=True)).to_be_disabled()
    assert ui.attachment_requests == [
        f"/api/content-screening/reviews/{SOURCE_SCAN}/downloads/{kind}"
        for kind in (("original", "clean") if clean else ("original",))
    ]
    expect(page.locator("iframe, object, embed")).to_have_count(0)
    assert page.evaluate("window.screeningEvidenceExecuted === true") is False
    ui.assert_no_secret_storage(UNTRUSTED_TEXT)


@pytest.mark.parametrize("url", [
    "javascript:window.screeningEvidenceExecuted=true",
    "https://private.invalid/source?signature=untrusted",
    "//private.invalid/source",
    "/api/content-screening/reviews/other-scan/downloads/original",
])
def test_v2_download_urls_must_be_local_and_bound_to_this_scan(screening_ui, url):
    ui = screening_ui
    ui.enable_downloads()
    ui.reviews[SOURCE_SCAN]["downloads"]["original"]["url"] = url
    open_review(ui)
    expect(ui.page.get_by_role("button", name="Download reviewer-only original", exact=True)).to_be_disabled()
    assert ui.attachment_requests == []


def test_v2_original_metadata_without_an_action_does_not_authorize_download(screening_ui):
    ui = screening_ui
    ui.enable_downloads()
    ui.reviews[SOURCE_SCAN]["allowed_actions"].remove("download_original")
    open_review(ui)
    expect(ui.page.get_by_role("button", name="Download reviewer-only original", exact=True)).to_be_disabled()
    assert ui.attachment_requests == []


@pytest.mark.parametrize("failure", ["inline", "revoked"])
def test_v2_attachment_failure_never_renders_or_saves_active_content(screening_ui, failure):
    ui = screening_ui
    ui.enable_downloads()
    ui.inline_attachment = failure == "inline"
    downloads = []
    ui.page.on("download", lambda download: downloads.append(download))
    if failure == "revoked":
        ui.reject_next("GET", f"/api/content-screening/reviews/{SOURCE_SCAN}/downloads/original",
                       status=403, error="Private provider message", code="screening_forbidden")
    open_review(ui)
    ui.page.get_by_role("button", name="Download reviewer-only original", exact=True).click()
    expect(ui.page.get_by_role("alert")).to_contain_text(
        "not authorized" if failure == "revoked" else "safe attachment response"
    )
    expect(ui.page.get_by_role("alert")).not_to_contain_text("Private provider")
    assert downloads == []
    assert ui.page.evaluate("window.screeningEvidenceExecuted === true") is False
    if failure == "revoked":
        expect(ui.page.get_by_label("Protected source text", exact=True)).to_have_count(0)


@pytest.mark.parametrize("source_missing", [True, False])
def test_v2_metadata_only_review_preserves_reject_delete_when_evidence_is_unavailable(screening_ui, source_missing):
    ui = screening_ui
    if source_missing:
        ui.reviews[SOURCE_SCAN].update({
            "state": "scan_error", "outcome": "error", "allowed_actions": ["reject", "delete"],
            "evidence": {"units_available": False, "findings_available": False},
        })
    else:
        ui.reject_next("GET", f"/api/content-screening/reviews/{SOURCE_SCAN}/units",
                       status=503, error="Unavailable", code="screening_evidence_unavailable")
    open_review(ui)
    page = ui.page
    expect(page.get_by_text("Canonical evidence is unavailable.", exact=False)).to_be_visible()
    expect(page.get_by_label("Protected source text", exact=True)).to_have_count(0)
    page.get_by_label("Decision reason", exact=True).fill("Missing evidence must remain held.")
    expect(page.get_by_role("button", name="Reject and keep held", exact=True)).to_be_enabled()
    expect(page.get_by_role("button", name="Delete document", exact=True)).to_be_enabled()
    if source_missing:
        assert not any(entry.path.endswith(("/units", "/findings")) for entry in ui.requests)
    else:
        expect(page.get_by_role("button", name="Approve with flags", exact=True)).to_be_disabled()
    page.get_by_role("button", name="Reject and keep held", exact=True).click()
    expect(page.get_by_test_id("screening-status")).to_contain_text("Rejected")
    assert ui.screening_writes[-1].body["action"] == "reject"


@pytest.mark.parametrize("outcome", ["pass", "error"])
def test_v2_queued_candidate_polls_without_approving_pending_or_failed_scans(screening_ui, outcome):
    ui = screening_ui
    ui.defer_candidate = True
    open_review(ui)
    page = ui.page
    page.get_by_role("button", name=re.compile(r"^Table cell")).click()
    page.get_by_label("Replacement cell value", exact=True).fill("safe cell")
    page.get_by_role("button", name="Replace cell", exact=True).click()
    page.get_by_role("button", name="Validate edit preview", exact=True).click()
    expect(page.get_by_test_id("screening-server-preview")).to_be_visible()
    page.get_by_role("button", name="Create candidate and rescan", exact=True).click()
    expect(page.get_by_text("is queued or scanning and remains held", exact=False)).to_be_visible()
    expect(page.get_by_role("button", name="Approve clean candidate", exact=True)).to_have_count(0)
    assert not any(entry.path == f"/api/content-screening/reviews/{CANDIDATE_SCAN}/findings" for entry in ui.requests)
    assert not any(entry.path.endswith("/decision") for entry in ui.screening_writes)
    ui.complete_candidate(outcome)
    expect(page.get_by_text("is queued or scanning and remains held", exact=False)).to_have_count(0, timeout=10000)
    if outcome == "pass":
        page.get_by_label("Decision reason", exact=True).fill("Required candidate checks are complete.")
        expect(page.get_by_role("button", name="Approve clean candidate", exact=True)).to_be_enabled()
    else:
        expect(page.get_by_test_id("screening-status")).to_contain_text("Scan failed")
        expect(page.get_by_role("button", name="Approve clean candidate", exact=True)).to_have_count(0)
    assert not any(entry.path.endswith("/decision") for entry in ui.screening_writes)


def test_stale_decision_requires_refresh_and_never_retries_automatically(screening_ui):
    ui = screening_ui
    open_review(ui)
    path = f"/api/content-screening/reviews/{SOURCE_SCAN}/decision"
    ui.reject_next("POST", path, status=409, error="Review changed.", code="screening_conflict")
    accept_flags(ui.page)
    expect(ui.page.get_by_role("alert")).to_contain_text("Refresh")
    expect(ui.page.get_by_role("button", name="Approve with flags", exact=True)).to_be_disabled()
    assert len([entry for entry in ui.requests if entry.method == "POST" and entry.path == path]) == 1
    ui.reviews[SOURCE_SCAN]["etag"] = '"refreshed-etag"'
    ui.page.get_by_role("button", name="Refresh review", exact=True).click()
    expect(ui.page.get_by_label("Decision reason", exact=True)).to_have_value("")
    accept_flags(ui.page)
    expect(ui.page.get_by_test_id("screening-status")).to_contain_text("Approved with flags")
    assert ui.screening_writes[-1].body["etag"] == '"refreshed-etag"'


def test_incomplete_coverage_disables_both_approval_actions(screening_ui):
    ui = screening_ui
    ui.reviews[SOURCE_SCAN].update({
        "state": "incomplete", "outcome": "incomplete", "candidate_of": "earlier",
        "coverage": {"complete": False, "units_total": 2},
        "allowed_actions": ["approve_clean", "approve_with_flags", "reject", "delete"],
    })
    open_review(ui)
    page = ui.page
    page.get_by_label("Decision reason", exact=True).fill("This must not authorize incomplete coverage.")
    page.get_by_role("checkbox", name=re.compile("^I have reviewed the findings")).check()
    expect(page.get_by_role("button", name="Approve with flags", exact=True)).to_be_disabled()
    expect(page.get_by_role("button", name="Approve clean candidate", exact=True)).to_be_disabled()
    page.get_by_role("button", name="Reject and keep held", exact=True).click()
    expect(page.get_by_test_id("screening-status")).to_contain_text("Rejected")
    assert ui.screening_writes[-1].body["action"] == "reject"


def test_deletion_requires_explicit_confirmation(screening_ui):
    ui = screening_ui
    open_review(ui)
    page = ui.page
    page.get_by_label("Decision reason", exact=True).fill("Document should be permanently removed.")
    page.get_by_role("button", name="Delete document", exact=True).click()
    dialog = page.get_by_role("dialog", name="Delete screened document?", exact=True)
    expect(dialog.get_by_role("button", name="Confirm document deletion", exact=True)).to_be_disabled()
    assert not ui.screening_writes
    dialog.get_by_label("Type DELETE to confirm", exact=True).fill("DELETE")
    dialog.get_by_role("button", name="Confirm document deletion", exact=True).click()
    expect(page.get_by_test_id("screening-status")).to_contain_text("Deleted")
    expect(page.get_by_label("Protected source text", exact=True)).to_have_count(0)


def test_admin_scan_role_does_not_override_denied_private_review(screening_ui):
    ui = screening_ui
    ui.admin = True
    path = f"/api/content-screening/reviews/{SOURCE_SCAN}"
    ui.reject_next("GET", path, status=403, error="Review unavailable.", code="screening_forbidden")
    ui.open(f"/content-review?scan_id={SOURCE_SCAN}")
    expect(ui.page.get_by_role("alert")).to_contain_text("not authorized")
    expect(ui.page.get_by_label("Protected source text", exact=True)).to_have_count(0)
    expect(ui.page.get_by_role("button", name="Approve with flags", exact=True)).to_have_count(0)
    assert not any(entry.path.endswith(("/units", "/findings")) for entry in ui.requests)


def test_deleting_state_can_retry_cleanup_without_requesting_deleted_evidence(screening_ui):
    ui = screening_ui
    ui.reviews[SOURCE_SCAN].update({"state": "deleting", "allowed_actions": ["delete"]})
    open_review(ui)
    page = ui.page
    expect(page.get_by_label("Protected source text", exact=True)).to_have_count(0)
    assert not any(entry.path.endswith(("/units", "/findings")) for entry in ui.requests)
    page.get_by_label("Decision reason", exact=True).fill("Complete the already-started cleanup.")
    page.get_by_role("button", name="Retry document deletion", exact=True).click()
    dialog = page.get_by_role("dialog", name="Delete screened document?", exact=True)
    dialog.get_by_label("Type DELETE to confirm", exact=True).fill("DELETE")
    dialog.get_by_role("button", name="Confirm document deletion", exact=True).click()
    expect(page.get_by_test_id("screening-status")).to_contain_text("Deleted")
    assert len(ui.screening_writes) == 1


def test_workspace_scan_uses_server_scope_and_returned_job_actions(screening_ui):
    ui = screening_ui
    ui.scan_enabled = True
    ui.open("/workspace/documents")
    page = ui.page
    page.get_by_role("button", name="Screening scans", exact=True).click()
    dialog = page.get_by_role("dialog", name="Content screening controls", exact=True)
    expect(dialog.get_by_role("region", name="Required administrative baseline")).to_be_visible()
    expect(dialog.get_by_role("option", name=re.compile("All workspaces"))).to_have_count(0)
    dialog.get_by_role("button", name="Start scan", exact=True).click()
    expect(dialog.get_by_role("button", name="Cancel scan", exact=True)).to_be_visible()
    assert ui.scan_writes[0].body == {"scope_type": "personal", "scope_id": OWNER_ID}
    expect(dialog.get_by_role("button", name="Pause scan", exact=True)).to_have_count(0)
    dialog.get_by_role("button", name="Cancel scan", exact=True).click()
    expect(dialog.get_by_text("Cancellation requested", exact=False)).to_be_visible()
    expect(dialog.get_by_role("button", name="Cancel scan", exact=True)).to_have_count(0)
    expect(dialog.get_by_role("button", name="Retry failed items", exact=True)).to_be_visible()
    dialog.get_by_role("button", name="Resume scan", exact=True).click()
    expect(dialog.get_by_role("button", name="Cancel scan", exact=True)).to_be_visible()
    assert [entry.body.get("action") for entry in ui.scan_writes[1:]] == ["cancel", "resume"]


def test_document_scan_targets_only_the_reviewed_document(screening_ui):
    ui = screening_ui
    ui.scan_enabled = True
    open_review(ui)
    page = ui.page
    page.get_by_role("button", name="Scan this document", exact=True).click()
    dialog = page.get_by_role("dialog", name="Content screening controls", exact=True)
    dialog.get_by_role("button", name="Start scan", exact=True).click()
    expect(dialog.get_by_role("button", name="Cancel scan", exact=True)).to_be_visible()
    assert ui.scan_writes[0].body == {
        "scope_type": "personal", "scope_id": OWNER_ID, "document_ids": ["held"],
    }


def test_schema_backed_admin_section_requires_explicit_all_workspace_confirmation(screening_ui):
    ui = screening_ui
    ui.admin = True
    ui.can_scan_all = True
    ui.scan_enabled = True
    ui.open("/admin")
    page = ui.page
    expect(page.get_by_role("checkbox", name=re.compile("^Screen workspace content before publication"))).to_be_checked()
    page.get_by_role("button", name="Screening scans", exact=True).click()
    controls = page.get_by_role("dialog", name="Content screening controls", exact=True)
    controls.get_by_role("button", name="Start scan", exact=True).click()
    confirmation = page.get_by_role("dialog", name="Scan all workspaces?", exact=True)
    expect(confirmation).to_be_visible()
    assert not ui.scan_writes
    confirmation.get_by_role("button", name="Confirm all-workspace scan", exact=True).click()
    expect(controls.get_by_role("button", name="Cancel scan", exact=True)).to_be_visible()
    assert ui.scan_writes[0].body == {"all_workspaces": True}


def test_bootstrap_admin_role_does_not_infer_scan_or_scope_permissions(screening_ui):
    ui = screening_ui
    ui.admin = True
    ui.scan_enabled = True
    ui.can_scan_all = False
    ui.open("/workspace/documents")
    page = ui.page
    page.get_by_role("button", name="Screening scans", exact=True).click()
    dialog = page.get_by_role("dialog", name="Content screening controls", exact=True)
    expect(dialog.get_by_role("option", name=re.compile("All workspaces"))).to_have_count(0)
    dialog.get_by_role("button", name="Close", exact=True).click()
    ui.can_manage_scope = False
    page.get_by_role("button", name="Screening scans", exact=True).click()
    expect(dialog.get_by_role("alert")).to_contain_text("not authorized")
    expect(dialog.get_by_role("button", name="Start scan", exact=True)).to_have_count(0)
    assert not ui.scan_writes


def open_screening_admin(ui):
    ui.admin = True
    ui.open("/admin")
    editor = ui.page.get_by_role("region", name="Global screening policy", exact=True)
    expect(editor.get_by_role("button", name="Save screening policy", exact=True)).to_be_visible()
    return editor


def test_admin_policy_is_discoverable_and_editable_before_citations_are_enabled(screening_ui):
    ui = screening_ui
    ui.enhanced_citations_enabled = False
    ui.content_safety_enabled = False
    ui.policy = default_policy()
    editor = open_screening_admin(ui)
    page = ui.page
    expect(page.get_by_role("heading", name="Content Screening", exact=True)).to_be_visible()
    toggle = page.get_by_role("checkbox", name=re.compile("^Screen workspace content before publication"))
    expect(toggle).to_be_visible()
    expect(toggle).to_be_disabled()
    expect(page.get_by_text("must be enabled before these settings take effect.", exact=False)).to_be_visible()
    editor.get_by_role("button", name="Add literal rule", exact=True).click()
    editor.get_by_label("Rule name", exact=True).fill("Restricted project values")
    editor.get_by_label("Literal values or phrases", exact=True).fill("DO_NOT_SHARE")
    editor.get_by_text("Baseline policy enabled", exact=True).click()
    editor.get_by_role("button", name="Save screening policy", exact=True).click()
    expect(editor.get_by_text("Screening policy saved.", exact=True)).to_be_visible()
    assert ui.policy_writes[0]["etag"] == '"policy-etag"'
    assert ui.policy["enabled"] is True
    assert ui.policy["rules"][0]["values"] == ["DO_NOT_SHARE"]
    assert not ui.scan_enabled and not ui.settings_writes
    editor.get_by_role("button", name="Reload saved policy", exact=True).click()
    expect(editor.get_by_label("Rule name", exact=True)).to_have_value("Restricted project values")


def test_admin_screening_saves_and_survives_reload_without_content_safety(screening_ui):
    ui = screening_ui
    ui.content_safety_enabled = False
    open_screening_admin(ui)
    toggle = ui.page.get_by_role("checkbox", name=re.compile("^Screen workspace content before publication"))
    ui.page.get_by_text("Screen workspace content before publication", exact=True).click()
    ui.page.get_by_role("button", name="Save changes", exact=True).click()
    expect(ui.page.get_by_text("Saved 1 setting.", exact=True)).to_be_visible()
    assert ui.scan_enabled is True
    assert ui.content_safety_enabled is False
    assert ui.settings_writes == [{"settings": {"enable_content_screening": True}}]
    ui.page.reload()
    expect(toggle).to_be_checked()


def test_admin_failed_screening_write_is_not_reported_as_saved(screening_ui):
    ui = screening_ui
    ui.reject_settings_save = True
    open_screening_admin(ui)
    toggle = ui.page.get_by_role("checkbox", name=re.compile("^Screen workspace content before publication"))
    ui.page.get_by_text("Screen workspace content before publication", exact=True).click()
    ui.page.get_by_role("button", name="Save changes", exact=True).click()
    expect(ui.page.get_by_text("Settings were not saved. Reload the current settings and try again.", exact=True)).to_be_visible()
    expect(ui.page.get_by_text("Saved 1 setting.", exact=True)).to_have_count(0)
    assert ui.scan_enabled is False


def test_admin_policy_sample_uses_draft_without_saving_or_executing_html(screening_ui):
    ui = screening_ui
    editor = open_screening_admin(ui)
    editor.get_by_label("Literal values or phrases", exact=True).fill("DRAFT_VALUE")
    sample = '<img src=x onerror="window.screeningSampleExecuted=true">DRAFT_VALUE'
    editor.get_by_label("Sample content", exact=True).fill(sample)
    editor.get_by_role("button", name="Test screening policy", exact=True).click()
    expect(editor.get_by_text("Sample inspection complete: 1 finding(s).", exact=True)).to_be_visible()
    assert ui.policy_samples[0]["policy"]["rules"][0]["values"] == ["DRAFT_VALUE"]
    assert ui.policy_samples[0]["sample_text"] == sample
    assert not ui.policy_writes and not ui.settings_writes
    assert ui.page.evaluate("Boolean(window.screeningSampleExecuted)") is False
    expect(editor.locator("pre img")).to_have_count(0)


def test_admin_policy_conflict_requires_reload_before_another_save(screening_ui):
    ui = screening_ui
    ui.reject_policy_save = 409
    editor = open_screening_admin(ui)
    editor.get_by_label("Rule name", exact=True).fill("Unsaved local name")
    editor.get_by_role("button", name="Save screening policy", exact=True).click()
    expect(editor.get_by_text("The saved policy changed.", exact=False)).to_be_visible()
    expect(editor.get_by_role("button", name="Save screening policy", exact=True)).to_be_disabled()
    assert len(ui.policy_writes) == 1
    ui.reject_policy_save = None
    ui.policy["rules"][0]["name"] = "Someone else's current name"
    ui.policy_etag = '"policy-other-admin"'
    editor.get_by_role("button", name="Reload current policy", exact=True).click()
    expect(editor.get_by_label("Rule name", exact=True)).to_have_value("Someone else's current name")
    editor.get_by_label("Rule name", exact=True).fill("Fresh reviewed name")
    editor.get_by_role("button", name="Save screening policy", exact=True).click()
    expect(editor.get_by_text("Screening policy saved.", exact=True)).to_be_visible()
    assert ui.policy_writes[1]["etag"] == '"policy-other-admin"'


def test_workspace_policy_editor_does_not_send_global_model_permissions(screening_ui):
    ui = screening_ui
    ui.policy["allowed_models"] = [{"endpoint_id": "global-only", "model_id": "model"}]
    ui.open("/workspace/documents")
    ui.page.get_by_role("button", name="Screening scans", exact=True).click()
    editor = ui.page.get_by_role("region", name="Workspace screening policy", exact=True)
    expect(editor.get_by_role("region", name="Required administrative baseline")).to_be_visible()
    editor.get_by_label("Rule name", exact=True).fill("Workspace restriction")
    editor.get_by_role("button", name="Save screening policy", exact=True).click()
    expect(editor.get_by_text("Screening policy saved.", exact=True)).to_be_visible()
    assert "allowed_models" not in ui.policy_writes[0]["policy"]


def test_policy_editor_uses_configured_model_ids_and_backend_default_instructions(screening_ui):
    ui = screening_ui
    ui.model_catalog = [{
        "selection_key": "global:global:scanner-endpoint:scanner-model",
        "endpoint_id": "scanner-endpoint", "model_id": "scanner-model",
        "model_name": "gpt-4o", "deployment_name": "scanner-deployment",
        "display_name": "Screening model", "provider": "aoai",
    }]
    editor = open_screening_admin(ui)
    editor.get_by_text("Enable AI checks", exact=True).click()
    editor.get_by_label("Scanner model", exact=True).select_option("0")
    editor.get_by_label("AI starter criteria", exact=True).select_option("1")
    editor.get_by_role("button", name="Use criteria", exact=True).click()
    editor.get_by_role("button", name="Save screening policy", exact=True).click()
    expect(editor.get_by_text("Screening policy saved.", exact=True)).to_be_visible()
    assert ui.policy["ai"]["model_selection"] == {"endpoint_id": "scanner-endpoint", "model_id": "scanner-model"}
    assert ui.policy["ai"]["instructions"] == list(AI_STARTER_CRITERIA.values())[1]
