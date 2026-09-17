# functions_embedding_compatibility.py
"""Fail-closed embedding activation and persisted-vector write boundaries."""

import copy
import logging
import uuid
from contextlib import contextmanager

from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import AzureError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.search.documents.indexes import SearchIndexClient

from app_settings_store import SettingsConflictError, SettingsUnavailableError
from functions_ai_connections import AIConnectionError, EMBEDDING_SELECTION_KEY, embedding_settings_use_connections
from functions_appinsights import log_event
from functions_data_management_search_write_fence import (
    acquire_data_management_search_write_fence,
    hold_data_management_search_write_slot,
    publish_data_management_embedding_profile,
    release_data_management_search_write_fence,
    renew_data_management_search_write_fence,
)
from functions_embedding_profile import (
    EMBEDDING_PROFILE_FIELD,
    EMBEDDING_SEARCH_INDEXES,
    EMBEDDING_VECTOR_FIELDS,
    EMBEDDING_VECTOR_PROFILE_KEY,
    resolve_embedding_profile,
)


REMOTE_OPTIONS = {"connection_timeout": 10, "read_timeout": 30, "retry_total": 0}


def _runtime_containers():
    # Config owns the existing containers; pure profile resolution never imports it.
    from config import cosmos_settings_container, cosmos_data_management_jobs_container, cosmos_agent_facts_container

    return cosmos_settings_container, cosmos_data_management_jobs_container, cosmos_agent_facts_container


def _get_embedding_settings_store():
    # Resolve the configured shared store only when runtime settings are needed.
    from functions_settings import _get_app_settings_store

    return _get_app_settings_store()


def read_embedding_settings():
    try:
        settings = _get_embedding_settings_store().read(use_cosmos=True)
    except (AzureError, SettingsUnavailableError, SettingsConflictError) as exc:
        log_event("[EMBEDDING] Settings could not be read", extra={"error_type": type(exc).__name__})
        raise AIConnectionError(
            "Embedding configuration is temporarily unavailable.", "embedding_compatibility_unavailable",
        ) from exc
    if not isinstance(settings, dict):
        raise AIConnectionError("Embedding configuration is invalid.", "embedding_compatibility_unavailable")
    return settings


def get_embedding_search_index_client(settings):
    from config import AZURE_ENVIRONMENT, search_resource_manager

    apim = bool(settings.get("enable_ai_search_apim"))
    endpoint = settings.get("azure_apim_ai_search_endpoint" if apim else "azure_ai_search_endpoint")
    if not endpoint:
        return None
    options = dict(REMOTE_OPTIONS)
    if not apim and settings.get("azure_ai_search_authentication_type") == "managed_identity":
        credential = DefaultAzureCredential()
        if AZURE_ENVIRONMENT in ("usgovernment", "custom"):
            options["audience"] = search_resource_manager
    else:
        key = settings.get("azure_apim_ai_search_subscription_key" if apim else "azure_ai_search_key")
        if not isinstance(key, str) or not key:
            raise AIConnectionError("AI Search credentials are required to inspect embedding compatibility.")
        credential = AzureKeyCredential(key)
    return SearchIndexClient(endpoint=endpoint, credential=credential, **options)


def _optional_profile(settings):
    try:
        return resolve_embedding_profile(settings)
    except AIConnectionError as exc:
        if exc.code == "model_configuration_unavailable":
            return None
        raise


def _previous_profile(settings):
    try:
        return _optional_profile(settings)
    except AIConnectionError as exc:
        # An invalid prior configuration is not proof of empty data. The replacement
        # still has to pass a complete store inspection before it can be activated.
        log_event("[EMBEDDING] Prior configuration is unavailable", extra={"code": exc.code})
        return None


