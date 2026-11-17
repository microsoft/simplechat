# v2_admin_global_identities.py
"""
Closed API fixture for the V2 Admin Settings Global Identities section.
Version: 0.261.445
Implemented in: 0.261.445

Extend the schema-backed Admin Settings fixture with an in-memory store of the deployment's global
identities. It answers the four administrator routes the section calls
(``/api/admin/workspace-identities/global/identities`` and one identity beneath it) in the shape the
server's older identity routes use: a list under ``identities``, a record under ``identity``, no
``etag`` and no ``identity_actions`` on a record, credentials masked with the Key Vault placeholder
and a ``*_stored`` flag, the server's own validation sentences on a refused write, and a delete that a
global action still uses refused as ``409`` with ``error_code: identity_in_use`` and the references.
``functional_tests/test_global_identity_admin_routes.py`` drives this fixture and the real routes
through the same requests and holds the two to the same statuses, keys and codes.

The real server does not version these records. A test that needs a conflict scripts the 409 a
versioned server would give (``fail_next``) and changes the stored record the way another
administrator's save would (``touch``), because the section reads that answer the same way for every
scope. Anything the fixture does not expect, a body field the section should not send, or a secret in
a response fails the test.

An explicitly released build can be pinned with SIMPLECHAT_UI_EXPECTED_JS and SIMPLECHAT_UI_EXPECTED_CSS
(both filenames must match the built index and exist on disk), as the workspace fixtures allow, for a
tree whose source timestamps are newer than the build. Without them the build must be newer than every
source file.
"""

import copy
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import unquote, urlsplit

import pytest
from playwright.sync_api import expect

from v2_admin_settings import ORIGIN, REPO_ROOT, SPA_INDEX, AdminSettingsFixture, connect_options  # noqa: F401


GLOBAL_IDENTITIES_PATH = "/api/admin/workspace-identities/global/identities"
STATIC_ROOT = REPO_ROOT / "application" / "single_app" / "static"
SECRET_PLACEHOLDER = "Stored_In_KeyVault"
STORED_SECRET = "fixture-only-global-secret"

API_KEY_ID = "30000000-0000-4000-8000-000000000001"
FILE_SHARE_ID = "30000000-0000-4000-8000-000000000002"
TICKET_TOKEN_ID = "30000000-0000-4000-8000-000000000003"
GRAPH_APP_ID = "30000000-0000-4000-8000-000000000004"

IN_USE_MESSAGE = "This workspace identity is still used by one or more File Sync sources or actions"
FORBIDDEN_BODY = {"error": "Forbidden", "message": "Insufficient permissions (Admin role required)"}
NOT_FOUND_BODY = {"error": "Workspace identity not found"}
ETAG_CONFLICT_BODY = {
    "error": "This workspace identity was modified. Reload and try again.",
    "error_code": "etag_conflict",
}

FILE_SYNC_SOURCE_TYPES = ["smb", "azure_files", "azure_blob", "onedrive", "google_drive", "google_shared_drive"]
USAGE_AUTH_TYPES = {
    "file_sync": {"anonymous", "client_secret", "connection_string", "managed_identity", "username_password"},
    "action": {"api_key", "bearer_token", "client_secret", "connection_string", "managed_identity", "username_password"},
}
ALLOWED_WRITE_FIELDS = {
    "name", "description", "provider", "source_type", "usage_contexts", "supported_source_types",
    "metadata", "credentials",
}
SECRET_KEYS = ("password", "secret")


def credentials_block(*, auth_type, username="", domain="", identity="", tenant_id="",
                      managed_identity_client_id="", secret_stored=False):
    """The sanitized ``credentials`` block, as ``sanitize_workspace_identity`` builds it."""
    uses_password = auth_type == "username_password"
    return {
        "auth_type": auth_type,
        "username": username,
        "domain": domain,
        "identity": identity,
        "tenant_id": tenant_id,
        "managed_identity_client_id": managed_identity_client_id,
        "password_stored": bool(uses_password and secret_stored),
        "secret_stored": bool(not uses_password and secret_stored),
        "password": SECRET_PLACEHOLDER if (uses_password and secret_stored) else "",
        "secret": SECRET_PLACEHOLDER if (not uses_password and secret_stored) else "",
    }


