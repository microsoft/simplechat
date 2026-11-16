# test_group_screening_fixture_parity.py
"""
Parity between the group content screening routes the V2 browser fixture models and the real routes.
Version: 0.261.174
Implemented in: 0.261.174

The group Documents section's screening controls call the screening routes, which the management
fixture answers with `ui_tests/fixtures/group_screening.py`. A model that invented a grant, a payload
or a refusal would let a browser test pass while proving nothing about production. This test runs the
real `route_backend_content_screening.py` blueprint with the real jobs, service and repository modules
(over the persistence tests' `FakeCosmos`) and the real group role check (`assert_group_role`, from
`functions_group.py`, over one group record), and requires the model to answer every request the same
way: status, and every field except a new job's generated id, timestamps and etag.

Two things are made ready on the real side, exactly as the model assumes them: the search-index
migration gate is open and screening storage validates. Everything else -- settings, Enhanced
Citations, the stored baseline, the group's role check -- is the server's own code.

The grid covers every group role in every stored status (the screening routes check no status), the
screening configuration's switches, a baseline with no active checks, and the request validation the
controls could meet.
"""

import copy
import importlib
import importlib.util
import json
import sys
from functools import wraps
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable
from unittest.mock import Mock

import pytest
from flask import Blueprint, Flask, jsonify, session

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
for candidate in (ROOT, ROOT / "ui_tests", ROOT / "ui_tests" / "fixtures", APP_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from test_content_screening_persistence import FakeCosmos  # noqa: E402
from test_support.agent_delegation import execute_functions, module_stub  # noqa: E402
from ui_tests.fixtures import group_screening  # noqa: E402
from ui_tests.fixtures.workspace_authoring import ApiRequest  # noqa: E402

GROUP = "group-a"
ROLE_USERS = {"Owner": "owner", "Admin": "admin", "DocumentManager": "manager", "User": "reader"}
STATUSES = ("active", "locked", "upload_disabled", "inactive")
POLICY_PATH = f"/api/content-screening/policies/group/{GROUP}"
LIST_QUERY = {"scope_type": "group", "scope_id": GROUP, "page_size": "100"}
SCAN_BODY = {"scope_type": "group", "scope_id": GROUP}
# A new job's generated identity and clock differ by construction; everything else must match.
VOLATILE_JOB_FIELDS = ("id", "created_at", "updated_at", "etag")


def _session_guard():
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            if not session.get("user"):
                return jsonify({"error": "Authentication required."}), 401
            return function(*args, **kwargs)
        return wrapped
    return decorate


class RealScreening:
    """The real screening blueprint for one group, one viewer at a time."""

    def __init__(self, monkeypatch, *, status="active", settings=None, baseline=None):
        self.record = {
            "id": GROUP, "name": "Workspace A", "status": status,
            "owner": {"id": "owner", "displayName": "Owner"},
            "admins": ["admin"], "documentManagers": ["manager"], "users": [{"userId": "reader"}],
        }
        namespace = {"find_group_by_id": lambda group_id: copy.deepcopy(self.record) if group_id == GROUP else None,
                     "Iterable": Iterable}
        execute_functions("functions_group.py", {"assert_group_role", "get_user_role_in_group"}, namespace)
        self.settings = {
            "enable_content_screening": True, "enable_content_screening_workspace_uploads": True,
            "enable_enhanced_citations": True, **(settings or {}),
        }
        guard = _session_guard()
        stubs = {
            "functions_group": module_stub("functions_group", assert_group_role=namespace["assert_group_role"]),
            "functions_authentication": module_stub(
                "functions_authentication", login_required=guard, user_required=guard, admin_required=guard,
                user_required_blueprint=lambda: (lambda: None),
                get_current_user_id=lambda: (session.get("user") or {}).get("oid"),
            ),
            "functions_settings": module_stub(
                "functions_settings", get_settings=lambda **_kwargs: copy.deepcopy(self.settings),
                cosmos_settings_container=SimpleNamespace(read_item=lambda **_kwargs: copy.deepcopy(self.settings)),
                update_settings=Mock(return_value=True), validate_content_screening_settings=Mock(),
            ),
            "functions_appinsights": module_stub("functions_appinsights", log_event=Mock()),
            "swagger_wrapper": module_stub(
                "swagger_wrapper", swagger_route=lambda **_kwargs: (lambda function: function),
                get_auth_security=lambda: [],
            ),
            # validate_screening_configuration builds the storage client from config; the storage
            # check itself is made to pass below.
            "config": module_stub("config", build_enhanced_citations_blob_service_client=lambda _settings: object()),
        }
        for name, module in stubs.items():
            monkeypatch.setitem(sys.modules, name, module)
        repository_module = importlib.import_module("content_screening.repository")
        service = importlib.import_module("content_screening.service")
        storage = importlib.import_module("content_screening.storage")
        jobs = importlib.import_module("content_screening.jobs")
        self.repository = repository_module.ScreeningRepository(
            FakeCosmos(), {scope: FakeCosmos(partition_field="id") for scope in ("personal", "group", "public")},
        )
        monkeypatch.setattr(repository_module, "get_repository", lambda: self.repository)
        monkeypatch.setattr(service, "_settings", lambda value=None: copy.deepcopy(
            value if isinstance(value, dict) else self.settings))
        monkeypatch.setattr(storage.ScreeningStorage, "validate_connection", lambda _self: None)
        monkeypatch.setattr(jobs, "_assert_migration_open", lambda: None)
        self.repository.save_policy(
            "global", "global", baseline if baseline is not None else group_screening.baseline_policy(
                group_screening.BASELINE_RULE), "administrator",
        )
        spec = importlib.util.spec_from_file_location("tested_screening_routes", APP_ROOT / "route_backend_content_screening.py")
        routes = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(routes)
        app = Flask("group_screening_parity")
        app.config.update(TESTING=True, SECRET_KEY="fixture-only-session-signing")
        blueprint = Blueprint("backend_content_screening", __name__)
        routes.register_route_backend_content_screening(blueprint)
        app.register_blueprint(blueprint)
        self.client = app.test_client()

    def as_user(self, user_id):
        with self.client.session_transaction() as state:
            state["user"] = {"oid": user_id, "roles": ["User"]}

    def request(self, method, path, *, query=None, body=None):
        response = self.client.open(path, method=method, query_string=query, json=body)
        return response.status_code, response.get_json()


class ModelledScreening(group_screening.GroupScreeningModel):
    """The browser fixture's screening model, driven without a browser."""

    def __init__(self, role, *, status="active", settings=None, baseline=None):
        self.groups = {GROUP: {"role": role, "status": status}}
        self.unexpected_requests = []
        self._init_group_screening()
        settings = settings or {}
        self.screening_enabled = settings.get("enable_content_screening", True)
        self.screening_enhanced_citations = settings.get("enable_enhanced_citations", True)
        if baseline is not None:
            self.screening_baseline = baseline

    def _json(self, route, payload, status=200):
        # What the browser receives: the fixture fulfils the route with the payload as JSON.
        route.answer = (status, json.loads(json.dumps(payload)))

    def request(self, method, path, *, query=None, body=None):
        route = SimpleNamespace(answer=None)
        entry = ApiRequest(method, path, {key: [value] for key, value in (query or {}).items()}, copy.deepcopy(body))
        self._serve_screening(route, entry)
        assert not self.unexpected_requests, self.unexpected_requests
        return route.answer


def comparable(answer):
    """A response with a job's generated identity and clock removed, wherever a job appears."""
    status, payload = answer

    def strip(value):
        if isinstance(value, dict) and value.get("state") is not None and "allowed_actions" in value:
            return {key: item for key, item in value.items() if key not in VOLATILE_JOB_FIELDS}
        if isinstance(value, dict):
            return {key: strip(item) for key, item in value.items()}
        if isinstance(value, list):
            return [strip(item) for item in value]
        return value

    return status, strip(payload)


def both(real, modelled, method, path, **options):
    """The same request on both sides, answered the same way."""
    real_answer = real.request(method, path, **options)
    modelled_answer = modelled.request(method, path, **options)
    assert comparable(modelled_answer) == comparable(real_answer), (
        f"{method} {path} {options}\n  server:  {real_answer}\n  fixture: {modelled_answer}"
    )
    return real_answer, modelled_answer


@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("role", list(ROLE_USERS))
def test_every_member_meets_the_servers_answers(monkeypatch, role, status):
    """The configuration, the group's policy and scans, a scan's start, its read, its cancellation and
    a refused resume: answered for every role in every status exactly as the routes answer them."""
    real = RealScreening(monkeypatch, status=status)
    real.as_user(ROLE_USERS[role])
    modelled = ModelledScreening(role, status=status)
    both(real, modelled, "GET", "/api/content-screening/configuration")
    both(real, modelled, "GET", POLICY_PATH)
    both(real, modelled, "GET", "/api/content-screening/scans", query=LIST_QUERY)
    (started, _), (_, modelled_job) = both(real, modelled, "POST", "/api/content-screening/scans", body=SCAN_BODY)
    if started != 202:
        assert role not in group_screening.SCREENING_REVIEW_ROLES
        return
    real_id, modelled_id = real.repository.query("job")["items"][0]["id"], modelled_job["id"]
    for method, suffix, body in (("GET", "", None), ("POST", "/actions", {"action": "cancel"}),
                                 ("POST", "/actions", {"action": "resume"}), ("GET", "", None)):
        real_answer = real.request(method, f"/api/content-screening/scans/{real_id}{suffix}", body=body)
        modelled_answer = modelled.request(method, f"/api/content-screening/scans/{modelled_id}{suffix}", body=body)
        assert comparable(modelled_answer) == comparable(real_answer), (method, suffix, body, real_answer, modelled_answer)
    real_list = real.request("GET", "/api/content-screening/scans", query=LIST_QUERY)
    modelled_list = modelled.request("GET", "/api/content-screening/scans", query=LIST_QUERY)
    assert comparable(modelled_list) == comparable(real_list)


def test_the_grid_is_not_vacuous(monkeypatch):
    """Both sides really split the roles: the managers start a scan and an ordinary member is refused."""
    outcomes = {}
    for role, user_id in ROLE_USERS.items():
        real = RealScreening(monkeypatch)
        real.as_user(user_id)
        outcomes[role] = real.request("POST", "/api/content-screening/scans", body=SCAN_BODY)[0]
    assert outcomes == {"Owner": 202, "Admin": 202, "DocumentManager": 202, "User": 403}


@pytest.mark.parametrize("settings", [
    {"enable_content_screening": False},
    {"enable_enhanced_citations": False},
    {"enable_content_screening": False, "enable_enhanced_citations": False},
], ids=["scanning-off", "citations-off", "both-off"])
def test_a_switched_off_prerequisite_is_refused_as_the_server_refuses_it(monkeypatch, settings):
    """The configuration reports each switch, and a start meets the refusal the server raises first."""
    real = RealScreening(monkeypatch, settings=settings)
    real.as_user("owner")
    modelled = ModelledScreening("Owner", settings=settings)
    both(real, modelled, "GET", "/api/content-screening/configuration")
    (status, payload), _ = both(real, modelled, "POST", "/api/content-screening/scans", body=SCAN_BODY)
    assert status >= 400 and payload["code"].startswith("screening_")


def test_a_baseline_with_no_active_checks_refuses_a_scan(monkeypatch):
    """An enabled but empty baseline composes to no active check, and neither side starts a scan."""
    empty = group_screening.baseline_policy()
    real = RealScreening(monkeypatch, baseline=empty)
    real.as_user("owner")
    modelled = ModelledScreening("Owner", baseline=empty)
    both(real, modelled, "GET", POLICY_PATH)
    (status, payload), _ = both(real, modelled, "POST", "/api/content-screening/scans", body=SCAN_BODY)
    assert (status, payload["code"]) == (400, "screening_policy_empty")


@pytest.mark.parametrize("method,path,options", [
    ("POST", "/api/content-screening/scans", {"body": {**SCAN_BODY, "priority": "high"}}),
    ("POST", "/api/content-screening/scans", {"body": {"all_workspaces": True}}),
    ("POST", "/api/content-screening/scans", {"body": {"all_workspaces": "yes"}}),
    ("POST", "/api/content-screening/scans", {"body": {**SCAN_BODY, "document_ids": ["one", "one"]}}),
    ("POST", "/api/content-screening/scans", {"body": {**SCAN_BODY, "document_ids": []}}),
    ("POST", "/api/content-screening/scans", {"body": {"scope_type": "global", "scope_id": "global"}}),
    ("GET", "/api/content-screening/scans", {"query": {**LIST_QUERY, "page_size": "500"}}),
    ("GET", "/api/content-screening/scans", {"query": {"scope_type": "global", "scope_id": "global"}}),
    ("GET", "/api/content-screening/scans/job-missing", {}),
    ("POST", "/api/content-screening/scans/job-missing/actions", {"body": {"action": "pause"}}),
    ("POST", "/api/content-screening/scans/job-missing/actions", {"body": {"action": "cancel"}}),
    ("GET", POLICY_PATH, {"query": {"etag": "stale"}}),
    ("GET", "/api/content-screening/configuration", {"query": {"scope_type": "group"}}),
], ids=[
    "unknown-field", "all-workspaces", "all-workspaces-not-boolean", "duplicate-documents", "no-documents",
    "global-scope", "page-too-large", "global-list", "missing-job", "unknown-action-before-lookup",
    "cancel-missing-job", "policy-query", "configuration-query",
])
def test_a_request_the_routes_refuse_is_refused_the_same_way(monkeypatch, method, path, options):
    real = RealScreening(monkeypatch)
    real.as_user("owner")
    modelled = ModelledScreening("Owner")
    (status, _payload), _ = both(real, modelled, method, path, **options)
    assert status >= 400


def test_a_scan_of_named_documents_stores_the_servers_selection(monkeypatch):
    """A start naming documents keeps them sorted and unique, as `create_scan_job` stores them."""
    real = RealScreening(monkeypatch)
    real.as_user("manager")
    modelled = ModelledScreening("DocumentManager")
    (status, payload), _ = both(
        real, modelled, "POST", "/api/content-screening/scans",
        body={**SCAN_BODY, "document_ids": ["zeta", "alpha"]},
    )
    assert status == 202 and payload["selection"]["document_ids"] == ["alpha", "zeta"]
