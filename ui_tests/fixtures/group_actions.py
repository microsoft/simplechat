# group_actions.py
"""
Closed M4 group action HTTP fixtures for the real production V2 SPA.
Version: 0.261.137
Implemented in: 0.261.137

The fixture serves the immutable `/api/groups/<group_id>/actions[...]` family and
the `/actions/types` catalogue, and injects the `action_management` context hint
that gates create, edit, delete and test. It never permits personal
`/api/user/plugins` writes and never falls back to personal behaviour: an
`action_management` block is always present for a shipped backend, but a member's
block advertises no operations, so the workbench renders read-only. Every
returned action identifies the requested group exactly as the reader validates,
stored credentials stay masked on the server side, and writes carry
`expected_revision`, `clear_secret_paths` and `removed_paths` like the personal
editor. Group actions have no cross-scope identities and no personal favourites.
"""

import copy
from datetime import datetime, timezone

import pytest

from ui_tests.fixtures.group_workspace import (
    GroupWorkspaceFixture, connect_options, group_context,  # noqa: F401
)
from ui_tests.fixtures.workspace_authoring import (
    SECRET_MASK, EditorSecretError, _editor_candidate, _set_pointer, action_record,
)


ACTION_OPERATIONS = ("create", "edit", "delete", "test")
ACTION_ACTIONS = ("edit", "delete", "test")
WRITER_ROLES = ("Owner", "Admin")

EDITABLE_ACTION_ID = "group-a-openapi"
WITHHELD_ACTION_ID = "group-a-withheld"
MEMBER_ACTION_ID = "group-b-openapi"
IDENTITY_ACTION_ID = "group-a-identity"
PROVIDED_ACTION_ID = "global-shared-api"
BOUND_IDENTITY_ID = "group-identity-legacy"


def group_action(group_id, identifier, name, *, actions=ACTION_ACTIONS, **overrides):
    """One shared OpenAPI action as the group projector returns it before masking."""
    record = action_record(
        identifier,
        name=name.lower().replace(" ", "-"),
        displayName=name,
        description=f"Shared connector for {name}.",
    )
    record.pop("user_id", None)
    record.update({
        "group_id": group_id,
        "is_group": True,
        "is_global": False,
        "action_actions": list(actions),
    })
    record.update(copy.deepcopy(overrides))
    return record


def action_management(role, status):
    """The management hint. A shipped backend always sends it; a member gets no operations."""
    if role in WRITER_ROLES and status == "active":
        return {"schema_version": 1, "operations": list(ACTION_OPERATIONS)}
    return {"schema_version": 1, "operations": []}


