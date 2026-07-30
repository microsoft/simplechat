# test_data_management_migration_provenance.py
"""
Functional test for Data Management migration provenance.
Version: 0.250.078
Implemented in: 0.250.075

This test ensures the application migration contract uses one durable GUID,
preserves Blob metadata, and only bypasses successful current or recent items.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))

from functions_migration_provenance import (
    add_cosmos_migration_provenance,
    add_search_migration_provenance,
    create_migration_provenance_context,
    get_blob_migration_provenance,
    get_cosmos_migration_provenance,
    get_search_migration_provenance,
    is_successful_migration_record,
    merge_blob_migration_metadata,
    migration_record_matches_source,
    should_skip_migration_record,
)


def test_data_management_migration_provenance_contract():
    """Validate provenance data and same-run or bounded recent skip behavior."""
    now = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
    context = create_migration_provenance_context(
        migration_id="11111111-1111-1111-1111-111111111111",
        migrated_at_utc=now,
        skip_within_hours=24,
    )

    cosmos_document = add_cosmos_migration_provenance({"id": "document-1"}, context)
    search_document = add_search_migration_provenance({"id": "document-1"}, context)
    blob_metadata = merge_blob_migration_metadata({"existing": "preserved"}, context)

    cosmos_record = get_cosmos_migration_provenance(cosmos_document)
    search_record = get_search_migration_provenance(search_document)
    blob_record = get_blob_migration_provenance(blob_metadata)

    assert cosmos_record == search_record == blob_record
    assert blob_metadata["existing"] == "preserved"
    assert should_skip_migration_record(cosmos_record, context, current_time=now)

    versioned_cosmos = add_cosmos_migration_provenance(
        {"id": "document-2"},
        context,
        source_version="1700000000",
    )
    hashed_search = add_search_migration_provenance(
        {"id": "document-2"},
        context,
        source_hash="sha256:abc123",
    )
    versioned_blob = merge_blob_migration_metadata(
        {},
        context,
        source_hash="sha256:def456",
        source_version="etag:123",
        scope_hash="scope-hash",
    )
    assert is_successful_migration_record(get_cosmos_migration_provenance(versioned_cosmos))
    assert migration_record_matches_source(
        get_cosmos_migration_provenance(versioned_cosmos),
        source_version="1700000000",
    )
    assert migration_record_matches_source(
        get_search_migration_provenance(hashed_search),
        source_hash="sha256:abc123",
    )
    assert migration_record_matches_source(
        get_blob_migration_provenance(versioned_blob),
        source_hash="sha256:def456",
    )
    assert get_blob_migration_provenance(versioned_blob)["scopeHash"] == "scope-hash"
    assert not migration_record_matches_source(
        get_blob_migration_provenance(versioned_blob),
        source_hash="sha256:changed",
    )
    assert not migration_record_matches_source(
        get_blob_migration_provenance(versioned_blob),
        source_hash="sha256:def456",
        source_version="etag:changed",
    )

    recent_record = {
        "migrationId": "22222222-2222-2222-2222-222222222222",
        "migratedAtUtc": (now - timedelta(hours=1)).isoformat(),
        "status": "succeeded",
    }
    stale_record = {
        "migrationId": "33333333-3333-3333-3333-333333333333",
        "migratedAtUtc": (now - timedelta(hours=25)).isoformat(),
        "status": "succeeded",
    }
    failed_record = {
        "migrationId": context["migration_id"],
        "migratedAtUtc": context["migrated_at_utc"],
        "status": "failed",
    }

    assert should_skip_migration_record(recent_record, context, current_time=now)
    assert not should_skip_migration_record(stale_record, context, current_time=now)
    assert not should_skip_migration_record(failed_record, context, current_time=now)