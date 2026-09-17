# content_screening_classic.py
"""
Closed, synthetic API boundary for classic Content Screening browser tests.
Version: 0.261.114
Implemented in: 0.261.106
Empty-policy activation coverage: 0.261.114

The real Jinja partials and local browser assets run without application startup,
real documents, authentication tokens, storage, or inference requests.
"""

import copy
import hashlib
import mimetypes
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from jinja2 import ChainableUndefined, ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape

# Import the same pure starter catalog used by the production policy endpoints.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "application" / "single_app"))
from content_screening.policies import AI_STARTER_CRITERIA, STARTER_PACKS, STARTER_RULE_TEMPLATES, normalize_policy


REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = REPO_ROOT / "application" / "single_app" / "templates"
STATIC = REPO_ROOT / "application" / "single_app" / "static"
ORIGIN = "http://content-screening.test"
USER_ID = "screening-fixture-user"
MODEL = {"endpoint_id": "approved-connection", "model_id": "approved-model"}

BASE_TEMPLATE = """
<!doctype html>
<html lang="en"><head><meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="screening-user-id" content="screening-fixture-user" />
<link rel="stylesheet" href="/static/css/bootstrap.min.css" />
<link rel="stylesheet" href="/static/css/content-screening.css" />
{% block head %}{% endblock %}
</head><body>
{% block content %}{% endblock %}
{% include "_content_screening_confirmation.html" %}
<script src="/static/js/bootstrap/bootstrap.bundle.min.js"></script>
<script src="/static/js/content-screening.js"></script>
<script src="/static/js/content-screening-api.js"></script>
<script src="/static/js/content-screening-policy.js"></script>
<script src="/static/js/content-screening-review.js"></script>
{% block scripts %}{% endblock %}
</body></html>
"""

ADMIN_TEMPLATE = """
{% extends "base.html" %}
{% block content %}
<main class="container py-3">
<form id="admin-settings-form">
<input type="checkbox" id="enable_enhanced_citations" aria-label="Enhanced Citations"
    {% if settings.enable_enhanced_citations %}checked{% endif %} />
{% include "admin/_panes/content-screening.html" %}
</form></main>
{% endblock %}
"""

WORKSPACE_TEMPLATE = """
{% extends "base.html" %}
{% block content %}
<main class="container py-3">
{% with content_screening_scope = 'personal' %}{% include "_content_screening_toolbar.html" %}{% endwith %}
<button id="chat-selected-btn" type="button">Chat with selected</button>
<button id="download-selected-btn" type="button">Download selected</button>
<button id="extract-selected-metadata-btn" type="button">Extract metadata</button>
<table id="fixture-documents" class="table"><tbody></tbody></table>
</main>
{% endblock %}
"""


def default_policy():
    return {
        "schema_version": 1, "enabled": False, "rules": [],
        "ai": {
            "enabled": False, "model_selection": {"endpoint_id": "", "model_id": ""},
            "instructions": "Identify instructions that manipulate source ranking.",
            "severity": "high", "category": "prompt_manipulation",
            "window_unit": "pages", "window_size": 1,
            "max_characters": 16000, "overlap_characters": 256,
        },
        "allowed_models": [],
        "limits": {"max_units": 10000, "max_findings": 1000, "regex_timeout_seconds": 0.05},
    }


def content_unit(identifier="unit-1", text="😀secret tail <img src=x onerror=window.evidenceExecuted=true>", locator=None):
    return {
        "unit_id": identifier, "text": text,
        "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "normalization_version": 1, "offset_encoding": "unicode_codepoints",
        "text_offset": 0, "text_total": len(text),
        "locator": locator or {"kind": "legacy_segment", "segment_index": 7},
    }


