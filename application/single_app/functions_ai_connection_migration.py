# functions_ai_connection_migration.py
"""Idempotent legacy image import; pure planning is separate from startup I/O."""

import copy
import uuid
from collections.abc import Mapping
from urllib.parse import urlsplit

from functions_ai_connections import (
    AIConnectionError,
    EMPTY_MODEL_SELECTION,
    IMAGE_GENERATION_CAPABILITY,
    IMAGE_MIGRATION_VERSION,
    IMAGE_MIGRATION_VERSION_KEY,
    IMAGE_SELECTION_KEY,
    image_connection_import_is_complete,
    image_settings_use_connections,
    resolve_model_capability,
    supports_model_capability,
)


MIGRATION_NOTICE_KEY = "ai_connections_image_migration_notice"


class ImageMigrationConflict(RuntimeError):
    """Another process changed settings; rebuild from its committed version."""


def preserve_legacy_image_form_settings(updates, submitted_fields, current_settings):
    """Omitted/disabled recovery controls are not instructions to erase retained data."""
    preserved = dict(updates)
    managed = image_settings_use_connections(current_settings)
    legacy_keys = {
        key for key in preserved
        if key.startswith(("azure_openai_image_gen_", "azure_apim_image_gen_"))
        or key in ("image_gen_model", "enable_image_gen_apim")
    }
    legacy_controls_submitted = any(
        ("image_gen_model_json" if key == "image_gen_model" else key) in submitted_fields
        for key in legacy_keys
    )
    for key in legacy_keys:
        field_name = "image_gen_model_json" if key == "image_gen_model" else key
        if managed or (
            not legacy_controls_submitted if key == "enable_image_gen_apim"
            else field_name not in submitted_fields
        ):
            preserved.pop(key)
    return preserved


def _endpoint_identity(endpoint):
    parsed = urlsplit(str(endpoint or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise AIConnectionError("The legacy image connection has an invalid endpoint.")
    return (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), parsed.query)


def _legacy_image_connection(settings, apim):
    prefix = "azure_apim_image_gen" if apim else "azure_openai_image_gen"
    endpoint = str(settings.get(f"{prefix}_endpoint") or "").strip()
    if not endpoint:
        return None, ""
    identity = _endpoint_identity(endpoint)
    source = "apim" if apim else "direct"
    endpoint_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"simplechat:legacy-image:{source}:{identity}"))
    if apim:
        deployment = str(settings.get("azure_apim_image_gen_deployment") or "").strip()
        selected = [{"deploymentName": deployment}] if deployment else []
        available = selected
    else:
        catalog = settings.get("image_gen_model") or {}
        if not isinstance(catalog, Mapping):
            raise AIConnectionError("The legacy image model selection is invalid.")
        selected = catalog.get("selected") or []
        available = catalog.get("all") or []
        if not isinstance(selected, list) or not isinstance(available, list):
            raise AIConnectionError("The legacy image model list is invalid.")

    active_name = str(selected[0].get("deploymentName") or "") if selected and isinstance(selected[0], Mapping) else ""
    models = []
    seen = set()
    for entry in [*selected, *available]:
        if not isinstance(entry, Mapping):
            continue
        deployment = str(entry.get("deploymentName") or entry.get("deployment") or "").strip()
        if not deployment or deployment in seen:
            continue
        seen.add(deployment)
        model = copy.deepcopy(entry)
        model.update({
            "id": str(uuid.uuid5(uuid.UUID(endpoint_id), deployment)),
            "deploymentName": deployment,
            "enabled": deployment == active_name,
            "enabled_capabilities": [IMAGE_GENERATION_CAPABILITY],
        })
        if deployment == active_name:
            support = resolve_model_capability(model, IMAGE_GENERATION_CAPABILITY, "aoai")
            model_name = str(model.get("modelName") or "").lower()
            legacy_route = (
                "responses"
                if not apim and model_name and not any(marker in model_name for marker in ("image", "dall-e", "dalle"))
                else "images"
            )
            model["supportsImageGeneration"] = True
            model["image_generation_api"] = support["api"] or legacy_route
        models.append(model)

    auth_type = "api_key" if apim else str(settings.get("azure_openai_image_gen_authentication_type") or "key")
    if auth_type == "key":
        auth_type = "api_key"
    auth = {"type": auth_type}
    if auth_type == "api_key":
        auth["api_key"] = settings.get(
            "azure_apim_image_gen_subscription_key" if apim else "azure_openai_image_gen_key", ""
        )
    profile = {
        "api_version": str(settings.get(f"{prefix}_api_version") or ""),
        "is_apim": apim,
    }
    if apim:
        profile["auth_header"] = "api-key"
    return {
        "id": endpoint_id,
        "name": "Imported image gateway" if apim else "Imported image connection",
        "provider": "aoai",
        "enabled": True,
        "identity_header": {
            "mode": "disabled" if settings.get("model_endpoint_identity_header_enabled") else "inherit"
        },
        "migration_source": f"legacy_image_{source}",
        "connection": {
            "endpoint": endpoint,
            "operation_settings": {IMAGE_GENERATION_CAPABILITY: profile},
        },
        "auth": auth,
        "management": {
            "subscription_id": "" if apim else settings.get("azure_openai_image_gen_subscription_id", ""),
            "resource_group": "" if apim else settings.get("azure_openai_image_gen_resource_group", ""),
        },
        "models": models,
    }, active_name


