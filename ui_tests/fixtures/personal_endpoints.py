# personal_endpoints.py
"""
Production-SPA personal endpoint fixture backed by real offline Flask routes.
Version: 0.261.315
Implemented in: 0.261.315

Reuse the workspace shell and Azure Playwright connection support. Personal
CRUD, discovery, normalization, governance and secret storage run unchanged
through the functional endpoint harness, with external services/network blocked.
"""

import json
from urllib.parse import urlsplit

import pytest

from ui_tests.fixtures.workspace_authoring import (
    OWNER_ID, SPA_INDEX, WorkspaceAuthoringFixture, connect_options,  # noqa: F401
)
from test_support.group_endpoint_harness import (
    aoai_endpoint, foundry_endpoint, group_endpoint_environment,
)


BASE = "/api/user/model-endpoints"
ENDPOINT_ID = "personal-chat"
ENDPOINT_NAME = "Personal research connection"
FOUNDRY_ID = "personal-foundry"


class PersonalEndpointsFixture(WorkspaceAuthoringFixture):
    def __init__(self, page, environment):
        super().__init__(page)
        self.environment = environment
        endpoint = aoai_endpoint(
            ENDPOINT_ID, name=ENDPOINT_NAME, contextWindow=128000,
            outputTokenAccounting="total_generation",
        )
        endpoint["models"][0].update({
            "deploymentName": "existing-chat", "modelName": "gpt-4o",
            "description": "Research model", "responseLength": 512,
            "contextWindow": 64000, "catalogModelId": "gpt-4o",
            "modelVersion": "2024-08-06", "icon": {"kind": "bootstrap", "value": "bi-stars"},
            "metadata": {"keep": False},
        })
        environment.seed_personal_endpoints(OWNER_ID, [endpoint, foundry_endpoint(FOUNDRY_ID)])
        environment.as_user(OWNER_ID)
        environment.vault.writes.clear()
        self.private_values.update({"sk-plain", "sp-plain"})
        self.malformed_list = False

    def _route(self, route):
        if route.request.method == "GET" and route.request.url == "http://simplechat.test/v2/workspace/endpoints":
            route.fulfill(path=str(SPA_INDEX), content_type="text/html")
            return
        super()._route(route)

    def _dispatch(self, route, entry):
        if entry.path == BASE and entry.method == "GET" and self.malformed_list:
            self._json(route, {"endpoints": [{}], "custom_api_types": []})
            return
        if entry.path == BASE or entry.path.startswith(f"{BASE}/") or entry.path in {
            "/api/user/models/fetch", "/api/user/models/test-model",
        }:
            response = self.environment.call(entry.method, entry.path, entry.body)
            self._json(route, response.get_json(), response.status_code)
            return
        if entry.path == "/api/models/catalog" and entry.method == "GET":
            self._json(route, {"profiles": [], "tasks": [], "generation": 1})
            return
        super()._dispatch(route, entry)

    def stored(self, endpoint_id=ENDPOINT_ID):
        return self.environment.personal_endpoint(OWNER_ID, endpoint_id)

    def assert_clean(self):
        super().assert_clean()
        forbidden = ("/api/v2/admin/", "/api/groups/", "/legacy", "/my_workspace")
        assert not [
            entry for entry in self.requests
            if entry.path.startswith(forbidden) or entry.path in {"/api/models/fetch", "/api/models/test-model"}
        ], "Personal endpoints reached an admin, group or classic route."
        for _, payload in self.responses:
            serialized = json.dumps(payload)
            assert "sk-plain" not in serialized and "sp-plain" not in serialized
            assert "--model-endpoint--" not in serialized, "Key Vault references reached the browser."
        assert urlsplit(self.page.url).path.startswith("/v2/"), "The editor left the native SPA."


@pytest.fixture
def personal_endpoints_ui(page):
    with group_endpoint_environment() as environment:
        fixture = PersonalEndpointsFixture(page, environment)
        yield fixture
        fixture.assert_clean()