def usage_fields(usage):
    """The provider and source types the server stores for a usage selection."""
    source_types = []
    for context in usage:
        for source_type in (FILE_SYNC_SOURCE_TYPES if context == "file_sync" else ["action"]):
            if source_type not in source_types:
                source_types.append(source_type)
    return {"provider": source_types[0], "source_type": source_types[0], "supported_source_types": source_types}


def global_identity(identifier, name, *, usage=("action",), auth_type="api_key", secret_stored=True,
                    username="", domain="", identity="", tenant_id="", managed_identity_client_id="",
                    **overrides):
    """One global identity, as the older identity routes serve it: no etag, no identity_actions."""
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "id": identifier,
        "identity_id": identifier,
        "type": "workspace_identity",
        "scope_type": "global",
        "global_id": "global",
        "created_by": "previous-admin",
        "updated_by": "previous-admin",
        "created_at": now,
        "updated_at": now,
        "name": name,
        "description": f"Stored credential for {name}.",
        "usage_contexts": list(usage),
        "metadata": {},
        **usage_fields(usage),
        "credentials": credentials_block(
            auth_type=auth_type, username=username, domain=domain, identity=identity,
            tenant_id=tenant_id, managed_identity_client_id=managed_identity_client_id,
            secret_stored=secret_stored,
        ),
    }
    record.update(copy.deepcopy(overrides))
    return record