def _compatible_connection(existing, imported):
    if not isinstance(existing, Mapping) or existing.get("enabled") is False:
        return False
    if str(existing.get("provider") or "aoai") != imported["provider"]:
        return False
    connection = existing.get("connection") or {}
    if not isinstance(connection, Mapping):
        return False
    try:
        if _endpoint_identity(connection.get("endpoint")) != _endpoint_identity(imported["connection"]["endpoint"]):
            return False
    except ValueError:
        return False
    existing_auth = existing.get("auth") or {}
    imported_auth = imported["auth"]
    if not isinstance(existing_auth, Mapping):
        return False
    if existing_auth.get("type") != imported_auth.get("type"):
        return False
    fields = ("api_key", "client_secret", "client_id", "tenant_id", "managed_identity_client_id", "management_cloud", "custom_authority")
    if any((existing_auth.get(field) or "") != (imported_auth.get(field) or "") for field in fields):
        return False
    existing_profile = (connection.get("operation_settings") or {}).get(IMAGE_GENERATION_CAPABILITY)
    if existing_profile and existing_profile != imported["connection"]["operation_settings"][IMAGE_GENERATION_CAPABILITY]:
        return False
    existing_identity = existing.get("identity_header") or {}
    imported_identity = imported.get("identity_header") or {}
    if existing_identity.get("mode", "inherit") != imported_identity.get("mode", "inherit"):
        return False
    for incoming in imported["models"]:
        match = next(
            (model for model in existing.get("models") or [] if model.get("deploymentName") == incoming["deploymentName"]),
            None,
        )
        if match and incoming["enabled"] and not supports_model_capability(match, IMAGE_GENERATION_CAPABILITY, existing.get("provider")):
            return False
    return bool(existing.get("id"))


def build_image_connection_migration(settings, normalize_endpoint=None):
    """Build a settings patch without writing, fetching deployments, or resolving secrets."""
    if image_connection_import_is_complete(settings):
        return None
    if IMAGE_SELECTION_KEY in settings:
        return {IMAGE_MIGRATION_VERSION_KEY: IMAGE_MIGRATION_VERSION}
    current = settings.get("model_endpoints") or []
    if not isinstance(current, list):
        raise AIConnectionError("The saved AI connection list is invalid.")
    if any(not isinstance(endpoint, Mapping) for endpoint in current):
        raise AIConnectionError("Each saved AI connection must be an object.")
    endpoints = copy.deepcopy(current)
    selected = dict(EMPTY_MODEL_SELECTION)
    imported_count = 0
    active_apim = bool(settings.get("enable_image_gen_apim"))
    for apim in (False, True):
        imported, active_name = _legacy_image_connection(settings, apim)
        if imported is None:
            continue
        if normalize_endpoint is not None:
            imported = normalize_endpoint(imported)
        existing = next((item for item in endpoints if _compatible_connection(item, imported)), None)
        if existing is None:
            if any(item.get("id") == imported["id"] for item in endpoints):
                raise AIConnectionError("An imported image connection conflicts with an existing connection.")
            existing = imported
            endpoints.append(existing)
            imported_count += 1
        else:
            profiles = existing.setdefault("connection", {}).setdefault("operation_settings", {})
            profiles.setdefault(IMAGE_GENERATION_CAPABILITY, imported["connection"]["operation_settings"][IMAGE_GENERATION_CAPABILITY])
            models = existing.setdefault("models", [])
            for model in imported["models"]:
                if not any(item.get("deploymentName") == model["deploymentName"] for item in models):
                    models.append(model)
        if apim == active_apim and active_name:
            model = next(item for item in existing["models"] if item.get("deploymentName") == active_name)
            if not model.get("id"):
                model["id"] = active_name
            if not existing.get("provider"):
                existing["provider"] = "aoai"
            selected = {
                "endpoint_id": str(existing["id"]),
                "model_id": str(model["id"]),
                "provider": str(existing["provider"]).lower(),
            }
    return {
        "model_endpoints": endpoints,
        IMAGE_SELECTION_KEY: selected,
        IMAGE_MIGRATION_VERSION_KEY: IMAGE_MIGRATION_VERSION,
        MIGRATION_NOTICE_KEY: {
            "status": "complete",
            "imported_connections": imported_count,
            "message": "Existing image configuration is now managed through AI Connections.",
        },
    }


