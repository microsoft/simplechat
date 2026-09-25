# public_prompts.py
"""
Closed M9C public prompt HTTP fixtures for the real production V2 SPA.
Version: 0.261.178
Implemented in: 0.261.178

The fixture serves the immutable `/api/public-workspaces/<workspace_id>/prompts[...]` family,
gated by the `prompt_management` context hint the shared public context carries exactly as the
server sends it: present in every context, with create, edit and delete only for a manager
(Owner, Admin or DocumentManager) of an active workspace. It never permits personal `/api/prompts`
writes and never falls back to personal or group behaviour: a hint without operations yields a
read-only workbench. Public prompts have no per-user favourite, so `is_favorite` is neither stored
nor accepted, and every returned prompt identifies the requested workspace with `public_id`
exactly as the reader validates.
"""

import copy
from datetime import datetime, timezone

import pytest

from ui_tests.fixtures.public_workspace import (
    PublicWorkspaceFixture, connect_options, public_context,  # noqa: F401
)


PROMPT_ACTIONS = ("edit", "delete")

# The exact bodies the scoped public route returns, mirrored so the per-route parity pin
# (functional_tests/test_public_prompt_fixture_parity.py) holds. The conflict text and code are
# shared byte-for-byte with the group family; a fixture that invented `success` where the server
# sends `message`, or dropped the server's `error_code`, is the F1/F2 seam class this pin closes.
PROMPT_CONFLICT_BODY = {
    "error": "The prompt was changed by someone else. Refresh and try again.",
    "error_code": "prompt_changed",
}
PROMPT_DELETED_BODY = {"message": "Prompt deleted successfully."}


def public_prompt(workspace_id, identifier, name, *, content, actions=PROMPT_ACTIONS, **overrides):
    """One shared public prompt as the public projector returns it, carrying its own etag."""
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "id": identifier,
        "name": name,
        "content": content,
        "description": f"Shared wording for {name}.",
        "public_id": workspace_id,
        "etag": f'"etag-{identifier}-0"',
        "prompt_actions": list(actions),
        "created_at": now,
        "updated_at": now,
    }
    record.update(copy.deepcopy(overrides))
    return record


