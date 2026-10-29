# test_m365_continuations.py
"""
Functional tests for conditional Microsoft 365 workflow continuation delivery.
Version: 0.261.029
Implemented in: 0.261.029

Approval delivery is idempotent and uncertain external execution is not replayed.
"""

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Test paths are installed before importing dependency-light application modules.
from functions_m365_continuations import resume_pending_workflows  # noqa: E402
from test_support.m365 import CosmosContainer  # noqa: E402


class PendingJobs(CosmosContainer):
    def query_items(self, **kwargs):
        return [
            self.read_item(record["id"], record["user_id"])
            for record in list(self.items.values())
            if record.get("status") in {"awaiting_approval", "ready_to_resume", "resuming"}
        ]


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

    def run_pending(self, execute):
        return resume_pending_workflows(
            self.jobs, Approvals(), execute=execute,
            can_resume=lambda job, approval: True,
            log_event=lambda *args, **kwargs: self.events.append(args),
            clock=lambda: datetime(2026, 9, 17, tzinfo=timezone.utc),
        )

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
        with self.assertRaises(RuntimeError):
            self.run_pending(execute)
        second = self.run_pending(execute)
        current = self.jobs.read_item("request", "reader")
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
        self.run_pending(execute)
        current = self.jobs.read_item("request", "reader")
        self.assertEqual(current["status"], "awaiting_approval")
        self.assertEqual(current["approval_id"], "second-approval")


if __name__ == "__main__":
    unittest.main()
