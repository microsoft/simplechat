# v2_admin_data_management.py
"""
In-memory Backup & Recovery API for the V2 Admin Settings browser tests.
Version: 0.261.260
Implemented in: 0.261.260

Serves the real built SPA through ``AdminSettingsFixture`` and answers every
``/api/admin/data-management/*`` call from memory, so the Backup & Recovery cards can be
exercised end to end with no application server, no Azure services and no live writes.
Every request is recorded in order, which is what lets a test prove that settings were
saved *before* a job was queued. Anything the stub does not recognise fails the test
through the base fixture's unexpected-request list.
"""

import copy
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from playwright.sync_api import Page, Route

sys.path.insert(0, str(Path(__file__).resolve().parent))

from v2_admin_settings import AdminSettingsFixture  # noqa: E402


REDACTED = "***REDACTED***"
API = "/api/admin/data-management"

# Every Backup & Recovery section, in navigation order.
BACKUP_RECOVERY_SECTIONS = {
    "backup-recovery": (
        "data-management-readiness-section",
        "data-management-backup-section",
        "data-management-schedule-section",
        "data-management-storage-section",
        "data-management-encryption-section",
        "data-management-migration-section",
        "data-management-backup-inventory-section",
        "data-management-cosmos-editor-section",
        "data-management-jobs-section",
    ),
}

# The keys the classic page saves, and therefore the only keys a save may send.
EDITABLE_KEYS = (
    "enabled", "full_backup_frequency", "scheduled_time_utc", "retention_value",
    "retention_unit", "retention_days", "partial_backups_enabled", "low_impact_mode",
    "include_cosmos", "include_ai_search", "include_source_blobs",
    "backup_storage_authentication_type", "backup_storage_blob_endpoint",
    "backup_storage_container_name", "backup_storage_connection_string",
    "backup_storage_path_prefix", "encryption_enabled", "backup_max_parallel_operations",
    "backup_retry_count", "backup_blob_max_parallel_operations", "backup_blob_chunk_size_mib",
    "backup_blob_retry_count", "backup_capacity_failure_policy",
    "backup_temporary_source_ru_enabled", "backup_temporary_source_ru",
    "target_cosmos_authentication_type", "target_cosmos_endpoint", "target_cosmos_database_name",
    "target_cosmos_key", "target_cosmos_subscription_id", "target_cosmos_resource_group",
    "target_ai_search_authentication_type", "target_ai_search_endpoint", "target_ai_search_key",
    "target_enhanced_citations_storage_authentication_type",
    "target_enhanced_citations_storage_blob_endpoint",
    "target_enhanced_citations_storage_connection_string", "migration_max_parallel_operations",
    "migration_retry_count", "migration_skip_recent_within_hours",
    "migration_temporary_destination_ru_enabled", "migration_temporary_destination_ru",
)

SECRET_KEYS = (
    "backup_storage_connection_string",
    "target_cosmos_key",
    "target_ai_search_key",
    "target_enhanced_citations_storage_connection_string",
)

# The public metadata the server returns with every Cosmos editor container, query and document.
COSMOS_CONTAINER = {
    "id": "user_settings", "name": "user_settings", "display_name": "User settings", "category": "users",
    "partition_key_path": "/user_id", "partition_key_field": "user_id", "max_page_size": 100,
    "empty_query_limit": 100, "editable": True,
}


