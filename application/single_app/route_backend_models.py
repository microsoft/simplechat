# route_backend_models.py

import logging

from config import *
from functions_authentication import *
from functions_governance import ensure_governance_access
from functions_group import (
    GROUP_WRITE_CONFLICT_CODE,
    GROUP_WRITE_CONFLICT_MESSAGE,
    GroupDocumentWriteConflict,
    assert_group_role,
    get_group_model_endpoints,
    require_active_group,
    update_group_model_endpoints,
)
from functions_group_endpoint_access import (
    clean_up_committed_group_endpoint_credentials,
    discard_staged_group_endpoint_credentials,
    group_endpoint_error_response,
    keep_staged_group_endpoint_credentials,
    read_strict_json_object,
    reject_query_parameters,
    require_group_endpoint_discovery_context,
    staged_group_endpoint_credentials,
)
from functions_keyvault import SecretReturnType, keyvault_model_endpoint_cleanup_helper, keyvault_model_endpoint_delete_helper, keyvault_model_endpoint_get_helper, keyvault_model_endpoint_save_helper
from functions_model_capabilities import ModelTokenBudgetError
from functions_model_endpoint_app_identity import check_application_identity_request, check_application_identity_save
from functions_model_endpoint_runtime import build_model_endpoint_sync_chat_client
from functions_model_endpoint_types import (
    DEFAULT_ANTHROPIC_VERSION,
    MODEL_ENDPOINT_PROVIDER_CUSTOM,
    get_model_endpoint_api_type,
    resolve_model_endpoint_request_model,
)
from functions_model_endpoint_validation import (
    ModelEndpointValidationError,
    validate_custom_model_endpoint,
    validate_custom_model_endpoints,
)
from functions_settings import *
from foundry_agent_runtime import FOUNDRY_DELEGATED_AUTH_REQUIRED_MESSAGE, FoundryAgentUserAuthenticationRequired, list_foundry_agents_from_endpoint, list_foundry_workflows_from_endpoint, list_new_foundry_agents_from_endpoint, resolve_foundry_project_base, resolve_foundry_project_api_version, build_project_credential, resolve_authority
from functions_appinsights import log_event
from functions_image_api_route import is_image_capable_model_name
from functions_ai_connections import AIConnectionError, describe_model_capabilities, supports_model_capability
from functions_model_capabilities import get_model_catalog_capabilities, resolve_model_vision_support
from functions_model_catalog import (
    ModelCatalogError, TASKS, get_effective_model_profiles, apply_model_profile,
)
from app_settings_store import SettingsConflictError, SettingsUnavailableError
from functions_model_endpoint_diagnostics import SanitizedModelEndpointError
from model_endpoint_clients import (
    MODEL_ENDPOINT_PROTOCOL_ANTHROPIC,
    MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI,
    MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE,
    build_anthropic_chat_client,
    build_openai_style_chat_client,
    infer_model_endpoint_protocol,
    normalize_anthropic_messages_url,
    normalize_openai_style_base_url,
    resolve_custom_openai_base_url,
)
from swagger_wrapper import swagger_route, get_auth_security
from azure.identity import DefaultAzureCredential, ClientSecretCredential, get_bearer_token_provider
import re
import requests
import uuid


def _get_configured_models(settings, setting_key):
    configured = settings.get(setting_key, {}) or {}
    return configured.get('all', []) if isinstance(configured, dict) else []


def _is_foundry_project_endpoint(endpoint):
    return 'services.ai.azure.com' in (endpoint or '').lower()


