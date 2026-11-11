# support_export_service.py
"""Server-authoritative support exports, private snapshots, and owner-only consent."""

import io
import hashlib
import json
import secrets
import time
import uuid
import zipfile
from collections import Counter
from datetime import timedelta

from functions_appinsights import diagnostic_log_context
from support_export_contracts import (
    ACTIVE_STATES, EXPIRY_SECONDS, PUBLIC_LIMITS, RUNNING_STATES, SCHEMA_VERSION, SOURCES,
    SupportExportError, check_size, digest, fail, identifier, iso, normalize_configuration,
    normalize_request, resolve_intervals, timestamp, utc_now,
)
from support_export_privacy import BundleRedactor, encoded_json, map_text, scrub_credentials
from support_export_store import LEASE_SECONDS


WARNINGS = [
    "Only retained, ingested telemetry can be exported. Sampling, ingestion delay, disabled logging, and expired retention leave gaps.",
    "Historical events without user/conversation correlation may be absent from scoped exports.",
    "Debug logs may contain request text. Privacy checks are best effort; review the bundle before sharing.",
]


def bounded_preview(value):
    remaining = 32000

    def project(item):
        nonlocal remaining
        remaining -= 1
        if remaining <= 0:
            return "[Preview limit reached; complete reviewed content remains in the ZIP.]"
        if isinstance(item, str):
            allowance = min(2000, remaining)
            remaining -= min(len(item), allowance)
            return item if len(item) <= allowance else item[:allowance] + " [Preview truncated]"
        if isinstance(item, list):
            result = []
            for child in item:
                result.append(project(child))
                if remaining <= 0:
                    break
            return result
        if isinstance(item, dict):
            result = {}
            for index, (key, child) in enumerate(item.items()):
                safe_key = key if len(key) <= 256 else key[:256] + f" [Preview key {index} truncated]"
                remaining -= len(safe_key)
                result[safe_key] = project(child)
                if remaining <= 0:
                    break
            return result
        return item

    result = project(value)
    serialized = json.dumps(result, ensure_ascii=False)
    if len(serialized.encode("utf-8")) > 256 * 1024:
        return {"notice": "Preview size limited; complete reviewed content remains in the ZIP.", "sample": serialized[:64000]}
    return result


def require_admin(actor, roles):
    identifier(actor)
    if not isinstance(roles, (list, tuple, set)) or "Admin" not in roles:
        fail("admin_required", "Administrator access is required.", 403)


def _intent(job):
    return {
        key: job[key] for key in (
            "plan", "intervals", "source_configuration", "source_cutoff", "model_disclosure",
            "privacy_salt", "storage_binding", "requested_by",
        )
    }


def _check_integrity(job):
    if job.get("fingerprint") != digest(_intent(job)):
        fail("export_changed", "The immutable export request changed. Create a new export.", 409)