class GlobalIdentitiesFixture(AdminSettingsFixture):
    """Admin Settings plus a scripted global identities boundary."""

    def __init__(self, page, *, admin=True):
        super().__init__(page, sections={"security": ("workspace-identities-section",)})
        self.settings.pop("enable_semantic_kernel", None)
        self.admin = admin
        self.identities = [
            global_identity(API_KEY_ID, "Reporting API key", description="Used by the reporting action."),
            global_identity(
                FILE_SHARE_ID, "File share account", usage=("file_sync",), auth_type="username_password",
                username="svc-files", domain="CORP", description="Reads the finance share.",
            ),
            global_identity(
                TICKET_TOKEN_ID, "Ticket API token", auth_type="bearer_token",
                description="Used by the ticket search action.",
            ),
            global_identity(
                GRAPH_APP_ID, "Graph app registration", usage=("file_sync", "action"), auth_type="client_secret",
                identity="11111111-2222-4333-8444-555555555555", tenant_id="contoso-tenant",
                description="Application permissions for OneDrive.",
            ),
        ]
        self.stored_secrets = {record["id"]: STORED_SECRET for record in self.identities}
        # Global actions that still use an identity: a delete is refused, naming them.
        self.references = {
            TICKET_TOKEN_ID: [
                {"kind": "action", "id": "ticket_search", "name": "Ticket search"},
                {"kind": "action", "id": "roadmap_lookup", "name": "Roadmap lookup"},
            ],
        }
        self.created_counter = 0
        self.rejection = None
        self.identity_requests = []
        self.identity_writes = []
        self.identity_responses = []
        self.protocol_violations = []
        # Failures a test scripts on purpose, and the console errors each one causes.
        self.pending_failures = []
        self.expected_failure_statuses = []
        self.private_values = {STORED_SECRET}

    # --- Test helpers ------------------------------------------------------

    def record(self, identifier):
        return next(row for row in self.identities if row["id"] == identifier)

    def writes(self, method=None):
        return [write for write in self.identity_writes if method is None or write[0] == method]

    def reads(self):
        return [request for request in self.identity_requests if request[0] == "GET"]

    def fail_next(self, method, status, payload, *, path=None):
        """Answer the next matching request with an error, as a failing server would."""
        self.pending_failures.append((method, path, status, copy.deepcopy(payload)))
        self.expected_failure_statuses.append(status)

    def reject_all(self, status, payload):
        """Answer every identity request with an error until `allow_all` is called."""
        self.rejection = (status, copy.deepcopy(payload))

    def allow_all(self):
        self.rejection = None

    def touch(self, identifier, **changes):
        """Another administrator saved this identity: it changes and its last-updated time moves."""
        record = self.record(identifier)
        record.update(copy.deepcopy(changes))
        record["updated_at"] = datetime.now(timezone.utc).isoformat()
        return record

    def drop(self, identifier):
        """Another administrator deleted this identity."""
        self.identities = [row for row in self.identities if row["id"] != identifier]
        self.stored_secrets.pop(identifier, None)

    # --- The boundary ------------------------------------------------------

    def _route(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        is_global_route = f"{parsed.scheme}://{parsed.netloc}" == ORIGIN and (
            parsed.path == GLOBAL_IDENTITIES_PATH or parsed.path.startswith(f"{GLOBAL_IDENTITIES_PATH}/")
        )
        if not is_global_route:
            super()._route(route)
            return
        body = request.post_data_json if request.post_data else None
        status, payload = self.handle_identity_request(request.method, parsed.path, body)
        route.fulfill(status=status, json=payload)

    def handle_identity_request(self, method, path, body=None):
        """Answer one identity request, returning (status, payload). Playwright-free, so a test of
        the fixture against the real routes can call it directly."""
        self.identity_requests.append((method, path))
        if method != "GET":
            self.identity_writes.append((method, path, copy.deepcopy(body)))
        status, payload = self._answer(method, path, body)
        self.identity_responses.append(copy.deepcopy(payload))
        return status, payload

    def _scripted_failure(self, method, path):
        for index, (failure_method, failure_path, status, payload) in enumerate(self.pending_failures):
            if failure_method == method and (failure_path is None or failure_path == path):
                del self.pending_failures[index]
                return status, copy.deepcopy(payload)
        return None

    def _answer(self, method, path, body):
        scripted = self._scripted_failure(method, path)
        if scripted is not None:
            return scripted
        if self.rejection is not None:
            status, payload = self.rejection
            self.expected_failure_statuses.append(status)
            return status, copy.deepcopy(payload)
        if not self.admin:
            self.expected_failure_statuses.append(403)
            return 403, copy.deepcopy(FORBIDDEN_BODY)

        if path == GLOBAL_IDENTITIES_PATH:
            if method == "GET":
                rows = sorted(self.identities, key=lambda row: str(row.get("name") or ""))
                return 200, {"identities": copy.deepcopy(rows)}
            if method == "POST":
                return self._create(body)
            return 405, {"error": "Method not allowed"}

        identifier = unquote(path.removeprefix(f"{GLOBAL_IDENTITIES_PATH}/"))
        record = next((row for row in self.identities if row["id"] == identifier), None)
        if method == "PATCH":
            return self._update(record, body)
        if method == "DELETE":
            return self._delete(record, body)
        return 405, {"error": "Method not allowed"}

    def _check_body(self, body, *, forbid=()):
        """Fields the section must never send: anything beyond the documented write, an auth block."""
        if not isinstance(body, dict):
            self.protocol_violations.append(f"The write body was not an object: {body!r}")
            return {}
        extra = set(body) - ALLOWED_WRITE_FIELDS - set(forbid)
        if extra:
            self.protocol_violations.append(f"The write carried fields the routes do not document: {sorted(extra)}")
        return body

    def _validation_error(self, body, prior):
        """The server's own sentences for the failures a form can reach, in the order it checks."""
        credentials = body.get("credentials") if isinstance(body.get("credentials"), dict) else {}
        usage = body.get("usage_contexts") if isinstance(body.get("usage_contexts"), list) else (
            prior["usage_contexts"] if prior else ["action"]
        )
        prior_credentials = (prior or {}).get("credentials") or {}
        auth_type = str(credentials.get("auth_type") or prior_credentials.get("auth_type") or "username_password")
        if auth_type not in {"anonymous", "api_key", "bearer_token", "client_secret", "connection_string",
                             "managed_identity", "username_password"}:
            return "Unsupported workspace identity authentication type"
        allowed = set().union(*(USAGE_AUTH_TYPES.get(context, set()) for context in usage))
        if allowed and auth_type not in allowed:
            return "Selected authentication type is not available for the selected identity uses"
        stored = bool(prior_credentials.get("password_stored") or prior_credentials.get("secret_stored"))
        stored = stored and prior_credentials.get("auth_type") == auth_type
        if auth_type == "username_password":
            if not str(credentials.get("password") or "") and not stored:
                return "Username/password identities require a password"
        elif auth_type not in ("anonymous", "managed_identity"):
            if not str(credentials.get("secret") or "") and not stored:
                return "This identity type requires a secret value"
        return None

    def _apply(self, record, body):
        for key in ("name", "description", "provider", "source_type", "usage_contexts", "supported_source_types"):
            if key in body:
                record[key] = copy.deepcopy(body[key])
        credentials = body.get("credentials") if isinstance(body.get("credentials"), dict) else {}
        prior = record["credentials"]
        auth_type = str(credentials.get("auth_type") or prior["auth_type"])
        new_secret = str(credentials.get("password") or credentials.get("secret") or "")
        if new_secret:
            self.private_values.add(new_secret)
            self.stored_secrets[record["id"]] = new_secret
        keeps_secret = prior["auth_type"] == auth_type and (prior["password_stored"] or prior["secret_stored"])
        secret_stored = bool(new_secret) or keeps_secret
        record["credentials"] = credentials_block(
            auth_type=auth_type,
            username=str(credentials.get("username", prior["username"])) if auth_type == "username_password" else "",
            domain=str(credentials.get("domain", prior["domain"])) if auth_type == "username_password" else "",
            identity=str(credentials.get("identity", prior["identity"])) if auth_type == "client_secret" else "",
            tenant_id=prior["tenant_id"] if auth_type == "client_secret" else "",
            managed_identity_client_id=(
                str(credentials.get("managed_identity_client_id", prior["managed_identity_client_id"]))
                if auth_type == "managed_identity" else ""
            ),
            secret_stored=secret_stored and auth_type not in ("anonymous", "managed_identity"),
        )
        record["updated_at"] = datetime.now(timezone.utc).isoformat()

    def _create(self, body):
        body = self._check_body(body)
        error = self._validation_error(body, None)
        if error:
            self.expected_failure_statuses.append(400)
            return 400, {"error": error}
        self.created_counter += 1
        identifier = f"30000000-0000-4000-8000-0000000001{self.created_counter:02d}"
        usage = body.get("usage_contexts") if isinstance(body.get("usage_contexts"), list) else ["action"]
        record = global_identity(
            identifier, str(body.get("name") or "Workspace Identity"), usage=tuple(usage), secret_stored=False,
            auth_type="api_key",
        )
        record["credentials"] = credentials_block(auth_type="api_key")
        self._apply(record, body)
        self.identities.append(record)
        return 201, {"identity": copy.deepcopy(record)}

    def _update(self, record, body):
        body = self._check_body(body)
        if "expected_etag" in body:
            self.protocol_violations.append("An edit sent expected_etag, but these records carry no etag.")
        if record is None:
            self.expected_failure_statuses.append(404)
            return 404, copy.deepcopy(NOT_FOUND_BODY)
        error = self._validation_error(body, record)
        if error:
            self.expected_failure_statuses.append(400)
            return 400, {"error": error}
        self._apply(record, body)
        return 200, {"identity": copy.deepcopy(record)}

    def _delete(self, record, body):
        if body:
            self.protocol_violations.append(f"A delete of a record with no etag carried a body: {body!r}")
        if record is None:
            self.expected_failure_statuses.append(404)
            return 404, copy.deepcopy(NOT_FOUND_BODY)
        references = self.references.get(record["id"])
        if references:
            self.expected_failure_statuses.append(409)
            return 409, {
                "error": IN_USE_MESSAGE,
                "error_code": "identity_in_use",
                "references": copy.deepcopy(references),
            }
        self.drop(record["id"])
        return 200, {"message": "Workspace identity deleted", "delete_result": {"identity_id": record["id"], "deleted_by": "test-admin"}}

    # --- Browser -----------------------------------------------------------

    def open(self, theme="light", width=1440, font_size="m", *, wait_until="networkidle", height=1000,
             ready_region="Global Identities", preferences=None):
        if not SPA_INDEX.is_file():
            pytest.fail("Build the V2 SPA first: npm --prefix application/v2_ui run build")
        self._require_current_build()
        self.preferences = {
            "darkModeEnabled": theme == "dark",
            "v2RailCollapsed": width < 1024,
            "fontSizePreference": font_size,
            **(preferences or {}),
        }
        self.page.set_viewport_size({"width": width, "height": height})
        self.page.goto(f"{ORIGIN}/v2/admin", wait_until=wait_until)
        expect(self.page.get_by_role("region", name=ready_region, exact=True)).to_be_visible()
        expect(self.page.locator("html")).to_have_attribute("data-font-size", font_size)

    @staticmethod
    def _require_current_build():
        """The build must be newer than the sources, or be the one build the run was pinned to."""
        expected_js = os.getenv("SIMPLECHAT_UI_EXPECTED_JS", "")
        expected_css = os.getenv("SIMPLECHAT_UI_EXPECTED_CSS", "")
        if expected_js or expected_css:
            if not expected_js or not expected_css:
                pytest.fail("Set both SIMPLECHAT_UI_EXPECTED_JS and SIMPLECHAT_UI_EXPECTED_CSS.")
            index = SPA_INDEX.read_text(encoding="utf-8")
            for filename, attribute, suffix in ((expected_js, "src", "js"), (expected_css, "href", "css")):
                if not re.fullmatch(rf"[A-Za-z0-9_.-]+\.{suffix}", filename):
                    pytest.fail("Expected build assets must be local filenames.")
                asset = STATIC_ROOT / "v2" / "assets" / filename
                reference = f"/static/v2/assets/{filename}"
                if not asset.is_file() or not re.search(rf'{attribute}=["\']{re.escape(reference)}["\']', index):
                    pytest.fail("The explicitly released SPA assets are missing or have changed.")
            return
        source_root = REPO_ROOT / "application" / "v2_ui" / "src"
        if any(path.stat().st_mtime > SPA_INDEX.stat().st_mtime for path in source_root.rglob("*") if path.is_file()):
            pytest.fail("The V2 bundle is stale. Run npm --prefix application/v2_ui run build")

    def assert_clean(self):
        assert not self.pending_failures, f"A scripted failure was never requested: {self.pending_failures}"
        assert not self.protocol_violations, self.protocol_violations
        # Each error the boundary answered on purpose logs one resource failure in the console.
        for status in self.expected_failure_statuses:
            prefix = f"Failed to load resource: the server responded with a status of {status}"
            match = next((error for error in self.errors if error.startswith(prefix)), None)
            if match is not None:
                self.errors.remove(match)
        super().assert_clean()
        for payload in self.identity_responses:
            text = json.dumps(payload)
            for secret in self.private_values:
                assert secret not in text, "A secret crossed the fixture API boundary."
        storage = self.page.evaluate("() => JSON.stringify({local: {...localStorage}, session: {...sessionStorage}})")
        for secret in self.private_values:
            assert secret not in storage + json.dumps(self.preferences), "A secret was persisted in the browser."


@pytest.fixture
def global_identities_ui(page):
    fixture = GlobalIdentitiesFixture(page)
    yield fixture
    fixture.assert_clean()
