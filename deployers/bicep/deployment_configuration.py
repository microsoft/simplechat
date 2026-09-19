# deployment_configuration.py
"""Safe post-provision configuration without importing the Flask application."""

import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess

from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ClientAuthenticationError, HttpResponseError, ResourceNotFoundError
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import SearchIndex
from dotenv import dotenv_values
from redis import Redis
from redis.exceptions import RedisError


APP_DIRECTORY = Path(__file__).resolve().parents[2] / "application" / "single_app"
DEPLOYERS_DIRECTORY = Path(__file__).resolve().parents[1]
REQUIRED_VALUES = (
    "AZURE_ENV_NAME", "AZURE_SUBSCRIPTION_ID", "AZURE_TENANT_ID",
    "var_authenticationType", "var_cosmosDb_accountName", "var_rgName",
    "var_openAIEndpoint", "var_openAIGPTModels", "var_openAIEmbeddingModels",
    "var_searchServiceEndpoint", "var_blobStorageEndpoint",
    "var_documentIntelligenceServiceEndpoint",
)
REDIS_FIELDS = (
    "enable_redis_cache", "redis_url", "redis_service_type", "redis_port",
    "redis_auth_type", "redis_key",
)


def load_app_module(name):
    spec = importlib.util.spec_from_file_location(name, APP_DIRECTORY / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


settings_store = load_app_module("app_settings_store")
redis_helpers = load_app_module("functions_redis_client")


def load_deployment_environment():
    name = os.environ.get("AZURE_ENV_NAME")
    if not name:
        raise ValueError("AZURE_ENV_NAME is required; select an explicit AZD environment.")
    executable = shutil.which("azd")
    if not executable:
        raise RuntimeError("AZD is required to resolve deployment outputs.")
    result = subprocess.run(
        [executable, "-C", str(DEPLOYERS_DIRECTORY), "env", "get-values", "--environment", name],
        capture_output=True, text=True, check=False,
    )
    if result.returncode:
        raise RuntimeError("Unable to load the selected AZD environment; no configuration was written.")
    values = dict(dotenv_values(stream=io.StringIO(result.stdout), interpolate=False))
    missing = [key for key in REQUIRED_VALUES if not values.get(key)]
    if missing:
        raise ValueError("Missing required deployment outputs: " + ", ".join(missing))
    if values["AZURE_ENV_NAME"] != name:
        raise ValueError("AZD returned a different environment than requested.")
    if values["var_authenticationType"] not in ("managed_identity", "key"):
        raise ValueError("Unsupported deployment authentication type.")
    for key in ("var_openAIGPTModels", "var_openAIEmbeddingModels"):
        models = json.loads(values[key])
        if not isinstance(models, list) or not models or any(
            not isinstance(model, dict) or not model.get("modelName") for model in models
        ):
            raise ValueError(f"Invalid model deployment output: {key}")
    for key in list(os.environ):
        if key.lower().startswith("var_"):
            os.environ.pop(key)
    os.environ.update({key: value for key, value in values.items() if value is not None})
    os.environ["var_subscriptionId"] = values["AZURE_SUBSCRIPTION_ID"]
    return values


def redis_client_for_settings(settings, credential):
    host = redis_helpers.normalize_redis_host(settings.get("redis_url"))
    if not host:
        raise ValueError("Enabled Redis requires a host before settings can be published.")
    options = {
        "host": host,
        "port": redis_helpers.resolve_redis_port(settings),
        "ssl": True,
        "socket_connect_timeout": 10,
        "socket_timeout": 10,
    }
    mode = settings.get("redis_auth_type", "key")
    if mode == "managed_identity":
        options["credential_provider"] = redis_helpers.RedisManagedIdentityCredentialProvider(
            credential=credential, scope=redis_helpers.get_redis_entra_token_scope(settings),
        )
    elif mode == "key" and settings.get("redis_key"):
        options["password"] = settings["redis_key"]
    else:
        raise ValueError("Postconfig requires managed_identity or key access to the configured Redis cache.")
    return Redis(**options)


def configure_redis(item, host, kind, port, authentication_type, keys):
    host = (host or "").strip()
    if not host:
        return
    if kind not in ("managed", "classic"):
        raise ValueError("Unknown deployed Redis service type.")
    if authentication_type not in ("managed_identity", "key"):
        raise ValueError("Unknown deployed Redis authentication type.")
    if authentication_type == "key" and not keys.get("redis_key"):
        raise ValueError("Redis key was not resolved; settings were not saved.")
    resolved_port = int(port or (10000 if kind == "managed" else 6380))
    if not 1 <= resolved_port <= 65535:
        raise ValueError("Deployed Redis port is out of range.")
    item.update({
        "enable_redis_cache": True,
        "redis_url": host,
        "redis_service_type": "azure_managed_redis" if kind == "managed" else "azure_cache_for_redis",
        "redis_port": str(resolved_port),
        "redis_auth_type": authentication_type,
        "redis_key": keys.get("redis_key", "") if authentication_type == "key" else "",
    })


def redis_connection_signature(settings):
    mode = str(settings.get("redis_auth_type") or "key").strip().lower()
    return (
        bool(settings.get("enable_redis_cache")),
        redis_helpers.normalize_redis_host(settings.get("redis_url")),
        redis_helpers.resolve_redis_port(settings),
        mode,
        settings.get("redis_key") if mode != "managed_identity" else None,
    )


def persist_settings(container, original, desired, credential):
    excluded = settings_store.COSMOS_METADATA_FIELDS | {settings_store.SETTINGS_REVISION_FIELD, "public_workspace_labels"}
    updates = {
        key: copy.deepcopy(value)
        for key, value in desired.items()
        if key not in excluded and (key not in original or original[key] != value)
    }
    before_redis = {key: original.get(key) for key in REDIS_FIELDS}
    if original.get("enable_redis_cache") and redis_connection_signature(original) != redis_connection_signature(desired):
        raise ValueError("Changing an active Redis configuration requires an administrator-managed cache migration.")
    redis_client = None
    try:
        if desired.get("enable_redis_cache"):
            redis_client = redis_client_for_settings(desired, credential)
            try:
                redis_client.ping()
            except (RedisError, ClientAuthenticationError):
                raise settings_store.SettingsUnavailableError(
                    "Deployment runner cannot publish settings to Redis. Check its Redis data access policy "
                    "and network connectivity; no Cosmos settings were written."
                ) from None
        store = settings_store.AppSettingsStore(
            container, redis_client, redis_required=bool(desired.get("enable_redis_cache")),
        )

        def merge(current):
            if {key: current.get(key) for key in REDIS_FIELDS} != before_redis:
                raise settings_store.SettingsConflictError("Redis settings changed during deployment; reload and retry.")
            current.update(copy.deepcopy(updates))
            current.pop("public_workspace_labels", None)
            return current

        stored = store.write(merge, defaults={"id": "app_settings", "partition_key": "app_settings"})
        verified = store.read(use_cosmos=True)
        if any(verified.get(key) != value for key, value in updates.items()):
            raise settings_store.SettingsConflictError("Settings changed after deployment; verify before retrying.")
        return stored
    finally:
        if redis_client is not None:
            redis_client.close()


def ensure_search_indexes(client, schemas_directory=None):
    schemas_directory = schemas_directory or APP_DIRECTORY / "static" / "json"
    created = []
    for kind in ("user", "group", "public"):
        schema = json.loads((schemas_directory / f"ai_search-index-{kind}.json").read_text(encoding="utf-8"))
        name = schema["name"]
        try:
            client.get_index(name)
            continue
        except ResourceNotFoundError:
            pass
        try:
            client.create_index(SearchIndex.deserialize(schema))
            created.append(name)
        except HttpResponseError as error:
            if error.status_code != 409:
                raise
        client.get_index(name)
    return created


def configure_search(settings, credential):
    if settings.get("azure_ai_search_authentication_type") == "key":
        credential = AzureKeyCredential(settings["azure_ai_search_key"])
    with SearchIndexClient(settings["azure_ai_search_endpoint"], credential) as client:
        return ensure_search_indexes(client)