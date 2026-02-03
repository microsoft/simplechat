# route_backend_models.py

from config import *
from functions_authentication import *
from functions_group import assert_group_role, get_group_model_endpoints, require_active_group, update_group_model_endpoints
from functions_settings import *
from foundry_agent_runtime import list_foundry_agents_from_endpoint
from functions_debug import debug_print
from swagger_wrapper import swagger_route, get_auth_security
from azure.identity import DefaultAzureCredential, ClientSecretCredential, get_bearer_token_provider
import re
import requests


def _merge_auth_settings(existing_auth, incoming_auth):
    if not isinstance(existing_auth, dict):
        existing_auth = {}
    if not isinstance(incoming_auth, dict):
        incoming_auth = {}
    merged = dict(existing_auth)
    for key, value in incoming_auth.items():
        if value in (None, ""):
            continue
        merged[key] = value
    return merged


def _merge_endpoint_payload(existing, incoming):
    if not isinstance(existing, dict):
        return incoming
    merged = dict(existing)
    for key, value in incoming.items():
        if key == "auth":
            merged["auth"] = _merge_auth_settings(existing.get("auth"), value)
            continue
        if value in (None, ""):
            continue
        merged[key] = value
    return merged


def register_route_backend_models(app):
    """
    Register backend routes for fetching Azure OpenAI models.
    """

    def resolve_scoped_model_endpoints(user_id, scope):
        settings = get_settings()
        endpoints = []
        if scope == "group":
            if settings.get("allow_group_custom_endpoints", False):
                group_id = require_active_group(user_id)
                endpoints.extend(get_group_model_endpoints(group_id))
        elif scope == "user":
            if settings.get("allow_user_custom_endpoints", False):
                user_settings = get_user_settings(user_id)
                endpoints.extend(user_settings.get("settings", {}).get("personal_model_endpoints", []))
        endpoints.extend(settings.get("model_endpoints", []) or [])
        return endpoints

    def resolve_endpoint_by_id(user_id, scope, endpoint_id):
        endpoints = resolve_scoped_model_endpoints(user_id, scope)
        return next((endpoint for endpoint in endpoints if endpoint.get("id") == endpoint_id), None)

    def build_foundry_settings_from_endpoint(endpoint_cfg):
        connection = endpoint_cfg.get("connection", {}) or {}
        auth = endpoint_cfg.get("auth", {}) or {}
        return {
            "endpoint": connection.get("endpoint"),
            "api_version": connection.get("project_api_version") or connection.get("api_version") or "v1",
            "project_name": connection.get("project_name") or "",
            "authentication_type": auth.get("type") or "managed_identity",
            "managed_identity_type": auth.get("managed_identity_type") or "system_assigned",
            "managed_identity_client_id": auth.get("managed_identity_client_id") or "",
            "tenant_id": auth.get("tenant_id") or "",
            "client_id": auth.get("client_id") or "",
            "client_secret": auth.get("client_secret") or "",
            "cloud": auth.get("management_cloud") or "",
            "authority": auth.get("custom_authority") or "",
        }

    def resolve_foundry_scope(auth_settings):
        management_cloud = (auth_settings.get("management_cloud") or "public").lower()
        if management_cloud == "government":
            return "https://ai.azure.us/.default"
        if management_cloud == "custom":
            custom_scope = (auth_settings.get("foundry_scope") or "").strip()
            if not custom_scope:
                raise ValueError("Foundry scope is required for custom cloud configurations.")
            return custom_scope
        return "https://ai.azure.com/.default"

    def build_foundry_token(auth_settings):
        auth_type = (auth_settings.get("type") or "managed_identity").lower()
        management_cloud = (auth_settings.get("management_cloud") or "public").lower()
        scope = resolve_foundry_scope(auth_settings)
        debug_print(f"[Models] Foundry token auth_type={auth_type}, scope={scope}, cloud={management_cloud}")
        if auth_type == "service_principal":
            authority_override = resolve_authority(auth_settings)
            credential = ClientSecretCredential(
                tenant_id=auth_settings.get("tenant_id"),
                client_id=auth_settings.get("client_id"),
                client_secret=auth_settings.get("client_secret"),
                authority=authority_override
            )
        elif auth_type == "api_key":
            debug_print("[Models] API key auth requested for model discovery (not supported).")
            raise ValueError("API key auth is not supported for model discovery.")
        else:
            managed_identity_client_id = auth_settings.get("managed_identity_client_id") or None
            credential = DefaultAzureCredential(managed_identity_client_id=managed_identity_client_id)
        token = credential.get_token(scope)
        return token.token

    def build_cognitive_services_client(subscription_id, auth_settings):
        auth_type = (auth_settings.get("type") or "managed_identity").lower()
        management_cloud = (auth_settings.get("management_cloud") or "public").lower()
        debug_print(f"[Models] Building ARM client auth_type={auth_type}, subscription_id={subscription_id}, cloud={management_cloud}")
        if auth_type == "service_principal":
            authority_override = resolve_authority(auth_settings)
            credential = ClientSecretCredential(
                tenant_id=auth_settings.get("tenant_id"),
                client_id=auth_settings.get("client_id"),
                client_secret=auth_settings.get("client_secret"),
                authority=authority_override
            )
        elif auth_type == "api_key":
            debug_print("[Models] API key auth requested for model discovery (not supported).")
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

    def resolve_authority(auth_settings):
        management_cloud = (auth_settings.get("management_cloud") or "public").lower()
        if management_cloud == "government":
            return "https://login.microsoftonline.us"
        if management_cloud == "custom":
            custom_authority = auth_settings.get("custom_authority") or ""
            return custom_authority.strip() or None
        return None

    def build_inference_client(endpoint, api_version, auth_settings, provider="aoai"):
        auth_type = (auth_settings.get("type") or "managed_identity").lower()
        if auth_type == "api_key":
            api_key = auth_settings.get("api_key")
            if not api_key:
                raise ValueError("API key is required for API key authentication.")
            return AzureOpenAI(
                api_version=api_version,
                azure_endpoint=endpoint,
                api_key=api_key
            )

        if auth_type == "service_principal":
            authority_override = resolve_authority(auth_settings)
            credential = ClientSecretCredential(
                tenant_id=auth_settings.get("tenant_id"),
                client_id=auth_settings.get("client_id"),
                client_secret=auth_settings.get("client_secret"),
                authority=authority_override
            )
        else:
            managed_identity_client_id = auth_settings.get("managed_identity_client_id") or None
            credential = DefaultAzureCredential(managed_identity_client_id=managed_identity_client_id)

        scope = cognitive_services_scope
        if provider == "aifoundry":
            scope = resolve_foundry_scope(auth_settings)
        debug_print(f"[Models] Inference token scope={scope} provider={provider}")
        token_provider = get_bearer_token_provider(credential, scope)
        return AzureOpenAI(
            api_version=api_version,
            azure_endpoint=endpoint,
            azure_ad_token_provider=token_provider
        )

    def resolve_foundry_project_base(endpoint, project_name):
        if not endpoint:
            raise ValueError("Missing Foundry endpoint")
        base = endpoint.rstrip("/")
        if "/api/projects/" in base:
            return base
        if project_name:
            return f"{base}/api/projects/{project_name}"
        raise ValueError("Foundry project name is required when endpoint does not include /api/projects/.")

    def resolve_foundry_project_api_version(api_version):
        version = (api_version or "").strip()
        if version and version.startswith("v"):
            return version
        return "v1"

    def fetch_foundry_project_deployments(endpoint, api_version, auth_settings, project_name=None):
        if not endpoint:
            raise ValueError("Missing Foundry project endpoint")

        auth_type = (auth_settings.get("type") or "managed_identity").lower()
        if auth_type == "api_key":
            debug_print("[Models] API key auth requested for Foundry project discovery (not supported).")
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
        debug_print(f"[Models] Foundry project deployments URL={url}")

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

    def handle_fetch_model_list():
        data = request.get_json() or {}
        provider = (data.get("provider") or "aoai").lower()
        connection = data.get("connection") or {}
        auth_settings = data.get("auth") or {}
        management = data.get("management") or {}
        auth_type = (auth_settings.get("type") or "managed_identity").lower()
        debug_print(
            "[Models] Fetch model list request"
            f" provider={provider} auth_type={auth_type}"
            f" endpoint={connection.get('endpoint') or ''}"
            f" subscription_id_present={bool(management.get('subscription_id'))}"
            f" resource_group_present={bool(management.get('resource_group'))}"
        )

        try:
            if provider == "aifoundry":
                endpoint = connection.get("endpoint")
                api_version = connection.get("project_api_version") or connection.get("api_version") or "v1"
                project_name = connection.get("project_name")
                debug_print(f"[Models] Foundry fetch project endpoint={endpoint or ''} api_version={api_version}")
                deployments = fetch_foundry_project_deployments(endpoint, api_version, auth_settings, project_name=project_name)
                mapped = []
                for item in deployments:
                    deployment_name = item.get("name") or item.get("deploymentName")
                    if not deployment_name:
                        continue
                    model_name = item.get("modelName")
                    if not model_name and isinstance(item.get("model"), dict):
                        model_name = item["model"].get("name")
                    mapped.append({
                        "deploymentName": deployment_name,
                        "modelName": model_name or ""
                    })
                return jsonify({"models": mapped})

            if provider == "aoai":
                subscription_id = management.get("subscription_id")
                resource_group = management.get("resource_group")
                endpoint = connection.get("endpoint") or ""
                account_name = endpoint.split('.')[0].replace("https://", "").replace("http://", "")
                debug_print(
                    f"[Models] AOAI fetch account_name={account_name}"
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
                        re.search(r"o\d+", model_name.lower())
                    ) and "image" not in model_name.lower():
                        mapped.append({
                            "deploymentName": deployment.name,
                            "modelName": model_name
                        })
                return jsonify({"models": mapped})

            return jsonify({"error": "Model provider not found."}), 400
        except Exception as e:
            debug_print(f"[Models] Fetch model list error: {str(e)}")
            return jsonify({"error": str(e)}), 400

    def handle_test_model_connection():
        data = request.get_json() or {}
        provider = (data.get("provider") or "aoai").lower()
        connection = data.get("connection") or {}
        auth_settings = data.get("auth") or {}
        model = data.get("model") or {}

        endpoint = connection.get("endpoint") or ""
        api_version = connection.get("openai_api_version") or connection.get("api_version") or ""
        deployment_name = model.get("deploymentName") or ""

        auth_type = (auth_settings.get("type") or "managed_identity").lower()
        debug_print(
            "[Models] Test model request"
            f" provider={provider} auth_type={auth_type}"
            f" endpoint={endpoint} deployment={deployment_name}"
        )

        if not endpoint or not api_version or not deployment_name:
            return jsonify({"error": "Endpoint, API version, and deployment name are required."}), 400

        try:
            if provider not in ("aoai", "aifoundry"):
                return jsonify({"error": "Model provider not found."}), 400

            gpt_client = build_inference_client(endpoint, api_version, auth_settings, provider=provider)
            response = gpt_client.chat.completions.create(
                model=deployment_name,
                messages=[{"role": "system", "content": "Testing access."}]
            )

            if response:
                return jsonify({"success": True}), 200

            return jsonify({"error": "No response returned from model."}), 400

        except Exception as e:
            debug_print(f"[Models] Test model error: {str(e)}")
            return jsonify({"error": str(e)}), 400

    @app.route('/api/models/gpt', methods=['GET'])
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
        account_name = settings.get('azure_openai_gpt_endpoint', '').split('.')[0].replace("https://", "")

        if not subscription_id or not resource_group or not account_name:
            return jsonify({"error": "Azure GPT Model subscription/RG/endpoint not configured"}), 400

        if AZURE_ENVIRONMENT == "usgovernment" or AZURE_ENVIRONMENT == "custom":
            
            credential = ClientSecretCredential(TENANT_ID, CLIENT_ID, MICROSOFT_PROVIDER_AUTHENTICATION_SECRET, authority=authority)

            client = CognitiveServicesManagementClient(
                credential=credential,
                subscription_id=subscription_id,
                base_url=resource_manager,
                credential_scopes=credential_scopes
            )
        else:
            credential = ClientSecretCredential(TENANT_ID, CLIENT_ID, MICROSOFT_PROVIDER_AUTHENTICATION_SECRET)

            client = CognitiveServicesManagementClient(
                credential=credential,
                subscription_id=subscription_id
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
            return jsonify({"error": str(e)}), 500

        return jsonify({"models": models})


    @app.route('/api/models/embedding', methods=['GET'])
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
        account_name = settings.get('azure_openai_embedding_endpoint', '').split('.')[0].replace("https://", "")

        if not subscription_id or not resource_group or not account_name:
            return jsonify({"error": "Azure Embedding Model subscription/RG/endpoint not configured"}), 400

        if AZURE_ENVIRONMENT == "usgovernment" or AZURE_ENVIRONMENT == "custom":
            
            credential = ClientSecretCredential(TENANT_ID, CLIENT_ID, MICROSOFT_PROVIDER_AUTHENTICATION_SECRET, authority=authority)

            client = CognitiveServicesManagementClient(
                credential=credential,
                subscription_id=subscription_id,
                base_url=resource_manager,
                credential_scopes=credential_scopes
            )
        else:
            credential = ClientSecretCredential(TENANT_ID, CLIENT_ID, MICROSOFT_PROVIDER_AUTHENTICATION_SECRET)

            client = CognitiveServicesManagementClient(
                credential=credential,
                subscription_id=subscription_id
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
            return jsonify({"error": str(e)}), 500

        return jsonify({"models": models})


    @app.route('/api/models/image', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @admin_required
    def get_image_models():
        """
        Fetch available DALL-E image generation Azure OpenAI deployments using Azure Management API.
        Returns a list of image generation models with deployment names and model information.
        """
        settings = get_settings()

        subscription_id = settings.get('azure_openai_image_gen_subscription_id', '')
        resource_group = settings.get('azure_openai_image_gen_resource_group', '')
        account_name = settings.get('azure_openai_image_gen_endpoint', '').split('.')[0].replace("https://", "")

        if not subscription_id or not resource_group or not account_name:
            return jsonify({"error": "Azure Image Model subscription/RG/endpoint not configured"}), 400

        if AZURE_ENVIRONMENT == "usgovernment" or AZURE_ENVIRONMENT == "custom":
            
            credential = ClientSecretCredential(TENANT_ID, CLIENT_ID, MICROSOFT_PROVIDER_AUTHENTICATION_SECRET, authority=authority)

            client = CognitiveServicesManagementClient(
                credential=credential,
                subscription_id=subscription_id,
                base_url=resource_manager,
                credential_scopes=credential_scopes
            )
        else:
            credential = ClientSecretCredential(TENANT_ID, CLIENT_ID, MICROSOFT_PROVIDER_AUTHENTICATION_SECRET)

            client = CognitiveServicesManagementClient(
                credential=credential,
                subscription_id=subscription_id
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
                    "dall-e" in model_name.lower() or
                    "image" in model_name.lower()
                ):
                    models.append({
                        "deploymentName": d.name,
                        "modelName": model_name
                    })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

        return jsonify({"models": models})


    @app.route('/api/models/test-connection', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @admin_required
    def test_model_inference_connection():
        data = request.get_json() or {}
        provider = (data.get("provider") or "aoai").lower()
        connection = data.get("connection") or {}
        management = data.get("management") or {}
        auth_settings = data.get("auth") or {}
        auth_type = (auth_settings.get("type") or "managed_identity").lower()
        debug_print(
            "[Models] Test connection request"
            f" provider={provider} auth_type={auth_type}"
            f" endpoint={connection.get('endpoint') or ''}"
            f" subscription_id_present={bool(management.get('subscription_id'))}"
            f" resource_group_present={bool(management.get('resource_group'))}"
        )

        try:
            if provider == "aifoundry":
                endpoint = connection.get("endpoint")
                api_version = connection.get("project_api_version") or connection.get("api_version") or "v1"
                project_name = connection.get("project_name")
                debug_print(f"[Models] Foundry test project endpoint={endpoint or ''} api_version={api_version}")
                deployments = fetch_foundry_project_deployments(endpoint, api_version, auth_settings, project_name=project_name)
                return jsonify({"success": True, "count": len(deployments)})

            if provider == "aoai":
                subscription_id = management.get("subscription_id")
                resource_group = management.get("resource_group")
                endpoint = connection.get("endpoint") or ""
                account_name = endpoint.split('.')[0].replace("https://", "").replace("http://", "")
                debug_print(
                    f"[Models] AOAI test account_name={account_name}"
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
                    model_name = deployment.properties.model.name
                    if model_name and (
                        "gpt" in model_name.lower() or
                        re.search(r"o\d+", model_name.lower())
                    ) and "image" not in model_name.lower():
                        count += 1
                return jsonify({"success": True, "count": count})

            return jsonify({"error": "Model provider not found."}), 400
        except Exception as e:
            debug_print(f"[Models] Test connection error: {str(e)}")
            return jsonify({"error": str(e)}), 400


    @app.route('/api/models/fetch', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @admin_required
    def fetch_model_list():
        return handle_fetch_model_list()


    @app.route('/api/user/model-endpoints', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_custom_endpoints')
    def get_user_model_endpoints():
        user_id = get_current_user_id()
        user_settings = get_user_settings(user_id)
        endpoints = user_settings.get("settings", {}).get("personal_model_endpoints", [])
        return jsonify({
            "endpoints": sanitize_model_endpoints_for_frontend(endpoints)
        })


    @app.route('/api/user/model-endpoints', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_custom_endpoints')
    def save_user_model_endpoints():
        user_id = get_current_user_id()
        data = request.get_json() or {}
        incoming = data.get("endpoints", [])
        if not isinstance(incoming, list):
            return jsonify({"error": "endpoints must be a list."}), 400

        user_settings = get_user_settings(user_id)
        existing = user_settings.get("settings", {}).get("personal_model_endpoints", [])

        merged = []
        for endpoint in incoming:
            if not isinstance(endpoint, dict):
                continue
            endpoint_id = endpoint.get("id")
            existing_endpoint = next((e for e in existing if e.get("id") == endpoint_id), None)
            merged.append(_merge_endpoint_payload(existing_endpoint or {}, endpoint))

        normalized, _ = normalize_model_endpoints(merged)
        update_user_settings(user_id, {"personal_model_endpoints": normalized})
        return jsonify({"success": True})


    @app.route('/api/group/model-endpoints', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    @enabled_required('allow_group_custom_endpoints')
    def get_group_model_endpoints_route():
        user_id = get_current_user_id()
        try:
            group_id = require_active_group(user_id)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        endpoints = get_group_model_endpoints(group_id)
        return jsonify({
            "endpoints": sanitize_model_endpoints_for_frontend(endpoints)
        })


    @app.route('/api/group/model-endpoints', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    @enabled_required('allow_group_custom_endpoints')
    def save_group_model_endpoints():
        user_id = get_current_user_id()
        data = request.get_json() or {}
        incoming = data.get("endpoints", [])
        if not isinstance(incoming, list):
            return jsonify({"error": "endpoints must be a list."}), 400

        try:
            group_id = require_active_group(user_id)
            assert_group_role(user_id, group_id)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except LookupError as exc:
            return jsonify({"error": str(exc)}), 404
        except PermissionError as exc:
            return jsonify({"error": str(exc)}), 403

        existing = get_group_model_endpoints(group_id)
        merged = []
        for endpoint in incoming:
            if not isinstance(endpoint, dict):
                continue
            endpoint_id = endpoint.get("id")
            existing_endpoint = next((e for e in existing if e.get("id") == endpoint_id), None)
            merged.append(_merge_endpoint_payload(existing_endpoint or {}, endpoint))

        normalized, _ = normalize_model_endpoints(merged)
        update_group_model_endpoints(group_id, normalized)
        return jsonify({"success": True})


    @app.route('/api/models/foundry/agents', methods=['POST'])
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
                return jsonify({"error": str(exc)}), 400
            except LookupError as exc:
                return jsonify({"error": str(exc)}), 404
            except PermissionError as exc:
                return jsonify({"error": str(exc)}), 403

        endpoint_cfg = resolve_endpoint_by_id(user_id, scope, endpoint_id)
        if not endpoint_cfg:
            return jsonify({"error": "Model endpoint not found."}), 404
        if (endpoint_cfg.get("provider") or "aoai").lower() != "aifoundry":
            return jsonify({"error": "Selected endpoint is not an Azure AI Foundry endpoint."}), 400

        foundry_settings = build_foundry_settings_from_endpoint(endpoint_cfg)
        try:
            agents = list_foundry_agents_from_endpoint(foundry_settings, get_settings())
        except Exception as exc:
            debug_print(f"[Models] Foundry agent list error: {str(exc)}")
            return jsonify({"error": str(exc)}), 400

        return jsonify({"agents": agents})


    @app.route('/api/models/test-model', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @admin_required
    def test_model_connection():
        return handle_test_model_connection()


    @app.route('/api/user/models/fetch', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def fetch_model_list_user():
        return handle_fetch_model_list()


    @app.route('/api/user/models/test-model', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def test_model_connection_user():
        return handle_test_model_connection()


    @app.route('/api/group/models/fetch', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    def fetch_model_list_group():
        user_id = get_current_user_id()
        try:
            group_id = require_active_group(user_id)
            assert_group_role(user_id, group_id)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except LookupError as exc:
            return jsonify({"error": str(exc)}), 404
        except PermissionError as exc:
            return jsonify({"error": str(exc)}), 403
        return handle_fetch_model_list()


    @app.route('/api/group/models/test-model', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_group_workspaces')
    def test_model_connection_group():
        user_id = get_current_user_id()
        try:
            group_id = require_active_group(user_id)
            assert_group_role(user_id, group_id)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except LookupError as exc:
            return jsonify({"error": str(exc)}), 404
        except PermissionError as exc:
            return jsonify({"error": str(exc)}), 403
        return handle_test_model_connection()