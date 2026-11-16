# optional_services.py
"""Optional-service selection and readiness, independent of Flask bootstrap."""

import argparse
import copy
import fnmatch
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid
from urllib.parse import urlparse
from urllib import error as urlerror
from urllib import request as urlrequest


WEB_IQ_API_VERSION = "2026-06-01-preview"
CU_API_VERSION = "2025-11-01"
CU_ANALYZERS = ("prebuilt-documentSearch", "prebuilt-imageSearch")
MEDIA_MODES = ("off", "text_only", "with_media")
CU_REGIONS = {
    "australiaeast", "canadacentral", "eastus", "eastus2", "japaneast", "southcentralus",
    "southeastasia", "swedencentral", "uksouth", "westeurope", "westus", "westus3",
}
OPTIONAL_SETTINGS_FIELDS = (
    "enable_web_search", "web_search_provider", "web_search_agent", "web_search_consent_accepted", "web_iq",
    "web_iq_consent_accepted", "web_iq_news_enabled", "web_iq_image_mode", "web_iq_video_mode",
    "azure_content_understanding_endpoint", "azure_content_understanding_authentication_type",
    "azure_content_understanding_api_version", "azure_content_understanding_analyzer_id",
    "azure_content_understanding_image_analyzer_id",
    "enable_key_vault_secret_storage", "key_vault_name", "key_vault_identity",
)
WEB_IQ_SECRET_PREFIX = "web-iq--model-endpoint--global--"


def is_web_iq_secret_reference(value):
    return (
        isinstance(value, str) and 0 < len(value) <= 127
        and value.startswith(WEB_IQ_SECRET_PREFIX)
        and re.fullmatch(r"[a-zA-Z0-9-]+", value) is not None
        and len(value) > len(WEB_IQ_SECRET_PREFIX)
    )


def configure_web_iq_vault(item, values):
    """Use the actual deployment vault, never migrate an existing vault implicitly."""
    uri = values.get("var_keyVaultUri") or ""
    parsed = urlparse(uri)
    host = parsed.hostname or ""
    if (
        parsed.scheme != "https" or not re.fullmatch(r"[a-zA-Z0-9-]{3,24}\.vault\.azure\.net", host)
        or parsed.username or parsed.password or parsed.port not in (None, 443)
        or parsed.path not in ("", "/") or parsed.query or parsed.fragment
    ):
        raise ValueError("Supplied Web IQ credentials require the actual public-Azure deployment Key Vault URI.")
    name = host.split(".")[0]
    if values.get("var_keyVaultName") and values["var_keyVaultName"].lower() != name:
        raise ValueError("Deployment Key Vault name and URI do not match.")
    existing_name = str(item.get("key_vault_name") or "").strip().lower()
    if existing_name and existing_name != name:
        raise ValueError("Existing Key Vault configuration uses another vault; automatic vault migration is not permitted.")
    if item.get("enable_key_vault_secret_storage") and not existing_name:
        raise ValueError("Existing enabled Key Vault configuration has no vault name; repair it before deployment.")
    item.update(enable_key_vault_secret_storage=True, key_vault_name=name)


def stage_web_iq_secret(client, supplied_name, existing_reference=None, field="key"):
    """Resolve privately and publish only a validated immutable scoped secret name."""
    # Azure dependencies are needed only during postconfig, not stdlib-only preprovision checks.
    from azure.core.exceptions import ResourceNotFoundError

    if not isinstance(supplied_name, str) or not re.fullmatch(r"[a-zA-Z0-9-]{1,127}", supplied_name):
        raise ValueError("Web IQ supplied secret must be a Key Vault secret name, not a URI or credential.")
    if field not in ("key", "client_secret"):
        raise ValueError("Unsupported Web IQ credential field.")
    source = client.get_secret(supplied_name)
    secret_value = source.value
    if not isinstance(secret_value, str) or not secret_value.strip():
        raise ValueError("Supplied Web IQ secret is empty.")
    if getattr(getattr(source, "properties", None), "enabled", True) is False:
        raise ValueError("Supplied Web IQ secret is disabled.")
    lifetime = {
        key: getattr(getattr(source, "properties", None), key, None)
        for key in ("expires_on", "not_before")
    }
    if is_web_iq_secret_reference(supplied_name):
        return supplied_name
    if is_web_iq_secret_reference(existing_reference):
        try:
            previous = client.get_secret(existing_reference)
        except ResourceNotFoundError:
            previous = None
        if (
            previous is not None and previous.value == secret_value
            and getattr(getattr(previous, "properties", None), "enabled", True) is not False
            and all(getattr(getattr(previous, "properties", None), key, None) == value for key, value in lifetime.items())
        ):
            return existing_reference
    for _ in range(3):
        reference = f"{WEB_IQ_SECRET_PREFIX}{field.replace('_', '-')}-{uuid.uuid4().hex}"
        try:
            client.get_secret(reference)
        except ResourceNotFoundError:
            client.set_secret(reference, secret_value, **{key: value for key, value in lifetime.items() if value is not None})
            verified = client.get_secret(reference)
            if verified.value != secret_value:
                raise ValueError("Staged Web IQ credential could not be verified; settings were not published.")
            return reference
    raise ValueError("Unable to allocate a unique staged Web IQ secret name; settings were not published.")


