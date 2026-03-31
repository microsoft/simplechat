# resolve_multiendpoint_gpt.py
"""
Emulate the multi-endpoint GPT resolver and send a test chat completion.

This script pulls settings from Cosmos DB (simplechat/settings), resolves the selected
model endpoint, then sends a GPT-only chat request with detailed logging.
"""

import argparse
import json
import logging
import os
from urllib.parse import urlparse

from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from azure.identity import ClientSecretCredential, DefaultAzureCredential, get_bearer_token_provider
from dotenv import load_dotenv
from openai import AzureOpenAI, OpenAI


def configure_logging(verbose):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="[%(levelname)s] %(message)s"
    )


def get_env_value(name):
    value = os.getenv(name, "")
    return value.strip()


def resolve_authority(auth_settings):
    management_cloud = (auth_settings.get("management_cloud") or "public").lower()
    if management_cloud == "government":
        return "https://login.microsoftonline.us"
    if management_cloud == "custom":
        custom_authority = auth_settings.get("custom_authority") or ""
        return custom_authority.strip() or None
    return None


def infer_foundry_scope_from_endpoint(endpoint):
    if not endpoint:
        return "https://ai.azure.com/.default"
    host = urlparse(endpoint).hostname or endpoint
    host = host.lower()
    if "azure.us" in host:
        return "https://ai.azure.us/.default"
    if "azure.cn" in host:
        return "https://ai.azure.cn/.default"
    if "azure.de" in host:
        return "https://ai.azure.de/.default"
    return "https://ai.azure.com/.default"


def resolve_foundry_scope_for_auth(auth_settings, endpoint=None):
    auth_type = (auth_settings.get("type") or "managed_identity").lower()
    if auth_type == "service_principal":
        management_cloud = (auth_settings.get("management_cloud") or "public").lower()
        if management_cloud == "government":
            return "https://ai.azure.us/.default"
        if management_cloud == "custom":
            custom_scope = (auth_settings.get("foundry_scope") or "").strip()
            if not custom_scope:
                raise ValueError("Foundry scope is required for custom cloud configurations.")
            return custom_scope
        return "https://ai.azure.com/.default"

    custom_scope = (auth_settings.get("foundry_scope") or "").strip()
    if custom_scope:
        return custom_scope
    return infer_foundry_scope_from_endpoint(endpoint)


def resolve_cognitive_services_scope():
    azure_env = (get_env_value("AZURE_ENVIRONMENT") or "public").lower()
    if azure_env == "usgovernment":
        return "https://cognitiveservices.azure.us/.default"
    if azure_env == "custom":
        custom_scope = get_env_value("CUSTOM_COGNITIVE_SERVICES_URL_VALUE")
        if not custom_scope:
            raise ValueError("CUSTOM_COGNITIVE_SERVICES_URL_VALUE is required for custom cloud.")
        return custom_scope
    return "https://cognitiveservices.azure.com/.default"


def normalize_foundry_base_url(endpoint):
    if not endpoint:
        raise ValueError("Foundry endpoint is required.")
    normalized = endpoint.rstrip("/")
    if "/models" in normalized:
        return normalized + "/"
    if "/openai/v1" in normalized:
        return normalized.replace("/openai/v1", "/models") + "/"
    if "/openai" in normalized:
        return normalized.replace("/openai", "/models") + "/"
    return normalized + "/models/"


def get_foundry_api_version_candidates(primary_version, settings):
    candidates = [primary_version]
    fallback = (settings.get("azure_openai_gpt_api_version") or "").strip()
    if fallback:
        candidates.append(fallback)
    candidates.extend([
        "2024-10-01-preview",
        "2024-07-01-preview",
        "2024-05-01-preview",
        "2024-02-01"
    ])
    seen = set()
    unique = []
    for item in candidates:
        if not item:
            continue
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def resolve_foundry_inference_api_version(connection, settings):
    api_version = (connection.get("openai_api_version") or connection.get("api_version") or "").strip()
    if api_version and api_version != "v1":
        return api_version
    fallback = settings.get("azure_openai_gpt_api_version") or "2024-05-01-preview"
    return fallback


