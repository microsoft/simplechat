# group_screening.py
"""
The group-scoped content screening routes the V2 group Documents section calls, modelled closed.
Version: 0.261.174
Implemented in: 0.261.174

The group Documents section mounts the shared screening controls for a member the context's
`screening_management` hint names. Opening them reads the screening configuration, the group's policy
(twice: the controls and the policy additions editor) and its scans; a scan starts for the group, and a
running scan is read and can be cancelled. This model answers exactly those routes, by the rules of
`route_backend_content_screening.py` and `content_screening/*`, computed with the server's own code
wherever the server's code is pure:

- Every group-scoped route authorizes with `assert_scope_access`: the group's Owner, Admin or
  DocumentManager (`REVIEW_ROLES`, read from the server), in any status. Anyone else is refused with
  `ScreeningPermissionError`'s public message and code, as the blueprint's error handler sends it.
- The policy payload is `_policy_payload`'s, built with the real `normalize_policy`, `compose_policy`
  and `safe_baseline_summary` over the modelled administrator baseline, with the real templates.
- A scan starts only when screening is on, Enhanced Citations is on and the composed policy is active
  (`policy_is_active`), each refusal carrying its own error class's message, code and status. The job
  is created as `_new_job` creates it and projected by the route's own `_safe_job`.
- A cancel only requests cancellation, as `request_scan_job_action` does: the worker, not the request,
  moves the job on, so the job stays queued and still lists `cancel`.

The viewer is not an application administrator, the search-index migration gate is open, and
screening storage is ready. functional_tests/test_group_screening_fixture_parity.py holds these
responses to the real routes.
"""

import ast
import copy
import itertools
import sys

from ui_tests.fixtures.group_workspace import APP_ROOT, SCREENING_REVIEW_ROLES, _app_constant, _app_functions

# The screening contracts and policies are pure (stdlib and `regex`), so the model runs them rather
# than a copy that could drift from them.
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from content_screening.contracts import (  # noqa: E402
    ScreeningChecksRequiredError, ScreeningCitationsRequiredError, ScreeningConfigurationError,
    ScreeningConflictError, ScreeningValidationError, normalize_identifier,
)
from content_screening.permissions import ScreeningNotFoundError, ScreeningPermissionError  # noqa: E402
from content_screening.policies import (  # noqa: E402
    AI_STARTER_CRITERIA, STARTER_PACKS, STARTER_RULE_TEMPLATES, compose_policy, default_policy,
    normalize_policy, policy_is_active, safe_baseline_summary,
)

_ROUTE = "route_backend_content_screening.py"
_ROUTE_RULES = {}
_app_functions(_ROUTE, {"_safe_job", "_safe_code"}, _ROUTE_RULES)
safe_job = _ROUTE_RULES["_safe_job"]
safe_code = _ROUTE_RULES["_safe_code"]
MAX_SELECTION_DOCUMENTS = _app_constant(_ROUTE, "MAX_SELECTION_DOCUMENTS")
ITEM_STATUSES = _app_constant("content_screening/jobs.py", "ITEM_STATUSES")


def _job_actions():
    """The route's `JOB_ACTIONS`, a frozenset of literals."""
    tree = ast.parse((APP_ROOT / _ROUTE).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "JOB_ACTIONS" for target in node.targets
        ):
            return frozenset(ast.literal_eval(node.value.args[0]))
    raise LookupError(f"{_ROUTE} defines no JOB_ACTIONS")


JOB_ACTIONS = _job_actions()
SCREENING_PREFIX = "/api/content-screening/"
# The one check the modelled baseline carries, so a scan of a group with no additions of its own is
# accepted exactly as the real composed policy decides.
BASELINE_RULE = {
    "id": "baseline-check", "name": "Baseline check", "type": "literal", "enabled": True,
    "severity": "high", "category": "custom", "values": ["fixture-value"],
    "case_sensitive": False, "whole_word": False,
}


def screening_refusal(error_class):
    """A refusal as the screening blueprint's error handler sends it."""
    return {"error": error_class.public_message, "code": safe_code(error_class.code)}, error_class.status_code


def screening_templates():
    """`_templates()`: the starter rules, packs and AI criteria, copied."""
    return copy.deepcopy({"rules": STARTER_RULE_TEMPLATES, "packs": STARTER_PACKS, "ai": AI_STARTER_CRITERIA})


def baseline_policy(*rules):
    """The administrator's saved baseline, normalized as the server stores it."""
    return normalize_policy({**default_policy(), "enabled": True, "rules": list(rules)})