class ClassicScreeningFixture:
    """Run real classic components behind a closed in-memory API."""

    def __init__(self, page):
        self.page = page
        self.errors = []
        self.can_review = True
        self.defer_cancel = False
        self.unexpected = []
        self.dialogs = []
        self.policy_writes = []
        self.policy_samples = []
        self.decisions = []
        self.previews = []
        self.remediations = []
        self.scan_starts = []
        self.scan_actions = []
        self.configuration_writes = []
        self.generic_approval_writes = []
        self.fail_policy = 0
        self.fail_configuration = 0
        self.fail_review = 0
        self.fail_decision = 0
        self.fail_evidence = 0
        self.fail_attachment = 0
        self.inline_attachment = False
        self.defer_candidate = False
        self.evidence_requests = []
        self.attachment_requests = []
        self.preview_truncated = False
        self.units_continuation = ""
        self.extra_units = []
        self.config = {
            "enabled": True, "enhanced_citations_enabled": True,
            "can_manage_global": True, "can_scan_all": True,
            "templates": copy.deepcopy({
                "rules": STARTER_RULE_TEMPLATES, "packs": STARTER_PACKS, "ai": AI_STARTER_CRITERIA,
            }),
        }
        self.global_policy = default_policy()
        self.global_policy["enabled"] = True
        self.global_policy["rules"] = [copy.deepcopy(self.config["templates"]["rules"]["email"])]
        self.global_policy["allowed_models"] = [copy.deepcopy(MODEL)]
        self.baseline_summary = {
            "schema_version": 1, "enabled": True, "rule_count": 1, "ai_check_count": 0,
            "rule_types": ["pii"], "pii_types": ["email"], "severities": ["medium"],
            "fingerprint": "baseline-fingerprint",
        }
        self.models = [{**MODEL, "label": "Approved synthetic model", "connection_name": "Configured connection"}]
        self.workspace_policy = default_policy()
        self.policy_etag = '"policy-etag-1"'
        self.units = [content_unit()]
        self.findings = [{
            "finding_id": "finding-1", "unit_id": "unit-1", "rule_id": "rule-sensitive",
            "category": "credentials", "severity": "high", "start": 1, "end": 7,
            "reason": "<script>window.evidenceExecuted=true</script>",
            "evidence": "secret",
        }]
        self.review = {
            "id": "scan-1", "state": "pending_review", "finding_count": 1,
            "subject": {"scope_type": "personal", "scope_id": USER_ID, "document_id": "held-document", "source_revision": "1", "kind": "workspace_document"},
            "outcome": "findings", "etag": '"review-etag-1"',
            "content_fingerprint": "source-fingerprint", "policy_fingerprint": "policy-fingerprint",
            "coverage": {"complete": True, "units_total": 1, "status": "findings"}, "coverage_mode": "indexed_snapshot",
            "candidate_of": None, "original_retained": False, "sanitized": False, "review_required": True,
            "evidence": {"units_available": True, "findings_available": True},
            "downloads": {"original": None, "clean": None},
            "warning": None, "decision": None,
            "allowed_actions": ["preview", "remediate", "approve_with_flags", "reject", "delete"],
        }
        self.approval = {
            "id": "screening-approval-1", "request_type": "content_screening_review", "status": "pending",
            "group_id": USER_ID, "requester_name": "<img src=x onerror=window.evidenceExecuted=true>",
            "reason": "private-approval-reason-must-not-appear",
            "created_at": "2026-09-08T12:00:00Z", "can_approve": True, "can_deny": True,
            "metadata": {"review_url": f"/content-review?scope_type=personal&scope_id={USER_ID}&scan_id=scan-1"},
        }
        self.job = {
            "id": "job-1", "state": "running", "counters": {"total": 3, "completed": 1, "findings": 1, "failed": 0, "queued": 2},
            "allowed_actions": ["cancel"], "enumeration_complete": True,
        }
        self.documents = [{
            "id": "held-document", "file_name": "<img src=x onerror=window.evidenceExecuted=true>.txt",
            "title": "Do not render source metadata", "abstract": "private-abstract-must-not-appear",
            "content_screening": {
                "state": "pending_review", "available": False, "finding_count": 1,
                "scan_id": "scan-1", "review_id": "scan-1",
            },
        }, {
            "id": "allowed-document", "file_name": "Approved synthetic.txt",
            "content_screening": {"state": "approved_with_flags", "available": True, "finding_count": 2, "scan_id": "approved-scan"},
        }]
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on("dialog", self._dialog)
        self.page.route("**/*", self._route)

    def _dialog(self, dialog):
        self.dialogs.append(dialog.type)
        dialog.dismiss()

    def _environment(self):
        return Environment(
            loader=ChoiceLoader([
                DictLoader({"base.html": BASE_TEMPLATE, "fixture-admin.html": ADMIN_TEMPLATE, "fixture-workspace.html": WORKSPACE_TEMPLATE}),
                FileSystemLoader(str(TEMPLATES)),
            ]),
            undefined=ChainableUndefined,
            autoescape=select_autoescape(["html"]),
        )

    def _markup(self, template):
        environment = self._environment()
        environment.globals["url_for"] = lambda endpoint, **values: "/static/" + values.get("filename", "")
        return environment.get_template(template).render(
            app_settings={"app_title": "Synthetic screening UI"},
            settings={
                "enable_content_screening": self.config["enabled"],
                "enable_enhanced_citations": self.config["enhanced_citations_enabled"],
            },
            session={"user": {"oid": USER_ID, "roles": ["User", "Admin"]}},
            config={"VERSION": "0.261.106"},
            admin_landing_tab="content-screening",
        )

    def _fail(self, route, status):
        route.fulfill(status=status, json={
            "error": "private-provider-diagnostic <img src=x onerror=window.evidenceExecuted=true>",
            "code": "screening_revision_conflict" if status == 409 else "screening_permission_denied",
        })

    def _apply_edits(self, edits):
        units = copy.deepcopy(self.units)
        for edit in edits:
            unit = next(item for item in units if item["unit_id"] == edit["unit_id"])
            assert edit["content_hash"] == unit["content_hash"]
            if edit["action"] == "remove_unit":
                units.remove(unit)
            elif edit["action"] == "remove_span":
                offset = unit.get("text_offset", 0)
                start, end = edit["start"] - offset, edit["end"] - offset
                unit["text"] = unit["text"][:start] + unit["text"][end:]
            elif edit["action"] == "replace_cell":
                unit["text"] = edit["text"]
            else:
                raise AssertionError("Unexpected edit operation")
        for unit in units:
            unit["content_hash"] = hashlib.sha256(unit["text"].encode("utf-8")).hexdigest()
            unit["text_total"] = len(unit["text"]) + unit.get("text_offset", 0)
        return units

    def _route(self, route):
        request = route.request
        url = urlsplit(request.url)
        if not request.url.startswith(ORIGIN + "/"):
            self.unexpected.append(request.url)
            route.abort()
            return
        path = unquote(url.path)
        query = parse_qs(url.query)
        if path.startswith("/static/"):
            file = (STATIC / path.removeprefix("/static/")).resolve()
            if file.is_relative_to(STATIC.resolve()) and file.is_file():
                mime = "text/javascript" if file.suffix == ".js" else mimetypes.guess_type(str(file))[0] or "application/octet-stream"
                route.fulfill(path=str(file), content_type=mime)
                return
        elif path == "/content-review":
            route.fulfill(body=self._markup("content_review.html"), content_type="text/html")
            return
        elif path == "/fixture/admin":
            route.fulfill(body=self._markup("fixture-admin.html"), content_type="text/html")
            return
        elif path == "/fixture/workspace":
            route.fulfill(body=self._markup("fixture-workspace.html"), content_type="text/html")
            return
        elif path == "/approvals":
            route.fulfill(body=self._markup("approvals.html"), content_type="text/html")
            return
        elif path == "/favicon.ico":
            route.fulfill(status=204)
            return
        elif path == "/api/v2/admin/capability-models/chat":
            route.fulfill(json={"choices": self.models})
            return
        elif path == "/api/approvals":
            route.fulfill(json={"approvals": [self.approval], "page": 1, "page_size": 20, "total_count": 1})
            return
        elif path.startswith("/api/approvals/"):
            if request.method == "POST":
                self.generic_approval_writes.append(path)
                self._fail(route, 403)
            else:
                route.fulfill(json=self.approval)
            return
        elif path == "/api/content-screening/configuration":
            if request.method == "PUT":
                self.configuration_writes.append(request.post_data_json)
                if self.fail_configuration:
                    self._fail(route, self.fail_configuration)
                    return
                if not self.config["enhanced_citations_enabled"] and request.post_data_json["enabled"]:
                    self._fail(route, 503)
                    return
                if request.post_data_json["enabled"] and self.policy_etag is None:
                    self.global_policy = normalize_policy({**self.global_policy, "enabled": True})
                    self.policy_etag = '"policy-initialized"'
                self.config["enabled"] = request.post_data_json["enabled"]
            route.fulfill(json=self.config)
            return
        elif path == "/api/content-screening/status":
            document_id = query["document_id"][0]
            document = next(item for item in self.documents if item["id"] == document_id)
            route.fulfill(json={
                "document_id": document_id, **document["content_screening"],
                "can_review": self.can_review,
                "review_url": f"/content-review?scope_type=personal&scope_id={USER_ID}&scan_id={document['content_screening']['scan_id']}" if self.can_review else None,
            })
            return
        elif path.startswith("/api/content-screening/policies/"):
            global_policy = "/global/global" in path
            if path.endswith("/test"):
                self.policy_samples.append(request.post_data_json)
                route.fulfill(json={"status": "findings", "complete": True, "finding_count": 1, "findings": self.findings})
                return
            if request.method == "PUT":
                self.policy_writes.append(request.post_data_json)
                if self.fail_policy:
                    self._fail(route, self.fail_policy)
                    return
                assert request.post_data_json["etag"] == self.policy_etag
                policy = normalize_policy(
                    request.post_data_json["policy"], scope_type="global" if global_policy else "personal"
                )
                if global_policy:
                    self.global_policy = policy
                else:
                    self.workspace_policy = policy
                self.policy_etag = f'"policy-etag-{len(self.policy_writes) + 1}"'
            route.fulfill(json={
                "scope_type": "global" if global_policy else "personal",
                "scope_id": "global" if global_policy else USER_ID,
                "policy": self.global_policy if global_policy else self.workspace_policy,
                "etag": self.policy_etag,
                "allowed_models": [MODEL],
                "inherited_summary": None if global_policy else self.baseline_summary,
                "templates": self.config["templates"],
            })
            return
        elif path == "/api/content-screening/scans":
            if request.method == "POST":
                self.scan_starts.append(request.post_data_json)
                route.fulfill(json=self.job)
            else:
                route.fulfill(json={"items": [], "continuation": None})
            return
        elif path == "/api/content-screening/scans/job-1/actions":
            action = request.post_data_json["action"]
            self.scan_actions.append(action)
            self.job["cancel_requested"] = action == "cancel"
            self.job["state"] = "cancelled" if action == "cancel" and not self.defer_cancel else "running"
            self.job["allowed_actions"] = ["resume"] if self.job["state"] == "cancelled" else ["cancel"]
            route.fulfill(json=self.job)
            return
        elif path == "/api/content-screening/scans/job-1":
            route.fulfill(json=self.job)
            return
        elif path == "/api/content-screening/reviews":
            route.fulfill(json={"items": [self.review] if self.review else [], "continuation": None})
            return
        elif path.startswith("/api/content-screening/reviews/"):
            if self.fail_review:
                self._fail(route, self.fail_review)
                return
            if "/downloads/" in path:
                kind = path.rsplit("/", 1)[-1]
                self.attachment_requests.append(path)
                if self.fail_attachment:
                    self._fail(route, self.fail_attachment)
                    return
                assert kind in {"original", "clean"}
                assert self.review["downloads"][kind]["url"] == path
                assert f"download_{kind}" in self.review["allowed_actions"]
                route.fulfill(body=(
                    "<script>window.evidenceExecuted=true</script>untrusted original"
                    if kind == "original" else "Released clean derivative"
                ), content_type="application/octet-stream", headers={
                    "Content-Disposition": f'{"inline" if self.inline_attachment else "attachment"}; filename="fixture-{kind}.txt"',
                    "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
                })
                return
            if path.endswith(("/units", "/findings")):
                self.evidence_requests.append(path)
                if self.fail_evidence:
                    self._fail(route, self.fail_evidence)
                    return
            if path.endswith("/units"):
                more = bool(query.get("continuation"))
                route.fulfill(json={"items": self.extra_units if more else self.units, "continuation": None if more else self.units_continuation or None, "total": len(self.units) + len(self.extra_units)})
                return
            if path.endswith("/findings"):
                route.fulfill(json={"items": self.findings, "continuation": None, "total": len(self.findings)})
                return
            if path.endswith("/preview") or path.endswith("/remediate"):
                body = request.post_data_json
                assert body["etag"] == self.review["etag"]
                units = self._apply_edits(body["edits"])
                if path.endswith("/preview"):
                    self.previews.append(body)
                    route.fulfill(json={
                        "units": units, "total_units": len(units), "preview_truncated": self.preview_truncated,
                        "content_fingerprint": "candidate-fingerprint",
                        "removed_unit_ids": [unit["unit_id"] for unit in self.units if unit["unit_id"] not in {item["unit_id"] for item in units}],
                        "removed_unit_count": len(self.units) - len(units), "warnings": [],
                    })
                else:
                    self.remediations.append(body)
                    self.units = units
                    self.findings = []
                    self.review.update({
                        "id": "candidate-2", "etag": '"candidate-etag-2"',
                        "state": "pending_scan", "outcome": None, "finding_count": 0, "candidate_of": "scan-1", "sanitized": True,
                        "coverage": {"complete": False, "units_total": len(units), "status": None},
                        "content_fingerprint": "candidate-fingerprint",
                        "allowed_actions": [],
                        "evidence": {"units_available": True, "findings_available": False},
                        "downloads": {"original": None, "clean": None},
                    })
                    route.fulfill(status=202, json=self.review)
                return
            if path.endswith("/decision"):
                body = request.post_data_json
                self.decisions.append(body)
                if self.fail_decision:
                    self._fail(route, self.fail_decision)
                    return
                assert body["etag"] == self.review["etag"]
                assert body["reason"].strip()
                action = body["action"]
                if action != "retry_publication":
                    self.review["decision"] = {
                        "action": action, "actor_id": USER_ID, "reason": body["reason"],
                        "decided_at": "2026-09-16T15:00:00Z",
                    }
                if action == "approve_with_flags":
                    assert body["acknowledge_flags"] is True and body["reason"].strip()
                    self.review.update({
                        "state": "approved_with_flags", "available": True, "allowed_actions": [],
                        "warning": "Approved with flags. Review the recorded findings before use.",
                    })
                elif action == "approve_clean":
                    assert self.review["coverage"]["complete"] and not self.findings and self.review["finding_count"] == 0
                    self.review.update({"state": "cleared", "available": True, "allowed_actions": []})
                elif action == "reject":
                    self.review.update({"state": "rejected", "available": False, "allowed_actions": ["delete"]})
                elif action == "retry_publication":
                    assert self.review["decision"]["action"] in {"approve_clean", "approve_with_flags"}
                    assert body["reason"] == self.review["decision"]["reason"]
                    self.review.update({
                        "state": "cleared" if self.review["decision"]["action"] == "approve_clean" else "approved_with_flags",
                        "available": True, "allowed_actions": [],
                    })
                elif action == "delete":
                    self.review = None
                    route.fulfill(json={"id": "deleted-review", "state": "deleted"})
                    return
                route.fulfill(json=self.review)
                return
            if self.review and self.review.get("candidate_of") and self.review["state"] == "pending_scan" and not self.defer_candidate:
                self.complete_candidate()
            route.fulfill(json=self.review)
            return
        self.unexpected.append(path)
        route.fulfill(status=404, json={"error": "Unexpected fixture request"})

    def complete_candidate(self, outcome="pass"):
        self.review.update({
            "state": "scan_error" if outcome == "error" else "pending_review",
            "outcome": outcome,
            "coverage": {"complete": outcome != "error", "units_total": len(self.units), "status": outcome},
            "evidence": {"units_available": True, "findings_available": True},
            "allowed_actions": ["remediate", "reject", "delete"] + (["approve_clean"] if outcome == "pass" else []),
        })

    def enable_downloads(self, *, clean=False):
        kinds = ["original", "clean"] if clean else ["original"]
        self.review["original_retained"] = True
        if clean:
            self.review.update({"state": "cleared", "sanitized": True, "allowed_actions": []})
        self.review["allowed_actions"].extend(f"download_{kind}" for kind in kinds)
        self.review["downloads"] = {
            kind: {
                "url": f"/api/content-screening/reviews/{self.review['id']}/downloads/{kind}",
                "file_name": f"fixture-{kind}.txt",
            } if kind in kinds else None for kind in ("original", "clean")
        }

    def open_review(self, query=""):
        self.page.goto(f"{ORIGIN}/content-review?scope_type=personal&scan_id=scan-1{query}", wait_until="networkidle")

    def open_admin(self):
        self.page.goto(f"{ORIGIN}/fixture/admin", wait_until="networkidle")

    def open_approvals(self):
        self.page.goto(f"{ORIGIN}/approvals", wait_until="networkidle")

    def open_workspace(self):
        self.page.goto(f"{ORIGIN}/fixture/workspace", wait_until="networkidle")
        self.page.evaluate(
            """documents => {
                const selected = new Set();
                const scope = {scopeType: 'personal', scopeId: ''};
                function render() {
                    const body = document.querySelector('#fixture-documents tbody');
                    body.replaceChildren();
                    window.ContentScreening.filterDocuments(documents, scope).forEach(doc => {
                        let row;
                        if (window.ContentScreening.isHeld(doc)) row = window.ContentScreening.createHeldDocument(doc, scope);
                        else {
                            row = document.createElement('tr');
                            for (let index = 0; index < 4; index++) row.appendChild(document.createElement('td'));
                            row.cells[1].textContent = doc.file_name;
                            window.ContentScreening.decorateDocument(row, doc, scope);
                        }
                        body.appendChild(row);
                    });
                    body.querySelectorAll('.document-checkbox').forEach(checkbox => {
                        checkbox.classList.remove('d-none');
                        checkbox.addEventListener('change', () => {
                            if (checkbox.checked) selected.add(checkbox.dataset.documentId);
                            else selected.delete(checkbox.dataset.documentId);
                        });
                    });
                }
                window.ContentScreening.registerWorkspace({
                    ...scope, documents, getSelectedIds: () => Array.from(selected), render, refresh: render
                });
                render();
            }""",
            self.documents,
        )

    def assert_clean(self):
        assert not self.errors, self.errors
        assert not self.unexpected, self.unexpected
        assert not self.dialogs, self.dialogs
        assert self.page.evaluate("window.evidenceExecuted") is None
