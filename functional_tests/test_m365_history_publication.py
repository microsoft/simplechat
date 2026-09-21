# test_m365_history_publication.py
"""
Functional tests for publication of retained Microsoft 365 conversation evidence.
Version: 0.261.029
Implemented in: 0.261.029

The real policy and memory modules protect private snapshots, reject stale
approvals, and share captured evidence only after the owner's acknowledgement.
"""

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Test-only path setup precedes the real modules.
from functions_m365_history import M365HistoryService  # noqa: E402
from functions_m365_approvals import (  # noqa: E402
    M365ApprovalRequired, M365ApprovalService, M365PolicyError,
)
from functions_conversation_memory import (  # noqa: E402
    ConversationMemoryStore, EvidenceChunk, EvidenceSource, MemoryContext, MemoryAuthorizationError,
)
from test_conversation_working_memory import InMemoryBlobTransport  # noqa: E402
from test_support.m365 import Clock, CosmosContainer, Notifications  # noqa: E402


class HistoryPublicationTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock(datetime(2026, 9, 17, 12, tzinfo=timezone.utc))
        self.jobs = CosmosContainer("user_id")
        self.approvals = M365ApprovalService(
            container_factory=lambda: self.approval_records,
            notification_sender=Notifications(), clock=self.clock,
            decision_validator=lambda approval: self.service.validate_decision(approval),
        )
        self.approval_records = CosmosContainer()
        self.context = MemoryContext("tenant", "owner", "conversation", "owner")
        self.memory = ConversationMemoryStore(
            transport=InMemoryBlobTransport(), authorize_access=lambda context, operation: True,
            log_event=lambda *args, **kwargs: None, clock=self.clock,
        )
        self.conversation = {"id": "conversation", "user_id": "owner"}
        self.messages = [{
            "id": "answer", "_etag": "1", "content": "A shared finding",
            "metadata": {"m365_source_policies": {"spo": "request"}},
        }]
        self.active = False
        self.service = M365HistoryService(
            tenant_id="tenant", jobs=self.jobs, approvals=self.approvals,
            read_conversation=lambda scope, id: self.conversation,
            read_messages=lambda scope, id: self.messages,
            memory_resolver=lambda user, conversation, scope: (self.memory, self.context),
            audience_resolver=lambda user, conversation, scope, participants: str(participants),
            has_active_request=lambda id: self.active,
        )

    def pending(self):
        with self.assertRaises(M365ApprovalRequired) as error:
            self.service.prepare("owner", "conversation", "personal", [{"user_id": "reader"}])
        return error.exception

    def approve(self, pending, duration="request"):
        return self.approvals.decide(pending.approval_id, "owner", {
            "decisions": {"spo": {"duration": duration, "timezone": "America/New_York"}},
        })

    def test_source_history_needs_approval_without_remote_oauth(self):
        pending = self.pending()
        self.approve(pending)
        publication = self.service.prepare("owner", "conversation", "personal", [{"user_id": "reader"}])
        self.assertEqual(publication.approval_ids, (pending.approval_id,))
        self.assertEqual(len(publication.messages), 1)

    def test_changed_history_invalidates_decision(self):
        pending = self.pending()
        self.messages[0]["_etag"] = "2"
        with self.assertRaises(M365PolicyError):
            self.approve(pending)

    def test_decline_keeps_history_private(self):
        pending = self.pending()
        self.approvals.decide(pending.approval_id, "owner", {
            "decisions": {"spo": {"duration": "no"}},
        })
        with self.assertRaises(M365PolicyError):
            self.service.prepare("owner", "conversation", "personal", [{"user_id": "reader"}])

    def test_evidence_is_private_until_published_then_readable_to_participants(self):
        run = self.memory.create_run(self.context, request_id="capture", purpose="m365_file_spo")
        source = self.memory.add_evidence(
            self.context, run["run_id"],
            source=EvidenceSource("spo", "drive-item", "v1", coverage_complete=True),
            chunks=[EvidenceChunk("Captured source material beyond the answer.")],
        )
        self.memory.complete_run(self.context, run["run_id"])
        reader = replace(self.context, principal_id="reader")
        with self.assertRaises(MemoryAuthorizationError):
            self.memory.read_evidence_range(reader, run["run_id"], source["evidence_id"])
        self.messages.append({
            "id": "memory-ref", "artifact_kind": "conversation_memory",
            "metadata": {"memory_run_id": run["run_id"]},
        })
        pending = self.pending()
        self.approve(pending)
        self.service.prepare("owner", "conversation", "personal", [{"user_id": "reader"}])
        evidence = self.memory.read_evidence_range(reader, run["run_id"], source["evidence_id"])
        self.assertEqual(evidence["chunks"][0]["text"], "Captured source material beyond the answer.")

    def test_non_owner_or_active_capture_cannot_publish(self):
        with self.assertRaises(PermissionError):
            self.service.prepare("stranger", "conversation", "personal", [])
        self.active = True
        with self.assertRaises(M365PolicyError):
            self.service.prepare("owner", "conversation", "personal", [])

    def test_unrelated_history_does_not_need_m365_acknowledgement(self):
        self.messages[0]["metadata"] = {}
        result = self.service.prepare("owner", "conversation", "personal", [])
        self.assertEqual(result.approval_ids, ())


if __name__ == "__main__":
    unittest.main()