def enabled(value):
    return str(value).strip().lower() in ("true", "1", "yes")


def selection(values):
    """Missing old-environment inputs mean preserve, never disable."""
    provider = values.get("WEB_SEARCH_PROVIDER") or "preserve"
    cu_mode = values.get("CONTENT_UNDERSTANDING_MODE") or "preserve"
    if provider not in ("preserve", "none", "foundry", "web_iq"):
        raise ValueError("WEB_SEARCH_PROVIDER must be preserve, none, foundry, or web_iq.")
    if cu_mode not in ("preserve", "none", "create", "reuse"):
        raise ValueError("CONTENT_UNDERSTANDING_MODE must be preserve, none, create, or reuse.")
    for key in ("WEB_IQ_IMAGE_MODE", "WEB_IQ_VIDEO_MODE"):
        if (values.get(key) or "off") not in MEDIA_MODES:
            raise ValueError(f"{key} must be off, text_only, or with_media.")
    if values.get("WEB_IQ_NEWS_ENABLED") not in (None, "", "true", "false"):
        raise ValueError("WEB_IQ_NEWS_ENABLED must be true or false.")
    cloud = values.get("env_AZURE_CLOUD_ENVIRONMENT") or values.get("AZURE_CLOUD_ENVIRONMENT") or "public"
    if cloud not in ("public", "AzureCloud") and (provider in ("foundry", "web_iq") or cu_mode in ("create", "reuse")):
        raise ValueError("Web search and Content Understanding are unavailable in Government/custom clouds.")
    if provider in ("foundry", "web_iq") and not enabled(values.get("WEB_SEARCH_TERMS_ACKNOWLEDGED")):
        raise ValueError("Review provider terms and set WEB_SEARCH_TERMS_ACKNOWLEDGED=true. This is not runtime consent.")
    if provider == "web_iq":
        if values.get("WEB_IQ_ENDPOINT") not in (None, "", "https://api.microsoft.ai/v3"):
            raise ValueError("Web IQ endpoint must be https://api.microsoft.ai/v3.")
        if values.get("WEB_IQ_AUTHENTICATION_TYPE") not in (None, "", "key", "service_principal"):
            raise ValueError("Web IQ supports key or service_principal, not managed identity.")
        for key, limit in (("WEB_IQ_MAX_RESULTS", 50), ("WEB_IQ_MAX_LENGTH", 3000)):
            if values.get(key) and not 1 <= int(values[key]) <= limit:
                raise ValueError(f"{key} must be an integer in 1..{limit}.")
        if not enabled(values.get("WEB_IQ_SUBSCRIPTION_ELIGIBLE")):
            raise ValueError("Confirm paid subscription and Microsoft Web IQ access; set WEB_IQ_SUBSCRIPTION_ELIGIBLE=true.")
        mode = values.get("WEB_IQ_RESOURCE_MODE") or "create"
        if mode not in ("create", "reuse"):
            raise ValueError("WEB_IQ_RESOURCE_MODE must be create or reuse.")
        if mode == "reuse" and not values.get("EXISTING_WEB_IQ_NAME"):
            raise ValueError("Web IQ reuse requires EXISTING_WEB_IQ_NAME and its resource group/subscription.")
    if provider == "foundry":
        if (values.get("FOUNDRY_RESOURCE_MODE") or "reuse") != "reuse":
            raise ValueError(
                "New Foundry classic agent provisioning is not automated: classic Agents retire March 31, 2027. "
                "Provision a supported compatible project/Bing connection/agent separately, then select reuse."
            )
        if not values.get("FOUNDRY_PROJECT_ENDPOINT") or not values.get("FOUNDRY_AGENT_ID"):
            raise ValueError("Foundry reuse requires FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_AGENT_ID; verify Bing connection/model and app access.")
        safe_endpoint(values["FOUNDRY_PROJECT_ENDPOINT"], ".services.ai.azure.com")
        if enabled(values.get("ENABLE_PRIVATE_NETWORKING")):
            raise ValueError("Classic Foundry Bing grounding requires public agent network access, not private endpoints.")
    if cu_mode in ("create", "reuse") and not values.get("CONTENT_UNDERSTANDING_LOCATION"):
        raise ValueError("Select an independently supported CONTENT_UNDERSTANDING_LOCATION.")
    if cu_mode in ("create", "reuse") and values["CONTENT_UNDERSTANDING_LOCATION"] not in CU_REGIONS:
        raise ValueError("CONTENT_UNDERSTANDING_LOCATION is not in the documented supported Content Understanding regions.")
    if cu_mode in ("create", "reuse") and not values.get("OPTIONAL_SERVICES_DEPLOYMENT_PRINCIPAL_ID"):
        raise ValueError("Set OPTIONAL_SERVICES_DEPLOYMENT_PRINCIPAL_ID to the runner object ID for defaults/analyzer readiness access.")
    if cu_mode == "reuse" and not values.get("EXISTING_CONTENT_UNDERSTANDING_NAME"):
        raise ValueError("Content Understanding reuse requires EXISTING_CONTENT_UNDERSTANDING_NAME.")
    if cu_mode == "create":
        models = json.loads(values.get("CONTENT_UNDERSTANDING_MODELS") or "[]")
        if not isinstance(models, list) or not models:
            raise ValueError("Supply CONTENT_UNDERSTANDING_MODELS with supported completion and embedding deployments and available quota.")
        defaults = json.loads(values.get("CONTENT_UNDERSTANDING_MODEL_DEFAULTS") or "{}")
        if not isinstance(defaults, dict):
            raise ValueError("CONTENT_UNDERSTANDING_MODEL_DEFAULTS must be an alias-to-deployment object.")
        by_name = {}
        for model in models:
            if not isinstance(model, dict) or not all(model.get(k) for k in ("modelName", "modelVersion", "skuName", "skuCapacity")):
                raise ValueError("Each Content Understanding model needs modelName, modelVersion, skuName and positive skuCapacity.")
            if type(model["skuCapacity"]) is not int or model["skuCapacity"] < 1:
                raise ValueError("Content Understanding model capacity must be a positive integer.")
            if model["modelName"] in by_name:
                raise ValueError("Content Understanding model deployment names must be unique.")
            by_name[model["modelName"]] = model
        for alias in ("prebuilt-analyzer-completion", "prebuilt-analyzer-completion-mini", "prebuilt-analyzer-embedding"):
            if defaults.get(alias) not in by_name:
                raise ValueError(f"Content Understanding defaults must map {alias} to a supplied deployment.")
    return provider, cu_mode