def default_settings():
    """A configured deployment: storage, a Key Vault key and a destination are set."""
    return {
        "enabled": False,
        "full_backup_frequency": "weekly",
        "scheduled_time_utc": "03:00",
        "retention_value": 30,
        "retention_unit": "days",
        "retention_days": 30,
        "partial_backups_enabled": True,
        "low_impact_mode": True,
        "include_cosmos": True,
        "include_ai_search": True,
        "include_source_blobs": True,
        "backup_storage_authentication_type": "managed_identity",
        "backup_storage_blob_endpoint": "https://backups.blob.core.windows.net",
        "backup_storage_container_name": "simplechat-backups",
        "backup_storage_connection_string": "",
        "backup_storage_path_prefix": "simplechat-backups",
        "encryption_enabled": True,
        "encryption_key_reference": REDACTED,
        "encryption_key_storage": "key_vault",
        "backup_max_parallel_operations": 4,
        "backup_retry_count": 5,
        "backup_blob_max_parallel_operations": 4,
        "backup_blob_chunk_size_mib": 8,
        "backup_blob_retry_count": 5,
        "backup_capacity_failure_policy": "continue_without_boost",
        "backup_temporary_source_ru_enabled": False,
        "backup_temporary_source_ru": 10000,
        "target_cosmos_authentication_type": "key",
        "target_cosmos_endpoint": "https://destination.documents.azure.com:443/",
        "target_cosmos_database_name": "SimpleChat",
        "target_cosmos_key": REDACTED,
        "target_cosmos_subscription_id": "",
        "target_cosmos_resource_group": "",
        "target_ai_search_authentication_type": "managed_identity",
        "target_ai_search_endpoint": "https://destination.search.windows.net",
        "target_ai_search_key": "",
        "target_enhanced_citations_storage_authentication_type": "managed_identity",
        "target_enhanced_citations_storage_blob_endpoint": "",
        "target_enhanced_citations_storage_connection_string": "",
        "migration_max_parallel_operations": 8,
        "migration_retry_count": 5,
        "migration_skip_recent_within_hours": 0,
        "migration_temporary_destination_ru_enabled": False,
        "migration_temporary_destination_ru": 10000,
        "next_full_backup_run_at": None,
        "next_partial_backup_run_at": None,
        "enhanced_citations_enabled": True,
        "include_source_blobs_manageable": True,
        "key_vault_secret_storage_enabled": True,
        "key_vault_name_configured": True,
        "operational_business_hours_warning": (
            "We suggest not running backups, restores, or migrations during your operational "
            "business hours."
        ),
    }


def backup_row(backup_id, backup_type="full", status="completed", **extra):
    row = {
        "id": backup_id,
        "backup_type": backup_type,
        "status": status,
        "created_at": "2026-09-01T03:00:00+00:00",
        "completed_at": "2026-09-01T03:20:00+00:00",
        "scheduled": True,
        "manifest_path": f"simplechat-backups/{backup_id}/manifest.json",
        "base_prefix": f"simplechat-backups/{backup_id}",
        "artifact_count": 12,
        "bytes": 5_242_880,
        "record_count": 1200,
        "blob_count": 40,
        "warning_count": 0,
        "encrypted": True,
        "last_message": "Backup completed.",
        "can_delete": True,
    }
    row.update(extra)
    return row


