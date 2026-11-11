# test_admin_support_export_filters.py
"""
Functional tests for bounded support-export contracts.
Version: 0.261.426
Implemented in: 0.261.426

Validate explicit scope, UTC windows, source configuration, and rejection of
oversized or ambiguous requests without any Azure/bootstrap dependency.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

from support_export_contracts import (
    MAX_BYTES, MAX_RECORDS, SupportExportError, check_size, normalize_configuration,
    normalize_request, resolve_intervals,
)


NOW = datetime(2026, 11, 10, 18, tzinfo=timezone.utc)


def test_time_defaults_and_explicit_scope():
    plan = normalize_request({"user_id": "user-1"}, NOW)
    assert plan["start"] == "2026-11-10T17:00:00+00:00"
    assert plan["end"] == "2026-11-10T18:00:00+00:00"
    assert plan["privacy"] == "deterministic"
    with pytest.raises(SupportExportError):
        normalize_request({}, NOW)
    with pytest.raises(SupportExportError):
        normalize_request({"all_users": True, "conversation_ids": ["one"]}, NOW)


@pytest.mark.parametrize("changes", [
    {"all_users": "true"}, {"privacy": "none"}, {"sources": ["arbitrary_table"]},
    {"conversation_ids": ["../not-an-id"]}, {"sources": ["console"]},
    {"before_minutes": True}, {"mode": "unknown"}, {"before_minutes": 1441},
    {"start": "2026-11-10T12:00:00"}, {"start": "2026-10-01T00:00:00Z"},
    {"start": "2026-11-11T00:00:00Z"}, {"unknown": "ignored"},
])
def test_invalid_requests_are_not_success_shaped(changes):
    with pytest.raises(SupportExportError):
        normalize_request({"user_id": "user-1", **changes}, NOW)


def test_disjoint_conversation_windows_and_overlap_merge():
    plan = normalize_request({
        "user_id": "user-1", "mode": "conversations", "conversation_ids": ["one", "two"],
    }, NOW)
    intervals = resolve_intervals(plan, [
        {"first_activity": "2026-11-10T10:00:00Z", "last_activity": "2026-11-10T10:05:00Z"},
        {"first_activity": "2026-11-10T15:00:00Z", "last_activity": "2026-11-10T15:05:00Z"},
    ], NOW)
    assert len(intervals) == 2
    assert intervals[0][0] == "2026-11-10T09:45:00+00:00"
    intervals = resolve_intervals(plan, [
        {"first_activity": "2026-11-10T10:00:00Z", "last_activity": "2026-11-10T10:05:00Z"},
        {"first_activity": "2026-11-10T10:10:00Z", "last_activity": "2026-11-10T10:20:00Z"},
    ], NOW)
    assert len(intervals) == 1


def test_effective_span_and_missing_activity_are_rejected():
    plan = normalize_request({"user_id": "user-1", "mode": "conversations", "conversation_ids": ["one"]}, NOW)
    for metadata in (
        [{"first_activity": None, "last_activity": None}],
        [{"first_activity": "2026-11-01T00:00:00Z", "last_activity": "2026-11-10T00:00:00Z"}],
    ):
        with pytest.raises(SupportExportError):
            resolve_intervals(plan, metadata, NOW)


def test_timezone_normalization_and_bounded_configuration():
    plan = normalize_request({
        "user_id": "user-1", "start": "2026-11-10T10:00:00-05:00", "end": "2026-11-10T11:00:00-05:00",
    }, NOW)
    assert plan["start"] == "2026-11-10T15:00:00+00:00"
    configuration = normalize_configuration({
        "cloud": "usgovernment",
        "app_resource_id": "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg/providers/Microsoft.Insights/components/app",
    })
    assert configuration["cloud"] == "usgovernment"
    with pytest.raises(SupportExportError):
        normalize_configuration({"cloud": "custom", "endpoint": "https://example.test"})
    with pytest.raises(SupportExportError):
        check_size(MAX_RECORDS + 1, 0)
    with pytest.raises(SupportExportError):
        check_size(1, MAX_BYTES + 1)
