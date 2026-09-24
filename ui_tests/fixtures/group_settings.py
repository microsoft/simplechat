# group_settings.py
"""
Test-arrangement fixture for the native V2 group Settings, Activity and Statistics sections (M7C).

Version: 0.261.165
Implemented in: 0.261.157

The HTTP serving for the native `/api/groups/<g>/settings[/logo]` and `/api/groups/<g>/insights/*`
families lives in `GroupWorkspaceFixture`, which models the server's settings policy and insight
routes with their exact messages. This subclass adds only the thin arrangement layer the browser
suite needs: a `configure` that rebuilds one group's context for a role, status and capability
flags so its `settings_management` hint and the handlers' refusals agree, plus scriptable stores
for the activity feed, statistics figures, file count and the one-shot write conflicts. A page that
read a personal or classic route, invented a control the hints withhold, or kept an optimistic draft
would fail the run rather than pass, exactly as it does for the other section fixtures.
"""

import pytest

from ui_tests.fixtures.group_workspace import (  # noqa: F401
    ALLOWED_STATS_WINDOW_DAYS as ALLOWED_STATS_WINDOW_DAYS,
    DEFAULT_STATS_WINDOW_DAYS as DEFAULT_STATS_WINDOW_DAYS,
    GROUP_ACTIVITY_DEFAULT_LIMIT as GROUP_ACTIVITY_DEFAULT_LIMIT,
    GROUP_ACTIVITY_LIMITS as GROUP_ACTIVITY_LIMITS,
    GROUP_ACTIVITY_UNAVAILABLE_MESSAGE as GROUP_ACTIVITY_UNAVAILABLE_MESSAGE,
    GROUP_MANAGER_REQUIRED as GROUP_MANAGER_REQUIRED,
    GROUP_OWNER_REQUIRED as GROUP_OWNER_REQUIRED,
    GROUP_SETTINGS_CHANGED_MESSAGE as GROUP_SETTINGS_CHANGED_MESSAGE,
    GROUP_SETTINGS_REFUSAL_MESSAGES as GROUP_SETTINGS_REFUSAL_MESSAGES,
    GROUP_STATS_UNAVAILABLE_MESSAGE as GROUP_STATS_UNAVAILABLE_MESSAGE,
    GROUP_WRITE_CONFLICT_MESSAGE as GROUP_WRITE_CONFLICT_MESSAGE,
    NO_GROUP_LOGO_MESSAGE as NO_GROUP_LOGO_MESSAGE,
    GroupWorkspaceFixture, _settings_kwargs, group_context,
)
from ui_tests.fixtures.workspace_authoring import ORIGIN as ORIGIN, OWNER_ID as OWNER_ID  # noqa: F401

_EXPORTED_FIXTURE_CONSTANTS = (
    ALLOWED_STATS_WINDOW_DAYS,
    DEFAULT_STATS_WINDOW_DAYS,
    GROUP_ACTIVITY_DEFAULT_LIMIT,
    GROUP_ACTIVITY_LIMITS,
    GROUP_ACTIVITY_UNAVAILABLE_MESSAGE,
    GROUP_MANAGER_REQUIRED,
    GROUP_OWNER_REQUIRED,
    GROUP_SETTINGS_CHANGED_MESSAGE,
    GROUP_SETTINGS_REFUSAL_MESSAGES,
    GROUP_STATS_UNAVAILABLE_MESSAGE,
    GROUP_WRITE_CONFLICT_MESSAGE,
    NO_GROUP_LOGO_MESSAGE,
    ORIGIN,
    OWNER_ID,
)


class GroupSettingsFixture(GroupWorkspaceFixture):
    """A scripted group settings boundary reusing the shell fixture's settings and insight routes."""

    def __init__(self, page):
        super().__init__(page)
        # The Settings suite models a deployment with group downloads and retention both on, so the
        # Downloads and Retention cards render unless a test turns one off. The base fixture keeps
        # retention off (the deployment the context parity test pins), so group-a opts in here.
        self.configure("group-a", role="Owner", status="active")
        self.active_group = "group-a"

    # --- state a test arranges -------------------------------------------------------------

    def configure(self, group_id="group-a", *, role="Owner", status="active", **flags):
        """Rebuild a group's context for `role`, `status` and capability `flags`.

        The handlers derive every refusal from the same flags through `group_settings_flags_by_id`,
        so both the context's `settings_management` hint and the routes' answers stay in step. This
        suite's deployment has group downloads and retention on, so both default on and a test turns
        just the one it is proving off.
        """
        name = self.groups[group_id]["workspace"]["name"] if group_id in self.groups else "Research group"
        resolved = {"downloads_admin": True, "retention_enabled": True, **flags}
        self.group_settings_flags_by_id[group_id] = dict(resolved)
        self.groups[group_id] = group_context(
            group_id, name, role=role, status=status, viewer=self.viewer_id,
            **_settings_kwargs(resolved),
        )
        if group_id not in self.native_group_settings:
            self._seed_group_settings(group_id)
        self.active_group = group_id
        return self.groups[group_id]

    def set_logo_present(self, group_id="group-a", *, version=1):
        """Give a group a logo before the page loads, so Replace and Remove are exercised."""
        store = self.native_group_settings[group_id]
        store["has_logo"] = True
        store["logo_version"] = max(1, version)
        self._sync_profile_context(group_id)

    def set_activity(self, group_id, items):
        self.group_activity[group_id] = items

    def clear_activity(self, group_id="group-a"):
        self.group_activity[group_id] = []

    def make_activity_unavailable(self, group_id="group-a"):
        self.activity_unavailable.add(group_id)

    def set_stats(self, group_id, figures):
        self.group_stats[group_id] = figures

    def make_stats_unavailable(self, group_id="group-a"):
        self.stats_unavailable.add(group_id)

    def set_file_count(self, group_id, count):
        self.group_file_count[group_id] = count

    def force_settings_changed(self, group_id="group-a"):
        """Answer the next write with the 409 `group_settings_changed` and move the revision on."""
        self.settings_force_changed.add(group_id)

    def force_write_conflict(self, group_id="group-a"):
        """Answer the next write with the plain-retry 409 `group_write_conflict`."""
        self.settings_force_write_conflict.add(group_id)

    def next_write_error(self, message):
        """Refuse the next write with a reviewed 400 carrying `message`."""
        self.next_settings_write_error = message

    def settings_requests(self, method=None):
        return [
            entry for entry in self.requests
            if "/settings" in entry.path and entry.path.startswith("/api/groups/")
            and (method is None or entry.method == method)
        ]

    def insight_requests(self, name, method="GET"):
        return [
            entry for entry in self.requests
            if entry.path.startswith("/api/groups/") and f"/insights/{name}" in entry.path
            and entry.method == method
        ]


@pytest.fixture
def group_settings_ui(page):
    fixture = GroupSettingsFixture(page)
    yield fixture
    fixture.assert_clean()