class SupportExportService:
    def __init__(self, store, sources, *, version, model_info, inspect_ai, notify, audit, storage_binding="", close_resources=None):
        self.store = store
        self.sources = sources
        self.version = version
        self.model_info = model_info
        self.inspect_ai = inspect_ai
        self.notify = notify
        self.audit = audit
        self.storage_binding = storage_binding
        self.last_heartbeat = 0.0
        self.close_resources = close_resources

    def close(self):
        if self.close_resources is not None:
            self.close_resources()

    def configuration(self):
        stored = self.store.configuration()
        return normalize_configuration(stored or {
            "cloud": "public", "app_resource_id": "", "site_resource_id": "",
        })

    def readiness(self):
        configuration = self.configuration()
        availability = {
            "activity": {"available": True, "message": "Retained Cosmos activity/audit records."},
            "file_processing": {"available": True, "message": "Retained Cosmos file-processing records; only present when logging collected them."},
        }
        for key, resource in (("telemetry", "app_resource_id"), ("console", "site_resource_id")):
            ready = bool(configuration[resource])
            availability[key] = {
                "available": ready, "access": "not_tested",
                "message": "Configured; read permissions are checked during collection." if ready
                else "Configure this application's resource ID.",
            }
        storage = {"available": False, "message": "Initialize the private support-export container."}
        try:
            self.store.require_private_storage()
            storage = {"available": True, "message": "Private export storage is accessible."}
        except SupportExportError as exc:
            storage["message"] = exc.public_message
        except Exception as exc:
            self.audit("storage_check_failed", error_type=type(exc).__name__)
            storage["message"] = "Application Blob storage could not be verified. Check its configuration and data-plane permissions."
        model = self.model_info()
        return {
            "configuration": configuration, "sources": availability, "storage": storage,
            "model": {key: model.get(key) for key in ("available", "label", "provider", "message")},
            "limits": PUBLIC_LIMITS, "warnings": WARNINGS,
        }

    def initialize_storage(self, actor, roles):
        require_admin(actor, roles)
        self.store.require_private_storage(create=True)
        self.store.set_configuration(self.configuration())
        self.audit("storage_initialized", actor=actor)
        return self.readiness()

    def test_sources(self, actor, roles):
        require_admin(actor, roles)
        result = self.readiness()
        configuration = self.configuration()
        for source in ("telemetry", "console"):
            if not result["sources"][source]["available"]:
                continue
            try:
                self.sources.probe_monitor(source, configuration)
                result["sources"][source].update(access="verified", message="Read access verified; empty or missing retained data is still possible.")
            except Exception as exc:
                self.audit("source_check_failed", actor=actor, source=source, error_type=type(exc).__name__)
                result["sources"][source].update(
                    available=False, access="failed",
                    message="Read access could not be verified. Check the resource IDs, cloud, collected tables, and resource-context Azure Monitor read permissions.",
                )
        return result

    def configure(self, actor, roles, value):
        require_admin(actor, roles)
        normalized = normalize_configuration(value)
        self.store.set_configuration(normalized)
        self.audit("configuration_saved", actor=actor)
        return {"configuration": normalized}

    def _own_job(self, actor, roles, job_id, *, allow_expired=False):
        require_admin(actor, roles)
        identifier(job_id)
        job = self.store.read(job_id, actor)
        if not job or job.get("record_kind") != "export" or job.get("requested_by") != actor:
            fail("export_not_found", "Support export not found.", 404)
        _check_integrity(job)
        if not allow_expired and timestamp(job["expires_at"]) <= utc_now():
            fail("export_expired", "This support export has expired.", 410)
        return job

    def public_job(self, job):
        result = {key: job.get(key) for key in (
            "id", "status", "created_at", "updated_at", "expires_at", "plan", "intervals",
            "error", "counts", "warnings", "phase", "privacy_report", "source_cutoff",
        )}
        result["expired"] = timestamp(job["expires_at"]) <= utc_now()
        if result["expired"]:
            result["status"] = "expired"
        result["can_download"] = job["status"] == "ready" and not result["expired"]
        return result

    def list_jobs(self, actor, roles, after=""):
        require_admin(actor, roles)
        if after:
            identifier(after)
        rows = self.store.query(
            "SELECT TOP 51 * FROM c WHERE c.record_kind = 'export' AND c.requested_by = @actor "
            "AND c.id > @after ORDER BY c.id",
            [{"name": "@actor", "value": actor}, {"name": "@after", "value": after}],
            partition=actor, limit=51,
        )
        return {"items": [self.public_job(row) for row in rows[:50]], "next": rows[49]["id"] if len(rows) > 50 else None}

    def _reserve_admin(self, actor, job_id, expires_at):
        lock = self.store.read("active-export", actor)
        if lock and timestamp(lock["expires_at"]) > utc_now() and lock["job_id"] != job_id:
            other = self.store.read(lock["job_id"], actor)
            if other and other["status"] in ACTIVE_STATES:
                fail("export_busy", "You already have an active export. Finish or cancel it first.", 409)
        body = {
            "id": "active-export", "partition_key": actor, "record_kind": "admin_lock",
            "job_id": job_id, "expires_at": expires_at,
        }
        if lock:
            body["_etag"] = lock["_etag"]
            self.store.save(body)
        else:
            try:
                self.store.create(body)
            except Exception as exc:
                if getattr(exc, "status_code", None) == 409:
                    fail("export_busy", "Another export request is being created. Retry after refreshing.", 409)
                raise

    def _prepare_data(self, actor, roles, data):
        require_admin(actor, roles)
        now = utc_now()
        plan = normalize_request(data, now)
        if plan["user_id"]:
            self.sources.require_registered_user(plan["user_id"])
        conversations = [
            self.sources.conversation(plan["user_id"], item, bounds=plan["mode"] == "conversations")
            for item in plan["conversation_ids"]
        ]
        if plan["include_transcripts"] and any(not item["transcript_eligible"] for item in conversations):
            fail("personal_only", "Shared and group conversations are logs-only. Select personal conversations for transcripts.", 403)
        configuration = self.configuration()
        for source in plan["sources"]:
            if source in ("telemetry", "console") and not (
                configuration["site_resource_id" if source == "console" else "app_resource_id"]
            ):
                fail("source_unavailable", "A selected Azure source is not configured. Configure it or explicitly deselect it.", 503)
        model = self.model_info() if plan["privacy"] == "ai" else {"available": False}
        if plan["privacy"] == "ai" and not model.get("available"):
            fail("model_unavailable", "The default text model cannot perform privacy inspection. Configure AI Connections or use deterministic-only checking.", 503)
        self.store.require_private_storage()
        plan["purpose"] = BundleRedactor().deterministic(plan["purpose"])
        return {
            "plan": plan, "conversations": conversations, "source_configuration": configuration,
            "source_cutoff": iso(now), "intervals": resolve_intervals(plan, conversations, now),
            "model_disclosure": model if plan["privacy"] == "ai" else {},
        }

    def prepare(self, actor, roles, data):
        prepared = self._prepare_data(actor, roles, data)
        review_id = "review-" + uuid.uuid4().hex
        expires_at = iso(utc_now() + timedelta(minutes=15))
        self.store.create({
            "id": review_id, "partition_key": actor, "record_kind": "review",
            "input_fingerprint": digest(data), "prepared": prepared, "expires_at": expires_at,
            "storage_binding": self.storage_binding, "ttl": 900,
        })
        return {
            "review_id": review_id, "request": prepared["plan"], "intervals": prepared["intervals"],
            "conversations": prepared["conversations"], "expires_at": expires_at,
            "model_label": prepared["model_disclosure"].get("label", ""), "warnings": WARNINGS,
        }

    def create(self, actor, roles, data, retry_key, review_id=None):
        require_admin(actor, roles)
        identifier(retry_key)
        input_fingerprint = digest(data)
        job_id = digest({"actor": actor, "retry_key": retry_key})[:32]
        existing = self.store.read(job_id, actor)
        if existing:
            if existing.get("input_fingerprint") != input_fingerprint:
                fail("retry_changed", "An export retry cannot change its requested scope.", 409)
            _check_integrity(existing)
            return self.public_job(existing)
        if review_id:
            identifier(review_id)
            review = self.store.read(review_id, actor)
            if (
                not review or review.get("record_kind") != "review"
                or review["input_fingerprint"] != input_fingerprint
                or timestamp(review["expires_at"]) <= utc_now()
                or review["storage_binding"] != self.storage_binding
            ):
                fail("review_expired", "Review this exact export scope again before generating.", 409)
            prepared = review["prepared"]
            if prepared["source_configuration"] != self.configuration():
                fail("configuration_changed", "Source configuration changed. Review the export again.", 409)
            for item in prepared["conversations"]:
                current = self.sources.conversation(prepared["plan"]["user_id"], item["id"])
                if prepared["plan"]["include_transcripts"] and not current["transcript_eligible"]:
                    fail("personal_only", "A conversation is no longer eligible for transcript release.", 403)
            if prepared["plan"]["privacy"] == "ai" and (
                self.model_info().get("fingerprint") != prepared["model_disclosure"].get("fingerprint")
            ):
                fail("model_changed", "The default AI destination changed. Review the export again.", 409)
        else:
            prepared = self._prepare_data(actor, roles, data)
        plan = prepared["plan"]
        conversations = prepared["conversations"]
        model = prepared["model_disclosure"]
        now = utc_now()
        job = {
            "id": job_id, "partition_key": actor, "record_kind": "export", "requested_by": actor,
            "input_fingerprint": input_fingerprint, "plan": plan,
            "source_configuration": prepared["source_configuration"], "storage_binding": self.storage_binding,
            "source_cutoff": prepared["source_cutoff"], "intervals": prepared["intervals"],
            "model_disclosure": model,
            "privacy_salt": secrets.token_hex(32), "created_at": iso(now), "updated_at": iso(now),
            "expires_at": iso(now + timedelta(seconds=EXPIRY_SECONDS)),
            "status": "waiting_for_consent" if plan["include_transcripts"] else "queued",
            "phase": "Waiting for owner approval" if plan["include_transcripts"] else "Queued",
            "warnings": WARNINGS, "ttl": 7 * 24 * 60 * 60,
        }
        job["fingerprint"] = digest(_intent(job))
        self._reserve_admin(actor, job_id, job["expires_at"])
        self.audit("requested", actor=actor, export_id=job_id, transcripts=plan["include_transcripts"])
        job = self.store.create(job)
        if plan["include_transcripts"]:
            consent = self.store.create({
                "id": "consent-" + job_id, "partition_key": plan["user_id"], "record_kind": "consent",
                "owner_id": plan["user_id"], "requester_id": actor, "job_id": job_id,
                "plan_fingerprint": job["fingerprint"], "status": "pending", "purpose": plan["purpose"],
                "created_at": job["created_at"], "expires_at": job["expires_at"],
                "source_cutoff": job["source_cutoff"], "conversations": conversations,
                "privacy": plan["privacy"], "model_label": scrub_credentials(model.get("label", "")),
                "ttl": 7 * 24 * 60 * 60,
            })
            try:
                self.notify(plan["user_id"], job_id)
            except Exception as exc:
                self.audit("consent_notification_failed", actor=actor, error_type=type(exc).__name__)
                job.update(status="failed", phase="Consent notification failed", error={
                    "code": "notification_failed", "message": "The consent notification could not be delivered. Create a new export.",
                })
                self.store.save(job)
                fail("notification_failed", "The consent notification could not be delivered. Create a new export.", 503)
        return self.public_job(job)

    def status(self, actor, roles, job_id):
        job = self._own_job(actor, roles, job_id, allow_expired=True)
        if job["plan"]["include_transcripts"] and job["status"] == "ready" and timestamp(job["expires_at"]) > utc_now():
            self._grant(job)
        return self.public_job(job)

    def cancel(self, actor, roles, job_id):
        job = self._own_job(actor, roles, job_id)
        if job["status"] != "cancelled":
            job.update(status="cancelled", phase="Cancelled", updated_at=iso(utc_now()), lease_token=None)
            job = self.store.save(job)
            self.audit("cancelled", actor=actor, export_id=job_id)
        if job["plan"]["include_transcripts"]:
            consent = self._consent(job["plan"]["user_id"], "consent-" + job["id"])
            if consent["status"] in ("pending", "approved"):
                consent["status"] = "withdrawn"
                self.store.save(consent)
        return self.public_job(job)

    def _consent(self, owner, consent_id):
        identifier(owner)
        identifier(consent_id)
        consent = self.store.read(consent_id, owner)
        if not consent or consent.get("record_kind") != "consent" or consent.get("owner_id") != owner:
            fail("consent_not_found", "Support-data consent request not found.", 404)
        return consent

    def list_consents(self, owner, after=""):
        identifier(owner)
        if after:
            identifier(after)
        rows = self.store.query(
            "SELECT TOP 51 * FROM c WHERE c.record_kind = 'consent' AND c.owner_id = @owner "
            "AND c.id > @after ORDER BY c.id",
            [{"name": "@owner", "value": owner}, {"name": "@after", "value": after}],
            partition=owner, limit=51,
        )
        return {"items": [self.public_consent(row) for row in rows[:50]], "next": rows[49]["id"] if len(rows) > 50 else None}

    def consent_details(self, owner, consent_id):
        return self.public_consent(self._consent(owner, consent_id))

    def public_consent(self, consent):
        result = {key: consent.get(key) for key in (
            "id", "job_id", "requester_id", "status", "purpose", "created_at", "expires_at",
            "source_cutoff", "conversations", "privacy", "model_label", "approved_at",
        )}
        result["expired"] = timestamp(consent["expires_at"]) <= utc_now()
        if result["expired"]:
            result["status"] = "expired"
        result["scope_notice"] = (
            "Approval releases whole personal conversations, not just the diagnostic time window. "
            "Downloaded copies and AI inputs already submitted cannot be recalled."
        )
        return result

    def consent_preview(self, owner, consent_id):
        consent = self._consent(owner, consent_id)
        if consent["status"] != "pending" or timestamp(consent["expires_at"]) <= utc_now():
            fail("consent_closed", "This consent request is no longer pending.", 409)
        job = self._consent_job(consent)
        snapshots = self.sources.snapshot(owner, job["plan"]["conversation_ids"], job["source_cutoff"])
        preview = [{"conversation_id": item["conversation_id"], "message_count": len(item["messages"]),
                    "messages": item["messages"][:10]} for item in snapshots]
        redactor = BundleRedactor(job["privacy_salt"])
        preview = redactor.deterministic(preview, identifiers=[owner, *job["plan"]["conversation_ids"]])
        return {"consent": self.public_consent(consent), "fingerprint": digest(snapshots), "preview": bounded_preview(preview)}

    def _consent_job(self, consent):
        job = self.store.read(consent["job_id"], consent["requester_id"])
        if (
            not job or job.get("record_kind") != "export" or not job["plan"]["include_transcripts"]
            or job["plan"]["user_id"] != consent["owner_id"]
            or consent["plan_fingerprint"] != job["fingerprint"]
            or timestamp(job["expires_at"]) <= utc_now() or job["status"] in ("failed", "cancelled", "expired")
        ):
            fail("consent_closed", "The related export is no longer available.", 409)
        _check_integrity(job)
        return job

    def decide(self, owner, consent_id, action, fingerprint=None):
        consent = self._consent(owner, consent_id)
        if action not in ("approve", "decline", "revoke"):
            fail("invalid_consent_action", "Choose approve, decline, or revoke.")
        if timestamp(consent["expires_at"]) <= utc_now():
            fail("consent_expired", "This consent request has expired.", 410)
        job = self._consent_job(consent)
        if action == "approve":
            if consent["status"] == "approved" and consent.get("snapshot_fingerprint") == fingerprint:
                return self.public_consent(consent)
            if consent["status"] != "pending" or job["status"] != "waiting_for_consent":
                fail("consent_closed", "This consent request is no longer pending.", 409)
            snapshots = self.sources.snapshot(owner, job["plan"]["conversation_ids"], job["source_cutoff"])
            if not isinstance(fingerprint, str) or fingerprint != digest(snapshots):
                fail("snapshot_changed", "The conversation snapshot changed. Review the refreshed preview before approving.", 409)
            if job["plan"]["privacy"] == "ai" and self.model_info().get("fingerprint") != job["model_disclosure"].get("fingerprint"):
                fail("model_changed", "The default AI destination changed. Ask the administrator to create a new export.", 409)
            redactor = BundleRedactor(job["privacy_salt"])
            cleaned = redactor.deterministic(snapshots, identifiers=[owner, *job["plan"]["conversation_ids"]])
            expires_at = iso(utc_now() + timedelta(seconds=EXPIRY_SECONDS))
            path = f"{job['id']}/{uuid.uuid4().hex}/snapshot.json"
            self.store.put(path, encoded_json(cleaned), expires_at)
            consent.update(
                status="approved", approved_at=iso(utc_now()), expires_at=expires_at,
                snapshot_blob=path, snapshot_fingerprint=fingerprint, privacy_report=redactor.report(),
                approved_by=owner, snapshot_checksum=hashlib.sha256(encoded_json(cleaned)).hexdigest(),
            )
            consent = self.store.save(consent)
            job.update(status="queued", phase="Owner approved; queued", expires_at=expires_at, updated_at=iso(utc_now()))
        else:
            expected = "pending" if action == "decline" else "approved"
            if consent["status"] != expected:
                fail("consent_closed", "This consent decision is no longer available.", 409)
            consent.update(status="denied" if action == "decline" else "revoked", decided_at=iso(utc_now()))
            consent = self.store.save(consent)
            job.update(status="cancelled", phase="Transcript consent " + consent["status"], lease_token=None, updated_at=iso(utc_now()))
        self.store.save(job)
        self.audit("consent_" + action, actor=owner, export_id=job["id"])
        return self.public_consent(consent)

    def _grant(self, job, *, check_snapshot=False):
        if not job["plan"]["include_transcripts"]:
            return None
        consent = self._consent(job["plan"]["user_id"], "consent-" + job["id"])
        if (
            consent["status"] != "approved" or timestamp(consent["expires_at"]) <= utc_now()
            or consent["plan_fingerprint"] != job["fingerprint"] or consent["requester_id"] != job["requested_by"]
            or consent.get("approved_by") != job["plan"]["user_id"]
            or not isinstance(consent.get("snapshot_blob"), str)
            or not consent["snapshot_blob"].startswith(job["id"] + "/")
            or not consent["snapshot_blob"].endswith("/snapshot.json")
        ):
            fail("consent_required", "A current owner approval is required for these transcripts.", 403)
        for conversation_id in job["plan"]["conversation_ids"]:
            metadata = self.sources.conversation(job["plan"]["user_id"], conversation_id)
            if not metadata["transcript_eligible"]:
                fail("personal_only", "A selected conversation is no longer a personal conversation.", 403)
        if check_snapshot:
            current = self.sources.snapshot(job["plan"]["user_id"], job["plan"]["conversation_ids"], job["source_cutoff"])
            if digest(current) != consent["snapshot_fingerprint"]:
                fail("snapshot_changed", "Conversation revisions or availability changed after approval. Create a new export.", 409)
        return consent

    def _downloadable(self, actor, roles, job_id):
        job = self._own_job(actor, roles, job_id)
        if job["status"] != "ready":
            fail("export_not_ready", "The support export is not ready.", 409)
        self._grant(job, check_snapshot=True)
        if job["storage_binding"] != self.storage_binding:
            fail("storage_changed", "Export storage changed. Restore its configuration or create a new export.", 409)
        return job

    def _artifact(self, job, field, filename):
        path = job.get(field)
        if not isinstance(path, str) or not path.startswith(job["id"] + "/") or not path.endswith("/" + filename):
            fail("invalid_artifact", "The support-export artifact is not bound to this request.", 503)
        data = self.store.get(path)
        if hashlib.sha256(data).hexdigest() != job.get(field + "_checksum"):
            fail("artifact_changed", "The support-export artifact changed. Create a new export.", 503)
        return data

    def preview(self, actor, roles, job_id):
        job = self._downloadable(actor, roles, job_id)
        data = self._artifact(job, "preview_blob", "preview.json")
        self._downloadable(actor, roles, job_id)
        return json.loads(data)

    def download(self, actor, roles, job_id):
        job = self._downloadable(actor, roles, job_id)
        data = self._artifact(job, "archive_blob", "bundle.zip")
        self._downloadable(actor, roles, job_id)
        self.audit("downloaded", actor=actor, export_id=job_id)
        return data

    def _heartbeat(self, job, slot, phase=None, *, force=False):
        if not phase and not force and time.monotonic() - self.last_heartbeat < 5:
            return
        current = self.store.read(job["id"], job["partition_key"])
        if (
            current is None or current["status"] not in RUNNING_STATES
            or current.get("lease_token") != job["lease_token"]
            or timestamp(current["lease_until"]) <= utc_now() or timestamp(current["expires_at"]) <= utc_now()
        ):
            fail("lease_lost", "The export was cancelled or its worker lease expired.", 409)
        _check_integrity(current)
        self._grant(current)
        self.store.renew_slot(slot)
        current.update(updated_at=iso(utc_now()), lease_until=iso(utc_now() + timedelta(seconds=LEASE_SECONDS)))
        if phase:
            current.update(status=phase, phase=phase.replace("_", " ").capitalize())
        saved = self.store.save(current)
        job.clear()
        job.update(saved)
        self.last_heartbeat = time.monotonic()

    def _archive(self, job, data, report, expires_at):
        logs, conversations = data["logs"], data["conversations"]
        files = {}
        source_files = {"telemetry": "telemetry", "activity": "activity", "file_processing": "file-processing", "console": "system-context"}
        groups = {}
        for row in logs:
            name = "system-context" if row["context_scope"] == "system_context" else source_files[row["source"]]
            groups.setdefault(name, []).append(row)
        for name, rows in groups.items():
            files[f"logs/{name}.jsonl"] = b"\n".join(encoded_json(row) for row in rows) + b"\n"
        files["logs/diagnostics.txt"] = "\n\n".join(
            f"{row['timestamp']} [{row['source']}] [{row['severity']}] {row['message']}\n"
            + json.dumps(row["properties"], ensure_ascii=False, indent=2) for row in logs
        ).encode("utf-8")
        for index, conversation in enumerate(conversations, 1):
            files[f"conversations/conversation-{index}.json"] = encoded_json(conversation)
            files[f"conversations/conversation-{index}.md"] = "\n\n".join(
                f"## {message['role']} - {message['timestamp']}\n\n{message['content']}"
                for message in conversation["messages"]
            ).encode("utf-8")
        report = map_text(report, scrub_credentials)
        files["privacy-report.json"] = encoded_json(report)
        files["README.md"] = (
            "# SimpleChat support bundle\n\n"
            "See manifest.json for scope, UTC windows, source exclusions, and checksums. "
            "logs/diagnostics.txt is a readable timeline; JSONL files preserve diagnostic structure.\n\n"
            "Only approved personal conversation snapshots are included. Logs may still contain "
            "sensitive information: privacy inspection is best effort, not an anonymity guarantee. "
            "Review before manually sharing with support. This application did not send the bundle.\n\n"
            + "\n".join("- " + warning for warning in WARNINGS)
        ).encode("utf-8")
        redactor = BundleRedactor(job["privacy_salt"])
        counts = dict(Counter(row["source"] for row in logs))
        manifest = {
            "schema_version": SCHEMA_VERSION, "application_version": self.version, "export_id": job["id"],
            "created_at": iso(utc_now()), "source_cutoff": job["source_cutoff"], "expires_at": expires_at,
            "intervals_utc": job["intervals"], "all_users": job["plan"]["all_users"],
            "subject": redactor.alias("identifier", job["plan"]["user_id"]) if job["plan"]["user_id"] else "all_users",
            "conversations": [redactor.alias("identifier", item) for item in job["plan"]["conversation_ids"]],
            "sources": {
                source: {"status": "collected" if source in job["plan"]["sources"] else "excluded_by_admin",
                         "records": counts.get(source, 0)} for source in SOURCES
            },
            "consent_reference": "consent-" + job["id"] if conversations else None,
            "privacy": report, "warnings": WARNINGS,
            "checksums_sha256": {name: hashlib.sha256(body).hexdigest() for name, body in files.items()},
        }
        files["manifest.json"] = encoded_json(map_text(manifest, scrub_credentials))
        check_size(len(logs) + sum(len(item["messages"]) for item in conversations), sum(map(len, files.values())))
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, body in files.items():
                archive.writestr(name, body)
        return output.getvalue(), counts

    def run(self, job, slot):
        with diagnostic_log_context(user_id=job["requested_by"]):
            self._run(job, slot)

    def _run(self, job, slot):
        current = self.store.read(job["id"], job["partition_key"])
        if (
            current is None or current["status"] not in ("queued", *RUNNING_STATES)
            or timestamp(current["expires_at"]) <= utc_now()
            or (current["status"] in RUNNING_STATES and timestamp(current["lease_until"]) > utc_now())
        ):
            return
        _check_integrity(current)
        current.update(
            status="collecting", phase="Collecting", lease_token=uuid.uuid4().hex,
            lease_until=iso(utc_now() + timedelta(seconds=LEASE_SECONDS)), updated_at=iso(utc_now()),
        )
        job = self.store.save(current)
        worker_token = job["lease_token"]
        try:
            if job["storage_binding"] != self.storage_binding or job["source_configuration"] != self.configuration():
                fail("configuration_changed", "Collection configuration changed. Create a new export.", 409)
            self.store.require_private_storage()
            grant = self._grant(job)
            for conversation_id in job["plan"]["conversation_ids"]:
                self.sources.conversation(job["plan"]["user_id"], conversation_id)
            progress = lambda: self._heartbeat(job, slot)
            records = []
            seen = set()
            byte_count = 0
            for source in job["plan"]["sources"]:
                rows = (
                    self.sources.collect_monitor(source, job["source_configuration"], job["plan"], job["intervals"], progress)
                    if source in ("telemetry", "console")
                    else self.sources.collect_cosmos(source, job["plan"], job["intervals"], progress)
                )
                for row in rows:
                    row_digest = digest(row)
                    if row_digest in seen:
                        continue
                    seen.add(row_digest)
                    byte_count += len(encoded_json(row))
                    check_size(len(records) + 1, byte_count)
                    records.append(row)
                progress()
            records.sort(key=lambda row: timestamp(row["timestamp"], stored=True))
            if grant:
                snapshot_bytes = self.store.get(grant["snapshot_blob"])
                if hashlib.sha256(snapshot_bytes).hexdigest() != grant["snapshot_checksum"]:
                    fail("snapshot_changed", "The approved snapshot artifact changed. Create a new export.", 409)
                snapshots = json.loads(snapshot_bytes)
            else:
                snapshots = []
            self._heartbeat(job, slot, "redacting")
            redactor = BundleRedactor(job["privacy_salt"])
            cleaned = {
                "logs": redactor.deterministic(
                    records, identifiers=[job["plan"]["user_id"], *job["plan"]["conversation_ids"]], progress=progress,
                ),
                # The checksum-bound owner snapshots already completed deterministic inspection.
                "conversations": snapshots,
            }
            ai = None
            if job["plan"]["privacy"] == "ai":
                self._heartbeat(job, slot, "ai_review")
                if self.model_info().get("fingerprint") != job["model_disclosure"].get("fingerprint"):
                    fail("model_changed", "The configured default AI destination changed. Create a new export.", 409)
                cleaned, ai = redactor.inspect_ai(
                    cleaned, selection=job["model_disclosure"]["selection"],
                    inspect=lambda units, selection, callback, budget: self.inspect_ai(
                        units, selection, callback, budget,
                        expected_fingerprint=job["model_disclosure"]["fingerprint"],
                    ), progress=progress,
                )
            report = redactor.report(ai)
            if grant:
                report["approved_snapshot_redactions"] = grant["privacy_report"]
                report["fields_checked"] += grant["privacy_report"]["fields_checked"]
                report["redaction_counts"] = dict(
                    Counter(report["redaction_counts"]) + Counter(grant["privacy_report"]["redaction_counts"]),
                )
            self._heartbeat(job, slot, force=True)
            expires_at = iso(utc_now() + timedelta(seconds=EXPIRY_SECONDS))
            if grant:
                expires_at = min(expires_at, grant["expires_at"])
            archive, counts = self._archive(job, cleaned, report, expires_at)
            attempt = f"{job['id']}/{job['lease_token']}"
            archive_blob, preview_blob = attempt + "/bundle.zip", attempt + "/preview.json"
            preview = bounded_preview({
                "logs": cleaned["logs"][:20],
                "conversations": [{"messages": item["messages"][:10]} for item in cleaned["conversations"]],
                "privacy_report": report, "notice": "Preview only; the ZIP contains all collected records.",
            })
            self.store.put(archive_blob, archive, expires_at, content_type="application/zip")
            self.store.put(preview_blob, encoded_json(preview), expires_at)
            self._heartbeat(job, slot, force=True)
            job.update(
                status="ready", phase="Ready for review and download", expires_at=expires_at,
                archive_blob=archive_blob, preview_blob=preview_blob, privacy_report=report,
                archive_blob_checksum=hashlib.sha256(archive).hexdigest(),
                preview_blob_checksum=hashlib.sha256(encoded_json(preview)).hexdigest(),
                counts=counts, lease_token=None, updated_at=iso(utc_now()),
            )
            self.store.save(job)
            self.audit("completed", actor=job["requested_by"], export_id=job["id"], records=len(records))
        except Exception as exc:
            self.audit("failed", actor=job["requested_by"], export_id=job["id"], error_type=type(exc).__name__)
            latest = self.store.read(job["id"], job["partition_key"])
            if latest and latest.get("lease_token") == worker_token and latest["status"] in RUNNING_STATES:
                latest.update(status="failed", phase="Export failed", lease_token=None, error={
                    "code": exc.code if isinstance(exc, SupportExportError) else "collection_failed",
                    "message": exc.public_message if isinstance(exc, SupportExportError)
                    else "Diagnostic collection failed. Check source read permissions, storage, and application logs.",
                })
                self.store.save(latest)

    def tick(self):
        now = utc_now()
        expired = self.store.query(
            "SELECT TOP 100 * FROM c WHERE c.record_kind = 'export' AND c.expires_at <= @now "
            "AND (c.status != 'expired' OR NOT IS_DEFINED(c.cleanup_complete) OR c.cleanup_complete != true)",
            [{"name": "@now", "value": iso(now)}],
        )
        for job in expired:
            if job["status"] != "expired":
                job.update(status="expired", phase="Expired", lease_token=None)
                job = self.store.save(job)
            try:
                self.store.delete_artifacts(job["id"])
                job["cleanup_complete"] = True
                self.store.save(job)
                self.audit("expired", export_id=job["id"])
            except Exception as exc:
                self.audit("cleanup_failed", export_id=job["id"], error_type=type(exc).__name__)
        cleanup = self.store.read("blob-cleanup", "configuration")
        if self.store.blobs is not None and cleanup and (
            not cleanup.get("next_scan_at") or timestamp(cleanup["next_scan_at"]) <= now
        ):
            try:
                self.store.sweep_expired_blobs()
            except Exception as exc:
                self.audit("cleanup_failed", error_type=type(exc).__name__)
        due = self.store.query(
            "SELECT TOP 1 * FROM c WHERE c.record_kind = 'export' AND c.expires_at > @now "
            "AND (c.status = 'queued' OR (ARRAY_CONTAINS(@running, c.status) AND c.lease_until <= @now))",
            [{"name": "@now", "value": iso(now)}, {"name": "@running", "value": list(RUNNING_STATES)}], limit=1,
        )
        if not due:
            return
        slot = self.store.acquire_slot()
        if slot is None:
            return
        try:
            self.run(due[0], slot)
        finally:
            self.store.release_slot(slot)