def safe_endpoint(endpoint, suffix):
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(suffix) or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Optional service endpoint must be an authenticated service's public HTTPS endpoint.")
    return endpoint.rstrip("/")


def run_json(arguments):
    result = subprocess.run(
        [shutil.which("az") or "az", *arguments, "--output", "json"],
        capture_output=True, text=True, check=False, timeout=60,
    )
    if result.returncode:
        raise ValueError("Optional service preflight failed. Check Azure CLI login, provider registration, resource access and network connectivity.")
    return json.loads(result.stdout)


def preflight(values, query=run_json):
    """Read-only ARM checks; no provider registrations, resource writes or paid requests."""
    provider, cu_mode = selection(values)
    if provider in ("preserve", "none") and cu_mode in ("preserve", "none"):
        return
    actual_cloud = query(["cloud", "show"])
    if actual_cloud.get("name") != "AzureCloud":
        raise ValueError("Optional services require the AzureCloud CLI cloud; cloud overrides cannot enable Government/custom deployment.")
    subscription = values.get("AZURE_SUBSCRIPTION_ID")
    if not subscription:
        raise ValueError("AZURE_SUBSCRIPTION_ID is required for optional service preflight.")
    targets = []
    if provider == "web_iq":
        targets.append(("Microsoft.WebIQ", "accounts", "global", WEB_IQ_API_VERSION,
                        (values.get("EXISTING_WEB_IQ_SUBSCRIPTION_ID") if values.get("WEB_IQ_RESOURCE_MODE") == "reuse" else None) or subscription))
    if cu_mode in ("create", "reuse"):
        targets.append(("Microsoft.CognitiveServices", "accounts", values["CONTENT_UNDERSTANDING_LOCATION"], "2025-06-01",
                        (values.get("EXISTING_CONTENT_UNDERSTANDING_SUBSCRIPTION_ID") if cu_mode == "reuse" else None) or subscription))
    for namespace, resource_type, location, version, target_subscription in targets:
        metadata = query(["provider", "show", "--namespace", namespace, "--subscription", target_subscription])
        types = [t for t in metadata.get("resourceTypes", []) if t.get("resourceType") == resource_type]
        if metadata.get("registrationState") != "Registered" or not types or version not in types[0].get("apiVersions", []):
            raise ValueError(f"Register/enable {namespace} and verify API {version} access before provisioning.")
        locations = {re.sub(r"\s", "", item).lower() for item in types[0].get("locations", [])}
        if location.lower().replace(" ", "") not in locations:
            raise ValueError(f"{namespace} is not advertised in selected location {location}; choose a supported location.")
    if cu_mode == "create":
        location = values["CONTENT_UNDERSTANDING_LOCATION"]
        owned_deployments = {}
        app_name, environment = values.get("env_DEPLOYMENT_APPNAME"), values.get("environment")
        owned_group = values.get("var_rgName") or (f"{app_name}-{environment}-rg" if app_name and environment else "")
        owned_name = f"{app_name}-{environment}-cu".lower() if app_name and environment else ""
        if owned_group and owned_name and query(["group", "exists", "--name", owned_group, "--subscription", subscription]):
            resources = query(["resource", "list", "--resource-group", owned_group, "--subscription", subscription,
                               "--resource-type", "Microsoft.CognitiveServices/accounts"])
            if any(resource.get("name") == owned_name for resource in resources):
                owned_deployments = {deployment["name"]: deployment for deployment in query([
                    "cognitiveservices", "account", "deployment", "list", "--name", owned_name,
                    "--resource-group", owned_group, "--subscription", subscription,
                ])}
        catalog = query(["cognitiveservices", "model", "list", "--location", location, "--subscription", subscription])
        usages = query(["cognitiveservices", "usage", "list", "--location", location, "--subscription", subscription])
        for deployment in json.loads(values["CONTENT_UNDERSTANDING_MODELS"]):
            candidates = [model for model in catalog if model.get("model", {}).get("name") == deployment["modelName"]
                          and model.get("model", {}).get("version") == deployment["modelVersion"]]
            skus = [sku for candidate in candidates for sku in candidate.get("model", {}).get("skus", []) if sku.get("name") == deployment["skuName"]]
            usage_names = {sku.get("usageName") for sku in skus}
            available = [usage for usage in usages if usage.get("name", {}).get("value") in usage_names]
            previous = owned_deployments.get(deployment["modelName"], {})
            previous_model = previous.get("properties", {}).get("model", {})
            matches = previous_model.get("name") == deployment["modelName"] and previous_model.get("version") == deployment["modelVersion"] and previous.get("sku", {}).get("name") == deployment["skuName"]
            existing_capacity = previous.get("sku", {}).get("capacity", 0) if matches else 0
            additional_capacity = max(0, deployment["skuCapacity"] - existing_capacity)
            if not skus or not available or not any(
                usage.get("limit", 0) - usage.get("currentValue", 0) >= additional_capacity for usage in available
            ):
                raise ValueError(f"Content Understanding model {deployment['modelName']} version/SKU is unavailable or has insufficient quota in {location}.")
    for prefix, namespace, mode in (
        ("WEB_IQ", "Microsoft.WebIQ", values.get("WEB_IQ_RESOURCE_MODE") if provider == "web_iq" else ""),
        ("CONTENT_UNDERSTANDING", "Microsoft.CognitiveServices", cu_mode),
    ):
        if mode != "reuse":
            continue
        name = values.get(f"EXISTING_{prefix}_NAME")
        group = values.get(f"EXISTING_{prefix}_RESOURCE_GROUP")
        sub = values.get(f"EXISTING_{prefix}_SUBSCRIPTION_ID") or subscription
        if not group:
            raise ValueError(f"Reuse requires EXISTING_{prefix}_RESOURCE_GROUP.")
        resource = query(["resource", "show", "--name", name, "--resource-group", group, "--subscription", sub,
                          "--resource-type", f"{namespace}/accounts", "--api-version",
                          WEB_IQ_API_VERSION if prefix == "WEB_IQ" else "2025-06-01"])
        expected_kind = "WebIQ.Grounding" if prefix == "WEB_IQ" else "AIServices"
        if resource.get("kind") != expected_kind:
            raise ValueError(f"Selected {prefix} resource has incompatible kind; expected {expected_kind}.")
        if prefix == "WEB_IQ" and (resource.get("location") != "global" or resource.get("sku", {}).get("name") != "G3"):
            raise ValueError("Reused Web IQ account must be global with the documented G3 SKU.")
        if prefix == "CONTENT_UNDERSTANDING" and resource.get("location") != values["CONTENT_UNDERSTANDING_LOCATION"]:
            raise ValueError("Reused Content Understanding location does not match the selected service region.")
        if prefix == "CONTENT_UNDERSTANDING" and not resource.get("properties", {}).get("customSubDomainName"):
            raise ValueError("Reused Content Understanding requires a custom subdomain for Entra data-plane authentication.")
    if cu_mode in ("create", "reuse"):
        target_sub = (values.get("EXISTING_CONTENT_UNDERSTANDING_SUBSCRIPTION_ID") if cu_mode == "reuse" else None) or subscription
        group = values.get("EXISTING_CONTENT_UNDERSTANDING_RESOURCE_GROUP") if cu_mode == "reuse" else values.get("var_rgName")
        if not group and values.get("env_DEPLOYMENT_APPNAME") and values.get("environment"):
            group = f"{values['env_DEPLOYMENT_APPNAME']}-{values['environment']}-rg"
        scope = f"/subscriptions/{target_sub}"
        if group and query(["group", "exists", "--name", group, "--subscription", target_sub]):
            scope += f"/resourceGroups/{group}"
        permissions = query(["rest", "--method", "get", "--url",
                             f"https://management.azure.com{scope}/providers/Microsoft.Authorization/permissions?api-version=2022-04-01"])
        actions = ["Microsoft.Authorization/roleAssignments/write"]
        if cu_mode == "create":
            actions += ["Microsoft.CognitiveServices/accounts/write", "Microsoft.CognitiveServices/accounts/deployments/write"]
        for action in actions:
            if not any(
                any(fnmatch.fnmatchcase(action.lower(), pattern.lower()) for pattern in permission.get("actions", []))
                and not any(fnmatch.fnmatchcase(action.lower(), pattern.lower()) for pattern in permission.get("notActions", []))
                for permission in permissions.get("value", [])
            ):
                raise ValueError("Optional Content Understanding provisioning requires resource/model write and role-assignment permissions at its target scope.")


