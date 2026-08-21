# functions_migration_provenance.py
"""Durable provenance metadata shared by in-app migration destinations."""

from datetime import datetime, timedelta, timezone
import uuid


MIGRATION_PROVENANCE_STATUS_SUCCEEDED = "succeeded"
COSMOS_MIGRATION_PROVENANCE_FIELD = "simplechatMigration"
SEARCH_MIGRATION_ID_FIELD = "simplechatMigrationId"
SEARCH_MIGRATED_AT_FIELD = "simplechatMigratedAtUtc"
SEARCH_MIGRATION_STATUS_FIELD = "simplechatMigrationStatus"
SEARCH_MIGRATION_SOURCE_HASH_FIELD = "simplechatMigrationSourceHash"
SEARCH_MIGRATION_SOURCE_VERSION_FIELD = "simplechatMigrationSourceVersion"
BLOB_MIGRATION_ID_METADATA_KEY = "simplechatMigrationId"
BLOB_MIGRATED_AT_METADATA_KEY = "simplechatMigratedAtUtc"
BLOB_MIGRATION_STATUS_METADATA_KEY = "simplechatMigrationStatus"
BLOB_MIGRATION_SOURCE_HASH_METADATA_KEY = "simplechatMigrationSourceHash"
BLOB_MIGRATION_SOURCE_VERSION_METADATA_KEY = "simplechatMigrationSourceVersion"
BLOB_MIGRATION_SCOPE_HASH_METADATA_KEY = "simplechatMigrationScopeHash"


def _parse_utc_datetime(value):
    """Return an aware UTC timestamp when the supplied value is valid."""
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _utc_iso(value):
    """Format a UTC datetime using the durable migration metadata format."""
    parsed = _parse_utc_datetime(value)
    if parsed is None:
        raise ValueError("Migration timestamp must be a valid UTC datetime.")
    return parsed.isoformat()


def _record_value(record, *names):
    """Read the first available provenance value without changing stored data."""
    if not isinstance(record, dict):
        return None
    for name in names:
        if name in record:
            return record.get(name)
    return None


def create_migration_provenance_context(migration_id=None, migrated_at_utc=None, skip_within_hours=0):
    """Create a validated provenance context for one durable migration job."""
    try:
        normalized_migration_id = str(uuid.UUID(str(migration_id or uuid.uuid4())))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Migration ID must be a valid GUID.") from exc

    try:
        normalized_skip_hours = int(skip_within_hours)
    except (TypeError, ValueError) as exc:
        raise ValueError("Migration provenance skip window must be an integer number of hours.") from exc
    if normalized_skip_hours < 0 or normalized_skip_hours > 8760:
        raise ValueError("Migration provenance skip window must be between 0 and 8760 hours.")

    return {
        "migration_id": normalized_migration_id,
        "migrated_at_utc": _utc_iso(migrated_at_utc or datetime.now(timezone.utc)),
        "skip_within_hours": normalized_skip_hours,
    }


def build_migration_provenance_record(
    context,
    source_hash="",
    source_version="",
    scope_hash="",
):
    """Return the neutral, destination-independent success record."""
    record = {
        "migrationId": str((context or {}).get("migration_id") or ""),
        "migratedAtUtc": str((context or {}).get("migrated_at_utc") or ""),
        "status": MIGRATION_PROVENANCE_STATUS_SUCCEEDED,
    }
    if source_hash:
        record["sourceHash"] = str(source_hash)
    if source_version:
        record["sourceVersion"] = str(source_version)
    if scope_hash:
        record["scopeHash"] = str(scope_hash)
    return record


def is_successful_migration_record(record):
    """Return whether a destination item has durable successful migration ownership."""
    if not isinstance(record, dict):
        return False
    status = str(_record_value(record, "status", "migrationStatus") or "").strip().lower()
    migration_id = str(_record_value(record, "migrationId", "migration_id") or "").strip()
    return status == MIGRATION_PROVENANCE_STATUS_SUCCEEDED and bool(migration_id)


def migration_record_matches_source(record, source_hash="", source_version=""):
    """Compare an owned destination marker with the current source fingerprint."""
    if not is_successful_migration_record(record):
        return False
    normalized_hash = str(source_hash or "").strip()
    normalized_version = str(source_version or "").strip()
    if not normalized_hash and not normalized_version:
        return False
    if normalized_hash and (
        str(_record_value(record, "sourceHash", "source_hash") or "").strip() != normalized_hash
    ):
        return False
    if normalized_version and (
        str(_record_value(record, "sourceVersion", "source_version") or "").strip() !=
        normalized_version
    ):
        return False
    return True


def should_skip_migration_record(record, context, current_time=None):
    """Return whether a successful current or recent migration owns an item."""
    status = str(_record_value(record, "status", "migrationStatus") or "").strip().lower()
    if status != MIGRATION_PROVENANCE_STATUS_SUCCEEDED:
        return False

    migration_id = str(_record_value(record, "migrationId", "migration_id") or "").strip()
    context_migration_id = str((context or {}).get("migration_id") or "").strip()
    if migration_id and migration_id.lower() == context_migration_id.lower():
        return True

    try:
        skip_within_hours = int((context or {}).get("skip_within_hours") or 0)
    except (TypeError, ValueError):
        return False
    if skip_within_hours <= 0:
        return False

    migrated_at = _parse_utc_datetime(_record_value(record, "migratedAtUtc", "migrated_at_utc"))
    now = _parse_utc_datetime(current_time or datetime.now(timezone.utc))
    if migrated_at is None or now is None:
        return False
    return migrated_at >= now - timedelta(hours=skip_within_hours)