def embedding_settings_changed(current, candidate):
    if embedding_settings_use_connections(current) or embedding_settings_use_connections(candidate):
        if current.get(EMBEDDING_SELECTION_KEY) != candidate.get(EMBEDDING_SELECTION_KEY):
            return True
        return _selected_connection_snapshot(current) != _selected_connection_snapshot(candidate)
    keys = {key for key in (*current, *candidate) if key.startswith(("azure_openai_embedding_", "azure_apim_embedding_"))}
    keys.update(("embedding_model", "enable_embedding_apim"))
    return any(current.get(key) != candidate.get(key) for key in keys)


def _selected_connection_snapshot(settings):
    selection = settings.get(EMBEDDING_SELECTION_KEY) or {}
    for endpoint in settings.get("model_endpoints") or []:
        if isinstance(endpoint, dict) and endpoint.get("id") == selection.get("endpoint_id"):
            snapshot = copy.deepcopy(endpoint)
            snapshot["models"] = [
                model for model in endpoint.get("models") or []
                if isinstance(model, dict) and (model.get("id") or model.get("deploymentName")) == selection.get("model_id")
            ]
            connection = snapshot.get("connection") or {}
            connection["operation_settings"] = {
                "embeddings": (connection.get("operation_settings") or {}).get("embeddings"),
            }
            return snapshot
    return None


def _check_index_dimensions(index, dimensions):
    fields = {field.name: field for field in index.fields}
    for field_name in EMBEDDING_VECTOR_FIELDS:
        field = fields.get(field_name)
        if field is not None and field.vector_search_dimensions != dimensions:
            raise AIConnectionError(
                f"AI Search index {index.name} has incompatible {field_name} dimensions. Recreate empty indexes for the selected embedding dimensions before switching.",
                "embedding_dimensions_mismatch",
            )


def build_embedding_index_schema(definition, settings):
    result = copy.deepcopy(definition)
    profile = _optional_profile(settings)
    dimensions = (
        profile.dimensions if profile else
        (settings.get(EMBEDDING_VECTOR_PROFILE_KEY) or {}).get("dimensions", 1536)
    )
    if isinstance(dimensions, bool) or not isinstance(dimensions, int) or dimensions <= 0:
        raise AIConnectionError("The stored embedding dimensions are invalid.")
    for field in result.get("fields") or []:
        if field.get("name") in EMBEDDING_VECTOR_FIELDS:
            field["dimensions"] = dimensions
    return result


def validate_embedding_index_schema(index, definition):
    dimensions = next(
        field["dimensions"] for field in definition["fields"] if field["name"] == "embedding"
    )
    _check_index_dimensions(index, dimensions)


def inspect_empty_embedding_stores(settings, profile, *, index_client=None, facts_container=None):
    """Inspect all app-managed stores; service errors never mean that a store is empty."""
    if facts_container is None:
        _, _, facts_container = _runtime_containers()
    owns_index_client = index_client is None
    if owns_index_client:
        index_client = get_embedding_search_index_client(settings)
    index_metadata = {}
    try:
        if index_client is not None:
            for name in EMBEDDING_SEARCH_INDEXES:
                try:
                    index = index_client.get_index(name)
                    _check_index_dimensions(index, profile.dimensions)
                    index_metadata[name] = _index_metadata(index, profile.dimensions)
                    with index_client.get_search_client(name) as client:
                        count = client.get_document_count(**REMOTE_OPTIONS)
                        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                            raise AIConnectionError(
                                "The AI Search document count could not be verified.",
                                "embedding_compatibility_unavailable",
                            )
                        if count:
                            raise AIConnectionError(
                                "Changing embedding models requires rebuilding existing document vectors, even when dimensions match. Empty/recreate all document indexes before activating another vector space.",
                                "embedding_rebuild_required",
                            )
                except ResourceNotFoundError:
                    index_metadata[name] = {"exists": False}
                    continue
        if facts_container is None:
            raise AIConnectionError("Fact-memory storage could not be inspected.", "embedding_compatibility_unavailable")
        try:
            facts = facts_container.query_items(
                query="SELECT TOP 1 c.id FROM c WHERE IS_ARRAY(c.value_embedding) AND ARRAY_LENGTH(c.value_embedding) > 0",
                enable_cross_partition_query=True,
                max_item_count=1,
            )
            if next(iter(facts), None) is not None:
                raise AIConnectionError(
                    "Existing fact-memory vectors require rebuilding before changing embedding models. Preserve fact text and explicitly clear incompatible vectors first.",
                    "embedding_rebuild_required",
                )
        except ResourceNotFoundError:
            pass
        return index_metadata
    except AzureError as exc:
        log_event("[EMBEDDING] Compatibility inspection failed", extra={"error_type": type(exc).__name__})
        raise AIConnectionError(
            "Embedding compatibility could not be checked. Review access to AI Search and fact-memory storage.",
            "embedding_compatibility_unavailable",
        ) from exc
    finally:
        if owns_index_client and index_client is not None:
            index_client.close()