def mask_secret(value, visible=4):
    if not value:
        return ""
    if len(value) <= visible:
        return "*" * len(value)
    return f"{value[:visible]}***{value[-visible:]}"


def log_available_databases(client):
    try:
        databases = list(client.list_databases())
    except Exception as exc:
        logging.warning("Failed to list databases: %s", exc)
        return
    ids = [db.get("id") for db in databases if isinstance(db, dict)]
    logging.info("Available databases: %s", ", ".join(ids) if ids else "<none>")


def log_available_containers(database):
    try:
        containers = list(database.list_containers())
    except Exception as exc:
        logging.warning("Failed to list containers: %s", exc)
        return
    ids = [c.get("id") for c in containers if isinstance(c, dict)]
    logging.info("Available containers: %s", ", ".join(ids) if ids else "<none>")


def fetch_settings_from_cosmos(database_name, container_name, settings_id):
    cosmos_endpoint = get_env_value("AZURE_COSMOS_ENDPOINT")
    cosmos_key = get_env_value("AZURE_COSMOS_KEY")
    if not cosmos_endpoint or not cosmos_key:
        raise ValueError("AZURE_COSMOS_ENDPOINT and AZURE_COSMOS_KEY must be set in the .env file.")

    logging.info("Connecting to Cosmos DB endpoint: %s", urlparse(cosmos_endpoint).hostname)
    client = CosmosClient(cosmos_endpoint, credential=cosmos_key)
    logging.info("Using Cosmos database=%s container=%s settings_id=%s", database_name, container_name, settings_id)
    database = client.get_database_client(database_name)
    try:
        database.read()
    except CosmosResourceNotFoundError:
        logging.error("Cosmos database '%s' not found in this account.", database_name)
        log_available_databases(client)
        raise ValueError("Cosmos database not found. Check AZURE_COSMOS_ENDPOINT and --database.")

    container = database.get_container_client(container_name)
    try:
        container.read()
    except CosmosResourceNotFoundError:
        logging.error("Cosmos container '%s' not found in database '%s'.", container_name, database_name)
        log_available_containers(database)
        raise ValueError("Cosmos container not found. Check --container.")

    try:
        settings = container.read_item(item=settings_id, partition_key=settings_id)
    except CosmosResourceNotFoundError:
        logging.warning("Settings item not found by id. Attempting query lookup for id=%s", settings_id)
        query = "SELECT * FROM c WHERE c.id = @id"
        try:
            items = list(container.query_items(query=query, parameters=[{"name": "@id", "value": settings_id}], enable_cross_partition_query=True))
        except CosmosResourceNotFoundError:
            logging.error("Container query failed. Verify database/container and Cosmos account endpoint.")
            log_available_containers(database)
            raise
        if items:
            settings = items[0]
        else:
            logging.warning("No matching settings id found. Falling back to first item in container.")
            items = list(container.query_items(query="SELECT TOP 1 * FROM c", enable_cross_partition_query=True))
            if not items:
                raise ValueError("No settings documents found in the container.")
            settings = items[0]
    logging.info("Settings loaded: enable_multi_model_endpoints=%s", settings.get("enable_multi_model_endpoints"))
    return settings


