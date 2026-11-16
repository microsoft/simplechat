# test_m365_continuations.py
"""
Functional tests for conditional Microsoft 365 workflow continuation delivery.
Version: 0.261.341
Implemented in: 0.261.029
Stale workflow containment implemented in: 0.261.341

Approval delivery is idempotent and uncertain external execution is not replayed.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import sys
import unittest

from azure.cosmos._cosmos_responses import CosmosDict
from azure.cosmos.exceptions import CosmosHttpResponseError


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Test paths are installed before importing dependency-light application modules.
from functions_m365_continuations import M365ContinuationNotStarted, resume_pending_workflows  # noqa: E402
from functions_m365_context import M365PolicyError  # noqa: E402
from test_support.m365 import CosmosContainer  # noqa: E402


class PendingJobs(CosmosContainer):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.before_replace = None

    def replace_item(self, item, body, *, etag, match_condition):
        if self.before_replace is not None:
            self.before_replace(item, body)
        return super().replace_item(item, body, etag=etag, match_condition=match_condition)

    def query_items(self, **kwargs):
        rows = [
            deepcopy(dict(record))
            for record in list(self.items.values())
            if record.get("type") == "m365_execution_request"
            and isinstance(record.get("workflow_id"), str) and record["workflow_id"]
            and record.get("status") in {"awaiting_approval", "awaiting_sign_in", "ready_to_resume", "resuming"}
        ]
        limit = next(parameter["value"] for parameter in kwargs["parameters"] if parameter["name"] == "@limit")
        return rows[:limit]


class Approvals:
    def get_approval(self, approval_id, user_id):
        return {"id": approval_id, "subject_user_id": user_id, "status": "approved"}


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.jobs = PendingJobs(partition_field="user_id")
        self.jobs.create_item(body={
            "id": "request", "user_id": "reader", "workflow_id": "workflow",
            "type": "m365_execution_request", "approval_id": "approval",
            "status": "awaiting_approval",
        })
        self.effects = []
        self.events = []
        self.now = datetime(2026, 9, 17, tzinfo=timezone.utc)

    def run_pending(self, execute, **kwargs):
        options = {
            "can_resume": lambda job, approval: True,
            "log_event": lambda *args, **kwargs: self.events.append((args, kwargs)),
            "clock": lambda: self.now,
        }
        options.update(kwargs)
        return resume_pending_workflows(
            self.jobs, options.pop("approvals", Approvals()), execute=execute, **options,
        )

    def add_valid_job(self):
        self.jobs.create_item(body={
            "id": "later-request", "user_id": "reader", "workflow_id": "valid-workflow",
            "type": "m365_execution_request", "approval_id": "valid-approval",
            "status": "awaiting_approval",
        })

    def execute_successfully(self, job):
        self.effects.append(job["id"])
        self.assertIs(type(job), CosmosDict)
        return {"success": True}

    @staticmethod
    def workflow_available(job, approval):
        if job["workflow_id"] == "workflow":
            raise M365PolicyError("m365_workflow_missing", "The workflow no longer exists.")
        return True

    def test_decided_job_runs_once(self):
        def execute(job):
            self.effects.append(job["id"])
            return {"success": True}
        first = self.run_pending(execute)
        second = self.run_pending(execute)
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertEqual(self.effects, ["request"])

    def test_uncertain_operation_requires_recovery(self):
        def execute(job):
            self.effects.append(job["id"])
            raise RuntimeError("Worker stopped after an external operation")
        first = self.run_pending(execute)
        second = self.run_pending(execute)
        current = self.jobs.read_item("request", "reader")
        self.assertEqual(first, [])
        self.assertEqual(second, [])
        self.assertEqual(current["status"], "recovery_required")
        self.assertEqual(self.effects, ["request"])

    def test_new_approval_is_not_overwritten_by_delivery_completion(self):
        def execute(job):
            current = self.jobs.read_item(job["id"], job["user_id"])
            current["status"] = "awaiting_approval"
            current["approval_id"] = "second-approval"
            self.jobs.upsert_item(body=current)
            return {"success": False, "pending": True}
        outcomes = self.run_pending(execute)
        current = self.jobs.read_item("request", "reader")
        self.assertEqual(current["status"], "awaiting_approval")
        self.assertEqual(current["approval_id"], "second-approval")
        self.assertEqual(outcomes, [{"request_id": "request", "result": {"success": False, "pending": True}}])

    def test_durable_handoff_remains_running_without_a_legacy_replay_lease(self):
        def execute(job):
            self.effects.append(job["id"])
            return {"success": False, "pending": True, "durable_execution": True}
        self.run_pending(execute)
        current = self.jobs.read_item("request", "reader")
        self.assertEqual(current["status"], "running")
        self.assertNotIn("completed_at", current)
        self.assertNotIn("resume_lease_expires_at", current)
        self.assertEqual(self.run_pending(execute), [])
        self.assertEqual(self.effects, ["request"])

    def test_deleted_then_valid_candidate_and_repeated_tick_has_no_error_storm(self):
        self.add_valid_job()
        first = self.run_pending(self.execute_successfully, can_resume=self.workflow_available)
        event_count = len(self.events)
        for _tick in range(3):
            repeated = self.run_pending(self.execute_successfully, can_resume=self.workflow_available)
            self.assertEqual(repeated, [])
        stale = self.jobs.read_item("request", "reader")
        self.assertEqual(stale["status"], "failed")
        self.assertEqual(stale["failure_code"], "workflow_deleted")
        self.assertEqual(stale["completed_at"], self.now.isoformat())
        self.assertNotIn("continuation_status", stale)
        self.assertNotIn("terminal_reason", stale)
        self.assertEqual([item["request_id"] for item in first], ["later-request"])
        self.assertEqual(self.effects, ["later-request"])
        self.assertEqual(len(self.events), event_count)
        self.assertTrue(all(event[1]["level"] != logging.ERROR for event in self.events))

    def test_deleted_workflow_is_closed_before_waiting_for_sign_in_or_approval(self):
        for status in ("awaiting_sign_in", "awaiting_approval"):
            with self.subTest(status=status):
                current = self.jobs.read_item("request", "reader")
                self.jobs.upsert_item(body={**current, "status": status})
                self.run_pending(
                    self.execute_successfully, can_resume=self.workflow_available,
                    approvals=object(), connection_ready=lambda job: self.fail("Sign-in is not needed to close stale work."),
                )
                current = self.jobs.read_item("request", "reader")
                self.assertEqual(current["status"], "failed")
        self.assertEqual(self.effects, [])

    def test_deletion_after_approval_read_is_still_authoritative(self):
        def can_resume(job, approval):
            if approval is not None:
                raise M365PolicyError("m365_workflow_missing", "The workflow no longer exists.")
            return True
        self.run_pending(self.execute_successfully, can_resume=can_resume)
        current = self.jobs.read_item("request", "reader")
        self.assertEqual(current["failure_code"], "workflow_deleted")
        self.assertEqual(self.effects, [])

    def test_deletion_between_check_and_execution_closes_only_unstarted_work(self):
        self.add_valid_job()
        def execute(job):
            if job["id"] == "request":
                raise M365ContinuationNotStarted()
            return self.execute_successfully(job)
        self.run_pending(execute)
        self.run_pending(execute)
        stale = self.jobs.read_item("request", "reader")
        self.assertEqual(stale["status"], "failed")
        self.assertEqual(stale["failure_code"], "workflow_deleted")
        self.assertNotIn("resume_lease_expires_at", stale)
        self.assertEqual(self.effects, ["later-request"])

    def test_missing_workflow_after_possible_effects_requires_recovery_and_does_not_block_later_work(self):
        self.add_valid_job()
        def execute(job):
            if job["id"] == "request":
                self.effects.append(job["id"])
                raise M365PolicyError("m365_workflow_missing", "The workflow no longer exists.")
            return self.execute_successfully(job)
        self.run_pending(execute)
        self.run_pending(execute)
        stale = self.jobs.read_item("request", "reader")
        self.assertEqual(stale["status"], "recovery_required")
        self.assertNotIn("failure_code", stale)
        self.assertEqual(self.effects, ["request", "later-request"])

    def test_unknown_execution_error_is_contained_logged_and_never_replayed(self):
        self.add_valid_job()
        def execute(job):
            if job["id"] == "request":
                self.effects.append(job["id"])
                raise RuntimeError("private-prompt-and-access-token")
            return self.execute_successfully(job)
        self.run_pending(execute)
        self.run_pending(execute)
        self.assertEqual(self.effects, ["request", "later-request"])
        failure = next(event[1] for event in self.events if event[1]["level"] == logging.ERROR)
        self.assertEqual(failure["extra"]["failure_code"], "continuation_execution_failed")
        self.assertEqual(failure["extra"]["error_type"], "RuntimeError")
        self.assertNotIn("private-prompt-and-access-token", repr(self.events))
        self.assertNotIn("'request_id':", repr(self.events))

    def test_transient_storage_authorization_and_same_message_failures_do_not_mean_deleted(self):
        failures = [
            PermissionError("The workflow no longer exists."),
            RuntimeError("The workflow no longer exists."),
            M365PolicyError("m365_workflow_changed", "The workflow no longer exists."),
            *(CosmosHttpResponseError(status_code=code, message="private storage details") for code in (403, 429, 503)),
        ]
        for error in failures:
            with self.subTest(error=type(error).__name__, code=getattr(error, "status_code", None)):
                self.setUp()
                self.add_valid_job()
                def can_resume(job, approval):
                    if job["id"] == "request":
                        raise error
                    return True
                self.run_pending(self.execute_successfully, can_resume=can_resume)
                current = self.jobs.read_item("request", "reader")
                self.assertEqual(current["status"], "awaiting_approval")
                self.assertNotIn("completed_at", current)
                self.assertEqual(self.effects, ["later-request"])
                self.assertTrue(any(event[1]["level"] == logging.ERROR for event in self.events))

    def test_approval_storage_failure_does_not_abort_later_jobs(self):
        self.add_valid_job()
        class UnavailableApproval(Approvals):
            def get_approval(self, approval_id, user_id):
                if approval_id == "approval":
                    raise CosmosHttpResponseError(status_code=503, message="temporarily unavailable")
                return super().get_approval(approval_id, user_id)
        self.run_pending(self.execute_successfully, approvals=UnavailableApproval())
        current = self.jobs.read_item("request", "reader")
        self.assertEqual(current["status"], "awaiting_approval")
        self.assertEqual(self.effects, ["later-request"])

    def test_stale_terminalization_cas_preserves_new_approval_cancellation_or_other_claim(self):
        for status in ("awaiting_approval", "cancelled", "resuming"):
            with self.subTest(status=status):
                self.setUp()
                self.add_valid_job()
                def change_record(item, body):
                    if item == "request":
                        self.jobs.before_replace = None
                        current = self.jobs.read_item(item, "reader")
                        self.jobs.upsert_item(body={
                            **current, "status": status, "approval_id": "new-approval",
                        })
                self.jobs.before_replace = change_record
                self.run_pending(self.execute_successfully, can_resume=self.workflow_available)
                current = self.jobs.read_item("request", "reader")
                self.assertEqual(current["status"], status)
                self.assertEqual(current["approval_id"], "new-approval")
                self.assertNotIn("failure_code", current)
                self.assertNotIn("completed_at", current)
                self.assertEqual(self.effects, ["later-request"])

    def test_delete_race_terminalization_preserves_a_newer_approval(self):
        self.add_valid_job()
        def execute(job):
            if job["id"] == "request":
                self.jobs.upsert_item(body={**job, "status": "awaiting_approval", "approval_id": "new-approval"})
                raise M365ContinuationNotStarted()
            return self.execute_successfully(job)
        self.run_pending(execute)
        current = self.jobs.read_item("request", "reader")
        self.assertEqual(current["status"], "awaiting_approval")
        self.assertEqual(current["approval_id"], "new-approval")
        self.assertNotIn("failure_code", current)
        self.assertEqual(self.effects, ["later-request"])

    def test_terminalization_storage_failure_preserves_the_unclaimed_job(self):
        self.add_valid_job()
        def fail_terminalization(item, body):
            if item == "request":
                raise CosmosHttpResponseError(status_code=503, message="storage unavailable")
        self.jobs.before_replace = fail_terminalization
        self.run_pending(self.execute_successfully, can_resume=self.workflow_available)
        current = self.jobs.read_item("request", "reader")
        self.assertEqual(current["status"], "awaiting_approval")
        self.assertNotIn("failure_code", current)
        self.assertEqual(self.effects, ["later-request"])
        self.jobs.before_replace = None
        self.run_pending(self.execute_successfully, can_resume=self.workflow_available)
        current = self.jobs.read_item("request", "reader")
        self.assertEqual(current["failure_code"], "workflow_deleted")
        self.assertEqual(self.effects, ["later-request"])

    def test_pending_approval_and_unready_connection_remain_unclaimed(self):
        class PendingApproval(Approvals):
            def get_approval(self, approval_id, user_id):
                return {"id": approval_id, "subject_user_id": user_id, "status": "pending"}
        self.run_pending(self.execute_successfully, approvals=PendingApproval())
        current = self.jobs.read_item("request", "reader")
        self.assertEqual(current["status"], "awaiting_approval")
        self.jobs.upsert_item(body={**current, "status": "awaiting_sign_in"})
        self.run_pending(self.execute_successfully, connection_ready=lambda job: False)
        current = self.jobs.read_item("request", "reader")
        self.assertEqual(current["status"], "awaiting_sign_in")
        self.assertEqual(self.effects, [])

    def test_claim_conflict_never_enters_execution_and_continues_batch(self):
        self.add_valid_job()
        def cancel_before_claim(item, body):
            if item == "request":
                self.jobs.before_replace = None
                self.jobs.upsert_item(body={**body, "status": "cancelled"})
        self.jobs.before_replace = cancel_before_claim
        self.run_pending(self.execute_successfully)
        current = self.jobs.read_item("request", "reader")
        self.assertEqual(current["status"], "cancelled")
        self.assertEqual(self.effects, ["later-request"])

    def test_execution_cannot_overwrite_new_approval_or_cancellation_on_error(self):
        for status in ("awaiting_approval", "cancelled"):
            with self.subTest(status=status):
                self.setUp()
                def execute(job):
                    self.jobs.upsert_item(body={**job, "status": status, "approval_id": "new-approval"})
                    raise RuntimeError("Worker stopped after saving a newer state")
                self.run_pending(execute)
                current = self.jobs.read_item("request", "reader")
                self.assertEqual(current["status"], status)
                self.assertEqual(current["approval_id"], "new-approval")

    def test_expired_uncertain_claim_is_recovered_without_checking_or_replaying_deleted_workflow(self):
        current = self.jobs.read_item("request", "reader")
        self.jobs.upsert_item(body={
            **current, "status": "resuming",
            "resume_lease_expires_at": (self.now - timedelta(minutes=1)).isoformat(),
        })
        self.run_pending(
            self.execute_successfully, can_resume=lambda *args: self.fail("A claimed effect is uncertain."),
        )
        self.run_pending(self.execute_successfully)
        current = self.jobs.read_item("request", "reader")
        self.assertEqual(current["status"], "recovery_required")
        self.assertNotIn("failure_code", current)
        self.assertEqual(self.effects, [])

    def test_active_claim_is_not_changed_or_executed(self):
        current = self.jobs.read_item("request", "reader")
        leased = self.jobs.upsert_item(body={
            **current, "status": "resuming",
            "resume_lease_expires_at": (self.now + timedelta(minutes=1)).isoformat(),
        })
        self.run_pending(self.execute_successfully)
        current = self.jobs.read_item("request", "reader")
        self.assertEqual(current, leased)
        self.assertEqual(self.effects, [])

    def test_acknowledgement_failure_leaves_claim_and_next_tick_recovers_without_replay(self):
        self.add_valid_job()
        def fail_acknowledgement(item, body):
            if item == "request" and body["status"] == "completed":
                raise CosmosHttpResponseError(status_code=503, message="private connection details")
        self.jobs.before_replace = fail_acknowledgement
        self.run_pending(self.execute_successfully)
        current = self.jobs.read_item("request", "reader")
        self.assertEqual(current["status"], "resuming")
        self.run_pending(self.execute_successfully)
        self.now += timedelta(minutes=16)
        self.run_pending(self.execute_successfully)
        current = self.jobs.read_item("request", "reader")
        self.assertEqual(current["status"], "recovery_required")
        self.assertEqual(self.effects, ["request", "later-request"])

    def test_failed_recovery_write_preserves_claim_and_continues_without_replay(self):
        self.add_valid_job()
        def fail_recovery(item, body):
            if item == "request" and body["status"] == "recovery_required":
                raise CosmosHttpResponseError(status_code=503, message="storage unavailable")
        def execute(job):
            if job["id"] == "request":
                self.effects.append(job["id"])
                raise RuntimeError("uncertain external write")
            return self.execute_successfully(job)
        self.jobs.before_replace = fail_recovery
        self.run_pending(execute)
        current = self.jobs.read_item("request", "reader")
        self.assertEqual(current["status"], "resuming")
        self.now += timedelta(minutes=16)
        self.run_pending(execute)
        current = self.jobs.read_item("request", "reader")
        self.assertEqual(current["status"], "resuming")
        self.jobs.before_replace = None
        self.run_pending(execute)
        current = self.jobs.read_item("request", "reader")
        self.assertEqual(current["status"], "recovery_required")
        self.assertEqual(self.effects, ["request", "later-request"])


if __name__ == "__main__":
    unittest.main()
