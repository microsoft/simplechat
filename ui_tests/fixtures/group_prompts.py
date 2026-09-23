# group_prompts.py
"""
Closed M3 group prompt HTTP fixtures for the real production V2 SPA.
Version: 0.261.136
Implemented in: 0.261.136

The fixture serves the immutable `/api/groups/<group_id>/prompts[...]` family and
injects the `prompt_management` context hint that gates create, edit and delete.
It never permits personal `/api/prompts` writes and never falls back to personal
behaviour: an absent hint yields a read-only workbench. Group prompts have no
per-user favourite, so `is_favorite` is neither stored nor accepted, and every
returned prompt identifies the requested group exactly as the reader validates.
"""

import copy
from datetime import datetime, timezone

import pytest

from ui_tests.fixtures.group_workspace import (
    GroupWorkspaceFixture, connect_options, group_context,  # noqa: F401
)


PROMPT_OPERATIONS = ("create", "edit", "delete")
PROMPT_ACTIONS = ("edit", "delete")
WRITER_ROLES = ("Owner", "Admin", "DocumentManager")


def group_prompt(group_id, identifier, name, *, content, actions=PROMPT_ACTIONS, **overrides):
    """One shared prompt as the group projector returns it, carrying its own etag."""
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "id": identifier,
        "name": name,
        "content": content,
        "description": f"Shared wording for {name}.",
        "group_id": group_id,
        "etag": f'"etag-{identifier}-0"',
        "prompt_actions": list(actions),
        "created_at": now,
        "updated_at": now,
    }
    record.update(copy.deepcopy(overrides))
    return record


def prompt_management(role, status):
    """The management hint, present only for a writer in an active workspace."""
    if role in WRITER_ROLES and status == "active":
        return {"schema_version": 1, "operations": list(PROMPT_OPERATIONS)}
    return None