def build_multi_endpoint_client(auth, provider, endpoint, api_version, settings):
    auth_type = (auth.get("type") or "managed_identity").lower()
    if provider == "aifoundry":
        base_url = normalize_foundry_base_url(endpoint)
        api_version = resolve_foundry_inference_api_version({"api_version": api_version}, settings)
        default_query = {"api-version": api_version}
        if auth_type == "api_key":
            api_key = auth.get("api_key")
            if not api_key:
                raise ValueError("API key is required for the selected endpoint.")
            logging.info("Using Foundry OpenAI-compatible endpoint: %s", base_url)
            logging.info("Using Foundry api-version: %s", api_version)
            return OpenAI(base_url=base_url, api_key=api_key, default_query=default_query)

        authority_override = None
        if auth_type == "service_principal":
            authority_override = resolve_authority(auth)
            credential = ClientSecretCredential(
                tenant_id=auth.get("tenant_id"),
                client_id=auth.get("client_id"),
                client_secret=auth.get("client_secret"),
                authority=authority_override
            )
        else:
            managed_identity_client_id = auth.get("managed_identity_client_id") or None
            credential = DefaultAzureCredential(managed_identity_client_id=managed_identity_client_id)

        scope = resolve_foundry_scope_for_auth(auth, endpoint)
        logging.info("Using Foundry AAD scope: %s", scope)
        token = credential.get_token(scope).token
        logging.info("Using Foundry OpenAI-compatible endpoint: %s", base_url)
        logging.info("Using Foundry api-version: %s", api_version)
        return OpenAI(base_url=base_url, api_key=token, default_query=default_query)

    if auth_type == "api_key":
        api_key = auth.get("api_key")
        if not api_key:
            raise ValueError("API key is required for the selected endpoint.")
        return AzureOpenAI(
            #api_version=api_version,
            azure_endpoint=endpoint,
            api_key=api_key
        )

    if auth_type == "service_principal":
        authority_override = resolve_authority(auth)
        credential = ClientSecretCredential(
            tenant_id=auth.get("tenant_id"),
            client_id=auth.get("client_id"),
            client_secret=auth.get("client_secret"),
            authority=authority_override
        )
        scope = resolve_cognitive_services_scope()
        logging.info("Using service principal scope: %s", scope)
        token_provider = get_bearer_token_provider(credential, scope)
    else:
        managed_identity_client_id = auth.get("managed_identity_client_id") or None
        credential = DefaultAzureCredential(managed_identity_client_id=managed_identity_client_id)
        scope = resolve_cognitive_services_scope()
        logging.info("Using managed identity scope: %s", scope)
        token_provider = get_bearer_token_provider(credential, scope)

    return AzureOpenAI(
        #api_version=api_version,
        azure_endpoint=endpoint,
        azure_ad_token_provider=token_provider
    )


def resolve_multi_endpoint_gpt_config(settings, model_id, endpoint_id, provider_override=None):
    enable_multi_model_endpoints = settings.get("enable_multi_model_endpoints", False)
    enable_gpt_apim = settings.get("enable_gpt_apim", False)

    if not enable_multi_model_endpoints or enable_gpt_apim or not model_id:
        raise ValueError("Multi-endpoint resolution is not active or model_id is missing.")

    endpoints = settings.get("model_endpoints", []) or []
    endpoint_cfg = next((e for e in endpoints if e.get("id") == endpoint_id), None)
    if not endpoint_cfg or not endpoint_cfg.get("enabled", True):
        raise ValueError("Selected model endpoint is not available.")

    models = endpoint_cfg.get("models", []) or []
    model_cfg = next((m for m in models if m.get("id") == model_id), None)
    if not model_cfg or not model_cfg.get("enabled", True):
        raise ValueError("Selected model is not available.")

    if provider_override and endpoint_cfg.get("provider") and provider_override != endpoint_cfg.get("provider"):
        raise ValueError("Selected model provider mismatch.")

    gpt_model = model_cfg.get("deploymentName") or model_cfg.get("deployment") or ""
    if not gpt_model:
        raise ValueError("Selected model is missing deployment name.")

    connection = endpoint_cfg.get("connection", {}) or {}
    auth = endpoint_cfg.get("auth", {}) or {}
    auth_type = (auth.get("type") or "managed_identity").lower()
    api_version = connection.get("openai_api_version") or connection.get("api_version")
    endpoint = connection.get("endpoint")
    provider = (endpoint_cfg.get("provider") or "aoai").lower()
    if provider == "aifoundry":
        api_version = resolve_foundry_inference_api_version(connection, settings)
        logging.info("Using Foundry inference api_version=%s", api_version)

    logging.info("Resolved endpoint: %s", endpoint_cfg.get("name"))
    logging.info("Resolved provider: %s", provider)
    logging.info("Resolved deployment: %s", gpt_model)
    logging.info("Resolved auth_type: %s", auth_type)

    gpt_client = build_multi_endpoint_client(auth, provider, endpoint, api_version, settings)
    return gpt_client, gpt_model, provider, endpoint, auth, api_version