class DataManagementFixture(AdminSettingsFixture):
    """The V2 admin page with a closed, in-memory Backup & Recovery API."""

    def __init__(self, page: Page, *, sections=None, **kwargs):
        # The base fixture installs its route handler, which records into this list.
        self.writes = []
        super().__init__(page, sections=sections or BACKUP_RECOVERY_SECTIONS, **kwargs)
        self.dm_settings = default_settings()
        self.dm_requests = []
        self.reject_next_dm_save = None
        self.backups = [
            backup_row("11111111-1111-4111-8111-111111111111", "full"),
            backup_row("22222222-2222-4222-8222-222222222222", "partial", warning_count=1),
        ]
        self.jobs = {}
        self.job_items = {}
        self.progress_polls = {}
        self.restore_review = {"ready": True, "blocker_count": 0, "warning_count": 0}
        self.migration_review = {"ready": True, "blocker_count": 0, "warning_count": 0}
        self.queue_status = 202
        self.queue_error = None
        self.catalog = {
            "users": [
                {"id": f"user-{index}", "label": f"User {index}", "description": f"user{index}@contoso.com", "document_count": index}
                for index in range(1, 31)
            ],
            "groups": [{"id": "group-1", "label": "Finance", "description": "Finance group", "document_count": 4}],
            "public_workspaces": [],
        }
        self.cosmos_documents = {
            "doc-1": {"id": "doc-1", "user_id": "user-1", "name": "Settings", "_etag": "etag-1", "_ts": 1},
        }
        self.cosmos_container_failures = 0

    # -- routing ---------------------------------------------------------------------

    def _route(self, route: Route):
        request = route.request
        path = urlsplit(request.url).path
        if path.startswith("/api/") and request.method in ("POST", "PUT", "PATCH", "DELETE"):
            # One ordered record of writes across the main and backup APIs, so a test can
            # prove which save happened first.
            self.writes.append((request.method, path))
        if path.startswith(API):
            self._data_management(route)
        else:
            super()._route(route)

    def _record(self, route):
        request = route.request
        body = None
        if request.post_data:
            try:
                body = request.post_data_json
            except Exception:
                body = request.post_data
        parsed = urlsplit(request.url)
        entry = {
            "method": request.method,
            "path": parsed.path[len(API):],
            "query": parse_qs(parsed.query),
            "body": body,
        }
        self.dm_requests.append(entry)
        return entry

    def requests_to(self, method, path_pattern):
        return [
            entry for entry in self.dm_requests
            if entry["method"] == method and re.fullmatch(path_pattern, entry["path"])
        ]

    def _data_management(self, route: Route):
        entry = self._record(route)
        method, path = entry["method"], entry["path"]

        if path == "/settings" and method == "GET":
            return route.fulfill(json={"success": True, "settings": self.dm_settings})
        if path == "/settings" and method == "PUT":
            return self._save_settings(route, entry["body"])
        if path == "/encryption-key" and method == "POST":
            self.dm_settings.update({"encryption_enabled": True, "encryption_key_storage": "key_vault", "encryption_key_reference": REDACTED})
            return route.fulfill(json={"success": True, "settings": self.dm_settings})
        if path == "/storage/test" and method == "POST":
            return route.fulfill(json={
                "success": True,
                "container_name": entry["body"]["settings"]["backup_storage_container_name"],
                "container_exists": True,
                "container_created": False,
            })
        if path == "/target/cosmos/test" and method == "POST":
            return route.fulfill(json={"success": True, "database_name": "SimpleChat", "migration_access": {"container_count": 7}})
        if path == "/target/cosmos/ru-boost/test" and method == "POST":
            return route.fulfill(json={"success": True, "target_ru": 10000, "targets": [{"scope": "database"}]})
        if path == "/target/search/test" and method == "POST":
            return route.fulfill(json={"success": True, "existing_indexes": ["simplechat-user-index"], "missing_indexes": []})
        if path == "/target/enhanced-citation-storage/test" and method == "POST":
            return route.fulfill(json={"success": True, "containers": [{"container_name": "user-documents", "container_exists": True}]})
        if path == "/backups" and method == "GET":
            return route.fulfill(json=self._backup_page(entry["query"]))
        if path == "/backups/retention/cleanup" and method == "POST":
            return route.fulfill(json={"success": True, "cleanup": {
                "success": True, "candidate_count": 0, "deleted_count": 0, "errors": [],
                "cutoff_at": "2026-08-07T00:00:00+00:00", "retention_days": self.dm_settings["retention_days"],
            }})
        match = re.fullmatch(r"/backups/([^/]+)", path)
        if match and method == "DELETE":
            backup_id = unquote(match.group(1))
            self.backups = [backup for backup in self.backups if backup["id"] != backup_id]
            return route.fulfill(json={"success": True, "cleanup": {"job_id": backup_id, "deleted_blob_count": 12}})
        if path == "/restore/review" and method == "POST":
            review = copy.deepcopy(self.restore_review)
            review.update({
                "checks": [{"id": "manifest_integrity", "label": "Backup manifest integrity", "status": "pass", "message": "Restore-safe."}],
                "review_fingerprint": "restore-fingerprint",
                "summary": {"artifact_count": 12, "service_counts": {"cosmos": 10, "ai_search": 2, "source_blobs": 0}, "warnings": 0, "failed_resource_names": []},
            })
            if review.get("ready"):
                review.update({"authorization_token": "restore-token", "authorization_expires_at": "2099-01-01T00:00:00+00:00"})
            return route.fulfill(json={"success": True, "review": review})
        if path == "/migration/review" and method == "POST":
            review = copy.deepcopy(self.migration_review)
            review.update({
                "review_fingerprint": "migration-fingerprint",
                "summary": {"users": {"mode": "selected", "count": 1, "document_count": 1, "include_documents": True}, "migration_mode": entry["body"]["migration_plan"]["migration_mode"]},
                "preview": {"estimated_outcomes": {"create_count": 3, "update_count": 0, "delete_count": 0, "conflict_count": 0}},
                "checks": review.get("checks") or [{"id": "scope", "label": "Migration scope", "workflow_step": "scope", "status": "pass", "summary": "1 principal scope is included."}],
            })
            if review.get("ready"):
                review.update({"authorization_token": "migration-token", "authorization_expires_at": "2099-01-01T00:00:00+00:00"})
            return route.fulfill(json={"success": True, "review": review})
        match = re.fullmatch(r"/migration/catalog/([a-z_]+)", path)
        if match and method == "GET":
            return route.fulfill(json=self._catalog_page(match.group(1), entry["query"]))
        if path == "/jobs" and method == "POST":
            return self._queue_job(route, entry["body"])
        if path == "/jobs" and method == "GET":
            return route.fulfill(json=self._job_page(entry["query"]))
        match = re.fullmatch(r"/jobs/([^/]+)(/progress|/retry|/cancel)?", path)
        if match:
            return self._job_action(route, unquote(match.group(1)), match.group(2) or "", method)
        if path == "/cosmos-editor/danger-acknowledgement" and method == "POST":
            return route.fulfill(json={"success": True})
        if path == "/cosmos-editor/containers" and method == "GET":
            if self.cosmos_container_failures:
                self.cosmos_container_failures -= 1
                return route.fulfill(status=503, json={"success": False, "error": "Cosmos DB containers could not be loaded."})
            return route.fulfill(json={"success": True, "containers": [COSMOS_CONTAINER]})
        if path == "/cosmos-editor/query" and method == "POST":
            custom = bool((entry["body"].get("query") or "").strip())
            return route.fulfill(json={"success": True, "container": COSMOS_CONTAINER, "items": [
                {"id": document["id"], "partition_key": document["user_id"], "etag": document["_etag"], "selectable": True, "preview": f"name: {document['name']}"}
                for document in self.cosmos_documents.values()
            ], "count": len(self.cosmos_documents),
                # Only a custom query pages on; a blank browse never returns a token.
                "continuation_token": "next-page" if custom else None, "has_more": custom,
                "query": {"mode": "custom" if custom else "empty"}})
        if path == "/cosmos-editor/document" and method == "POST":
            document = self.cosmos_documents[entry["body"]["id"]]
            return route.fulfill(json={"success": True, "container": COSMOS_CONTAINER, "document": document, "id": document["id"], "partition_key": document["user_id"], "etag": document["_etag"]})
        if path == "/cosmos-editor/document" and method == "PUT":
            return self._save_cosmos_document(route, entry["body"])

        self.unexpected_requests.append(f"{method} {API}{path}")
        return route.fulfill(status=404, json={"success": False, "error": "Unexpected data-management request."})

    # -- handlers --------------------------------------------------------------------

    def _save_settings(self, route, body):
        if self.reject_next_dm_save:
            message, self.reject_next_dm_save = self.reject_next_dm_save, None
            return route.fulfill(status=400, json={"success": False, "error": message})
        unexpected = sorted(set(body) - set(EDITABLE_KEYS))
        assert not unexpected, f"A save sent keys the classic page never sends: {unexpected}"
        for key, value in body.items():
            if key in SECRET_KEYS:
                if value == REDACTED:
                    continue
                self.dm_settings[key] = REDACTED if value else ""
            else:
                self.dm_settings[key] = value
        return route.fulfill(json={"success": True, "settings": self.dm_settings})

    def _backup_page(self, query):
        status = (query.get("status") or [""])[0]
        backup_type = (query.get("backup_type") or [""])[0]
        rows = [
            backup for backup in self.backups
            if (not backup_type or backup["backup_type"] == backup_type)
            and (not status or (status == "available" and backup["status"] in ("completed", "completed_with_warnings")) or backup["status"] == status)
        ]
        available = [backup for backup in self.backups if backup["status"] in ("completed", "completed_with_warnings")]
        latest_full = next((backup for backup in available if backup["backup_type"] == "full"), None)
        latest_partial = next((backup for backup in available if backup["backup_type"] == "partial"), None)
        return {
            "success": True,
            "summary": {
                "available": len(available),
                "full": len([backup for backup in available if backup["backup_type"] == "full"]),
                "partial": len([backup for backup in available if backup["backup_type"] == "partial"]),
                "total": len(self.backups),
                "latest_full": latest_full,
                "latest_partial": latest_partial,
            },
            "backups": rows,
            "pagination": {"page_size": 25, "returned_count": len(rows), "has_more": False, "next_token": None},
            "filters": {},
        }

    def _catalog_page(self, target_type, query):
        search = (query.get("search") or [""])[0].lower()
        token = (query.get("continuation_token") or [""])[0]
        items = [item for item in self.catalog.get(target_type, []) if search in f"{item['label']} {item['description']}".lower()]
        start = int(token or 0)
        page = items[start : start + 25]
        has_more = start + 25 < len(items)
        return {
            "type": target_type, "items": page, "total_count": len(items), "page_size": 25,
            "has_more": has_more, "continuation_token": str(start + 25) if has_more else "",
        }

    def _queue_job(self, route, body):
        if self.queue_error:
            status, payload = self.queue_error
            self.queue_error = None
            return route.fulfill(status=status, json=payload)
        job_id = f"{body['operation']}-{len(self.jobs) + 1}"
        job = {
            "id": job_id,
            "operation": body["operation"],
            "backup_type": body.get("backup_type"),
            "status": "queued",
            "created_at": "2026-09-02T10:00:00+00:00",
            "requested_by_email": "admin@contoso.com",
            "scheduled": False,
            "progress": {"current_step": "queued", "percent_complete": 0, "completed_steps": 0, "total_steps": 4},
            "warnings": [],
            "result": {},
            "options": body.get("options") or {},
            "can_retry": False,
            "can_cancel": True,
        }
        self.jobs[job_id] = job
        self.job_items[job_id] = [{"id": f"{job_id}-1", "job_id": job_id, "step_name": "queued", "status": "queued", "message": "Job queued.", "created_at": job["created_at"]}]
        return route.fulfill(status=self.queue_status, json={"success": True, "job": {key: value for key, value in job.items() if key != "options"}})

    def _public_job(self, job):
        return {key: value for key, value in job.items() if key != "options"}

    def _job_page(self, query):
        operation = (query.get("operation") or [""])[0]
        status = (query.get("status") or [""])[0]
        jobs = [
            self._public_job(job) for job in reversed(list(self.jobs.values()))
            if (not operation or job["operation"] == operation) and (not status or job["status"] == status)
        ]
        return {"success": True, "jobs": jobs, "pagination": {"page_size": 25, "returned_count": len(jobs), "has_more": False, "next_token": None}, "filters": {}}

    def _job_action(self, route, job_id, action, method):
        job = self.jobs.get(job_id)
        if not job:
            return route.fulfill(status=404, json={"success": False, "error": "Data Management job was not found."})
        if action == "" and method == "GET":
            return route.fulfill(json={"success": True, "job": self._public_job(job), "items": self.job_items.get(job_id, [])})
        if action == "/progress" and method == "GET":
            polls = self.progress_polls.get(job_id, 0) + 1
            self.progress_polls[job_id] = polls
            if polls >= 2 and job["status"] in ("queued", "running"):
                job.update({"status": "completed", "can_cancel": False, "completed_at": "2026-09-02T10:05:00+00:00", "progress": {"current_step": "completed", "percent_complete": 100, "completed_steps": 4, "total_steps": 4}, "last_message": "Job completed."})
            elif job["status"] == "queued":
                job.update({"status": "running", "progress": {"current_step": "export", "percent_complete": 40, "completed_steps": 1, "total_steps": 4}})
            return route.fulfill(json={"success": True, "job": self._public_job(job)})
        if action == "/cancel" and method == "POST":
            job.update({"cancel_requested_at": "2026-09-02T10:01:00+00:00", "can_cancel": False})
            return route.fulfill(status=202, json={"success": True, "job": self._public_job(job)})
        if action == "/retry" and method == "POST":
            job.update({"status": "queued", "can_retry": False, "can_cancel": True})
            return route.fulfill(status=202, json={"success": True, "job": self._public_job(job)})
        self.unexpected_requests.append(f"{method} {API}/jobs/{job_id}{action}")
        return route.fulfill(status=404, json={"success": False, "error": "Unexpected job request."})

    def _save_cosmos_document(self, route, body):
        document = self.cosmos_documents[body["id"]]
        assert body["confirmation_accepted"] is True
        assert body["confirmation_phrase"] == "I understand this can damage system data"
        if body["etag"] != document["_etag"]:
            return route.fulfill(status=409, json={"success": False, "error": "Cosmos DB document changed after it was opened. Refresh before saving again."})
        updated = dict(body["document"])
        updated["_etag"] = f"{document['_etag']}-next"
        self.cosmos_documents[body["id"]] = updated
        return route.fulfill(json={
            "success": True, "container": COSMOS_CONTAINER, "document": updated, "id": updated["id"], "partition_key": updated["user_id"], "etag": updated["_etag"],
            "change_summary": {"changed_paths": ["name"], "changed_count": 1, "added_count": 0, "removed_count": 0, "updated_count": 1},
        })

    # -- helpers ---------------------------------------------------------------------

    def add_job(self, job_id, **extra):
        """Seed one job into history, as a finished or failed run would leave it."""
        job = {
            "id": job_id,
            "operation": "backup",
            "backup_type": "full",
            "status": "failed",
            "created_at": "2026-09-01T09:00:00+00:00",
            "completed_at": "2026-09-01T09:10:00+00:00",
            "requested_by_email": "admin@contoso.com",
            "scheduled": False,
            "progress": {"current_step": "export", "percent_complete": 40, "completed_steps": 1, "total_steps": 4},
            "warnings": [],
            "result": {},
            "last_message": "Backup failed.",
            "can_retry": True,
            "can_cancel": False,
        }
        job.update(extra)
        self.jobs[job_id] = job
        self.job_items[job_id] = []
        return job

    def open_backup_recovery(self, **kwargs):
        kwargs.setdefault("ready_region", "Start Here")
        kwargs.setdefault("width", 1600)
        self.open(**kwargs)
