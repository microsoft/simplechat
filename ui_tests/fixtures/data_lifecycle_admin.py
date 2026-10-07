# data_lifecycle_admin.py
"""
Closed V2 fixture for the Admin Settings Data Lifecycle group.
Version: 0.261.272
Implemented in: 0.261.272

Serves the real built SPA with the real Data Lifecycle field schema and the real settings
normalizer, and answers the three retention routes the controls call from memory: Run
now, Force push, and the schedule readout. No application server, signed-in account or
live settings are touched, and an unexpected request fails the test.

Each route can be made to fail or to hold its answer, which is how the tests reach the
timeout and server-error states without waiting on a real retention run.
"""

import copy
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from v2_admin_settings import ORIGIN, AdminSettingsFixture, import_app_module


DATA_LIFECYCLE_SECTIONS = {
    "data-lifecycle": (
        "retention-policy-section",
        "document-classification-section",
        "conversation-archiving-section",
    ),
}

# Raw exception text a failing route can return. The UI must never show it.
SERVER_EXCEPTION_TEXT = "Failed to execute retention policy: KeyError('cosmos-secret-detail')"

_DELIBERATE_FAILURE_RE = re.compile(
    r"Failed to load resource: the server responded with a status of (400|500|504) \([^)]*\)"
)


class DataLifecycleAdminFixture(AdminSettingsFixture):
    """The Data Lifecycle sections, with retention switched on for two workspace types."""

    def __init__(self, page):
        super().__init__(page, validate_updates=True, sections=DATA_LIFECYCLE_SECTIONS)
        self.fields = import_app_module("admin_settings_fields")
        # The base fixture seeds the Agents switch for its own sections. Outside them it is
        # an undeclared enable_* key, which the fallback scan would draw as a stray row.
        self.settings.pop("enable_semantic_kernel", None)
        now = datetime.now(timezone.utc)
        self.settings.update({
            "enable_retention_policy_personal": True,
            "enable_retention_policy_group": True,
            "enable_retention_policy_public": False,
            "default_retention_conversation_personal": "none",
            "default_retention_document_personal": "none",
            "default_retention_conversation_group": "90",
            "default_retention_document_group": "365",
            "retention_policy_execution_hour": 2,
            "retention_policy_last_run": (now - timedelta(days=1)).isoformat(),
            "retention_policy_next_run": self.fields.compute_retention_next_run(2, now),
            "enable_document_classification": True,
            "enable_conversation_archiving": True,
        })
        self.executions = []
        self.force_pushes = []
        self.schedule_reads = 0
        self.execute_status = 200
        self.force_push_status = 200
        self.run_counts = {
            "personal": {"conversations": 4, "documents": 2, "users_affected": 3},
            "group": {"conversations": 1, "documents": 0, "workspaces_affected": 1},
            "public": {"conversations": 0, "documents": 0, "workspaces_affected": 0},
        }
        self.push_counts = {"personal": 120, "group": 2, "public": 0}
        self.deliberate_failures = False

    def _route(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        if f"{parsed.scheme}://{parsed.netloc}" == ORIGIN:
            if parsed.path == "/api/admin/retention-policy/execute" and request.method == "POST":
                self._execute(route)
                return
            if parsed.path == "/api/admin/retention-policy/force-push" and request.method == "POST":
                self._force_push(route)
                return
            if parsed.path == "/api/admin/retention-policy/settings" and request.method == "GET":
                self.schedule_reads += 1
                route.fulfill(json={
                    "success": True,
                    "settings": {
                        "retention_policy_last_run": self.settings.get("retention_policy_last_run"),
                        "retention_policy_next_run": self.settings.get("retention_policy_next_run"),
                    },
                })
                return
            if parsed.path == "/api/v2/admin/settings" and request.method == "PATCH":
                # The real normalizer refuses bad categories with a 400, which is expected.
                self.deliberate_failures = True
        super()._route(route)

    def _execute(self, route):
        body = route.request.post_data_json
        self.executions.append(copy.deepcopy(body))
        if self.execute_status == 504:
            self.deliberate_failures = True
            route.fulfill(status=504, body="Gateway Timeout", content_type="text/plain")
            return
        if self.execute_status != 200:
            self.deliberate_failures = True
            route.fulfill(status=self.execute_status, json={"success": False, "error": SERVER_EXCEPTION_TEXT})
            return

        scopes = list(body.get("scopes") or [])
        now = datetime.now(timezone.utc)
        hour = self.settings.get("retention_policy_execution_hour", 2)
        self.settings["retention_policy_last_run"] = now.isoformat()
        self.settings["retention_policy_next_run"] = self.fields.compute_retention_next_run(hour, now)
        results = {
            "success": True,
            "execution_time": now.isoformat(),
            "manual_execution": True,
            "scopes_processed": scopes,
            "errors": [],
        }
        for scope in ("personal", "group", "public"):
            results[scope] = copy.deepcopy(self.run_counts[scope]) if scope in scopes else {
                "conversations": 0,
                "documents": 0,
                "users_affected" if scope == "personal" else "workspaces_affected": 0,
            }
        route.fulfill(json={
            "success": True,
            "message": "Retention policy executed successfully",
            "results": results,
        })

    def _force_push(self, route):
        body = route.request.post_data_json
        self.force_pushes.append(copy.deepcopy(body))
        if self.force_push_status != 200:
            self.deliberate_failures = True
            route.fulfill(status=self.force_push_status, json={"success": False, "error": SERVER_EXCEPTION_TEXT})
            return
        scopes = list(body.get("scopes") or [])
        details = {scope: self.push_counts[scope] for scope in scopes}
        route.fulfill(json={
            "success": True,
            "message": f"Defaults pushed to {sum(details.values())} items",
            "updated_count": sum(details.values()),
            "scopes": scopes,
            "details": details,
        })

    def open_data_lifecycle(self, **kwargs):
        self.open(ready_region="Retention Policy", **kwargs)

    def assert_clean(self):
        if self.deliberate_failures:
            # The browser logs every non-2xx response; the ones a test served on purpose
            # are not defects.
            self.errors = [error for error in self.errors if not _DELIBERATE_FAILURE_RE.fullmatch(error)]
        super().assert_clean()