def configure_optional_settings(item, values, credential, stage_secret=None, cu_request=None, query=run_json):
    """Never let billing creation or a deployment acknowledgement imply runtime consent."""
    provider, cu_mode = selection(values)
    if provider == "none":
        item["enable_web_search"] = False
    elif provider == "foundry":
        connection = copy.deepcopy(item.get("web_search_agent") or {})
        settings = connection.setdefault("other_settings", {}).setdefault("azure_ai_foundry", {})
        changed = settings.get("endpoint") != values["FOUNDRY_PROJECT_ENDPOINT"] or settings.get("agent_id") != values["FOUNDRY_AGENT_ID"]
        settings.update(endpoint=values["FOUNDRY_PROJECT_ENDPOINT"], agent_id=values["FOUNDRY_AGENT_ID"])
        settings.setdefault("authentication_type", "managed_identity")
        settings.setdefault("managed_identity_type", "system_assigned")
        connection.setdefault("agent_type", "aifoundry")
        item["web_search_agent"] = connection
        if changed or item.get("web_search_provider", "foundry") != "foundry":
            item["enable_web_search"] = False
            item["web_search_consent_accepted"] = False
        item["web_search_provider"] = "foundry"
    elif provider == "web_iq":
        config = copy.deepcopy(item.get("web_iq") or {})
        existing_config = copy.deepcopy(config)
        config.setdefault("endpoint", "https://api.microsoft.ai/v3")
        config.setdefault("authentication_type", "key")
        for field in ("language", "region", "max_results", "max_length"):
            config.setdefault(field, {"language": "en", "region": "US", "max_results": 10, "max_length": 3000}[field])
        for field in ("endpoint", "authentication_type", "tenant_id", "client_id", "app_id", "language", "region"):
            if values.get(f"WEB_IQ_{field.upper()}"):
                config[field] = values[f"WEB_IQ_{field.upper()}"]
        for field, limit in (("max_results", 50), ("max_length", 3000)):
            if values.get(f"WEB_IQ_{field.upper()}"):
                config[field] = int(values[f"WEB_IQ_{field.upper()}"])
            if type(config[field]) is not int or not 1 <= config[field] <= limit:
                raise ValueError(f"Web IQ {field} must be an integer in 1..{limit}.")
        supplied_secrets = {field: values.get(f"WEB_IQ_{field.upper()}_SECRET_NAME") for field in ("key", "client_secret")}
        if any(supplied_secrets.values()):
            configure_web_iq_vault(item, values)
        for field, secret_name in supplied_secrets.items():
            if secret_name:
                if stage_secret is None:
                    raise ValueError("Web IQ credentials require validated Key Vault reference staging.")
                reference = stage_secret(secret_name, existing_config.get(field), field)
                if not is_web_iq_secret_reference(reference):
                    raise ValueError("Web IQ credential staging did not return a scoped Key Vault reference.")
                config[field] = reference
        if config["endpoint"] != "https://api.microsoft.ai/v3":
            raise ValueError("Web IQ endpoint must be https://api.microsoft.ai/v3.")
        if config["authentication_type"] not in ("key", "service_principal"):
            raise ValueError("Web IQ authentication_type must be key or service_principal.")
        # Destination/credential changes require a fresh administrator connection test and consent.
        changed = item.get("web_search_provider", "foundry") != "web_iq" or config != existing_config
        if changed:
            item["enable_web_search"] = False
            item["web_iq_consent_accepted"] = False
        ready = bool(config.get("key")) if config["authentication_type"] == "key" else all(
            config.get(field) for field in ("tenant_id", "client_id", "client_secret", "app_id")
        )
        if not ready or not item.get("web_iq_consent_accepted"):
            item["enable_web_search"] = False
        item.update(web_search_provider="web_iq", web_iq=config)
        for key, default in (("web_iq_news_enabled", False), ("web_iq_image_mode", "off"), ("web_iq_video_mode", "off")):
            env_key = key.upper()
            if values.get(env_key) not in (None, ""):
                item[key] = enabled(values[env_key]) if key == "web_iq_news_enabled" else values[env_key]
            else:
                item.setdefault(key, default)
    if cu_mode in ("create", "reuse"):
        endpoint = safe_endpoint(values.get("var_contentUnderstandingEndpoint") or "", ".services.ai.azure.com")
        if cu_request is None:
            raise ValueError("Content Understanding defaults and analyzer readiness must be validated before publishing settings.")
        defaults = json.loads(values.get("CONTENT_UNDERSTANDING_MODEL_DEFAULTS") or "{}")
        name = values["EXISTING_CONTENT_UNDERSTANDING_NAME"] if cu_mode == "reuse" else urlparse(endpoint).hostname.split(".")[0]
        group = values["EXISTING_CONTENT_UNDERSTANDING_RESOURCE_GROUP"] if cu_mode == "reuse" else values["var_rgName"]
        sub = values.get("EXISTING_CONTENT_UNDERSTANDING_SUBSCRIPTION_ID") if cu_mode == "reuse" else None
        deployments = query(["cognitiveservices", "account", "deployment", "list", "--name", name,
                             "--resource-group", group, "--subscription", sub or values["AZURE_SUBSCRIPTION_ID"]])
        deployed_models = {
            deployment["name"]: deployment.get("properties", {}).get("model", {}).get("name")
            for deployment in deployments if deployment.get("properties", {}).get("provisioningState") == "Succeeded"
        }
        validate_cu_readiness(endpoint, defaults, cu_request, deployed_models, configure=cu_mode == "create")
        item.update({
            "azure_content_understanding_endpoint": endpoint,
            "azure_content_understanding_authentication_type": "managed_identity",
            "azure_content_understanding_api_version": CU_API_VERSION,
            "azure_content_understanding_analyzer_id": CU_ANALYZERS[0],
            "azure_content_understanding_image_analyzer_id": CU_ANALYZERS[1],
        })