class GroupActionsFixture(GroupWorkspaceFixture):
    """A small scripted action boundary; no second plugin service, no live Key Vault."""

    def __init__(self, page):
        super().__init__(page)
        self.active_group = "group-a"
        self.created_counter = 0
        # Per (group, action) mutable server state kept apart from the legacy group_actions store.
        self.native_actions = {}
        self.native_secret_paths = {}
        self.native_revisions = {}
        # group-a: a manager workspace. The OpenAPI action is fully editable; the withheld action
        # keeps an empty inline `action_actions` while the workspace advertises the operations, so
        # its edit, delete and test affordances stay hidden beside the editable control.
        self.set_action_policy("group-a", role="Owner", status="active")
        # A provided (global) action merged into the group list read-only. It carries is_global with
        # an empty inline action_actions and no owning group_id, so no edit, delete or test is offered
        # and the group read route still answers for it.
        provided_action = group_action("group-a", PROVIDED_ACTION_ID, "Shared platform API",
                                       actions=(), is_global=True, is_group=False)
        provided_action["group_id"] = None
        self._seed("group-a", [
            group_action("group-a", EDITABLE_ACTION_ID, "Weekly report API"),
            group_action("group-a", WITHHELD_ACTION_ID, "Withheld API", actions=()),
            # A V1-era action bound to a group identity. No reusable group identity route exists yet
            # (M5A), so the editor keeps the binding with neutral copy and lists no identities.
            group_action("group-a", IDENTITY_ACTION_ID, "Bound report API",
                         identity_id=BOUND_IDENTITY_ID, auth={"type": "identity"}),
            provided_action,
        ])
        # group-b: an ordinary member. Actions are readable but the management hint offers no
        # operations, so the workbench is read-only: no create, edit, delete or test affordances.
        self.set_action_policy("group-b", role="User", status="active")
        self._seed("group-b", [
            group_action("group-b", MEMBER_ACTION_ID, "Team charter API", actions=()),
        ])
        # group-c: group agents are on but group actions are off. Navigation still surfaces the
        # Actions slot through native_delegation, so the pre-M4 Call agent view must render and no
        # /api/groups/group-c/actions request may be made.
        delegation_only = group_context("group-c", "Delegation only workspace", role="Owner", status="active")
        delegation_only["sections"]["actions"]["enabled"] = False
        delegation_only["sections"]["actions"]["can_manage"] = False
        delegation_only["sections"]["actions"]["reason"] = "Group actions are turned off for this workspace."
        self.groups["group-c"] = delegation_only
        # group-c is added after the parent seeded its per-group delegation stores, so mirror that
        # seeding here: the Call agent view reads the group's caller agent when actions are off.
        self.group_agents["group-c"] = [{
            "id": "caller", "name": "caller", "display_name": "Local caller",
            "agent_type": "local", "group_id": "group-c", "is_group": True,
            "actions_to_load": ["legacy-name"], "other_settings": {},
        }]
        self.group_actions["group-c"] = []
        self.workflows["group-c"] = []

    def set_action_policy(self, group_id, *, role=None, status="active"):
        """Recompute a group's context with an action_management hint for the role and status."""
        current = self.groups.get(group_id)
        name = current["workspace"]["name"] if current else f"{group_id} workspace"
        role = role or (current["role"] if current else "Owner")
        context = group_context(group_id, name, role=role, status=status)
        context["action_management"] = copy.deepcopy(action_management(role, status))
        self.groups[group_id] = context
        return context

    def _seed(self, group_id, records):
        rows = []
        for record in records:
            identifier = record["id"]
            rows.append(record)
            # Only actions carrying an inline credential register a secret path; an identity-bound
            # or provided action has none, so the projector must not mask a path it never stored.
            paths = ["/auth/key"] if record.get("auth", {}).get("key") else []
            self.native_secret_paths[(group_id, identifier)] = paths
            self.native_revisions[(group_id, identifier)] = 1
        self.native_actions[group_id] = rows

    def record(self, group_id, identifier):
        return next((row for row in self.native_actions.get(group_id, []) if row["id"] == identifier), None)

    def _action_revision(self, group_id, identifier):
        return f"group-rev:{group_id}:{identifier}:{self.native_revisions[(group_id, identifier)]}"

    def touch_action(self, group_id, identifier):
        """Simulate a concurrent edit by another manager: the stored revision moves on."""
        self.native_revisions[(group_id, identifier)] += 1
        return self._action_revision(group_id, identifier)

    def _project_action(self, group_id, record):
        result = copy.deepcopy(record)
        for pointer in self.native_secret_paths.get((group_id, record["id"]), []):
            _set_pointer(result, pointer, SECRET_MASK)
        return result

    def _action_envelope(self, group_id, record):
        actions = record.get("action_actions") or []
        read_only = bool(record.get("is_global")) or "edit" not in actions
        return {
            "record": self._project_action(group_id, record),
            "revision": self._action_revision(group_id, record["id"]),
            "secret_paths": copy.deepcopy(self.native_secret_paths.get((group_id, record["id"]), [])),
            "read_only": read_only,
        }

    def _dispatch(self, route, entry):
        path = entry.path
        if path.startswith("/api/groups/") and "/actions" in path:
            self._actions(route, entry)
            return
        super()._dispatch(route, entry)

    def _actions(self, route, entry):
        parts = entry.path.split("/")
        # /api/groups/<group_id>/actions[/types|/<action_id>]
        group_id = parts[3]
        tail = parts[5] if len(parts) > 5 else None
        method = entry.method
        assert group_id in self.groups, f"Unknown group action scope: {entry}"
        if group_id in self.denied_groups:
            self._json(route, {"error": "You do not have access to this group's actions."}, 403)
            return
        management = self.groups[group_id].get("action_management", {})
        operations = set(management.get("operations", []))
        # Every native group action route rejects unexpected query parameters with a 400, mirroring
        # the server's _reject_query_parameters(); the frontend therefore sends none. Answering 400
        # here means a regression to ?view=editor fails a test instead of silently passing.
        if entry.query:
            self._json(route, {"error": "This endpoint does not accept query parameters."}, 400)
            return
        if tail == "types":
            # The enriched editor catalogue is a read capability served to every member role, in a
            # {"types": [...]} envelope, exactly as the personal ?view=editor branch returns it.
            assert method == "GET", entry
            self._json(route, {"types": copy.deepcopy(self.types)})
            return
        if tail is None:
            if method == "GET":
                self._json(route, {"actions": [
                    self._project_action(group_id, row) for row in self.native_actions.get(group_id, [])
                ]})
                return
            if method == "POST":
                assert "create" in operations, f"Create reached a workspace without the hint: {entry}"
                self._create(route, entry, group_id)
                return
        else:
            record = self.record(group_id, tail)
            if record is None:
                self._json(route, {"error": "Action not found in this group."}, 404)
                return
            if method == "GET":
                self._json(route, self._action_envelope(group_id, record))
                return
            if method == "PATCH":
                self._patch(route, entry, group_id, tail, record, operations)
                return
            if method == "DELETE":
                assert "delete" in operations and "delete" in (record.get("action_actions") or []), (
                    f"Delete reached a read-only action: {entry}"
                )
                assert entry.body is None, "A group action delete carries no body."
                self.native_actions[group_id] = [
                    row for row in self.native_actions[group_id] if row["id"] != tail
                ]
                self._json(route, {"success": True})
                return
        self.unexpected_requests.append(f"{method} {entry.path}")
        self._json(route, {"error": "Unexpected group action request."}, 500)

    def _create(self, route, entry, group_id):
        assert isinstance(entry.body, dict) and set(entry.body) == {
            "updates", "clear_secret_paths", "removed_paths",
        }, entry
        updates = entry.body["updates"]
        assert isinstance(updates, dict) and "id" not in updates, entry
        assert not {"user_id", "is_global", "is_group", "group_id", "revision", "secret_paths"} & set(updates)
        # action_actions is a read projection the schema does not accept; it must never be echoed
        # into a write, in updates or as a removed path.
        assert "action_actions" not in updates, "action_actions is projection-only; it must not be sent in updates."
        assert "/action_actions" not in entry.body["removed_paths"], "action_actions must not appear in removed_paths."
        self.created_counter += 1
        identifier = f"group-created-{self.created_counter}"
        base = {"id": identifier, "group_id": group_id, "is_group": True, "is_global": False,
                "action_actions": list(ACTION_ACTIONS)}
        try:
            record = _editor_candidate(base, updates, [], entry.body["clear_secret_paths"], entry.body["removed_paths"])
        except EditorSecretError:
            self._json(route, {"error": "Stored credentials must be kept, replaced, or explicitly cleared."}, 400)
            return
        paths = []
        if record.get("auth", {}).get("key"):
            paths.append("/auth/key")
        self.native_actions.setdefault(group_id, []).insert(0, record)
        self.native_secret_paths[(group_id, identifier)] = paths
        self.native_revisions[(group_id, identifier)] = 1
        record["created_at"] = datetime.now(timezone.utc).isoformat()
        self._json(route, self._action_envelope(group_id, record), 201)

    def _patch(self, route, entry, group_id, identifier, record, operations):
        assert "edit" in operations and "edit" in (record.get("action_actions") or []), (
            f"Edit reached a read-only action: {entry}"
        )
        assert isinstance(entry.body, dict) and set(entry.body) == {
            "updates", "expected_revision", "clear_secret_paths", "removed_paths",
        }, entry
        updates = entry.body["updates"]
        assert isinstance(updates, dict) and "id" not in updates, entry
        assert not {"user_id", "is_global", "is_group", "group_id", "revision", "secret_paths"} & set(updates)
        assert "action_actions" not in updates, "action_actions is projection-only; it must not be sent in updates."
        assert "/action_actions" not in entry.body["removed_paths"], "action_actions must not appear in removed_paths."
        if entry.body["expected_revision"] != self._action_revision(group_id, identifier):
            self._json(route, {"error": "This action changed in another session. Reload before saving."}, 409)
            return
        paths = self.native_secret_paths.get((group_id, identifier), [])
        try:
            candidate = _editor_candidate(
                record, updates, paths, entry.body["clear_secret_paths"], entry.body["removed_paths"],
            )
        except EditorSecretError:
            self._json(route, {
                "error": "Stored credentials must be kept at their original paths, replaced, or explicitly cleared.",
            }, 400)
            return
        self.native_secret_paths[(group_id, identifier)] = [
            pointer for pointer in paths if pointer not in entry.body["clear_secret_paths"]
        ]
        if candidate.get("auth", {}).get("key"):
            kept = self.native_secret_paths.setdefault((group_id, identifier), [])
            if "/auth/key" not in kept:
                kept.append("/auth/key")
        index = next(i for i, row in enumerate(self.native_actions[group_id]) if row["id"] == identifier)
        self.native_actions[group_id][index] = candidate
        self.native_revisions[(group_id, identifier)] += 1
        self._json(route, self._action_envelope(group_id, candidate))


@pytest.fixture
def group_actions_ui(page):
    fixture = GroupActionsFixture(page)
    yield fixture
    fixture.assert_clean()