def register_route_backend_models(bp):
    """
    Register backend routes for fetching Azure OpenAI models.
    """

    def catalog_response(settings, *, admin=False):
        profiles = get_effective_model_profiles(settings)
        if not admin:
            profiles = [profile for profile in profiles if not profile["archived"]]
        payload = {"profiles": profiles, "tasks": TASKS}
        if admin:
            payload["etag"] = settings.get("_etag")
            links = {profile["id"]: [] for profile in profiles}
            for endpoint in settings.get("model_endpoints") or []:
                for model in endpoint.get("models") or []:
                    identity = str(model.get("modelName") or model.get("deploymentName") or "").casefold()
                    profile = next((
                        item for item in profiles if item["id"] == model.get("catalogProfileId")
                        or (not model.get("catalogProfileId") and item["origin"] == "built_in"
                            and identity in {str(value).casefold() for value in [item["id"], *item["aliases"]]})
                    ), None)
                    if profile is not None:
                        effective = apply_model_profile(model, endpoint, settings, profiles)
                        links[profile["id"]].append({
                            "connection": endpoint.get("name") or endpoint.get("id"),
                            "model": model.get("displayName") or model.get("deploymentName") or model.get("modelName"),
                            "enabled": bool(endpoint.get("enabled", True) and model.get("enabled", True)),
                            "capabilities": {key: value for key, value in effective.get("capabilities", {}).items()
                                             if type(value) is bool},
                        })
            for profile in profiles:
                profile["linked_models"] = links[profile["id"]]
        return jsonify(payload)

    def read_catalog(*, admin=False):
        try:
            return catalog_response(get_settings(), admin=admin)
        except Exception as exc:
            log_event("[MODELS] Catalog load failed.", level=logging.ERROR, extra={"error_type": type(exc).__name__})
            return jsonify({"error": "Unable to load the model catalog. Retry or contact an administrator."}), 503

    @bp.route('/api/models/catalog', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def model_catalog_choices():
        """Public profile metadata only; no settings, secrets, or deployment inventory."""
        return read_catalog()

    @bp.route('/api/admin/model-catalog', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def admin_model_catalog():
        return read_catalog(admin=True)

    def save_catalog(profile_id=None):
        try:
            settings = save_model_catalog_change(request.get_json(silent=True), profile_id=profile_id)
            return catalog_response(settings, admin=True)
        except ModelCatalogError as exc:
            return jsonify({"error": exc.public_message, "field": exc.field, "code": exc.code}), 400
        except SettingsConflictError:
            return jsonify({"error": "The catalog changed. Reload and review before saving.", "code": "catalog_conflict"}), 409
        except SettingsUnavailableError:
            return jsonify({"error": "Unable to confirm the save. Reload and verify before retrying."}), 503
        except Exception as exc:
            log_event("[MODELS] Catalog save failed.", level=logging.ERROR, extra={"error_type": type(exc).__name__})
            return jsonify({"error": "Unable to save the model catalog."}), 500

    @bp.route('/api/admin/model-catalog', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def create_model_catalog_profile():
        return save_catalog()

    @bp.route('/api/admin/model-catalog/<profile_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def update_model_catalog_profile(profile_id):
        return save_catalog(profile_id)

    def log_models_debug(message, extra=None):
        log_event(f"[MODELS] {message}", extra=extra, debug_only=True, category="Models")

    def log_models_exception(message, exception, extra=None, level=logging.ERROR):
        properties = dict(extra or {})
        properties["exception_type"] = type(exception).__name__
        log_event(
            f"[MODELS] {message}",
            extra=properties,
            level=level,
            exceptionTraceback=level >= logging.ERROR,
        )

    def build_safe_error_response(user_message, status_code):
        return jsonify({"error": user_message}), status_code

    def build_group_access_error_response(user_id, exception, resource_name):
        extra = {
            "user_id": user_id,
            "resource": resource_name,
        }
        if isinstance(exception, ValueError):
            log_event(
                "[MODELS] Group access blocked because no active group was selected",
                extra=extra,
                level=logging.WARNING,
            )
            return build_safe_error_response(
                f"Select an active group before accessing {resource_name}.",
                400,
            )
        if isinstance(exception, LookupError):
            log_event(
                "[MODELS] Group access blocked because the group could not be found",
                extra=extra,
                level=logging.WARNING,
            )
            return build_safe_error_response("The selected group could not be found.", 404)

        log_event(
            "[MODELS] Group access denied",
            extra=extra,
            level=logging.WARNING,
        )
        return build_safe_error_response(
            f"You do not have access to {resource_name}.",
            403,
        )

    def resolve_scoped_model_endpoints(user_id, scope, group_id=None):
        # ``group_id`` names the group for the immutable-target routes, which have
        # already authorized it from the path. Only the legacy callers, which pass
        # nothing, fall back to the account's active group.
        settings = get_settings()
        endpoints = []

        def get_governed_endpoints(candidate_endpoints, feature_key, endpoint_scope):
            try:
                ensure_governance_access(feature_key, user_id)
            except PermissionError:
                return []

            governed_endpoints = []
            for endpoint in candidate_endpoints or []:
                if not isinstance(endpoint, dict):
                    continue
                endpoint_id = str(endpoint.get("id") or "").strip()
                if endpoint_id:
                    try:
                        ensure_governance_access(
                            feature_key,
                            user_id,
                            item_entity_type="global_endpoint",
                            item_id=endpoint_id,
                        )
                    except PermissionError:
                        continue
                governed_endpoint = dict(endpoint)
                governed_endpoint["_governance_endpoint_scope"] = endpoint_scope
                governed_endpoints.append(governed_endpoint)
            return governed_endpoints

        if scope == "group":
            if settings.get("allow_group_custom_endpoints", False):
                if group_id is None:
                    group_id = require_active_group(user_id)
                endpoints.extend(get_governed_endpoints(get_group_model_endpoints(group_id), "governance_group_endpoints", "group"))
        elif scope == "user":
            if settings.get("allow_user_custom_endpoints", False):
                user_settings = get_user_settings(user_id)
                endpoints.extend(get_governed_endpoints(user_settings.get("settings", {}).get("personal_model_endpoints", []), "governance_user_endpoints", "user"))
        endpoints.extend(get_governed_endpoints(settings.get("model_endpoints", []) or [], "governance_global_endpoints", "global"))
        return endpoints

    def resolve_endpoint_by_id(user_id, scope, endpoint_id, group_id=None):
        endpoints = resolve_scoped_model_endpoints(user_id, scope, group_id=group_id)
        endpoint = next((endpoint for endpoint in endpoints if endpoint.get("id") == endpoint_id), None)
        if endpoint:
            endpoint = dict(endpoint)
            endpoint_scope = endpoint.pop("_governance_endpoint_scope", scope)
            feature_key = "governance_global_endpoints"
            if endpoint_scope in ("user", "group"):
                feature_key = f"governance_{endpoint_scope}_endpoints"
            ensure_governance_access(
                feature_key,
                user_id,
                item_entity_type="global_endpoint",
                item_id=endpoint_id,
            )
            # A group or user route also resolves global endpoints. Each is hydrated
            # under the scope it is stored in, so a global endpoint is never judged by
            # the group and personal application identity rule.
            endpoint["_endpoint_scope"] = endpoint_scope
        return endpoint

    def resolve_endpoint_scope_value(endpoint_cfg, fallback_endpoint_id=""):
        endpoint_id = (fallback_endpoint_id or endpoint_cfg.get("id") or "").strip()
        if not endpoint_id:
            raise ValueError("Endpoint ID is required to resolve stored secrets.")
        return endpoint_id

    def resolve_request_endpoint_payload(payload, scope="global", *, for_chat_test=False, group_id=None):
        user_id = get_current_user_id()
        endpoint_id = str(payload.get("endpoint_id") or payload.get("id") or "").strip()
        persisted_endpoint = resolve_endpoint_by_id(user_id, scope, endpoint_id, group_id=group_id) if endpoint_id else None

        if scope in ("user", "group") and endpoint_id:
            if not persisted_endpoint:
                log_models_debug(f"Rejecting {scope} request for unknown endpoint_id={endpoint_id}.")
                log_event(
                    "[MODELS] Model endpoint lookup failed",
                    extra={"user_id": user_id, "scope": scope, "endpoint_id": endpoint_id},
                    level=logging.WARNING,
                )
                raise LookupError("Model endpoint not found.")

            # Persisted non-admin endpoints must resolve from stored configuration only.
            merged_payload = merge_model_endpoint_payload(persisted_endpoint, {})
            if "model" in payload:
                requested_model = payload.get("model")
                if not isinstance(requested_model, dict):
                    raise LookupError("Model endpoint model not found.")
                requested_model_id = str(requested_model.get("id") or "").strip()
                requested_model_name = resolve_model_endpoint_request_model(
                    persisted_endpoint,
                    requested_model,
                )
                persisted_model = next(
                    (
                        model
                        for model in (persisted_endpoint.get("models") or [])
                        if isinstance(model, dict)
                        and model.get("enabled", True)
                        and (
                            (
                                requested_model_id
                                and str(model.get("id") or "").strip() == requested_model_id
                            )
                            or (
                                requested_model_name
                                and resolve_model_endpoint_request_model(
                                    persisted_endpoint,
                                    model,
                                ) == requested_model_name
                            )
                        )
                    ),
                    None,
                )
                if not persisted_model:
                    raise LookupError("Model endpoint model not found.")
                merged_payload["model"] = persisted_model
        else:
            merged_payload = merge_model_endpoint_payload(persisted_endpoint or {}, payload)
            if scope in ("user", "group"):
                merged_payload = check_application_identity_request(merged_payload, scope)

        # Hydrate under the scope the endpoint is stored in: a group or user route also
        # resolves global endpoints. An unsaved draft keeps the route's own scope.
        merged_payload.pop("_endpoint_scope", None)
        endpoint_scope = (persisted_endpoint or {}).get("_endpoint_scope") or scope

        if endpoint_id:
            merged_payload["id"] = endpoint_id

        # A draft provider override must not borrow saved custom credentials for chat.
        if for_chat_test and any(
            isinstance(endpoint, dict)
            and str(endpoint.get("provider") or "").strip().lower() == "openai_compatible"
            for endpoint in (persisted_endpoint, merged_payload)
        ):
            raise AIConnectionError(
                "Custom connections support embeddings only. Save a global embedding default and use Test embeddings.",
                "model_capability_unavailable",
            )

        scope_value = merged_payload.get("id") or endpoint_id
        if scope_value:
            merged_payload = keyvault_model_endpoint_get_helper(
                merged_payload,
                resolve_endpoint_scope_value(merged_payload, scope_value),
                scope=endpoint_scope,
                return_type=SecretReturnType.VALUE,
            )
        return merged_payload

    def build_foundry_settings_from_endpoint(endpoint_cfg):
        connection = endpoint_cfg.get("connection", {}) or {}
        auth = endpoint_cfg.get("auth", {}) or {}
        return {
            "endpoint": connection.get("endpoint"),
            "api_version": connection.get("project_api_version") or connection.get("api_version") or "v1",
            "responses_api_version": connection.get("openai_api_version") or connection.get("api_version") or "",
            "activity_api_version": connection.get("project_api_version") or connection.get("api_version") or "",
            "project_name": connection.get("project_name") or "",
            "authentication_type": "delegated_user",
            "managed_identity_type": auth.get("managed_identity_type") or "system_assigned",
            "managed_identity_client_id": auth.get("managed_identity_client_id") or "",
            "tenant_id": auth.get("tenant_id") or "",
            "client_id": auth.get("client_id") or "",
            "client_secret": auth.get("client_secret") or "",
            "cloud": auth.get("management_cloud") or "",
            "authority": auth.get("custom_authority") or "",
            "foundry_scope": auth.get("foundry_scope") or "",
        }

    def resolve_foundry_scope(auth_settings):
        return resolve_model_endpoint_foundry_scope(auth_settings)

    def build_foundry_token(auth_settings):
        management_cloud = (auth_settings.get("management_cloud") or "public").lower()
        scope = resolve_foundry_scope(auth_settings)
        auth_type = (auth_settings.get("type") or "managed_identity").lower()
        log_models_debug(f"Foundry token auth_type={auth_type}, scope={scope}, cloud={management_cloud}")
        credential = build_project_credential(auth_settings)
        token = credential.get_token(scope)
        return token.token


    def build_cognitive_services_client(subscription_id, auth_settings):
        auth_type = (auth_settings.get("type") or "managed_identity").lower()
        management_cloud = (auth_settings.get("management_cloud") or "public").lower()
        log_models_debug(f"Building ARM client auth_type={auth_type}, subscription_id={subscription_id}, cloud={management_cloud}")
        if auth_type == "service_principal":
            authority_override = resolve_authority(auth_settings)
            credential = ClientSecretCredential(
                tenant_id=auth_settings.get("tenant_id"),
                client_id=auth_settings.get("client_id"),
                client_secret=auth_settings.get("client_secret"),
                authority=authority_override
            )
        elif auth_type == "api_key":
            log_models_debug("API key auth requested for model discovery (not supported).")
            raise ValueError("API key auth is not supported for model discovery.")
        else:
            managed_identity_client_id = auth_settings.get("managed_identity_client_id") or None
            credential = DefaultAzureCredential(managed_identity_client_id=managed_identity_client_id)

        if AZURE_ENVIRONMENT in ("usgovernment", "custom"):
            return CognitiveServicesManagementClient(
                credential=credential,
                subscription_id=subscription_id,
                base_url=resource_manager,
                credential_scopes=credential_scopes
            )

        return CognitiveServicesManagementClient(
            credential=credential,
            subscription_id=subscription_id
        )

    def get_aoai_account_name(endpoint):
        endpoint_host = (endpoint or "").strip().replace("https://", "").replace("http://", "").split("/")[0]
        return endpoint_host.split(".")[0].strip()

    def get_management_cloud_for_environment():
        return get_model_endpoint_management_cloud_for_environment()

    def build_legacy_aoai_discovery_auth_settings():
        return {
            "type": "service_principal",
            "management_cloud": get_management_cloud_for_environment(),
            "custom_authority": get_model_endpoint_default_custom_authority(),
            "tenant_id": TENANT_ID,
            "client_id": CLIENT_ID,
            "client_secret": MICROSOFT_PROVIDER_AUTHENTICATION_SECRET,
        }

    def build_inference_client(
        endpoint,
        api_version,
        auth_settings,
        provider="aoai",
        deployment_name="",
        api_type="",
        anthropic_version=DEFAULT_ANTHROPIC_VERSION,
        url_mode="",
        endpoint_config=None,
    ):
        client, runtime_protocol = build_model_endpoint_sync_chat_client(
            auth_settings,
            provider,
            endpoint,
            api_version,
            deployment_name=deployment_name,
            api_type=api_type,
            url_mode=url_mode,
            anthropic_version=anthropic_version,
            settings=get_settings(),
            endpoint_config=endpoint_config,
        )
        log_models_debug(
            f"Inference client provider={provider} protocol={runtime_protocol}"
        )
        return client

    def describe_resolved_request_url(provider, endpoint, api_type, url_mode, runtime_protocol):
        """Return the URL SimpleChat actually calls, for display after a test."""
        try:
            if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_ANTHROPIC:
                return normalize_anthropic_messages_url(
                    endpoint,
                    direct_custom=provider == MODEL_ENDPOINT_PROVIDER_CUSTOM,
                    url_mode=url_mode,
                )
            if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE:
                if provider == MODEL_ENDPOINT_PROVIDER_CUSTOM:
                    return resolve_custom_openai_base_url(endpoint, api_type, url_mode)
                return normalize_openai_style_base_url(endpoint)
            return str(endpoint or "")
        except Exception:
            return str(endpoint or "")

    def fetch_foundry_project_deployments(endpoint, api_version, auth_settings, project_name=None):
        if not endpoint:
            raise ValueError("Missing Foundry project endpoint")

        auth_type = (auth_settings.get("type") or "managed_identity").lower()
        if auth_type == "api_key":
            log_models_debug("API key auth requested for Foundry project discovery (not supported).")
            raise ValueError("API key auth is not supported for Foundry project model discovery.")

        token = build_foundry_token(auth_settings)
        headers = {
            "Authorization": f"Bearer {token}"
        }

        base = resolve_foundry_project_base(endpoint, project_name)
        params = {
            "api-version": resolve_foundry_project_api_version(api_version),
            "deploymentType": "ModelDeployment"
        }
        url = f"{base}/deployments"
        log_models_debug(f"Foundry project deployments URL={url}")

        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        return payload.get("value", [])

    def extract_provisioning_state(deployment):
        properties = getattr(deployment, "properties", None) or {}
        if isinstance(properties, dict):
            return properties.get("provisioningState") or properties.get("provisioning_state")
        return getattr(properties, "provisioning_state", None) or getattr(properties, "provisioningState", None)

    def is_deployment_enabled(deployment):
        state = extract_provisioning_state(deployment)
        if not state:
            return True
        return str(state).lower() == "succeeded"

    def handle_fetch_model_list(scope="global", group_id=None):
        try:
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                return jsonify({"error": "Model endpoint payload must be an object."}), 400
            data = resolve_request_endpoint_payload(data, scope=scope, group_id=group_id)
            provider = (data.get("provider") or "aoai").lower()
            if provider == "openai_compatible":
                return jsonify({
                    "error": "Custom OpenAI-compatible connections use manually configured embedding models. Azure discovery is not supported.",
                    "code": "model_discovery_unsupported",
                }), 400
            connection = data.get("connection") or {}
            auth_settings = data.get("auth") or {}
            management = data.get("management") or {}
            auth_type = (auth_settings.get("type") or "managed_identity").lower()
            if provider == "custom":
                if not get_model_endpoint_api_type(data):
                    return jsonify({"error": "Custom endpoint API type is not supported."}), 400
                return jsonify({
                    "models": [],
                    "manual_models_required": True,
                    "message": "Custom connections use manually configured model names or deployments; management discovery is not available.",
                })
            log_models_debug(
                "Fetch model list request"
                f" provider={provider} auth_type={auth_type}"
                f" endpoint={connection.get('endpoint') or ''}"
                f" subscription_id_present={bool(management.get('subscription_id'))}"
                f" resource_group_present={bool(management.get('resource_group'))}"
            )

            if provider == MODEL_ENDPOINT_PROVIDER_CUSTOM:
                return build_safe_error_response(
                    "Model discovery is not available for Custom endpoints. Add models manually.",
                    400,
                )

            if provider in ("aifoundry", "new_foundry"):
                endpoint = connection.get("endpoint")
                api_version = connection.get("project_api_version") or connection.get("api_version") or "v1"
                project_name = connection.get("project_name")
                log_models_debug(f"Foundry fetch project endpoint={endpoint or ''} api_version={api_version}")
                deployments = fetch_foundry_project_deployments(endpoint, api_version, auth_settings, project_name=project_name)
                mapped = []
                for item in deployments:
                    deployment_name = item.get("name") or item.get("deploymentName")
                    if not deployment_name:
                        continue
                    model_name = item.get("modelName")
                    if not model_name and isinstance(item.get("model"), dict):
                        model_name = item["model"].get("name")
                    model_version = item.get("modelVersion")
                    if not model_version and isinstance(item.get("model"), dict):
                        model_version = item["model"].get("version")
                    mapped_model = {
                        "deploymentName": deployment_name,
                        "modelName": model_name or ""
                    }
                    if isinstance(model_version, (str, int)) and not isinstance(model_version, bool):
                        mapped_model["modelVersion"] = str(model_version)
                    mapped.append(mapped_model)
                for model in mapped:
                    model["capability_status"] = describe_model_capabilities(model, provider, endpoint=data)
                return jsonify({"models": mapped})

            if provider == "aoai":
                subscription_id = management.get("subscription_id")
                resource_group = management.get("resource_group")
                endpoint = connection.get("endpoint") or ""
                account_name = endpoint.split('.')[0].replace("https://", "").replace("http://", "")
                log_models_debug(
                    f"AOAI fetch account_name={account_name}"
                    f" subscription_id={subscription_id or ''}"
                    f" resource_group={resource_group or ''}"
                )
                if not subscription_id or not resource_group or not account_name:
                    raise ValueError("Azure OpenAI model discovery requires subscription ID, resource group, and endpoint.")

                client = build_cognitive_services_client(subscription_id, auth_settings)
                deployments = client.deployments.list(
                    resource_group_name=resource_group,
                    account_name=account_name
                )

                mapped = []
                for deployment in deployments:
                    if not is_deployment_enabled(deployment):
                        continue
                    model_name = deployment.properties.model.name
                    if model_name and (
                        "gpt" in model_name.lower() or
                        re.search(r"o\d+", model_name.lower()) or
                        supports_model_capability({"modelName": model_name}, "image_generation", provider) or
                        supports_model_capability({"modelName": model_name}, "embeddings", provider) or
                        (
                            get_model_catalog_capabilities({"modelName": model_name}, strict_identity=True)
                            or {}
                        ).get("generatesEmbeddings") is True
                    ):
                        mapped_model = {
                            "deploymentName": deployment.name,
                            "modelName": model_name
                        }
                        model_version = getattr(deployment.properties.model, "version", None)
                        if isinstance(model_version, (str, int)) and not isinstance(model_version, bool):
                            mapped_model["modelVersion"] = str(model_version)
                        mapped.append(mapped_model)
                for model in mapped:
                    model["capability_status"] = describe_model_capabilities(model, provider, endpoint=data)
                return jsonify({"models": mapped})

            return jsonify({"error": "Model provider not found."}), 400
        except AIConnectionError as exc:
            return jsonify({"error": exc.public_message, "code": exc.code}), 400
        except LookupError as exc:
            log_event(
                "[MODELS] Fetch model list blocked because the model endpoint was not found",
                extra={"scope": scope},
                level=logging.WARNING,
            )
            return build_safe_error_response("The selected model endpoint could not be found.", 404)
        except ValueError as exc:
            log_models_exception(
                "Fetch model list validation failed",
                exc,
                extra={"scope": scope},
                level=logging.WARNING,
            )
            return build_safe_error_response(
                "Unable to fetch models. Review the endpoint configuration and try again.",
                400,
            )
        except Exception as e:
            log_models_exception("Fetch model list failed", e, extra={"scope": scope})
            return build_safe_error_response(
                "Unable to fetch models right now. Try again later or contact an administrator.",
                400,
            )

    def handle_test_model_connection(scope="global", group_id=None):
        try:
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                raise AIConnectionError("Model endpoint payload must be an object.", "invalid_model_selection")
            data = resolve_request_endpoint_payload(data, scope=scope, for_chat_test=True, group_id=group_id)
            provider = (data.get("provider") or "aoai").lower()
            if provider == "openai_compatible":
                return jsonify({
                    "error": "Custom connections support embeddings only. Save a global embedding default and use Test embeddings.",
                    "code": "model_capability_unavailable",
                }), 400
            connection = data.get("connection") or {}
            auth_settings = data.get("auth") or {}
            model = data.get("model") or {}
            if not isinstance(model, dict) or not model:
                raise AIConnectionError("Supply a nonempty model selection object.", "invalid_model_selection")
            if any(
                model.get(key) is not None and not isinstance(model[key], str)
                for key in ("id", "deploymentName", "modelName")
            ):
                raise AIConnectionError("Model selection identifiers must be text.", "invalid_model_selection")
            configured_model = next((
                item for item in data.get("models") or []
                if isinstance(item, dict) and (
                    (model.get("id") and item.get("id") == model["id"])
                    or (
                        model.get("deploymentName")
                        and item.get("deploymentName") == model["deploymentName"]
                    )
                )
            ), None)
            model = configured_model or model

            endpoint = connection.get("endpoint") or ""
            api_version = connection.get("openai_api_version") or connection.get("api_version") or ""
            api_type = get_model_endpoint_api_type(data)
            anthropic_version = (
                connection.get("anthropic_version")
                or DEFAULT_ANTHROPIC_VERSION
            )
            request_model = resolve_model_endpoint_request_model(data, model)
            runtime_protocol = infer_model_endpoint_protocol(
                provider,
                endpoint,
                request_model,
                api_type,
            )

            auth_type = (auth_settings.get("type") or "managed_identity").lower()
            log_models_debug(
                "Test model request"
                f" provider={provider} auth_type={auth_type}"
                f" endpoint={endpoint} model={request_model}"
            )

            if provider == MODEL_ENDPOINT_PROVIDER_CUSTOM:
                validation_endpoint = dict(data)
                validation_endpoint["models"] = [model]
                validate_custom_model_endpoint(
                    validation_endpoint,
                    get_settings(),
                )

            if not endpoint or not request_model:
                return jsonify({"error": "Endpoint and model identifier are required."}), 400

            if not supports_model_capability(model, "chat", provider, endpoint=data):
                return jsonify({
                    "error": "This model is not available for chat. Use the test for its published capability; embedding models use Test embeddings.",
                    "code": "model_capability_unavailable",
                }), 400

            if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI and not api_version:
                return jsonify({"error": "Endpoint, API version, and model identifier are required."}), 400

            if provider not in (
                "aoai",
                "aifoundry",
                "new_foundry",
                "anthropic",
                "claude",
                MODEL_ENDPOINT_PROVIDER_CUSTOM,
            ):
                return jsonify({"error": "Model provider not found."}), 400

            gpt_client = build_inference_client(
                endpoint,
                api_version,
                auth_settings,
                provider=provider,
                deployment_name=request_model,
                api_type=api_type,
                anthropic_version=anthropic_version,
                url_mode=connection.get("url_mode") or "",
                endpoint_config={**data, "models": [model]},
            )
            try:
                response = gpt_client.chat.completions.create(
                    model=request_model,
                    messages=[{"role": "user", "content": "Testing access."}]
                )
            finally:
                close_client = getattr(gpt_client, "close", None)
                if callable(close_client):
                    close_client()

            if getattr(response, "choices", None):
                # Report what was actually called. URL normalization can rewrite
                # the configured endpoint, and that rewrite was previously
                # invisible, so a working test could still hide a surprise.
                return jsonify({
                    "success": True,
                    "resolved": {
                        "request_url": describe_resolved_request_url(
                            provider,
                            endpoint,
                            api_type,
                            connection.get("url_mode") or "",
                            runtime_protocol,
                        ),
                        "protocol": runtime_protocol,
                        "api_type": api_type,
                        "request_model": request_model,
                    },
                }), 200

            return jsonify({"error": "No response returned from model."}), 400

        except AIConnectionError as exc:
            return jsonify({"error": exc.public_message, "code": exc.code}), 400
        except ModelEndpointValidationError as exc:
            return jsonify({"error": exc.public_message}), 400
        except SanitizedModelEndpointError as exc:
            return jsonify({"error": exc.public_message}), 400
        except LookupError as exc:
            log_event(
                "[MODELS] Test model request blocked because the model endpoint was not found",
                extra={"scope": scope},
                level=logging.WARNING,
            )
            return build_safe_error_response("The selected model endpoint could not be found.", 404)
        except ValueError as exc:
            log_models_exception(
                "Test model validation failed",
                exc,
                extra={"scope": scope},
                level=logging.WARNING,
            )
            return build_safe_error_response(
                "Unable to test the model connection. Review the endpoint configuration and try again.",
                400,
            )
        except Exception as e:
            log_models_exception("Test model connection failed", e, extra={"scope": scope})
            return build_safe_error_response(
                "Unable to test the model connection right now. Try again later or contact an administrator.",
                400,
            )

    @bp.route('/api/models/vision-capability', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @admin_required
    def resolve_models_vision_capability():
        """Resolve whether each supplied model can accept image input.

        The Model Endpoints editor needs this to pre-fill the image-support checkbox
        when models are fetched from an endpoint, so an administrator does not have to
        answer a question the shipped capability catalog already knows.

        Resolved here rather than in the browser because the rules -- an explicit flag,
        then the catalog, then a name heuristic -- have exactly one implementation in
        ``functions_model_capabilities``. Mirroring them in JavaScript is how the old
        name-matching pattern came to exist in two places and drift.
        """
        payload = request.get_json(silent=True) or {}
        models = payload.get('models')
        if not isinstance(models, list):
            return jsonify({'error': 'Expected a list of models.'}), 400

        resolved = {}
        for entry in models[:200]:
            record = entry if isinstance(entry, dict) else {'deploymentName': entry}
            deployment = str(
                record.get('deploymentName') or record.get('deployment') or ''
            ).strip()
            if not deployment:
                continue

            supports_vision, source = resolve_model_vision_support(record)
            resolved[deployment] = {
                'supports_vision': supports_vision,
                'source': source,
            }

        return jsonify({'models': resolved}), 200

    @bp.route('/api/models/gpt', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @admin_required
    def get_gpt_models():
        """
        Fetch available GPT-like Azure OpenAI deployments using Azure Management API.
        Returns a list of GPT models with deployment names and model information.
        """
        settings = get_settings()

        subscription_id = settings.get('azure_openai_gpt_subscription_id', '')
        resource_group = settings.get('azure_openai_gpt_resource_group', '')
        endpoint = settings.get('azure_openai_gpt_endpoint', '')
        account_name = get_aoai_account_name(endpoint)
        configured_models = _get_configured_models(settings, 'gpt_model')

        if _is_foundry_project_endpoint(endpoint) or not subscription_id or not resource_group or not account_name:
            return jsonify({"models": configured_models}), 200

        client = build_cognitive_services_client(
            subscription_id,
            build_legacy_aoai_discovery_auth_settings()
        )

        models = []
        try:
            deployments = client.deployments.list(
                resource_group_name=resource_group,
                account_name=account_name
            )

            for d in deployments:
                if not is_deployment_enabled(d):
                    continue
                model_name = d.properties.model.name
                if model_name and (
                    "gpt" in model_name.lower() or
                    re.search(r"o\d+", model_name.lower())
                ) and "image" not in model_name.lower():
                    models.append({
                        "deploymentName": d.name,
                        "modelName": model_name
                    })

        except Exception as e:
            log_models_exception("Fetch GPT models failed", e)
            return build_safe_error_response(
                "Unable to fetch available GPT models right now.",
                500,
            )

        return jsonify({"models": models})


    @bp.route('/api/models/embedding', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @admin_required
    def get_embedding_models():
        """
        Fetch available embedding Azure OpenAI deployments using Azure Management API.
        Returns a list of embedding models with deployment names and model information.
        """
        settings = get_settings()

        subscription_id = settings.get('azure_openai_embedding_subscription_id', '')
        resource_group = settings.get('azure_openai_embedding_resource_group', '')
        endpoint = settings.get('azure_openai_embedding_endpoint', '')
        account_name = get_aoai_account_name(endpoint)
        configured_models = _get_configured_models(settings, 'embedding_model')

        if _is_foundry_project_endpoint(endpoint) or not subscription_id or not resource_group or not account_name:
            return jsonify({"models": configured_models}), 200

        client = build_cognitive_services_client(
            subscription_id,
            build_legacy_aoai_discovery_auth_settings()
        )

        models = []
        try:
            deployments = client.deployments.list(
                resource_group_name=resource_group,
                account_name=account_name
            )
            for d in deployments:
                if not is_deployment_enabled(d):
                    continue
                model_name = d.properties.model.name
                if model_name and (
                    "embedding" in model_name.lower() or
                    "ada" in model_name.lower()
                ):
                    models.append({
                        "deploymentName": d.name,
                        "modelName": model_name
                    })
        except Exception as e:
            log_models_exception("Fetch embedding models failed", e)
            return build_safe_error_response(
                "Unable to fetch available embedding models right now.",
                500,
            )

        return jsonify({"models": models})


    @bp.route('/api/models/image', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @admin_required
    def get_image_models():
        """
        Fetch available image-capable Azure OpenAI deployments using Azure Management API.

        This legacy Azure discovery path offers compatible dedicated image deployments.
        GPT chat deployments are excluded by the standalone-only Azure image policy.
        Direct OpenAI image tools and other Foundry image APIs use shared connections.
        """
        settings = get_settings()

        subscription_id = settings.get('azure_openai_image_gen_subscription_id', '')
        resource_group = settings.get('azure_openai_image_gen_resource_group', '')
        endpoint = settings.get('azure_openai_image_gen_endpoint', '')
        account_name = get_aoai_account_name(endpoint)

        if not subscription_id or not resource_group or not account_name:
            return jsonify({"error": "Azure Image Model subscription/RG/endpoint not configured"}), 400

        client = build_cognitive_services_client(
            subscription_id,
            build_legacy_aoai_discovery_auth_settings()
        )

        models = []
        try:
            deployments = client.deployments.list(
                resource_group_name=resource_group,
                account_name=account_name
            )
            for d in deployments:
                if not is_deployment_enabled(d):
                    continue
                model_name = d.properties.model.name
                if model_name and is_image_capable_model_name(model_name):
                    models.append({
                        "deploymentName": d.name,
                        "modelName": model_name
                    })
        except Exception as e:
            log_models_exception("Fetch image models failed", e)
            return build_safe_error_response(
                "Unable to fetch available image models right now.",
                500,
            )

        return jsonify({"models": models})


    @bp.route('/api/models/test-connection', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @admin_required
    def test_model_inference_connection():
        try:
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                return jsonify({"error": "Model endpoint payload must be an object."}), 400
            data = resolve_request_endpoint_payload(data, scope="global")
            provider = (data.get("provider") or "aoai").lower()
            if provider == "openai_compatible":
                return jsonify({
                    "error": "Custom OpenAI-compatible connections use manually configured embedding models. Azure discovery is not supported.",
                    "code": "model_discovery_unsupported",
                }), 400
            connection = data.get("connection") or {}
            management = data.get("management") or {}
            auth_settings = data.get("auth") or {}
            auth_type = (auth_settings.get("type") or "managed_identity").lower()
            log_models_debug(
                "Test connection request"
                f" provider={provider} auth_type={auth_type}"
                f" endpoint={connection.get('endpoint') or ''}"
                f" subscription_id_present={bool(management.get('subscription_id'))}"
                f" resource_group_present={bool(management.get('resource_group'))}"
            )

            if provider == "custom":
                validate_custom_model_endpoint(data, get_settings())
                return jsonify({
                    "success": True,
                    "validation_only": True,
                    "message": "Custom configuration is valid. Use Test Model to verify authentication and inference.",
                })
            if provider in ("aifoundry", "new_foundry"):
                endpoint = connection.get("endpoint")
                api_version = connection.get("project_api_version") or connection.get("api_version") or "v1"
                project_name = connection.get("project_name")
                log_models_debug(f"Foundry test project endpoint={endpoint or ''} api_version={api_version}")
                deployments = fetch_foundry_project_deployments(endpoint, api_version, auth_settings, project_name=project_name)
                return jsonify({"success": True, "count": len(deployments)})

            if provider == "aoai":
                subscription_id = management.get("subscription_id")
                resource_group = management.get("resource_group")
                endpoint = connection.get("endpoint") or ""
                account_name = endpoint.split('.')[0].replace("https://", "").replace("http://", "")
                log_models_debug(
                    f"AOAI test account_name={account_name}"
                    f" subscription_id={subscription_id or ''}"
                    f" resource_group={resource_group or ''}"
                )
                if not subscription_id or not resource_group or not account_name:
                    raise ValueError("Azure OpenAI model discovery requires subscription ID, resource group, and endpoint.")

                client = build_cognitive_services_client(subscription_id, auth_settings)
                deployments = client.deployments.list(
                    resource_group_name=resource_group,
                    account_name=account_name
                )

                count = 0
                for deployment in deployments:
                    if not is_deployment_enabled(deployment):
                        continue
                    model_name = deployment.properties.model.name
                    if model_name and (
                        "gpt" in model_name.lower() or
                        re.search(r"o\d+", model_name.lower()) or
                        supports_model_capability({"modelName": model_name}, "image_generation", provider) or
                        supports_model_capability({"modelName": model_name}, "embeddings", provider) or
                        (
                            get_model_catalog_capabilities({"modelName": model_name}, strict_identity=True)
                            or {}
                        ).get("generatesEmbeddings") is True
                    ):
                        count += 1
                return jsonify({"success": True, "count": count})

            return jsonify({"error": "Model provider not found."}), 400
        except ModelEndpointValidationError as exc:
            return jsonify({"error": exc.public_message}), 400
        except LookupError as e:
            log_event(
                "[MODELS] Test connection blocked because the model endpoint was not found",
                level=logging.WARNING,
            )
            return build_safe_error_response("The selected model endpoint could not be found.", 404)
        except PermissionError as e:
            log_models_exception("Test connection blocked by governance policy", e, level=logging.WARNING)
            return build_safe_error_response("You do not have access to this model connection.", 403)
        except ValueError as e:
            log_models_exception("Test connection validation failed", e, level=logging.WARNING)
            return build_safe_error_response(
                "Unable to validate the model connection. Review the endpoint configuration and try again.",
                400,
            )
        except Exception as e:
            log_models_exception("Test connection failed", e)
            return build_safe_error_response(
                "Unable to validate the model connection right now. Try again later or contact an administrator.",
                400,
            )


    @bp.route('/api/models/fetch', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @admin_required
    def fetch_model_list():
        return handle_fetch_model_list(scope="global")


    @bp.route('/api/user/model-endpoints', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_custom_endpoints')
    def get_user_model_endpoints():
        user_id = get_current_user_id()
        try:
            ensure_governance_access("governance_user_endpoints", user_id)
        except PermissionError as exc:
            return jsonify({"error": str(exc)}), 403
        user_settings = get_user_settings(user_id)
        endpoints = user_settings.get("settings", {}).get("personal_model_endpoints", [])
        return jsonify({
            "endpoints": sanitize_model_endpoints_for_frontend(endpoints)
        })


    def _load_personal_endpoints(user_id):
        """Read the caller's stored personal endpoints as a list."""
        user_settings = get_user_settings(user_id)
        endpoints = user_settings.get("settings", {}).get("personal_model_endpoints", [])
        return endpoints if isinstance(endpoints, list) else []

    def _find_personal_endpoint(endpoints, endpoint_id):
        reference = str(endpoint_id or "")
        for endpoint in endpoints:
            if isinstance(endpoint, dict) and str(endpoint.get("id") or "") == reference:
                return endpoint
        return None

    def _normalize_personal_endpoints(incoming, existing=None):
        """Apply shared budget and outbound-policy validation to every write path."""
        try:
            merged = (
                merge_model_endpoints_with_existing(incoming, existing)
                if existing is not None else incoming
            )
            normalized, _ = normalize_model_endpoints(merged)
        except ModelTokenBudgetError as exc:
            log_models_exception(
                "Personal model token-budget validation failed",
                exc,
                extra={"scope": "user", "code": exc.code},
                level=logging.WARNING,
            )
            return None, (jsonify({"error": exc.public_message, "error_code": exc.code}), 400)
        try:
            validate_custom_model_endpoints(normalized, get_settings())
        except ModelEndpointValidationError as exc:
            log_models_exception(
                "Personal model endpoint validation failed",
                exc,
                extra={"scope": "user"},
                level=logging.WARNING,
            )
            return None, build_safe_error_response("Invalid Custom model endpoint configuration.", 400)
        return normalized, None

    def save_scoped_endpoint_secrets(normalized, existing_by_id, scope):
        """Run the Key Vault save pass for a personal or group endpoint collection.

        Returns ``(saved_endpoints, None)``, or ``(None, response)`` when a save is
        refused. The application identity rule is applied first to every new or changed
        endpoint, before anything is staged. The helper may then refuse a credential, for
        example a reference that is not the endpoint's own stored one. Nothing has been
        written at that point, so a credential this pass has already staged for an
        earlier endpoint is deleted again.
        """
        try:
            for endpoint in normalized:
                check_application_identity_save(endpoint, existing_by_id.get(endpoint.get("id")), scope)
        except AIConnectionError as exc:
            return None, (jsonify({"error": exc.public_message, "code": exc.code}), 400)

        saved_endpoints = []
        try:
            for endpoint in normalized:
                saved_endpoints.append(keyvault_model_endpoint_save_helper(
                    endpoint,
                    resolve_endpoint_scope_value(endpoint),
                    scope=scope,
                    existing_endpoint=existing_by_id.get(endpoint.get("id")),
                ))
        except ValueError as exc:
            for staged in saved_endpoints:
                try:
                    keyvault_model_endpoint_cleanup_helper(
                        staged, existing_by_id.get(staged.get("id")), staged.get("id"), scope=scope,
                    )
                except Exception as cleanup_exc:
                    log_models_exception(
                        "Unable to remove a credential staged for a refused save",
                        cleanup_exc,
                        extra={"scope": scope},
                        level=logging.WARNING,
                    )
            log_models_exception(
                "Model endpoint credential refused",
                exc,
                extra={"scope": scope},
                level=logging.WARNING,
            )
            return None, build_safe_error_response(
                "A model endpoint credential could not be saved. Re-enter the secret value and try again.",
                400,
            )
        return saved_endpoints, None

    def _persist_personal_endpoints(user_id, normalized, existing):
        """Save a full endpoint list, moving Key Vault secrets to match.

        Secrets are handled in three passes because each endpoint can carry them: saved
        endpoints write theirs, changed endpoints have the superseded version cleaned up,
        and endpoints that are gone have theirs deleted. Skipping the last one would leave
        orphaned secrets behind after a delete.

        Returns ``(saved_endpoints, None)``, or ``(None, response)`` when a credential
        is refused, in which case nothing is written.
        """
        existing_by_id = {
            endpoint.get("id"): endpoint
            for endpoint in existing
            if isinstance(endpoint, dict) and endpoint.get("id")
        }
        saved_endpoints, error = save_scoped_endpoint_secrets(normalized, existing_by_id, "user")
        if error:
            return None, error

        for endpoint in saved_endpoints:
            if not isinstance(endpoint, dict):
                continue
            endpoint_id = endpoint.get("id")
            if not endpoint_id:
                continue
            keyvault_model_endpoint_cleanup_helper(
                existing_by_id.get(endpoint_id),
                endpoint,
                endpoint_id,
                scope="user",
            )

        saved_endpoint_ids = {
            endpoint.get("id")
            for endpoint in saved_endpoints
            if isinstance(endpoint, dict) and endpoint.get("id")
        }
        for endpoint in existing:
            if not isinstance(endpoint, dict):
                continue
            endpoint_id = endpoint.get("id")
            if endpoint_id and endpoint_id not in saved_endpoint_ids:
                keyvault_model_endpoint_delete_helper(endpoint, endpoint_id, scope="user")

        update_user_settings(user_id, {"personal_model_endpoints": saved_endpoints})
        return saved_endpoints, None

    def _single_endpoint_response(saved_endpoints, endpoint_id, status):
        saved = _find_personal_endpoint(saved_endpoints, endpoint_id)
        sanitized = sanitize_model_endpoints_for_frontend([saved]) if saved else []
        return jsonify({"endpoint": sanitized[0] if sanitized else {}}), status

    def _create_personal_model_endpoint(user_id, payload):
        """Add one endpoint to the caller's stored list."""
        if not isinstance(payload, dict) or not payload:
            return jsonify({"error": "Model endpoint payload must be an object."}), 400

        existing = _load_personal_endpoints(user_id)
        candidate = dict(payload)
        endpoint_id = str(candidate.get("id") or "").strip()
        if not endpoint_id:
            endpoint_id = str(uuid.uuid4())
        elif _find_personal_endpoint(existing, endpoint_id):
            return jsonify({"error": "A model endpoint with that id already exists."}), 409
        candidate["id"] = endpoint_id

        normalized, error = _normalize_personal_endpoints(list(existing) + [candidate], existing)
        if error:
            return error
        saved_endpoints, error = _persist_personal_endpoints(user_id, normalized, existing)
        if error:
            return error
        return _single_endpoint_response(saved_endpoints, endpoint_id, 201)

    @bp.route('/api/user/model-endpoints', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_custom_endpoints')
    def save_user_model_endpoints():
        """Create one endpoint, or replace the whole collection.

        A body carrying an ``endpoints`` list replaces every personal endpoint at once. That
        is how the classic interface saves, so it is retained, but it is deprecated: the
        client has to send back endpoints it never edited, and a stale copy silently
        overwrites another tab's work. Any other object body creates a single endpoint.
        """
        user_id = get_current_user_id()
        try:
            ensure_governance_access("governance_user_endpoints", user_id)
        except PermissionError as exc:
            return jsonify({"error": str(exc)}), 403
        data = request.get_json() or {}

        if "endpoints" not in data:
            return _create_personal_model_endpoint(user_id, data)

        incoming = data.get("endpoints", [])
        if not isinstance(incoming, list):
            return jsonify({"error": "endpoints must be a list."}), 400

        existing = _load_personal_endpoints(user_id)

        normalized, error = _normalize_personal_endpoints(incoming, existing)
        if error:
            return error
        saved_endpoints, error = _persist_personal_endpoints(user_id, normalized, existing)
        if error:
            return error
        return jsonify({
            "success": True,
            "endpoints": sanitize_model_endpoints_for_frontend(saved_endpoints),
        })


    @bp.route('/api/user/model-endpoints/<endpoint_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_custom_endpoints')
    def get_user_model_endpoint(endpoint_id):
        """Return one personal model endpoint, with its secrets stripped."""
        user_id = get_current_user_id()
        try:
            ensure_governance_access("governance_user_endpoints", user_id)
        except PermissionError as exc:
            return jsonify({"error": str(exc)}), 403

        endpoint = _find_personal_endpoint(_load_personal_endpoints(user_id), endpoint_id)
        if not endpoint:
            return jsonify({"error": "Model endpoint not found."}), 404

        sanitized = sanitize_model_endpoints_for_frontend([endpoint])
        return jsonify({"endpoint": sanitized[0] if sanitized else {}})


    @bp.route('/api/user/model-endpoints/<endpoint_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_custom_endpoints')
    def update_user_model_endpoint(endpoint_id):
        """Apply a partial update to one personal model endpoint.

        The stored endpoint is merged with the supplied keys server-side, so a client that
        never received the secret values -- they are stripped on the way out -- cannot blank
        them by sending the object back.
        """
        user_id = get_current_user_id()
        try:
            ensure_governance_access("governance_user_endpoints", user_id)
        except PermissionError as exc:
            return jsonify({"error": str(exc)}), 403

        updates = request.get_json(silent=True)
        if not isinstance(updates, dict):
            return jsonify({"error": "Model endpoint payload must be an object."}), 400

        existing = _load_personal_endpoints(user_id)
        current = _find_personal_endpoint(existing, endpoint_id)
        if not current:
            return jsonify({"error": "Model endpoint not found."}), 404

        replaced = [
            {**updates, "id": current.get("id")}
            if isinstance(endpoint, dict) and str(endpoint.get("id") or "") == str(endpoint_id)
            else endpoint
            for endpoint in existing
        ]

        normalized, error = _normalize_personal_endpoints(replaced, existing)
        if error:
            return error
        saved_endpoints, error = _persist_personal_endpoints(user_id, normalized, existing)
        if error:
            return error
        return _single_endpoint_response(saved_endpoints, current.get("id"), 200)


    @bp.route('/api/user/model-endpoints/<endpoint_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_custom_endpoints')
    def delete_user_model_endpoint(endpoint_id):
        """Remove one personal model endpoint and its stored secrets.

        Unlike the collection save, this reads the stored list server-side, so it cannot
        drop an endpoint the caller could not see. That is the case
        ``merge_model_endpoints_with_existing`` has to defend against when a whole list
        arrives from a browser.
        """
        user_id = get_current_user_id()
        try:
            ensure_governance_access("governance_user_endpoints", user_id)
        except PermissionError as exc:
            return jsonify({"error": str(exc)}), 403

        existing = _load_personal_endpoints(user_id)
        if not _find_personal_endpoint(existing, endpoint_id):
            return jsonify({"error": "Model endpoint not found."}), 404

        remaining = [
            endpoint
            for endpoint in existing
            if not (isinstance(endpoint, dict) and str(endpoint.get("id") or "") == str(endpoint_id))
        ]

        normalized, error = _normalize_personal_endpoints(remaining)
        if error:
            return error
        _saved, error = _persist_personal_endpoints(user_id, normalized, existing)
        if error:
            return error
        log_event(
            "User model endpoint deleted",
            extra={"user_id": user_id, "endpoint_id": endpoint_id},
        )
        return jsonify({"success": True})


    @bp.route('/api/group/model-endpoints', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    @enabled_required('allow_group_custom_endpoints')
    def get_group_model_endpoints_route():
        user_id = get_current_user_id()
        try:
            ensure_governance_access("governance_group_endpoints", user_id)
            group_id = require_active_group(user_id)
            assert_group_role(
                user_id,
                group_id,
                allowed_roles=("Owner", "Admin", "DocumentManager", "User"),
            )
        except ValueError as exc:
            return build_group_access_error_response(user_id, exc, "group model endpoints")
        except LookupError as exc:
            return build_group_access_error_response(user_id, exc, "group model endpoints")
        except PermissionError as exc:
            return build_group_access_error_response(user_id, exc, "group model endpoints")
        endpoints = get_group_model_endpoints(group_id)
        return jsonify({
            "endpoints": sanitize_model_endpoints_for_frontend(endpoints)
        })


    @bp.route('/api/group/model-endpoints', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    @enabled_required('allow_group_custom_endpoints')
    def save_group_model_endpoints():
        user_id = get_current_user_id()
        try:
            ensure_governance_access("governance_group_endpoints", user_id)
        except PermissionError as exc:
            return jsonify({"error": str(exc)}), 403
        data = request.get_json() or {}
        incoming = data.get("endpoints", [])
        if not isinstance(incoming, list):
            return jsonify({"error": "endpoints must be a list."}), 400

        try:
            group_id = require_active_group(user_id)
            assert_group_role(user_id, group_id, allowed_roles=("Owner", "Admin"))
        except ValueError as exc:
            return build_group_access_error_response(user_id, exc, "group model endpoint settings")
        except LookupError as exc:
            return build_group_access_error_response(user_id, exc, "group model endpoint settings")
        except PermissionError as exc:
            return build_group_access_error_response(user_id, exc, "group model endpoint settings")

        existing = get_group_model_endpoints(group_id)

        try:
            merged = merge_model_endpoints_with_existing(incoming, existing)
            normalized, _ = normalize_model_endpoints(merged)
        except ModelTokenBudgetError as exc:
            log_models_exception(
                "Group model token-budget validation failed",
                exc,
                extra={"scope": "group", "code": exc.code},
                level=logging.WARNING,
            )
            return jsonify({"error": exc.public_message, "error_code": exc.code}), 400
        try:
            validate_custom_model_endpoints(normalized, get_settings())
        except ModelEndpointValidationError as exc:
            log_models_exception(
                "Group model endpoint validation failed",
                exc,
                extra={"scope": "group"},
                level=logging.WARNING,
            )
            return build_safe_error_response(str(exc), 400)
        existing_by_id = {
            endpoint.get("id"): endpoint
            for endpoint in existing
            if isinstance(endpoint, dict) and endpoint.get("id")
        }
        saved_endpoints, error = save_scoped_endpoint_secrets(normalized, existing_by_id, "group")
        if error:
            return error

        # The list is written through the etag guard, which checks the caller's role
        # again on the group's current copy. Superseded and removed credentials are
        # deleted only after the write commits, judged against the endpoints it
        # replaced, and never while the committed endpoints still use them. A write
        # that fails definitively deletes only what this save staged.
        staged = staged_group_endpoint_credentials(normalized, existing_by_id, saved_endpoints)
        outcome = {}
        try:
            committed = update_group_model_endpoints(group_id, saved_endpoints, user_id=user_id, outcome=outcome)
        except GroupDocumentWriteConflict:
            discard_staged_group_endpoint_credentials(group_id, staged)
            return jsonify({"error": GROUP_WRITE_CONFLICT_MESSAGE, "error_code": GROUP_WRITE_CONFLICT_CODE}), 409
        except (LookupError, PermissionError) as exc:
            discard_staged_group_endpoint_credentials(group_id, staged)
            return build_group_access_error_response(user_id, exc, "group model endpoint settings")
        except Exception:
            keep_staged_group_endpoint_credentials(group_id, staged)
            raise
        clean_up_committed_group_endpoint_credentials(group_id, committed, outcome, staged)
        return jsonify({
            "success": True,
            "endpoints": sanitize_model_endpoints_for_frontend(saved_endpoints),
        })


    def list_foundry_resources_for_endpoint(endpoint_cfg, data, scope, endpoint_id):
        """List the Foundry agents or workflows of one resolved, authorized endpoint.

        Shared by the legacy ``/api/models/foundry/agents`` route and the named-group
        route. The caller has already authorized the endpoint; its stored credentials
        are hydrated here and reach only its stored Foundry project.
        """
        endpoint_cfg = dict(endpoint_cfg)
        endpoint_scope = endpoint_cfg.pop("_endpoint_scope", None) or scope
        try:
            endpoint_cfg = keyvault_model_endpoint_get_helper(
                endpoint_cfg,
                resolve_endpoint_scope_value(endpoint_cfg, endpoint_id),
                scope=endpoint_scope,
                return_type=SecretReturnType.VALUE,
            )
        except AIConnectionError as exc:
            return jsonify({"error": exc.public_message, "code": exc.code}), 400
        provider = (endpoint_cfg.get("provider") or "aoai").lower()
        requested_resource_type = str(data.get("resource_type") or "").strip().lower()
        if provider not in ("aifoundry", "new_foundry", "foundry_workflow"):
            return jsonify({"error": "Selected endpoint is not a Foundry endpoint."}), 400

        foundry_settings = build_foundry_settings_from_endpoint(endpoint_cfg)
        try:
            if provider == "foundry_workflow" or requested_resource_type == "workflow":
                agents = list_foundry_workflows_from_endpoint(foundry_settings, get_settings())
            elif provider == "new_foundry":
                agents = list_new_foundry_agents_from_endpoint(foundry_settings, get_settings())
            else:
                agents = list_foundry_agents_from_endpoint(foundry_settings, get_settings())
        except FoundryAgentUserAuthenticationRequired as exc:
            log_models_exception(
                "Foundry delegated user authentication required",
                exc,
                extra={"scope": scope, "provider": provider, "endpoint_id": endpoint_id},
                level=logging.WARNING,
            )
            auth_response = getattr(exc, "auth_response", {}) or {}
            payload = {
                # The exception is only ever raised with this message, so legacy
                # callers see the same body while no exception text reaches a client.
                "error": FOUNDRY_DELEGATED_AUTH_REQUIRED_MESSAGE,
                "auth_required": True,
                "scopes": auth_response.get("scopes") or [],
            }
            if auth_response.get("consent_url") or auth_response.get("auth_url"):
                payload["consent_url"] = auth_response.get("consent_url") or auth_response.get("auth_url")
                payload["auth_url"] = auth_response.get("auth_url") or auth_response.get("consent_url")
            return jsonify(payload), 401
        except Exception as exc:
            log_models_exception(
                "Foundry agent list failed",
                exc,
                extra={"scope": scope, "provider": provider, "endpoint_id": endpoint_id},
            )
            return build_safe_error_response(
                "Unable to load Foundry agents for the selected endpoint right now.",
                400,
            )

        connection = endpoint_cfg.get("connection", {}) or {}
        responses_api_version = ""
        if provider in ("new_foundry", "foundry_workflow") or requested_resource_type == "workflow":
            responses_api_version = str(
                connection.get("openai_api_version")
                or connection.get("api_version")
                or ""
            ).strip()

        return jsonify({
            "agents": agents,
            "provider": provider,
            "responses_api_version": responses_api_version,
        })


    @bp.route('/api/models/foundry/agents', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def list_foundry_agents():
        user_id = get_current_user_id()
        data = request.get_json() or {}
        endpoint_id = (data.get("endpoint_id") or "").strip()
        scope = (data.get("scope") or "global").lower()
        if scope not in ("global", "user", "group"):
            scope = "global"
        if not endpoint_id:
            return jsonify({"error": "endpoint_id is required."}), 400

        if scope == "group":
            try:
                group_id = require_active_group(user_id)
                assert_group_role(user_id, group_id)
            except ValueError as exc:
                return build_group_access_error_response(user_id, exc, "group Foundry agents")
            except LookupError as exc:
                return build_group_access_error_response(user_id, exc, "group Foundry agents")
            except PermissionError as exc:
                return build_group_access_error_response(user_id, exc, "group Foundry agents")

        try:
            endpoint_cfg = resolve_endpoint_by_id(user_id, scope, endpoint_id)
        except PermissionError as exc:
            return jsonify({"error": str(exc)}), 403
        if not endpoint_cfg:
            return jsonify({"error": "Model endpoint not found."}), 404
        return list_foundry_resources_for_endpoint(endpoint_cfg, data, scope, endpoint_id)


    @bp.route('/api/models/test-model', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @admin_required
    def test_model_connection():
        return handle_test_model_connection(scope="global")


    @bp.route('/api/user/models/fetch', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_custom_endpoints')
    def fetch_model_list_user():
        return handle_fetch_model_list(scope="user")


    @bp.route('/api/user/models/test-model', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_custom_endpoints')
    def test_model_connection_user():
        return handle_test_model_connection(scope="user")


    @bp.route('/api/group/models/fetch', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    @enabled_required('allow_group_custom_endpoints')
    def fetch_model_list_group():
        user_id = get_current_user_id()
        try:
            group_id = require_active_group(user_id)
            assert_group_role(user_id, group_id)
        except ValueError as exc:
            return build_group_access_error_response(user_id, exc, "group model discovery")
        except LookupError as exc:
            return build_group_access_error_response(user_id, exc, "group model discovery")
        except PermissionError as exc:
            return build_group_access_error_response(user_id, exc, "group model discovery")
        return handle_fetch_model_list(scope="group")


    @bp.route('/api/group/models/test-model', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    @enabled_required('allow_group_custom_endpoints')
    def test_model_connection_group():
        user_id = get_current_user_id()
        try:
            group_id = require_active_group(user_id)
            assert_group_role(user_id, group_id, allowed_roles=("Owner", "Admin"))
        except ValueError as exc:
            return build_group_access_error_response(user_id, exc, "group model connection tests")
        except LookupError as exc:
            return build_group_access_error_response(user_id, exc, "group model connection tests")
        except PermissionError as exc:
            return build_group_access_error_response(user_id, exc, "group model connection tests")
        return handle_test_model_connection(scope="group")


    # Immutable-target discovery for the group named in the path (M5C). The legacy
    # group routes above resolve the account's active group; these authorize the
    # path group first (Owner or Admin in an active group, the one availability
    # predicate) and then thread that ``group_id`` through the shared resolvers, so
    # another tab changing the active group can never retarget them.
    def authorize_named_group_discovery(group_id):
        """Return a refusal response, or ``None`` once the path group is authorized."""
        try:
            reject_query_parameters()
            read_strict_json_object()
            require_group_endpoint_discovery_context(get_current_user_id(), group_id)
        except Exception as exc:
            return group_endpoint_error_response(exc)
        return None


    @bp.route('/api/groups/<group_id>/models/fetch', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    def fetch_model_list_named_group(group_id):
        refusal = authorize_named_group_discovery(group_id)
        if refusal:
            return refusal
        return handle_fetch_model_list(scope="group", group_id=group_id)


    @bp.route('/api/groups/<group_id>/models/test-model', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    def test_model_connection_named_group(group_id):
        refusal = authorize_named_group_discovery(group_id)
        if refusal:
            return refusal
        return handle_test_model_connection(scope="group", group_id=group_id)


    @bp.route('/api/groups/<group_id>/models/foundry/agents', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    def list_foundry_agents_named_group(group_id):
        refusal = authorize_named_group_discovery(group_id)
        if refusal:
            return refusal
        user_id = get_current_user_id()
        data = request.get_json(silent=True) or {}
        endpoint_id = data.get("endpoint_id")
        if not isinstance(endpoint_id, str) or not endpoint_id.strip():
            return jsonify({"error": "endpoint_id is required."}), 400
        endpoint_id = endpoint_id.strip()
        try:
            endpoint_cfg = resolve_endpoint_by_id(user_id, "group", endpoint_id, group_id=group_id)
        except PermissionError as exc:
            log_models_exception(
                "Group Foundry discovery blocked by governance policy",
                exc,
                extra={"group_id": group_id, "endpoint_id": endpoint_id},
                level=logging.WARNING,
            )
            return build_safe_error_response("You do not have access to this model connection.", 403)
        if not endpoint_cfg:
            return jsonify({"error": "Model endpoint not found."}), 404
        return list_foundry_resources_for_endpoint(endpoint_cfg, data, "group", endpoint_id)