def validate_cu_readiness(endpoint, defaults, request, deployed_models, configure=False):
    """Only configure new owned resources; reused resources' defaults are never overwritten."""
    url = f"{endpoint}/contentunderstanding/defaults?api-version={CU_API_VERSION}"
    current = request("GET", url).get("modelDeployments", {})
    if not isinstance(current, dict):
        raise ValueError("Content Understanding returned malformed model defaults.")
    if configure:
        conflicts = [key for key, value in defaults.items() if key in current and current[key] != value]
        if conflicts:
            raise ValueError("Existing Content Understanding defaults differ; preserve them and use reuse mode.")
        if any(current.get(key) != value for key, value in defaults.items()):
            request("PATCH", url, {"modelDeployments": {**current, **defaults}})
            current = request("GET", url).get("modelDeployments", {})
            if not isinstance(current, dict) or any(current.get(key) != value for key, value in defaults.items()):
                raise ValueError("Content Understanding model defaults were not verified after configuration.")
    for analyzer_id in CU_ANALYZERS:
        analyzer = request("GET", f"{endpoint}/contentunderstanding/analyzers/{analyzer_id}?api-version={CU_API_VERSION}")
        if analyzer.get("status") != "ready" or analyzer.get("analyzerId") != analyzer_id:
            raise ValueError(f"Content Understanding analyzer {analyzer_id} is not ready.")
        models = analyzer.get("models")
        if not isinstance(models, dict) or not models:
            raise ValueError(f"Content Understanding analyzer {analyzer_id} has no model requirements.")
        if any(not current.get(alias) for alias in models.values()):
            raise ValueError(f"Content Understanding analyzer {analyzer_id} requires configured model defaults.")
        supported = analyzer.get("supportedModels")
        if not isinstance(supported, dict):
            raise ValueError("Content Understanding analyzer did not report supported models.")
        for role, alias in models.items():
            model = deployed_models.get(current[alias])
            if not model or model not in supported.get(role, []):
                raise ValueError(
                    f"Content Understanding analyzer {analyzer_id} model mapping is unavailable/incompatible. "
                    "Cross-resource capacity must be verified separately; use supported local deployments for automatic setup."
                )


