# personal_identities.py
"""
Closed production-SPA personal identity fixture, held to real APIs by parity tests.
Version: 0.261.315
Implemented in: 0.261.315

Uses real local built assets and a non-admin bootstrap. Classic pages and unknown
requests remain unavailable. Secrets are masked in every served identity.
"""

import copy
import re
from urllib.parse import urlsplit

import pytest

from ui_tests.fixtures.workspace_authoring import OWNER_ID, SPA_INDEX
from ui_tests.fixtures.personal_file_sources import PersonalFileSourcesFixture
from ui_tests.fixtures.public_identities import _credentials


LIST_PATH = "/api/user/identities"
SAVED_ID = "personal-saved-identity"
SAVED_NAME = "Personal service account"


def personal_identity(identifier=SAVED_ID, name=SAVED_NAME, *, auth_type="api_key", usage=None, **overrides):
    uses = usage or ["action"]
    provider = "smb" if "file_sync" in uses else "action"
    record = {
        "id": identifier, "identity_id": identifier, "name": name, "description": "",
        "type": "workspace_identity", "scope_type": "personal", "user_id": OWNER_ID,
        "provider": provider, "source_type": provider, "usage_contexts": uses,
        "supported_source_types": ["smb", "azure_files", "azure_blob"] if provider == "smb" else ["action"],
        "metadata": {}, "credentials": _credentials(auth_type=auth_type, secret_stored=True),
        "etag": '"etag-1"', "identity_actions": ["edit", "delete"],
    }
    record.update(copy.deepcopy(overrides))
    return record


class PersonalIdentitiesFixture(PersonalFileSourcesFixture):
    def __init__(self, page):
        super().__init__(page)
        self.identities = {SAVED_ID: personal_identity()}
        self.identity_secrets = {SAVED_ID: "fixture-existing-personal-secret"}
        self.identity_references = {}
        self.identity_revision = 1
        self.created_identity_count = 0
        self.malformed_identity_list = False
        self.private_values.add("fixture-existing-personal-secret")

    def _route(self, route):
        if route.request.method == "GET" and urlsplit(route.request.url).path == "/v2/workspace/identities":
            route.fulfill(path=str(SPA_INDEX), content_type="text/html")
            return
        super()._route(route)

    def _next_identity_etag(self):
        self.identity_revision += 1
        return f'"etag-{self.identity_revision}"'

    def _sync_source_catalog(self):
        self.source_identities = list(self.identities.values())
        auth_types = {
            "smb": {"username_password", "anonymous"},
            "azure_files": {"managed_identity", "client_secret", "connection_string"},
            "azure_blob": {"managed_identity", "client_secret", "connection_string"},
        }
        self.source_options["eligible_identity_ids"] = {
            source: [
                record["id"] for record in self.source_identities
                if "file_sync" in record["usage_contexts"]
                and source in record["supported_source_types"]
                and record["credentials"]["auth_type"] in allowed
            ]
            for source, allowed in auth_types.items()
        }

    def _dispatch(self, route, entry):
        path, method = entry.path, entry.method
        single = re.fullmatch(r"/api/user/identities/([^/]+)", path)
        if path == "/api/workspace-identities/personal/identities" and method == "GET":
            # Existing connector readers share the same personal identity container.
            self._json(route, {"identities": list(self.identities.values())})
            return
        if path != LIST_PATH and not single:
            self._sync_source_catalog()
            super()._dispatch(route, entry)
            return
        if not self.workspace_enabled or "identities" in self.disabled_sections:
            self._json(route, {"error": "Your personal workspace is not enabled."}, 403)
            return
        if method == "GET":
            if not single:
                self._json(route, {"identities": None if self.malformed_identity_list else list(self.identities.values())})
            elif single[1] in self.identities:
                self._json(route, {"identity": self.identities[single[1]]})
            else:
                self._json(route, {"error": "The workspace identity was not found."}, 404)
            return
        identifier = single[1] if single else None
        prior = self.identities.get(identifier)
        if single:
            if not prior:
                self._json(route, {"error": "The workspace identity was not found."}, 404)
                return
            if not entry.body.get("expected_etag"):
                self._json(route, {"error": "An expected_etag is required for this action."}, 400)
                return
            if entry.body["expected_etag"] != prior["etag"]:
                self._json(route, {
                    "error": "This workspace identity was modified. Reload and try again.",
                    "error_code": "etag_conflict",
                }, 409)
                return
        if method == "DELETE":
            references = self.identity_references.get(identifier)
            if references:
                self._json(route, {
                    "error": "This workspace identity is still in use.",
                    "error_code": "identity_in_use", "references": references,
                }, 409)
                return
            self.identities.pop(identifier)
            self.identity_secrets.pop(identifier, None)
            self._json(route, {"success": True})
            return
        credentials = entry.body.get("credentials", {})
        old = prior["credentials"] if prior else {}
        auth_type = credentials.get("auth_type", old.get("auth_type", "username_password"))
        field = "password" if auth_type == "username_password" else "secret"
        secret = credentials.get(field) or self.identity_secrets.get(identifier, "")
        if auth_type not in ("managed_identity", "anonymous") and not secret:
            message = "Username/password identities require a password" if field == "password" else "This identity type requires a secret value"
            self._json(route, {"error": message}, 400)
            return
        if not prior:
            self.created_identity_count += 1
            identifier = f"personal-created-{self.created_identity_count}"
        record = copy.deepcopy(prior) if prior else personal_identity(identifier, entry.body["name"])
        for key in ("name", "description", "provider", "source_type", "usage_contexts", "supported_source_types"):
            if key in entry.body:
                record[key] = copy.deepcopy(entry.body[key])
        record["credentials"] = _credentials(
            auth_type=auth_type,
            username=credentials.get("username", old.get("username", "")),
            domain=credentials.get("domain", old.get("domain", "")),
            identity=credentials.get("client_id", credentials.get("identity", old.get("identity", ""))),
            tenant_id=credentials.get("tenant_id", old.get("tenant_id", "")),
            managed_identity_client_id=credentials.get("managed_identity_client_id", old.get("managed_identity_client_id", "")),
            secret_stored=bool(secret) and auth_type not in ("managed_identity", "anonymous"),
        )
        record["etag"] = self._next_identity_etag()
        self.identities[identifier] = record
        self.identity_secrets[identifier] = secret
        if secret:
            self.private_values.add(secret)
        self._json(route, {"identity": record}, 200 if prior else 201)


@pytest.fixture
def personal_identities_ui(page):
    fixture = PersonalIdentitiesFixture(page)
    yield fixture
    fixture.assert_clean()
