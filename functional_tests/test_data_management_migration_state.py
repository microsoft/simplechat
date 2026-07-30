# test_data_management_migration_state.py
"""
Functional test for Data Management migration checkpoint state.
Version: 0.250.078
Implemented in: 0.250.075

This test ensures in-app migration checkpoints retain one migration ID,
reject changed scopes, and expose durable transfer throughput metrics.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))

from functions_data_management_migration_state import (
    build_transfer_metrics,
    complete_migration_resource,
    initialize_migration_state,
    is_migration_resource_completed,
    start_migration_resource,
    update_migration_resource,
)


def test_data_management_migration_checkpoint_and_metrics():
    """Verify resumable resource state and calculated rate fields."""
    started_at = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
    configuration = {
        "migration_plan": {"users": {"mode": "selected", "ids": ["user-1"]}},
        "parallel_operations": 8,
    }
    state = initialize_migration_state(
        None,
        "11111111-1111-1111-1111-111111111111",
        configuration,
        current_time=started_at,
    )
    start_migration_resource(state, "cosmos:users:user_settings", current_time=started_at)
    metrics = build_transfer_metrics(
        state["resources"]["cosmos:users:user_settings"]["started_at"],
        copied_count=8,
        skipped_count=1,
        byte_count=900,
        request_units=45.5,
        current_time=started_at + timedelta(seconds=3),
    )
    update_migration_resource(
        state,
        "cosmos:users:user_settings",
        metrics,
        current_time=started_at + timedelta(seconds=3),
    )
    complete_migration_resource(
        state,
        "cosmos:users:user_settings",
        result=metrics,
        current_time=started_at + timedelta(seconds=3),
    )

    assert is_migration_resource_completed(state, "cosmos:users:user_settings")
    assert metrics["processed_count"] == 9
    assert metrics["items_per_second"] == 3.0
    assert metrics["bytes_per_second"] == 300.0
    assert metrics["request_units_per_second"] == round(45.5 / 3, 3)

    resumed_state = initialize_migration_state(
        state,
        "11111111-1111-1111-1111-111111111111",
        configuration,
        current_time=started_at + timedelta(minutes=1),
    )
    assert resumed_state["resume_count"] == 1
    assert is_migration_resource_completed(resumed_state, "cosmos:users:user_settings")

    changed_configuration = dict(configuration)
    changed_configuration["parallel_operations"] = 16
    try:
        initialize_migration_state(
            resumed_state,
            "11111111-1111-1111-1111-111111111111",
            changed_configuration,
            current_time=started_at + timedelta(minutes=2),
        )
    except ValueError as exc:
        assert "settings changed" in str(exc).lower()
    else:
        raise AssertionError("Checkpoint state accepted changed migration settings.")