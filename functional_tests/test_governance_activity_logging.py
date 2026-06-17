# test_governance_activity_logging.py
#!/usr/bin/env python3
"""
Functional test for governance activity logging and policy mutation behavior.
Version: 0.241.010
Implemented in: 0.241.010

This test ensures that governance changes create activity log records with
activity_type/type set to governance and include detailed before/after fields.
"""

import os
import sys


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SINGLE_APP_DIR = os.path.join(CURRENT_DIR, "..", "application", "single_app")
if SINGLE_APP_DIR not in sys.path:
    sys.path.append(SINGLE_APP_DIR)

import functions_activity_logging as activity_logging
import functions_governance as governance


class _InMemoryContainer:
    def __init__(self):
        self.items = {}

    def read_item(self, item, partition_key):
        if item not in self.items:
            raise KeyError(item)
        return self.items[item]

    def upsert_item(self, body):
        item_id = str(body.get("id") or "").strip()
        if not item_id:
            raise ValueError("id is required")
        self.items[item_id] = dict(body)
        return self.items[item_id]


def test_log_governance_change_payload_shape():
    print("Testing governance activity log payload shape...")

    captured_records = []

    class _CaptureContainer:
        def create_item(self, body):
            captured_records.append(body)

    original_container = activity_logging.cosmos_activity_logs_container
    try:
        activity_logging.cosmos_activity_logs_container = _CaptureContainer()

        activity_logging.log_governance_change(
            admin_user_id="admin-123",
            admin_email="admin@example.com",
            action="feature_policy_updated",
            scope="feature_policy",
            target_id="feature:governance_user_agents",
            before_state={"allow_all": True},
            after_state={"allow_all": False},
            change_details={"users_added": ["user-a"]},
        )

        assert len(captured_records) == 1, "Expected exactly one governance activity record"
        record = captured_records[0]

        assert record.get("activity_type") == "governance", "activity_type must be governance"
        assert record.get("type") == "governance", "type must be governance"

        governance_change = record.get("governance_change") or {}
        assert governance_change.get("before") == {"allow_all": True}, "before payload mismatch"
        assert governance_change.get("after") == {"allow_all": False}, "after payload mismatch"
        assert governance_change.get("details") == {"users_added": ["user-a"]}, "details payload mismatch"

        print("PASS: governance activity payload includes required governance fields")
        return True
    finally:
        activity_logging.cosmos_activity_logs_container = original_container


def test_upsert_feature_policy_emits_detailed_diff():
    print("Testing governance feature policy diff generation...")

    original_container = governance.cosmos_governance_policies_container
    original_logger = governance.log_governance_change

    captured_logs = []

    def _capture_log(**kwargs):
        captured_logs.append(kwargs)

    try:
        governance.cosmos_governance_policies_container = _InMemoryContainer()
        governance.log_governance_change = _capture_log

        updated = governance.upsert_feature_policy(
            feature_key="governance_user_agents",
            payload={
                "allow_all": False,
                "allowed_users": ["user-1", "user-2"],
                "allowed_groups": ["group-1"],
            },
            actor_user_id="admin-xyz",
            actor_email="admin@example.com",
        )

        assert updated.get("allow_all") is False, "allow_all was not updated"
        assert sorted(updated.get("allowed_users", [])) == ["user-1", "user-2"], "allowed_users mismatch"
        assert updated.get("allowed_groups") == ["group-1"], "allowed_groups mismatch"

        assert len(captured_logs) == 1, "Expected one governance log event"
        details = captured_logs[0].get("change_details") or {}
        assert details.get("allow_all", {}).get("before") is True, "diff.before allow_all mismatch"
        assert details.get("allow_all", {}).get("after") is False, "diff.after allow_all mismatch"
        assert details.get("users_added") == ["user-1", "user-2"], "users_added mismatch"
        assert details.get("groups_added") == ["group-1"], "groups_added mismatch"

        print("PASS: governance feature policy emits detailed diff data")
        return True
    finally:
        governance.cosmos_governance_policies_container = original_container
        governance.log_governance_change = original_logger


if __name__ == "__main__":
    tests = [
        test_log_governance_change_payload_shape,
        test_upsert_feature_policy_emits_detailed_diff,
    ]
    results = []

    for test in tests:
        try:
            results.append(test())
        except Exception as exc:
            print(f"FAIL: {test.__name__} -> {exc}")
            results.append(False)

    passed = sum(1 for result in results if result)
    print(f"Results: {passed}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
