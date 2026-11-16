# personal_file_sources.py
"""
Closed production-SPA HTTP fixture for native personal source configuration.
Version: 0.261.310
Implemented in: 0.261.310
"""

import copy
import re
from urllib.parse import urlsplit

import pytest

from ui_tests.fixtures.workspace_authoring import ORIGIN, SPA_INDEX, WorkspaceAuthoringFixture


BASE = "/api/file-sync/personal/sources"
SOURCE_ID = "personal-source"
SOURCE_NAME = "Personal reports"
STORED_PASSWORD = "fixture-personal-stored-password"


class PersonalFileSourcesFixture(WorkspaceAuthoringFixture):
    def __init__(self, page):
        super().__init__(page)
        self.sources = {
            SOURCE_ID: {
                "id": SOURCE_ID, "name": SOURCE_NAME, "source_type": "smb", "enabled": True,
                "recursive": True, "connection": {"unc_path": "\\\\files\\reports", "selected_paths": ["Reports"]},
                "filters": {"include_patterns": ["*.pdf"], "exclude_patterns": [], "allowed_extensions": ["pdf"],
                            "fixed_tags": ["finance"], "folder_tag_mode": "parent"},
                "schedule": {"enabled": False, "interval_minutes": 30}, "remote_delete_policy": "ignore",
                "identity_id": "", "identity_name": "",
                "credentials": {"auth_type": "username_password", "username": "svc-reports", "domain": "CORP",
                                "password_stored": True, "secret_stored": False, "password": "", "secret": ""},
                "config_revision": "revision-1",
            },
        }
        self.source_secrets = {SOURCE_ID: STORED_PASSWORD}
        self.source_versions = {SOURCE_ID: 1}
        self.private_values.add(STORED_PASSWORD)
        self.source_options = {
            "source_types": [
                {"value": value, "label": label, "visible": True}
                for value, label in [("smb", "Network share"), ("azure_files", "Azure Files"), ("azure_blob", "Azure Blob Storage")]
            ],
            "eligible_identity_ids": {"smb": ["personal-smb-identity"], "azure_files": [], "azure_blob": []},
            "schedule": {"min_interval_minutes": 5, "max_interval_minutes": 10080},
            "limits": {"max_sources": 25}, "recursive_allowed": True,
            "default_remote_delete_policy": "ignore",
        }
        self.source_identities = [{
            "id": "personal-smb-identity", "name": "Personal share account", "provider": "smb",
            "is_enabled": True, "usage_contexts": ["file_sync"], "supported_source_types": ["smb"],
        }]

    def _bootstrap(self):
        bootstrap = super()._bootstrap()
        bootstrap["workspace"]["sections"]["sync"] = {
            "enabled": "sync" not in self.disabled_sections,
            "reason": self.disabled_sections.get("sync"), "group": "connections",
        }
        return bootstrap

    def _route(self, route):
        parsed = urlsplit(route.request.url)
        if route.request.method == "GET" and f"{parsed.scheme}://{parsed.netloc}" == ORIGIN and parsed.path == "/v2/workspace/sync":
            route.fulfill(path=str(SPA_INDEX), content_type="text/html")
            return
        super()._route(route)

    def change_source(self, identifier, **changes):
        self.sources[identifier].update(copy.deepcopy(changes))
        self.source_versions[identifier] += 1
        self.sources[identifier]["config_revision"] = f"revision-{self.source_versions[identifier]}"

    def _apply(self, identifier, write):
        source = self.sources[identifier]
        for field in ("name", "source_type", "enabled", "recursive", "connection", "filters", "schedule", "remote_delete_policy", "identity_id"):
            if field in write:
                source[field] = copy.deepcopy(write[field])
        if source.get("identity_id"):
            identity = next(item for item in self.source_identities if item["id"] == source["identity_id"])
            source["identity_name"] = identity["name"]
        else:
            source["identity_name"] = ""
            if "credentials" in write:
                incoming = write["credentials"]
                auth_type = incoming["auth_type"]
                old = source.get("credentials", {})
                secret = incoming.get("password") or incoming.get("secret") or incoming.get("connection_string")
                if secret:
                    self.source_secrets[identifier] = secret
                    self.private_values.add(secret)
                elif old.get("auth_type") != auth_type:
                    self.source_secrets.pop(identifier, None)
                source["credentials"] = {
                    **{key: copy.deepcopy(incoming[key]) for key in ("auth_type", "username", "domain", "identity", "tenant_id", "managed_identity_client_id") if key in incoming},
                    "password_stored": bool(self.source_secrets.get(identifier)) and auth_type == "username_password",
                    "secret_stored": bool(self.source_secrets.get(identifier)) and auth_type in ("client_secret", "connection_string"),
                    "password": "", "secret": "",
                }
        self.change_source(identifier)

    def _dispatch(self, route, entry):
        path, method = entry.path, entry.method
        if path == "/api/file-sync/personal/source-options" and method == "GET":
            self._json(route, self.source_options)
            return
        if path == "/api/workspace-identities/personal/identities" and method == "GET":
            self._json(route, {"identities": self.source_identities})
            return
        if path == "/api/documents/tags" and method == "GET":
            self._json(route, {"tags": [{"name": "finance", "count": 3}, {"name": "legal", "count": 1}]})
            return
        if path == BASE:
            if method == "GET":
                self._json(route, {"sources": list(self.sources.values())})
                return
            if method == "POST":
                identifier = f"created-source-{len(self.sources)}"
                self.sources[identifier] = {"id": identifier, "credentials": {}}
                self.source_versions[identifier] = 0
                self._apply(identifier, entry.body)
                self._json(route, {"source": self.sources[identifier]}, 201)
                return
        match = re.fullmatch(re.escape(BASE) + r"(?:/([^/]+))?/(test-connection|browse|ignore-path|sync|runs)", path)
        if match:
            identifier, operation = match.groups()
            if identifier and identifier not in self.sources:
                self._json(route, {"error": "File source not found."}, 404)
                return
            if operation == "test-connection" and method == "POST":
                self._json(route, {"connection": {
                    "success": True, "entries_checked": 1, "folders_seen": 0, "files_seen": 1,
                }})
                return
            if operation == "browse" and method == "POST":
                browse_path = entry.body.get("browse_path", "")
                entries = [
                    {"name": "Reports", "path": "Reports", "is_dir": True},
                    {"name": "report.pdf", "path": "report.pdf", "is_dir": False, "remote_path": "\\\\files\\reports\\report.pdf"},
                ] if not browse_path else [
                    {"name": "Q1.pdf", "path": "Reports/Q1.pdf", "is_dir": False, "remote_path": "\\\\files\\reports\\Reports\\Q1.pdf"},
                ]
                self._json(route, {"browse": {"path": browse_path, "entries": entries}})
                return
            if operation == "ignore-path" and method == "POST":
                self._json(route, {"item": {"remote_path": entry.body["remote_path"], "ignored": entry.body["ignored"]}})
                return
            if operation == "sync" and method == "POST":
                self._json(route, {"run": {"id": "queued-run", "status": "queued"}}, 202)
                return
            if operation == "runs" and method == "GET":
                self._json(route, {"runs": [{"id": "completed-run", "status": "completed"}]})
                return
        match = re.fullmatch(re.escape(BASE) + r"/([^/]+)", path)
        if match:
            identifier = match.group(1)
            source = self.sources.get(identifier)
            if not source:
                self._json(route, {"error": "File source not found."}, 404)
                return
            if method == "GET":
                self._json(route, {"source": source})
                return
            if method in ("PATCH", "DELETE") and entry.body["expected_config_revision"] != source["config_revision"]:
                self._json(route, {"error": "This file source changed while you were editing.", "error_code": "config_conflict"}, 409)
                return
            if method == "PATCH":
                self._apply(identifier, entry.body)
                self._json(route, {"source": self.sources[identifier]})
                return
            if method == "DELETE":
                del self.sources[identifier]
                self._json(route, {"delete_result": {
                    "associated_files_requested": entry.body["delete_associated_files"],
                    "documents_deleted": 3 if entry.body["delete_associated_files"] else 0,
                    "documents_skipped": 0, "documents_failed": 0,
                }})
                return
        super()._dispatch(route, entry)

    def assert_clean(self):
        super().assert_clean()
        for _, payload in self.responses:
            assert STORED_PASSWORD not in str(payload), "Stored personal credentials must never cross HTTP."
        assert not [entry for entry in self.requests if entry.path.startswith(("/api/groups/", "/api/public-workspaces/"))]


@pytest.fixture
def personal_file_sources_ui(page):
    fixture = PersonalFileSourcesFixture(page)
    yield fixture
    fixture.assert_clean()