def add_cosmos_migration_provenance(document, context, source_hash="", source_version=""):
    """Add migration provenance to a writable Cosmos document."""
    if not isinstance(document, dict):
        raise ValueError("Cosmos migration documents must be dictionaries.")
    document[COSMOS_MIGRATION_PROVENANCE_FIELD] = build_migration_provenance_record(
        context,
        source_hash=source_hash,
        source_version=source_version,
    )
    return document


def get_cosmos_migration_provenance(document):
    """Get a Cosmos document's migration record when present."""
    if not isinstance(document, dict):
        return None
    value = document.get(COSMOS_MIGRATION_PROVENANCE_FIELD)
    return value if isinstance(value, dict) else None


def add_search_migration_provenance(document, context, source_hash="", source_version=""):
    """Add migration provenance to a writable Azure AI Search document."""
    if not isinstance(document, dict):
        raise ValueError("AI Search migration documents must be dictionaries.")
    record = build_migration_provenance_record(
        context,
        source_hash=source_hash,
        source_version=source_version,
    )
    document[SEARCH_MIGRATION_ID_FIELD] = record["migrationId"]
    document[SEARCH_MIGRATED_AT_FIELD] = record["migratedAtUtc"]
    document[SEARCH_MIGRATION_STATUS_FIELD] = record["status"]
    if record.get("sourceHash"):
        document[SEARCH_MIGRATION_SOURCE_HASH_FIELD] = record["sourceHash"]
    if record.get("sourceVersion"):
        document[SEARCH_MIGRATION_SOURCE_VERSION_FIELD] = record["sourceVersion"]
    return document


def get_search_migration_provenance(document):
    """Translate Azure AI Search provenance fields into the neutral record."""
    if not isinstance(document, dict):
        return None
    record = {
        "migrationId": document.get(SEARCH_MIGRATION_ID_FIELD),
        "migratedAtUtc": document.get(SEARCH_MIGRATED_AT_FIELD),
        "status": document.get(SEARCH_MIGRATION_STATUS_FIELD),
    }
    if document.get(SEARCH_MIGRATION_SOURCE_HASH_FIELD):
        record["sourceHash"] = document.get(SEARCH_MIGRATION_SOURCE_HASH_FIELD)
    if document.get(SEARCH_MIGRATION_SOURCE_VERSION_FIELD):
        record["sourceVersion"] = document.get(SEARCH_MIGRATION_SOURCE_VERSION_FIELD)
    return record


def merge_blob_migration_metadata(
    metadata,
    context,
    source_hash="",
    source_version="",
    scope_hash="",
):
    """Preserve existing Blob metadata while appending migration provenance."""
    merged = {
        str(key): str(value)
        for key, value in (metadata or {}).items()
        if key is not None and value is not None
    }
    record = build_migration_provenance_record(
        context,
        source_hash=source_hash,
        source_version=source_version,
        scope_hash=scope_hash,
    )
    merged[BLOB_MIGRATION_ID_METADATA_KEY] = record["migrationId"]
    merged[BLOB_MIGRATED_AT_METADATA_KEY] = record["migratedAtUtc"]
    merged[BLOB_MIGRATION_STATUS_METADATA_KEY] = record["status"]
    if record.get("sourceHash"):
        merged[BLOB_MIGRATION_SOURCE_HASH_METADATA_KEY] = record["sourceHash"]
    if record.get("sourceVersion"):
        merged[BLOB_MIGRATION_SOURCE_VERSION_METADATA_KEY] = record["sourceVersion"]
    if record.get("scopeHash"):
        merged[BLOB_MIGRATION_SCOPE_HASH_METADATA_KEY] = record["scopeHash"]
    return merged


def get_blob_migration_provenance(metadata):
    """Translate Blob metadata provenance fields into the neutral record."""
    values = metadata or {}
    record = {
        "migrationId": values.get(BLOB_MIGRATION_ID_METADATA_KEY),
        "migratedAtUtc": values.get(BLOB_MIGRATED_AT_METADATA_KEY),
        "status": values.get(BLOB_MIGRATION_STATUS_METADATA_KEY),
    }
    if values.get(BLOB_MIGRATION_SOURCE_HASH_METADATA_KEY):
        record["sourceHash"] = values.get(BLOB_MIGRATION_SOURCE_HASH_METADATA_KEY)
    if values.get(BLOB_MIGRATION_SOURCE_VERSION_METADATA_KEY):
        record["sourceVersion"] = values.get(BLOB_MIGRATION_SOURCE_VERSION_METADATA_KEY)
    if values.get(BLOB_MIGRATION_SCOPE_HASH_METADATA_KEY):
        record["scopeHash"] = values.get(BLOB_MIGRATION_SCOPE_HASH_METADATA_KEY)
    return record