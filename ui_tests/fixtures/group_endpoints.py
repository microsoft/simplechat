# group_endpoints.py
"""
Closed M5C group model endpoint HTTP fixtures for the real production V2 SPA.
Version: 0.261.143
Implemented in: 0.261.143

The fixture serves the immutable `/api/groups/<group_id>/model-endpoints[...]` CRUD family
and the group `/api/groups/<group_id>/models/{fetch,test-model}` discovery and test routes,
and injects the `endpoint_management` context hint that gates create plus the per-row
`endpoint_actions` projection that gates edit, enable, delete and test. It never permits a
tenant-admin read: the shared base fixture records any `/api/v2/admin/*` request from a group
page as unexpected, so a group endpoints section that reached the admin network-policy,
default-model or migration routes would fail the run. Endpoints carry an opaque `revision`
marker round-tripped as `expected_revision`, exactly like the group prompt editor, and the
list envelope proves scope at the shape -- an `endpoints` array whose every item carries a
non-empty `id`, `revision` and `endpoint_actions` -- rather than a per-item group id.

group-a is a manager workspace carrying four endpoints: a fully editable one whose stored API
key proves masking survives a rename, a withheld one whose empty `endpoint_actions` hides
enable, edit and delete beside the editable control, a Foundry one whose editor can discover
models, and one still referenced by an agent so a delete returns the in-use 409 with its
references. group-b is an ordinary member: its `endpoint_management` hint is empty and its rows
carry no `endpoint_actions`, so its section renders read-only with no write affordance.
"""

import pytest

from ui_tests.fixtures.group_workspace import (  # noqa: F401
    GroupWorkspaceFixture, group_model_endpoint,
    ENDPOINT_STORED_CREDENTIAL_SUPPLIED, ENDPOINT_STORED_CREDENTIAL_UNAVAILABLE,
)


EDITABLE_ENDPOINT_ID = "group-a-editable-endpoint"
WITHHELD_ENDPOINT_ID = "group-a-withheld-endpoint"
FOUNDRY_ENDPOINT_ID = "group-a-foundry-endpoint"
IN_USE_ENDPOINT_ID = "group-a-in-use-endpoint"
DISCOVERY_ENDPOINT_ID = "group-a-discovery-endpoint"

EDITABLE_ENDPOINT_NAME = "Research chat connection"
WITHHELD_ENDPOINT_NAME = "Locked platform connection"
FOUNDRY_ENDPOINT_NAME = "Group Foundry connection"
IN_USE_ENDPOINT_NAME = "Bound reviewer connection"
DISCOVERY_ENDPOINT_NAME = "Discovery-ready connection"


class GroupEndpointsFixture(GroupWorkspaceFixture):
    """A small scripted endpoint boundary; no second connection service, no live inference."""

    def __init__(self, page):
        super().__init__(page)
        self.active_group = "group-a"
        # group-a: a manager workspace. Recomputing the context from the same Owner policy carries the
        # full endpoint_management hint, exactly like the identity fixture recomputes its policy.
        self.set_endpoint_policy("group-a", role="Owner", status="active")
        self._seed_endpoints("group-a", [
            # Fully editable: a stored API key proves a rename keeps it masked, and its endpoint_actions
            # carry edit, enable, delete and test so a manager reaches every control.
            group_model_endpoint(EDITABLE_ENDPOINT_ID, EDITABLE_ENDPOINT_NAME, has_api_key=True),
            # Withheld: the workspace advertises the operations, but this row's empty endpoint_actions
            # hide its enable, edit and delete beside the editable control. An explicit defensive case
            # kept so the per-row gate is proven, not merely the workspace-level hint.
            group_model_endpoint(WITHHELD_ENDPOINT_ID, WITHHELD_ENDPOINT_NAME, has_api_key=True, actions=()),
            # A Foundry connection whose editor can discover models through the group /models/fetch route.
            group_model_endpoint(FOUNDRY_ENDPOINT_ID, FOUNDRY_ENDPOINT_NAME, provider="aifoundry"),
            # Still referenced by a group agent, so a delete is refused with the in-use 409 and its
            # references, and nothing is removed.
            group_model_endpoint(IN_USE_ENDPOINT_ID, IN_USE_ENDPOINT_NAME, has_api_key=True),
            # A managed-identity connection whose editor exposes Azure model discovery through the
            # group /models/fetch route; an API key connection cannot reach ARM, so it has none.
            group_model_endpoint(DISCOVERY_ENDPOINT_ID, DISCOVERY_ENDPOINT_NAME,
                                 auth_type="managed_identity"),
        ])
        self.endpoint_references[("group-a", IN_USE_ENDPOINT_ID)] = [
            {"kind": "agent", "id": "group-a-assistant", "name": "Group assistant"},
        ]
        # group-b: an ordinary member. The endpoints section is available but its endpoint_management
        # hint is empty and every seeded row carries no endpoint_actions, so it renders read-only.
        self.set_endpoint_policy("group-b", role="User", status="active")
        self._seed_endpoints("group-b", [
            group_model_endpoint("group-b-shared-endpoint", "Shared team connection",
                                 has_api_key=True, actions=()),
        ])


@pytest.fixture
def group_endpoints_ui(page):
    fixture = GroupEndpointsFixture(page)
    yield fixture
    fixture.assert_clean()