def preflight_embedding_settings(current, candidate):
    """Reject incompatible edits before an editor stages credentials; commit checks again."""
    if not embedding_settings_changed(current, candidate):
        return
    profile = _optional_profile(candidate)
    if profile is None:
        return
    baseline = current.get(EMBEDDING_VECTOR_PROFILE_KEY) or {}
    previous = _previous_profile(current) if not baseline else None
    prior_id = baseline.get("id") or (previous.profile_id if previous else None)
    if profile.profile_id != prior_id:
        _, jobs_container, _ = _runtime_containers()
        fence = acquire_data_management_search_write_fence(
            jobs_container, f"embedding-preflight-{uuid.uuid4().hex}", lease_seconds=600,
        )
        try:
            _check_embedding_write_history(fence, baseline or (previous.as_state() if previous else {}))
            inspect_empty_embedding_stores(candidate, profile)
        finally:
            if not release_data_management_search_write_fence(jobs_container, fence):
                log_event("[EMBEDDING] Preflight fence release failed", level=logging.WARNING)


def _check_embedding_write_history(fence, baseline):
    if fence.get("embedding_vectors_written") or (
        baseline.get("legacy") and fence.get("embedding_vectors_written") is not False
    ):
        raise AIConnectionError(
            "Embedding write history requires a controlled external rebuild. Clear the vector stores and reset the embedding write ledger before switching models.",
            "embedding_rebuild_required",
        )


@contextmanager
def embedding_settings_write_guard(current, candidate, *, force_check=False):
    """Hold the existing distributed Search fence across inspection and settings CAS."""
    # A generic settings payload cannot replace the durable vector-space baseline.
    candidate.pop(EMBEDDING_VECTOR_PROFILE_KEY, None)
    if EMBEDDING_VECTOR_PROFILE_KEY in current:
        candidate[EMBEDDING_VECTOR_PROFILE_KEY] = copy.deepcopy(current[EMBEDDING_VECTOR_PROFILE_KEY])
    if not embedding_settings_changed(current, candidate) and not force_check:
        yield
        return
    profile = _optional_profile(candidate)
    previous = _previous_profile(current) if not current.get(EMBEDDING_VECTOR_PROFILE_KEY) else None
    baseline = current.get(EMBEDDING_VECTOR_PROFILE_KEY) or (previous.as_state() if previous else {})
    if baseline:
        candidate[EMBEDDING_VECTOR_PROFILE_KEY] = copy.deepcopy(baseline)
    target_id = profile.profile_id if profile else baseline.get("id")
    changing_space = profile is not None and profile.profile_id != baseline.get("id")
    if not target_id or (not changing_space and not force_check):
        yield
        return
    _, jobs_container, _ = _runtime_containers()
    fence = acquire_data_management_search_write_fence(
        jobs_container, f"embedding-activation-{uuid.uuid4().hex}", lease_seconds=600,
    )
    try:
        if changing_space:
            _check_embedding_write_history(fence, baseline)
            index_metadata = inspect_empty_embedding_stores(candidate, profile)
            candidate[EMBEDDING_VECTOR_PROFILE_KEY] = {**profile.as_state(), "indexes": index_metadata}
        renew_data_management_search_write_fence(jobs_container, fence, 600)
        # An indeterminate settings write must not let stale workers resume old vectors.
        publish_data_management_embedding_profile(jobs_container, fence, f"pending:{uuid.uuid4().hex}")
        yield
        publish_data_management_embedding_profile(
            jobs_container, fence, target_id if profile is not None else f"inactive:{target_id}",
        )
    finally:
        if not release_data_management_search_write_fence(jobs_container, fence):
            log_event("[EMBEDDING] Activation fence release failed", level=logging.WARNING)