def migrate_image_connections(
    read_settings, write_settings, prepare_endpoint, attempts=3,
    normalize_endpoint=None, discard_endpoint=None,
):
    """Commit the import with optimistic concurrency; collaborators make I/O testable."""
    for _attempt in range(attempts):
        original = read_settings()
        updates = build_image_connection_migration(original, normalize_endpoint)
        if updates is None:
            return original
        etag = original.get("_etag")
        if not etag:
            raise AIConnectionError("Image configuration import requires a current settings version.")
        candidate = copy.deepcopy(original)
        existing = {item.get("id"): item for item in original.get("model_endpoints") or []}
        prepared_changes = []
        if "model_endpoints" in updates:
            prepared_endpoints = []
            try:
                for endpoint in updates["model_endpoints"]:
                    previous = existing.get(endpoint.get("id"))
                    if endpoint != previous:
                        endpoint = prepare_endpoint(endpoint, previous)
                        prepared_changes.append((endpoint, previous))
                    prepared_endpoints.append(endpoint)
            except (RuntimeError, ValueError):
                if discard_endpoint is not None:
                    for prepared, previous in prepared_changes:
                        discard_endpoint(prepared, previous)
                raise
            updates["model_endpoints"] = prepared_endpoints
        candidate.update(updates)
        try:
            return write_settings(candidate, etag)
        except ImageMigrationConflict:
            if discard_endpoint is not None:
                for prepared, previous in prepared_changes:
                    discard_endpoint(prepared, previous)
            continue
    raise AIConnectionError("Image configuration changed during import. Retry after other settings changes finish.")


def initialize_ai_connections(settings):
    """Import after cache initialization; retain legacy operation on a reported failure."""
    if image_connection_import_is_complete(settings):
        return settings

    # Startup collaborators are lazy so the migration builder is usable without Azure.
    from azure.core import MatchConditions
    from azure.core.exceptions import AzureError
    from azure.cosmos.exceptions import CosmosAccessConditionFailedError
    from config import cosmos_settings_container
    from functions_appinsights import log_event
    from functions_keyvault import (
        keyvault_model_endpoint_cleanup_helper,
        keyvault_model_endpoint_save_helper,
        resolve_secret_reference_for_context,
        validate_secret_name_dynamic,
    )
    from functions_settings import _refresh_app_settings_cache_after_write, normalize_model_endpoints

    def read():
        return cosmos_settings_container.read_item(item="app_settings", partition_key="app_settings")

    def normalize(endpoint):
        normalized, _ = normalize_model_endpoints([endpoint])
        return normalized[0]

    def prepare(endpoint, previous):
        prepared = normalize(endpoint)
        auth = prepared.get("auth") or {}
        if (
            settings.get("enable_key_vault_secret_storage")
            and not settings.get("key_vault_name")
            and any(auth.get(field) for field in ("api_key", "client_secret"))
        ):
            raise AIConnectionError("Configure Key Vault before importing image credentials.")
        if previous is None and prepared.get("migration_source"):
            for field in ("api_key", "client_secret"):
                value = auth.get(field)
                if value and validate_secret_name_dynamic(value):
                    auth[field] = resolve_secret_reference_for_context(
                        value, scope="global", allowed_sources={"other"},
                        context_label="legacy image configuration",
                    )
        return keyvault_model_endpoint_save_helper(
            prepared, prepared["id"], scope="global", existing_endpoint=previous,
            stage_new_secrets=True,
        )

    def discard(prepared, previous):
        try:
            keyvault_model_endpoint_cleanup_helper(
                prepared, previous, prepared["id"], scope="global"
            )
        except (AzureError, RuntimeError, ValueError) as exc:
            log_event(
                "[AI_CONNECTIONS] Uncommitted image credential cleanup failed",
                extra={"error_type": type(exc).__name__},
            )

    def write(candidate, etag):
        try:
            return cosmos_settings_container.replace_item(
                item="app_settings", body=candidate,
                etag=etag, match_condition=MatchConditions.IfNotModified,
            )
        except CosmosAccessConditionFailedError as exc:
            raise ImageMigrationConflict() from exc

    try:
        result = migrate_image_connections(
            read, write, prepare, normalize_endpoint=normalize, discard_endpoint=discard
        )
        _refresh_app_settings_cache_after_write(result, context="ai_connections_image_import")
        log_event("[AI_CONNECTIONS] Legacy image connection import completed")
        return result
    except (AzureError, RuntimeError, ValueError) as exc:
        retained = dict(settings)
        retained[MIGRATION_NOTICE_KEY] = {
            "status": "error",
            "message": (
                f"{exc.public_message} "
                if isinstance(exc, AIConnectionError)
                else "Image connection import could not finish. Review connection and Key Vault permissions. "
            ) + "Existing image settings remain active. Restart after correcting the configuration to retry.",
        }
        log_event(
            "[AI_CONNECTIONS] Image connection import failed; retaining legacy configuration",
            extra={"error_type": type(exc).__name__},
        )
        return retained
