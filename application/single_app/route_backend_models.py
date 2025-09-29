# route_backend_models.py

from config import *
from functions_authentication import *
from functions_settings import *
from swagger_wrapper import swagger_route, get_auth_security
import re


def register_route_backend_models(app):
    """
    Register backend routes for fetching Azure OpenAI models.
    """

    @app.route('/api/models/gpt', methods=['GET'])
    @swagger_route(
        security=get_auth_security()
    )
    @login_required
    @user_required
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
    @swagger_route(
        security=get_auth_security()
    )
    @login_required
    @user_required
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
    @swagger_route(
        security=get_auth_security()
    )
    @login_required
    @user_required
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