class PublicPromptsFixture(PublicWorkspaceFixture):
    """A small scripted public prompt boundary; no second prompt app, no live service."""

    def __init__(self, page):
        super().__init__(page)
        self.etag_counter = {}
        self.created_counter = 0
        self.prompts = {}
        self.deleted_prompt_conflicts = set()
        # Workspaces the chat composer catalog never carries, so a "Use in chat" link to one of
        # them misses the catalog and exercises R4a's scoped resolver fallback.
        self.hidden_from_chat_catalog = set()
        # pub-a: a manager workspace. weekly-status is fully editable; the withheld prompt keeps an
        # empty inline `prompt_actions` while the workspace still advertises the operations, so its
        # edit and delete affordances must stay hidden beside the editable control.
        self.set_prompt_policy("pub-a", name="Research library", role="Owner", status="active")
        self.prompts["pub-a"] = [
            public_prompt(
                "pub-a", "weekly-status", "Weekly status",
                content="Summarise this week's progress for the workspace as five bullet points.",
            ),
            public_prompt(
                "pub-a", "withheld-template", "Withheld template",
                content="A shared template the server has locked from this member's edits.",
                actions=(),
            ),
        ]
        # pub-b: an ordinary reader. Prompts are readable but the management hint offers no
        # operations, so the workbench is read-only: no create, edit, delete, or favourite affordances.
        self.set_prompt_policy("pub-b", name="Read-only library", role="User", status="active")
        self.prompts["pub-b"] = [
            public_prompt(
                "pub-b", "reading-guide", "Reading guide",
                content="Explain how to browse this workspace's published knowledge.",
                actions=(),
            ),
        ]
        # pub-hidden: a readable workspace kept out of the chat composer catalog (its owner hid it
        # from chat). A public "Use in chat" link still names it, so R4a's scoped resolver fetches
        # the one prompt by id and workspace -- reauthorized by role and status, never through the
        # visibility-filtered catalog -- and attaches it without writing catalog or visibility state.
        self.hidden_from_chat_catalog.add("pub-hidden")
        self.set_prompt_policy("pub-hidden", name="Field notes", role="User", status="active")
        self.prompts["pub-hidden"] = [
            public_prompt(
                "pub-hidden", "field-guide", "Field guide",
                content="Explain how to record careful observations during fieldwork.",
                actions=(),
            ),
        ]

    def set_prompt_policy(self, workspace_id, *, name=None, role=None, status="active"):
        """Recompute a workspace's context, whose prompt management hint is the server's for the role and status."""
        current = self.workspaces.get(workspace_id)
        name = name or (current["workspace"]["name"] if current else f"{workspace_id} workspace")
        role = role or (current["role"] if current else "Owner")
        context = public_context(workspace_id, name, role=role, status=status)
        self.workspaces[workspace_id] = context
        return context

    def touch_prompt(self, workspace_id, identifier):
        """Simulate a concurrent edit by another manager: the stored etag moves on."""
        record = self.record(workspace_id, identifier)
        self.etag_counter[identifier] = self.etag_counter.get(identifier, 0) + 1
        record["etag"] = f'"etag-{identifier}-{self.etag_counter[identifier]}"'
        return record["etag"]

    def record(self, workspace_id, identifier):
        return next(row for row in self.prompts[workspace_id] if row["id"] == identifier)

    def drop_prompt_for_conflict(self, workspace_id, identifier):
        """Remove a prompt while making the next stale save look like a conditional conflict."""
        self.prompts[workspace_id] = [row for row in self.prompts[workspace_id] if row["id"] != identifier]
        self.deleted_prompt_conflicts.add((workspace_id, identifier))

    def catalog_prompts(self):
        """Public prompts as the chat composer catalog carries them, with explicit scope."""
        catalog = []
        for workspace_id, rows in self.prompts.items():
            if workspace_id in self.hidden_from_chat_catalog:
                continue
            scope_name = self.workspaces[workspace_id]["workspace"]["name"]
            for row in rows:
                catalog.append({
                    "id": row["id"], "name": row["name"], "content": row["content"],
                    "description": row["description"], "scope_type": "public",
                    "scope_id": workspace_id, "scope_name": scope_name,
                })
        return catalog

    def _bootstrap(self):
        payload = super()._bootstrap()
        payload["catalogs"]["prompts"] = self.catalog_prompts()
        return payload

    def _dispatch(self, route, entry):
        path, method = entry.path, entry.method
        if path.startswith("/api/public-workspaces/") and "/prompts" in path:
            self._prompts(route, entry)
            return
        super()._dispatch(route, entry)

    def _prompts(self, route, entry):
        parts = entry.path.split("/")
        # /api/public-workspaces/<workspace_id>/prompts[/<prompt_id>]
        workspace_id = parts[3]
        identifier = parts[5] if len(parts) > 5 else None
        method = entry.method
        assert workspace_id in self.workspaces, f"Unknown public prompt scope: {entry}"
        # A readable status is a precondition for every prompt request; an unreadable status is a 403,
        # exactly as require_public_prompt_read_context refuses one.
        status = self.workspaces[workspace_id]["status"]
        if status not in ("active", "locked", "upload_disabled"):
            self._json(route, {"error": "Prompts are unavailable for this workspace's current status."}, 403)
            return
        # The hint is always present, so what a write may do is read from its operations.
        allowed = set(self.workspaces[workspace_id].get("prompt_management", {}).get("operations", ()))
        if identifier is None:
            if method == "GET":
                assert set(entry.query) <= {"page", "page_size", "search"}, entry
                self._json(route, {
                    "prompts": copy.deepcopy(self.prompts.get(workspace_id, [])),
                    "page": int(entry.query.get("page", ["1"])[0]),
                    "page_size": int(entry.query.get("page_size", ["500"])[0]),
                    "total_count": len(self.prompts.get(workspace_id, [])),
                })
                return
            if method == "POST":
                assert "create" in allowed, f"Create reached a read-only workspace: {entry}"
                assert set(entry.body) <= {"name", "content", "description"}, entry
                assert "is_favorite" not in entry.body, "Public prompts must not carry favourites."
                self.created_counter += 1
                new_id = f"public-created-{self.created_counter}"
                record = public_prompt(
                    workspace_id, new_id, entry.body["name"],
                    content=entry.body.get("content", ""),
                    description=entry.body.get("description", ""),
                )
                self.prompts.setdefault(workspace_id, []).insert(0, record)
                self._json(route, copy.deepcopy(record), 201)
                return
        else:
            record = next((row for row in self.prompts.get(workspace_id, []) if row["id"] == identifier), None)
            if record is None:
                if method == "PATCH" and (workspace_id, identifier) in self.deleted_prompt_conflicts:
                    self._json(route, copy.deepcopy(PROMPT_CONFLICT_BODY), 409)
                    return
                self._json(route, {"error": "Prompt not found or access denied."}, 404)
                return
            if method == "GET":
                self._json(route, copy.deepcopy(record))
                return
            if method == "PATCH":
                assert "edit" in allowed, f"Edit reached a read-only workspace: {entry}"
                assert "expected_etag" in entry.body, "A conditional edit must carry expected_etag."
                assert "is_favorite" not in entry.body, "Public prompts must not carry favourites."
                if entry.body["expected_etag"] != record["etag"]:
                    self._json(route, copy.deepcopy(PROMPT_CONFLICT_BODY), 409)
                    return
                self.etag_counter[identifier] = self.etag_counter.get(identifier, 0) + 1
                record["etag"] = f'"etag-{identifier}-{self.etag_counter[identifier]}"'
                for field in ("name", "content", "description"):
                    if field in entry.body:
                        record[field] = entry.body[field]
                record["updated_at"] = datetime.now(timezone.utc).isoformat()
                self._json(route, copy.deepcopy(record))
                return
            if method == "DELETE":
                assert "delete" in allowed, f"Delete reached a read-only workspace: {entry}"
                assert isinstance(entry.body, dict) and "expected_etag" in entry.body, (
                    "A conditional delete must carry expected_etag in its JSON body."
                )
                if entry.body["expected_etag"] != record["etag"]:
                    self._json(route, copy.deepcopy(PROMPT_CONFLICT_BODY), 409)
                    return
                self.prompts[workspace_id] = [row for row in self.prompts[workspace_id] if row["id"] != identifier]
                self._json(route, copy.deepcopy(PROMPT_DELETED_BODY))
                return
        self.unexpected_requests.append(f"{method} {entry.path}")
        self._json(route, {"error": "Unexpected public prompt request."}, 500)


@pytest.fixture
def public_prompts_ui(page):
    fixture = PublicPromptsFixture(page)
    yield fixture
    fixture.assert_clean()