class GroupPromptsFixture(GroupWorkspaceFixture):
    """A small scripted prompt boundary; no second prompt app, no live service."""

    def __init__(self, page):
        super().__init__(page)
        self.active_group = "group-a"
        self.etag_counter = {}
        self.created_counter = 0
        self.prompts = {}
        # group-a: a manager workspace. p1 is fully editable; the withheld prompt keeps an
        # empty inline `prompt_actions` while the workspace still advertises the operations,
        # so its edit and delete affordances must stay hidden beside the editable control.
        self.set_prompt_policy("group-a", role="Owner", status="active")
        self.prompts["group-a"] = [
            group_prompt(
                "group-a", "weekly-status", "Weekly status",
                content="Summarise this week's progress for the team as five bullet points.",
            ),
            group_prompt(
                "group-a", "withheld-template", "Withheld template",
                content="A shared template the server has locked from this member's edits.",
                actions=(),
            ),
        ]
        # group-b: an ordinary member. Prompts are readable but no management hint is present,
        # so the workbench is read-only: no create, edit, delete, or favourite affordances.
        self.set_prompt_policy("group-b", role="User", status="active")
        self.prompts["group-b"] = [
            group_prompt(
                "group-b", "team-charter", "Team charter",
                content="Draft a short charter for a new working group.",
                actions=(),
            ),
        ]

    def set_prompt_policy(self, group_id, *, role=None, status="active"):
        """Recompute a group's context with a prompt management hint for the role and status."""
        current = self.groups.get(group_id)
        name = current["workspace"]["name"] if current else f"{group_id} workspace"
        role = role or (current["role"] if current else "Owner")
        context = group_context(group_id, name, role=role, status=status)
        hint = prompt_management(role, status)
        if hint is not None:
            context["prompt_management"] = copy.deepcopy(hint)
        self.groups[group_id] = context
        return context

    def touch_prompt(self, group_id, identifier):
        """Simulate a concurrent edit by another member: the stored etag moves on."""
        record = self.record(group_id, identifier)
        self.etag_counter[identifier] = self.etag_counter.get(identifier, 0) + 1
        record["etag"] = f'"etag-{identifier}-{self.etag_counter[identifier]}"'
        return record["etag"]

    def record(self, group_id, identifier):
        return next(row for row in self.prompts[group_id] if row["id"] == identifier)

    def catalog_prompts(self):
        """Group prompts as the chat composer catalog carries them, with explicit scope."""
        catalog = []
        for group_id, rows in self.prompts.items():
            scope_name = self.groups[group_id]["workspace"]["name"]
            for row in rows:
                catalog.append({
                    "id": row["id"], "name": row["name"], "content": row["content"],
                    "description": row["description"], "scope_type": "group",
                    "scope_id": group_id, "scope_name": scope_name,
                })
        return catalog

    def _bootstrap(self):
        payload = super()._bootstrap()
        payload["version"] = "0.261.136"
        payload["catalogs"]["prompts"] = self.catalog_prompts()
        return payload

    def _dispatch(self, route, entry):
        path, method = entry.path, entry.method
        if path.startswith("/api/groups/") and "/prompts" in path:
            self._prompts(route, entry)
            return
        if path == "/api/v2/orchestration/runs" and method == "GET":
            self._json(route, {"runs": []})
            return
        super()._dispatch(route, entry)

    def _prompts(self, route, entry):
        parts = entry.path.split("/")
        # /api/groups/<group_id>/prompts[/<prompt_id>]
        group_id = parts[3]
        identifier = parts[5] if len(parts) > 5 else None
        method = entry.method
        assert group_id in self.groups, f"Unknown group prompt scope: {entry}"
        if group_id in self.denied_groups:
            self._json(route, {"error": "You do not have access to this group's prompts."}, 403)
            return
        writable = "prompt_management" in self.groups[group_id]
        if identifier is None:
            if method == "GET":
                assert set(entry.query) <= {"page", "page_size", "search"}, entry
                self._json(route, {
                    "prompts": copy.deepcopy(self.prompts.get(group_id, [])),
                    "page": int(entry.query.get("page", ["1"])[0]),
                    "page_size": int(entry.query.get("page_size", ["500"])[0]),
                    "total_count": len(self.prompts.get(group_id, [])),
                })
                return
            if method == "POST":
                assert writable, f"Create reached a read-only workspace: {entry}"
                assert set(entry.body) <= {"name", "content", "description"}, entry
                assert "is_favorite" not in entry.body, "Group prompts must not carry favourites."
                self.created_counter += 1
                new_id = f"group-created-{self.created_counter}"
                record = group_prompt(
                    group_id, new_id, entry.body["name"],
                    content=entry.body.get("content", ""),
                    description=entry.body.get("description", ""),
                )
                self.prompts.setdefault(group_id, []).insert(0, record)
                self._json(route, copy.deepcopy(record), 201)
                return
        else:
            record = next((row for row in self.prompts.get(group_id, []) if row["id"] == identifier), None)
            if record is None:
                self._json(route, {"error": "Prompt not found in this group."}, 404)
                return
            if method == "PATCH":
                assert writable, f"Edit reached a read-only workspace: {entry}"
                assert "expected_etag" in entry.body, "A conditional edit must carry expected_etag."
                assert "is_favorite" not in entry.body, "Group prompts must not carry favourites."
                if entry.body["expected_etag"] != record["etag"]:
                    self._json(route, {"error": "prompt_changed"}, 409)
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
                assert writable, f"Delete reached a read-only workspace: {entry}"
                assert isinstance(entry.body, dict) and "expected_etag" in entry.body, (
                    "A conditional delete must carry expected_etag in its JSON body."
                )
                if entry.body["expected_etag"] != record["etag"]:
                    self._json(route, {"error": "prompt_changed"}, 409)
                    return
                self.prompts[group_id] = [row for row in self.prompts[group_id] if row["id"] != identifier]
                self._json(route, {"success": True})
                return
        self.unexpected_requests.append(f"{method} {entry.path}")
        self._json(route, {"error": "Unexpected group prompt request."}, 500)


@pytest.fixture
def group_prompts_ui(page):
    fixture = GroupPromptsFixture(page)
    yield fixture
    fixture.assert_clean()