def active_embedding_profile(settings=None):
    settings = read_embedding_settings() if settings is None else settings
    profile = resolve_embedding_profile(settings)
    baseline = settings.get(EMBEDDING_VECTOR_PROFILE_KEY) or {}
    if baseline.get("id") and baseline["id"] != profile.profile_id:
        raise AIConnectionError(
            "The configured embedding model does not match the stored vector space. Restore the previous connection or complete the documented rebuild.",
            "embedding_profile_mismatch",
        )
    return profile


def assert_embedding_vector_current(vector, settings=None):
    profile = active_embedding_profile(settings)
    if not getattr(vector, "profile_id", None) or vector.profile_id != profile.profile_id:
        raise AIConnectionError(
            "The embedding model changed while this work was running. Retry with the active model.",
            "embedding_profile_changed",
        )
    if len(vector) != profile.dimensions:
        raise AIConnectionError("The embedding vector dimensions are incompatible.", "embedding_dimensions_mismatch")
    return profile


def _index_metadata(index, dimensions):
    return {
        "exists": True, "dimensions": dimensions,
        "provenance": any(field.name == EMBEDDING_PROFILE_FIELD for field in index.fields),
    }


@contextmanager
def embedding_index_maintenance(settings):
    profile = _optional_profile(settings)
    _, jobs_container, _ = _runtime_containers()
    with hold_data_management_search_write_slot(
        jobs_container, embedding_profile_id=profile.profile_id if profile else "unconfigured",
        records_vectors=False,
    ):
        yield


def record_embedding_index_schema(index, settings):
    """Persist admin-observed schema metadata; inference keeps its data-plane-only roles."""
    expected = _optional_profile(settings)
    if expected is None:
        return
    _check_index_dimensions(index, expected.dimensions)
    def record_observation(current):
        actual = active_embedding_profile(current)
        if actual.profile_id != expected.profile_id:
            raise AIConnectionError("The embedding model changed during index maintenance. Reload and retry.", "embedding_profile_changed")
        baseline = copy.deepcopy(current.get(EMBEDDING_VECTOR_PROFILE_KEY) or expected.as_state())
        indexes = dict(baseline.get("indexes") or {})
        indexes[index.name] = _index_metadata(index, expected.dimensions)
        baseline["indexes"] = indexes
        current[EMBEDDING_VECTOR_PROFILE_KEY] = baseline
        return current

    try:
        _get_embedding_settings_store().write(record_observation)
    except SettingsConflictError as exc:
        raise AIConnectionError(
            "Settings changed during index maintenance. Reload and retry.", "settings_conflict",
        ) from exc
    except SettingsUnavailableError as exc:
        raise AIConnectionError(
            "Index schema metadata could not be confirmed. Reload before retrying.",
            "embedding_compatibility_unavailable",
        ) from exc


def _runtime_index_metadata(search_client, profile, settings):
    index_name = getattr(search_client, "index_name", None) or getattr(search_client, "_index_name", None)
    if index_name not in EMBEDDING_SEARCH_INDEXES:
        raise AIConnectionError("The embedding search index is not an app-managed index.")
    baseline = settings.get(EMBEDDING_VECTOR_PROFILE_KEY) or {}
    metadata = (baseline.get("indexes") or {}).get(index_name) or {}
    if metadata.get("exists") and metadata.get("dimensions") != profile.dimensions:
        raise AIConnectionError("The stored index dimensions are incompatible.", "embedding_dimensions_mismatch")
    if metadata.get("exists") and metadata.get("provenance"):
        return metadata
    if profile.legacy:
        return {"provenance": False}
    raise AIConnectionError(
        "Update AI Search index fields in administration before using this embedding model.",
        "embedding_schema_update_required",
    )