def run_chat_completion(gpt_client, gpt_model, message, reasoning_effort=None, provider=None, endpoint=None, auth=None, api_version=None, settings=None):
    logging.info("Sending GPT-only request (model=%s)", gpt_model)

    api_params = {
        "model": gpt_model.lower(),
        "messages": [
            {"role": "system", "content": "You are an AI assistant that helps people find information."},
            {"role": "user", "content": message}
        ]
    }
    if reasoning_effort and reasoning_effort.lower() != "none":
        api_params["reasoning_effort"] = reasoning_effort
        logging.info("Using reasoning_effort=%s", reasoning_effort)

    try:
        print(f"\nAPI Params: {api_params}\n")
        response = gpt_client.chat.completions.create(**api_params)
    except Exception as exc:
        error_str = str(exc).lower()
        if provider == "aifoundry" and "api version not supported" in error_str:
            logging.warning("Foundry API version not supported. Retrying with fallback versions...")
            api_params.pop("reasoning_effort", None)
            last_error = exc
            for candidate in get_foundry_api_version_candidates(api_version, settings or {}):
                if candidate == api_version:
                    continue
                try:
                    logging.info("Retrying Foundry with api_version=%s", candidate)
                    retry_client = build_multi_endpoint_client(auth or {}, "aifoundry", endpoint, candidate, settings or {})
                    response = retry_client.chat.completions.create(**api_params)
                    break
                except Exception as retry_exc:
                    last_error = retry_exc
                    logging.debug("Foundry retry failed for api_version=%s: %s", candidate, retry_exc)
            else:
                raise last_error
        else:
            raise
    choice = response.choices[0]
    content = choice.message.content if choice.message else ""
    logging.info("Response received. Finish reason=%s", getattr(choice, "finish_reason", None))
    logging.debug("Full response: %s", json.dumps(response.model_dump(), indent=2, default=str))
    return content


def parse_args():
    parser = argparse.ArgumentParser(description="Resolve multi-endpoint GPT config and send a test message.")
    parser.add_argument("--env-path", required=True, help="Path to the .env file containing Cosmos settings.")
    parser.add_argument("--endpoint-id", required=True, help="Model endpoint ID from settings.")
    parser.add_argument("--model-id", required=True, help="Model ID from settings.")
    parser.add_argument("--database", default="SimpleChat", help="Cosmos database name.")
    parser.add_argument("--container", default="settings", help="Cosmos settings container name.")
    parser.add_argument("--settings-id", default="app_settings", help="Settings document id.")
    parser.add_argument("--provider", default=None, help="Optional provider override (aoai/aifoundry).")
    parser.add_argument("--message", default="Hello from the multi-endpoint resolver.", help="Test message to send.")
    parser.add_argument("--reasoning-effort", default=None, help="Optional reasoning_effort value.")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging.")
    return parser.parse_args()


def main():
    args = parse_args()
    load_dotenv(args.env_path, override=True)
    configure_logging(args.verbose)

    logging.info("Loading .env from: %s", args.env_path)
    settings = fetch_settings_from_cosmos(
        database_name=args.database,
        container_name=args.container,
        settings_id=args.settings_id
    )

    gpt_client, gpt_model, provider, endpoint, auth, api_version = resolve_multi_endpoint_gpt_config(
        settings,
        model_id=args.model_id,
        endpoint_id=args.endpoint_id,
        provider_override=args.provider
    )

    response_text = run_chat_completion(
        gpt_client,
        gpt_model,
        message=args.message,
        reasoning_effort=args.reasoning_effort,
        provider=provider,
        endpoint=endpoint,
        auth=auth,
        api_version=api_version,
        settings=settings
    )

    logging.info("Response text:\n%s", response_text)


if __name__ == "__main__":
    main()