class GroupScreeningModel:
    """Mixin for a group fixture. Call `_init_group_screening()` from `__init__`, route every
    `/api/content-screening/` request to `_serve_screening`, and check recorded ones with
    `_validate_screening_request`."""

    def _init_group_screening(self):
        # `enable_content_screening` and `enable_enhanced_citations`.
        self.screening_enabled = True
        self.screening_enhanced_citations = True
        self.screening_workspace_uploads = True
        self.screening_baseline = baseline_policy(BASELINE_RULE)
        # A workspace policy record per group, as `repository.get_policy` returns it, or none.
        self.screening_policies = {}
        self.screening_jobs = {}
        self.screening_scan_starts = []
        self.screening_actions = []
        self._screening_job_numbers = itertools.count(1)

    # --- the viewer and the scope -----------------------------------------------------------

    def _screening_role(self, group_id):
        """The viewer's role in the group, from the group record the context is built from."""
        context = self.groups.get(group_id)
        return context.get("role") if context else None

    def _screening_authorized(self, scope_type, scope_id):
        """`assert_scope_access` for a non-administrator viewer: only a group scope is modelled."""
        return scope_type == "group" and self._screening_role(scope_id) in SCREENING_REVIEW_ROLES

    def _screening_policy_payload(self, group_id):
        """`_policy_payload(repository, "group", group_id)`."""
        record = self.screening_policies.get(group_id)
        allowed_models = compose_policy(self.screening_baseline)["allowed_models"]
        return {
            "scope_type": "group", "scope_id": group_id,
            "policy": normalize_policy(record["policy"] if record else default_policy(), scope_type="group"),
            "etag": record.get("_etag") if record else None,
            "allowed_models": allowed_models,
            "inherited_summary": {**safe_baseline_summary(self.screening_baseline), "allowed_models": allowed_models},
            "templates": screening_templates(),
        }

    def _screening_configuration(self):
        """`_configuration()` for a viewer who is not an application administrator."""
        return {
            "enabled": self.screening_enabled,
            "workspace_uploads_enabled": self.screening_workspace_uploads,
            "enhanced_citations_enabled": self.screening_enhanced_citations,
            "can_manage_global": False, "can_scan_all": False,
            "templates": screening_templates(),
        }

    def _screening_start_refusal(self, group_id):
        """`_configuration_snapshot`'s refusals, in its order, or None when the scan may start."""
        if not self.screening_enabled:
            return ScreeningConfigurationError
        if not self.screening_enhanced_citations:
            return ScreeningCitationsRequiredError
        record = self.screening_policies.get(group_id)
        if not policy_is_active(compose_policy(self.screening_baseline, record["policy"] if record else None)):
            return ScreeningChecksRequiredError
        return None

    def _screening_new_job(self, selection):
        """The fields `_new_job` sets that `_safe_job` projects, for a scope-authorized viewer."""
        number = next(self._screening_job_numbers)
        timestamp = f"2026-09-08T12:00:{number:02d}+00:00"
        return {
            "id": f"job-group-{number}", "kind": "job",
            "scope_key": f"{selection['scope_type']}:{selection['scope_id']}",
            "selection": selection, "status": "queued", "cancel_requested": False, "lease": None,
            "enumeration": {"complete": False},
            "counts": {**{status: 0 for status in ITEM_STATUSES}, "total": 0},
            "created_at": timestamp, "updated_at": timestamp, "_etag": f'"job-etag-{number}"',
        }

    # --- serving ------------------------------------------------------------------------------

    def _screening_refuse(self, route, error_class):
        payload, status = screening_refusal(error_class)
        self._json(route, payload, status)

    def _serve_screening(self, route, entry):
        path, method, query = entry.path, entry.method, entry.query
        resource = path.removeprefix(SCREENING_PREFIX)
        parts = resource.split("/")
        if resource == "configuration" and method == "GET":
            if query:
                return self._screening_refuse(route, ScreeningValidationError)
            return self._json(route, self._screening_configuration())
        if parts[0] == "policies" and len(parts) == 3 and method == "GET":
            scope_type, scope_id = parts[1], parts[2]
            if query:
                return self._screening_refuse(route, ScreeningValidationError)
            if not self._screening_authorized(scope_type, scope_id):
                return self._screening_refuse(route, ScreeningPermissionError)
            return self._json(route, self._screening_policy_payload(scope_id))
        if resource == "scans" and method == "GET":
            if set(query) - {"scope_type", "scope_id", "page_size", "continuation"} or any(
                len(values) != 1 for values in query.values()
            ):
                return self._screening_refuse(route, ScreeningValidationError)
            page_size = query.get("page_size", ["50"])[0]
            if not page_size.isascii() or not page_size.isdigit() or len(page_size) > 3 or not 1 <= int(page_size) <= 100:
                return self._screening_refuse(route, ScreeningValidationError)
            scope_type, scope_id = query.get("scope_type", [None])[0], query.get("scope_id", [None])[0]
            if scope_type is None and scope_id is None:
                # The actor's own unscoped list; the section always names its group.
                self.unexpected_requests.append(f"{method} {path} without a scope")
                return self._json(route, {"error": "Unexpected unscoped screening scan list."}, 500)
            if scope_type not in ("personal", "group", "public") or not scope_id or not scope_id.strip():
                return self._screening_refuse(route, ScreeningValidationError)
            if not self._screening_authorized(scope_type, scope_id):
                return self._screening_refuse(route, ScreeningPermissionError)
            scope_key = f"{scope_type}:{scope_id}"
            items = [safe_job(job) for job in self.screening_jobs.values() if job["scope_key"] == scope_key]
            return self._json(route, {"items": items, "continuation": None})
        if resource == "scans" and method == "POST":
            return self._screening_start(route, entry)
        if parts[0] == "scans" and len(parts) == 2 and method == "GET":
            if query:
                return self._screening_refuse(route, ScreeningValidationError)
            job, refusal = self._screening_job(parts[1])
            return self._screening_refuse(route, refusal) if refusal else self._json(route, safe_job(job))
        if parts[0] == "scans" and len(parts) == 3 and parts[2] == "actions" and method == "POST":
            return self._screening_action(route, entry, parts[1])
        self.unexpected_requests.append(f"{method} {path}")
        self._json(route, {"error": "Unexpected content screening fixture request."}, 500)

    def _screening_job(self, job_id):
        """`_get_job`: the job, or the refusal for a missing one or one outside the viewer's scope."""
        job = self.screening_jobs.get(job_id)
        if job is None:
            return None, ScreeningNotFoundError
        selection = job["selection"]
        if not self._screening_authorized(selection["scope_type"], selection["scope_id"]):
            return None, ScreeningPermissionError
        return job, None

    def _screening_start(self, route, entry):
        """The route's `_body` and `_selection`, then `create_scan_job`'s configuration snapshot."""
        body = entry.body
        if not isinstance(body, dict) or set(body) - {"scope_type", "scope_id", "document_ids", "all_workspaces"}:
            return self._screening_refuse(route, ScreeningValidationError)
        all_workspaces = body.get("all_workspaces", False)
        if type(all_workspaces) is not bool or (all_workspaces and set(body) != {"all_workspaces"}):
            return self._screening_refuse(route, ScreeningValidationError)
        if all_workspaces:
            # Only an application administrator may, and the modelled viewer is not one.
            return self._screening_refuse(route, ScreeningPermissionError)
        scope_type = body.get("scope_type")
        if not isinstance(scope_type, str) or scope_type not in ("personal", "group", "public"):
            return self._screening_refuse(route, ScreeningValidationError)
        try:
            scope_id = normalize_identifier(body.get("scope_id"), "scope_id")
        except ScreeningValidationError:
            return self._screening_refuse(route, ScreeningValidationError)
        if not self._screening_authorized(scope_type, scope_id):
            return self._screening_refuse(route, ScreeningPermissionError)
        selection = {"scope_type": scope_type, "scope_id": scope_id}
        if "document_ids" in body:
            ids = body["document_ids"]
            if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_SELECTION_DOCUMENTS:
                return self._screening_refuse(route, ScreeningValidationError)
            try:
                normalized = [normalize_identifier(value, "document_id") for value in ids]
            except ScreeningValidationError:
                return self._screening_refuse(route, ScreeningValidationError)
            if len(set(normalized)) != len(ids):
                return self._screening_refuse(route, ScreeningValidationError)
            # `create_scan_job` stores the selection's ids sorted and de-duplicated.
            selection["document_ids"] = sorted(set(normalized))
        refusal = self._screening_start_refusal(scope_id)
        if refusal is not None:
            return self._screening_refuse(route, refusal)
        job = self._screening_new_job(selection)
        self.screening_jobs[job["id"]] = job
        self.screening_scan_starts.append(copy.deepcopy(body))
        self._json(route, safe_job(job), 202)

    def _screening_action(self, route, entry, job_id):
        # The body is checked before the job is read, as the route's `_body` runs first.
        body = entry.body
        if not isinstance(body, dict) or set(body) != {"action"} or body["action"] not in JOB_ACTIONS:
            return self._screening_refuse(route, ScreeningValidationError)
        job, refusal = self._screening_job(job_id)
        if refusal:
            return self._screening_refuse(route, refusal)
        action = body["action"]
        self.screening_actions.append((job["id"], action))
        if action == "cancel":
            if job["status"] not in ("completed", "completed_with_findings"):
                job.update({"cancel_requested": True, "status": "queued"})
            return self._json(route, safe_job(job))
        # Resume and retry re-check the configuration, then reopen only a cancelled, failed or
        # incomplete job. The modelled worker never runs, so no job reaches one of those states.
        refusal = self._screening_start_refusal(job["selection"]["scope_id"])
        if refusal is None and job["status"] not in ("cancelled", "failed", "incomplete"):
            refusal = ScreeningConflictError
        return self._screening_refuse(route, refusal) if refusal else self._json(route, safe_job(job))

    def _validate_screening_request(self, entry):
        """Every recorded screening request is one the section's controls make for a group."""
        resource = entry.path.removeprefix(SCREENING_PREFIX)
        assert entry.path.startswith(SCREENING_PREFIX), entry
        if resource.startswith("policies/"):
            assert resource.startswith("policies/group/") and entry.method == "GET", entry
        elif resource == "scans":
            if entry.method == "GET":
                assert entry.query.get("scope_type") == ["group"], entry
            else:
                assert entry.method == "POST" and entry.body.get("scope_type") == "group", entry
        else:
            assert resource == "configuration" or resource.startswith("scans/"), entry