def prepare_embedding_search_documents(search_client, documents, settings=None):
    """Called inside the Search write slot, so activation cannot race the mutation."""
    vector_documents = [doc for doc in documents if isinstance(doc, dict) and doc.get("embedding") is not None]
    if not vector_documents:
        return
    settings = read_embedding_settings() if settings is None else settings
    profile = active_embedding_profile(settings)
    for doc in vector_documents:
        assert_embedding_vector_current(doc["embedding"], settings)
    has_provenance = _runtime_index_metadata(search_client, profile, settings).get("provenance")
    for doc in vector_documents:
        if has_provenance:
            doc[EMBEDDING_PROFILE_FIELD] = profile.profile_id


def embedding_search_filter(search_client, profile, settings):
    if not _runtime_index_metadata(search_client, profile, settings).get("provenance"):
        return ""
    # profile_id is a server-computed hex digest, never request-supplied OData.
    matching = f"{EMBEDDING_PROFILE_FIELD} eq '{profile.profile_id}'"
    return f"({matching} or {EMBEDDING_PROFILE_FIELD} eq null)" if profile.legacy else matching


@contextmanager
def embedding_query_slot(profile_id):
    _, jobs_container, _ = _runtime_containers()
    with hold_data_management_search_write_slot(
        jobs_container, embedding_profile_id=profile_id, records_vectors=False,
    ):
        yield


def search_with_embedding_profile(search_client, profile, **kwargs):
    """Fence each bounded Search page against a cross-worker profile transition."""
    kwargs.update(REMOTE_OPTIONS)
    pages = iter(search_client.search(**kwargs).by_page())
    results = []
    while True:
        with embedding_query_slot(profile.profile_id):
            page = next(pages, None)
            if page is None:
                return results
            results.extend(page)
        if len(results) >= kwargs["top"]:
            return results[:kwargs["top"]]


def persist_fact_with_embedding(container, item, vector):
    _, jobs_container, _ = _runtime_containers()
    vector_profile = getattr(vector, "profile_id", None) or item.get(EMBEDDING_PROFILE_FIELD)
    # Untagged legacy facts may be retained, but their write still participates in the ledger.
    if not vector_profile:
        vector_profile = active_embedding_profile().profile_id
    with hold_data_management_search_write_slot(jobs_container, embedding_profile_id=vector_profile):
        profile = active_embedding_profile()
        provenance = getattr(vector, "profile_id", None) or item.get(EMBEDDING_PROFILE_FIELD)
        if vector_profile != profile.profile_id or (not provenance and not profile.legacy):
            raise AIConnectionError(
                "The fact embedding belongs to another model. Regenerate it before saving.",
                "embedding_profile_changed",
            )
        if len(vector) != profile.dimensions:
            raise AIConnectionError("Fact embedding dimensions are incompatible.", "embedding_dimensions_mismatch")
        if provenance:
            item[EMBEDDING_PROFILE_FIELD] = profile.profile_id
        return container.upsert_item(item, **REMOTE_OPTIONS)


def embedding_compatibility_status(settings):
    """Read-only local status, not a paid probe or an expensive empty-store inspection."""
    try:
        profile = active_embedding_profile(settings)
    except AIConnectionError as exc:
        return {"status": "unavailable", "message": exc.public_message}
    return {
        "status": "legacy" if profile.legacy else "configured",
        "dimensions": profile.dimensions,
        "message": (
            "Existing vectors retain their legacy provenance. Changing models requires an explicit rebuild."
            if profile.legacy else
            "Changing models or dimensions requires empty/recreated document indexes and cleared fact-memory vectors."
        ),
    }