def cu_request_for_credential(credential):
    """Bounded metadata/defaults calls; no document/image analysis or automatic redirects."""
    class NoRedirect(urlrequest.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urlrequest.build_opener(NoRedirect())

    def request(method, url, body=None):
        token = credential.get_token("https://cognitiveservices.azure.com/.default").token
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urlrequest.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json",
        })
        try:
            with opener.open(req, timeout=30) as response:
                content = response.read(1024 * 1024 + 1)
                if len(content) > 1024 * 1024:
                    raise ValueError("Content Understanding readiness response exceeded the size limit.")
                result = json.loads(content)
                if not isinstance(result, dict):
                    raise ValueError("Content Understanding readiness returned invalid metadata.")
                return result
        except (urlerror.URLError, OSError, json.JSONDecodeError):
            raise ValueError("Content Understanding readiness failed; verify runner RBAC, defaults and network access. Settings were not published.") from None
    return request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--environment")
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    values = dict(os.environ)
    if args.environment:
        # Explicit AZD environment loading needs dotenv; preprovision policy checks remain stdlib-only.
        from dotenv import dotenv_values
        result = subprocess.run([shutil.which("azd") or "azd", "-C", str(Path(__file__).resolve().parents[1]),
                                 "env", "get-values", "--environment", args.environment],
                                capture_output=True, text=True, check=True, timeout=30)
        values.update(dict(dotenv_values(stream=io.StringIO(result.stdout), interpolate=False)))
    if args.interactive:
        cloud = values.get("AZURE_CLOUD_ENVIRONMENT") or values.get("env_AZURE_CLOUD_ENVIRONMENT") or "public"
        if cloud in ("AzureCloud", "public"):
            values["WEB_SEARCH_PROVIDER"] = input("Web search [preserve/none/foundry/web_iq] (preserve): ").strip() or values.get("WEB_SEARCH_PROVIDER") or "preserve"
            values["CONTENT_UNDERSTANDING_MODE"] = input("Content Understanding [preserve/none/create/reuse] (preserve): ").strip() or values.get("CONTENT_UNDERSTANDING_MODE") or "preserve"
            if values["WEB_SEARCH_PROVIDER"] == "web_iq":
                values["WEB_IQ_RESOURCE_MODE"] = input("Web IQ billing account [create/reuse] (create): ").strip() or values.get("WEB_IQ_RESOURCE_MODE") or "create"
                for key, label, default in (
                    ("WEB_IQ_NEWS_ENABLED", "News [off/on]", "false"),
                    ("WEB_IQ_IMAGE_MODE", "Images [off/text_only/with_media]", "off"),
                    ("WEB_IQ_VIDEO_MODE", "Videos [off/text_only/with_media]", "off"),
                ):
                    values[key] = input(f"{label} ({values.get(key) or default}): ").strip() or values.get(key) or default
                    if key == "WEB_IQ_NEWS_ENABLED":
                        values[key] = {"off": "false", "on": "true"}.get(values[key], values[key])
                if values["WEB_IQ_RESOURCE_MODE"] == "reuse":
                    for key in ("EXISTING_WEB_IQ_NAME", "EXISTING_WEB_IQ_RESOURCE_GROUP"):
                        values[key] = input(f"{key} ({values.get(key) or ''}): ").strip() or values.get(key) or ""
                values["WEB_IQ_SUBSCRIPTION_ELIGIBLE"] = input("Paid subscription and Microsoft Web IQ access confirmed [true/false]: ").strip()
            if values["WEB_SEARCH_PROVIDER"] in ("foundry", "web_iq"):
                terms = "https://www.microsoft.com/en-us/webiq/webiq-legal" if values["WEB_SEARCH_PROVIDER"] == "web_iq" else "https://www.microsoft.com/en-us/bing/apis/grounding-legal"
                values["WEB_SEARCH_TERMS_ACKNOWLEDGED"] = input(f"Review {terms}. Acknowledge deployment terms (NOT runtime consent) [true/false]: ").strip()
            if values["WEB_SEARCH_PROVIDER"] == "foundry":
                for key in ("FOUNDRY_PROJECT_ENDPOINT", "FOUNDRY_AGENT_ID"):
                    values[key] = input(f"{key} ({values.get(key) or ''}): ").strip() or values.get(key) or ""
            if values["CONTENT_UNDERSTANDING_MODE"] in ("create", "reuse"):
                for key in ("CONTENT_UNDERSTANDING_LOCATION", "OPTIONAL_SERVICES_DEPLOYMENT_PRINCIPAL_ID"):
                    values[key] = input(f"{key} ({values.get(key) or ''}): ").strip() or values.get(key) or ""
                fields = ("EXISTING_CONTENT_UNDERSTANDING_NAME", "EXISTING_CONTENT_UNDERSTANDING_RESOURCE_GROUP") if values["CONTENT_UNDERSTANDING_MODE"] == "reuse" else ("CONTENT_UNDERSTANDING_MODELS", "CONTENT_UNDERSTANDING_MODEL_DEFAULTS")
                for key in fields:
                    values[key] = input(f"{key} ({values.get(key) or ''}): ").strip() or values.get(key) or ""
    selection(values)
    if args.preflight:
        preflight(values)
    if args.environment:
        for key in (
            "WEB_SEARCH_PROVIDER", "CONTENT_UNDERSTANDING_MODE", "WEB_IQ_NEWS_ENABLED", "WEB_IQ_IMAGE_MODE", "WEB_IQ_VIDEO_MODE",
            "WEB_IQ_RESOURCE_MODE", "WEB_IQ_SUBSCRIPTION_ELIGIBLE", "WEB_SEARCH_TERMS_ACKNOWLEDGED",
            "EXISTING_WEB_IQ_NAME", "EXISTING_WEB_IQ_RESOURCE_GROUP", "FOUNDRY_PROJECT_ENDPOINT", "FOUNDRY_AGENT_ID",
            "CONTENT_UNDERSTANDING_LOCATION", "OPTIONAL_SERVICES_DEPLOYMENT_PRINCIPAL_ID",
            "EXISTING_CONTENT_UNDERSTANDING_NAME", "EXISTING_CONTENT_UNDERSTANDING_RESOURCE_GROUP",
            "CONTENT_UNDERSTANDING_MODELS", "CONTENT_UNDERSTANDING_MODEL_DEFAULTS",
        ):
            if args.interactive and values.get(key) is not None:
                subprocess.run([shutil.which("azd") or "azd", "-C", str(Path(__file__).resolve().parents[1]), "env", "set", key, values[key], "--environment", args.environment],
                               check=True, capture_output=True, timeout=30)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as error:
        raise SystemExit(f"Optional service configuration stopped: {error}") from None
    except subprocess.SubprocessError:
        raise SystemExit("Unable to read/save the selected AZD environment; no resources were provisioned.") from None
