# group_identities.py
"""
Closed M5A group identity HTTP fixtures for the real production V2 SPA.
Version: 0.261.138
Implemented in: 0.261.138

The fixture serves the immutable `/api/groups/<group_id>/identities[...]` family and
injects the `identity_management` context hint that gates create, and the per-row
`identity_actions` projection that gates edit and delete. It never permits a
personal-scope read: the shared base fixture records any `/api/user/*`, personal
`/api/workspace-identities/personal/*`, personal MCP preconfiguration, or
`?agent_scope=personal` request from a group page as unexpected rather than
answering it, so a group identity surface that leaked into personal reads would
fail the run. It never falls back to personal behaviour: identity reads use the
same manage roles as writes -- Owner, Admin and DocumentManager -- so an ordinary
member is refused with 403 on every identity route, which the group action editor
turns into a silent unresolved list rather than a personal identity read.

group-a is a manager workspace carrying four identities: a fully editable one whose
stored secret proves masking survives a rename, a withheld one whose empty
`identity_actions` hides edit and delete beside the editable control, a File Sync
identity the action editor's action-usage filter excludes, and one still referenced
by an action so a delete returns the in-use 409 with its references. group-b is an
ordinary member: identities are manager-only, so its section is unavailable and its
identity routes answer 403. Writes carry `expected_etag` in the JSON body like the
group prompt editor, secrets stay masked server-side, and every returned identity
identifies the requested group exactly as the reader validates.
"""

import pytest

from ui_tests.fixtures.group_workspace import (  # noqa: F401
    GroupWorkspaceFixture, group_identity,
)


EDITABLE_IDENTITY_ID = "group-a-editable-identity"
WITHHELD_IDENTITY_ID = "group-a-withheld-identity"
FILE_SYNC_IDENTITY_ID = "group-a-file-sync-identity"
IN_USE_IDENTITY_ID = "group-a-in-use-identity"
CONNECTOR_ACTION_ID = "group-a-connector"


class GroupIdentitiesFixture(GroupWorkspaceFixture):
    """A small scripted identity boundary; no second identity service, no live Key Vault."""

    def __init__(self, page):
        super().__init__(page)
        self.active_group = "group-a"
        # group-a: a manager workspace. Recomputing the context from the same Owner policy carries the
        # full identity_management hint, exactly like the agent fixture recomputes its agent policy.
        self.set_identity_policy("group-a", role="Owner", status="active")
        self._seed_identities("group-a", [
            # Fully editable: an inline stored secret proves a rename keeps it masked, and its
            # identity_actions carry edit and delete so a manager reaches every control.
            group_identity("group-a", EDITABLE_IDENTITY_ID, "Reporting service account",
                           usage=("action",), auth_type="api_key", secret_stored=True),
            # Withheld: the workspace advertises the operations, but this row's empty identity_actions
            # hide its edit and delete beside the editable control. This is an explicit defensive
            # case -- the server does not emit an empty projection for a manager's own group identity
            # today -- kept so the per-row gate is proven, not merely the workspace-level hint.
            group_identity("group-a", WITHHELD_IDENTITY_ID, "Locked platform credential",
                           usage=("action",), auth_type="api_key", secret_stored=True, actions=()),
            # File Sync usage only: the Identities section lists it, but the action editor's
            # action-usage filter excludes it, proving the editor offers action identities alone.
            group_identity("group-a", FILE_SYNC_IDENTITY_ID, "Archive file share",
                           usage=("file_sync",), auth_type="username_password", secret_stored=True,
                           username="svc-archive", domain="CORP"),
            # Still referenced by the seeded connector action, so a delete is refused with the in-use
            # 409 and its references, and nothing is removed.
            group_identity("group-a", IN_USE_IDENTITY_ID, "Bound integration credential",
                           usage=("action",), auth_type="api_key", secret_stored=True),
        ])
        self.identity_references[("group-a", IN_USE_IDENTITY_ID)] = [
            {"kind": "action", "id": CONNECTOR_ACTION_ID, "name": "Shared connector"},
        ]
        # group-b: an ordinary member. Identities are manager-only, so the section is unavailable and
        # every identity route answers 403. The base already seeds one identity for it and models the
        # member role; the seeded row is never served, which is exactly the M4-gap silent path the
        # action editor must take rather than reading a personal identity.
        self.set_identity_policy("group-b", role="User", status="active")


@pytest.fixture
def group_identities_ui(page):
    fixture = GroupIdentitiesFixture(page)
    yield fixture
    fixture.assert_clean()
