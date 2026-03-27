# postconfig.py
from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from azure.identity import AzureCliCredential
import json
import os
import shutil
import subprocess
from urllib.parse import urlparse

credential = AzureCliCredential()


def get_azure_cli_executable():
    """Resolve the Azure CLI executable path for subprocess usage."""
    configured_path = os.getenv("AZURE_CLI_PATH")
    if configured_path and os.path.exists(configured_path):
        return configured_path

    candidate_names = ["az.cmd", "az.exe", "az"]
    for candidate_name in candidate_names:
        resolved_path = shutil.which(candidate_name)
        if resolved_path:
            return resolved_path

    windows_fallback_paths = [
        r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd",
        r"C:\Program Files (x86)\Microsoft SDKs\Azure\CLI2\wbin\az.cmd",
    ]
    for fallback_path in windows_fallback_paths:
        if os.path.exists(fallback_path):
            return fallback_path

    raise FileNotFoundError(
        "Azure CLI executable was not found. Set AZURE_CLI_PATH or ensure az.cmd is installed and available on PATH."
    )


def run_azure_cli_command(command_args, description):
    """Run an Azure CLI command and return the trimmed result."""
    azure_cli_executable = get_azure_cli_executable()
    result = subprocess.run(
        [azure_cli_executable, *command_args],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to retrieve {description}: {result.stderr.strip() or result.stdout.strip()}"
        )

    value = result.stdout.strip()
    if not value:
        raise RuntimeError(f"Failed to retrieve {description}: empty response from Azure CLI")

    print(f"Retrieved {description}")
    return value


def extract_resource_name_from_endpoint(endpoint):
    """Extract the Azure resource name from a standard service endpoint."""
    parsed_endpoint = urlparse(endpoint or "")
    hostname = parsed_endpoint.netloc or parsed_endpoint.path

    if not hostname:
        return ""

    return hostname.split(".")[0]


def get_cognitive_services_key(resource_name, resource_group, subscription_id, description):
    return run_azure_cli_command(
        [
            "cognitiveservices",
            "account",
            "keys",
            "list",
            "--name",
            resource_name,
            "--resource-group",
            resource_group,
            "--subscription",
            subscription_id,
            "--query",
            "key1",
            "-o",
            "tsv",
        ],
        description,
    )


def get_search_service_key(resource_name, resource_group, subscription_id):
    return run_azure_cli_command(
        [
            "search",
            "admin-key",
            "show",
            "--service-name",
            resource_name,
            "--resource-group",
            resource_group,
            "--subscription",
            subscription_id,
            "--query",
            "primaryKey",
            "-o",
            "tsv",
        ],
        "Azure AI Search admin key",
    )


def get_redis_cache_key(resource_name, resource_group, subscription_id):
    return run_azure_cli_command(
        [
            "redis",
            "list-keys",
            "--name",
            resource_name,
            "--resource-group",
            resource_group,
            "--subscription",
            subscription_id,
            "--query",
            "primaryKey",
            "-o",
            "tsv",
        ],
        "Redis cache primary key",
    )


def get_storage_account_connection_string(resource_name, resource_group, subscription_id):
    return run_azure_cli_command(
        [
            "storage",
            "account",
            "show-connection-string",
            "--name",
            resource_name,
            "--resource-group",
            resource_group,
            "--subscription",
            subscription_id,
            "--query",
            "connectionString",
            "-o",
            "tsv",
        ],
        "Storage account connection string",
    )


def get_core_service_keys(
    authentication_type,
    openai_endpoint,
    openai_resource_group,
    openai_subscription_id,
    subscription_id,
    resource_group,
    content_safety_endpoint,
    search_service_endpoint,
    document_intelligence_endpoint,
    redis_cache_host_name,
    speech_service_endpoint,
):
    if authentication_type != "key":
        return {}

    openai_resource_name = extract_resource_name_from_endpoint(openai_endpoint)
    search_resource_name = extract_resource_name_from_endpoint(search_service_endpoint)
    docintel_resource_name = extract_resource_name_from_endpoint(document_intelligence_endpoint)
    redis_resource_name = extract_resource_name_from_endpoint(redis_cache_host_name)
    content_safety_resource_name = extract_resource_name_from_endpoint(content_safety_endpoint)
    speech_resource_name = extract_resource_name_from_endpoint(speech_service_endpoint)

    keys = {
        "azure_openai_key": get_cognitive_services_key(
            openai_resource_name,
            openai_resource_group,
            openai_subscription_id or subscription_id,
            "Azure OpenAI key",
        ),
        "azure_ai_search_key": get_search_service_key(
            search_resource_name,
            resource_group,
            subscription_id,
        ),
        "azure_document_intelligence_key": get_cognitive_services_key(
            docintel_resource_name,
            resource_group,
            subscription_id,
            "Azure Document Intelligence key",
        ),
    }

    if redis_resource_name:
        keys["redis_key"] = get_redis_cache_key(
            redis_resource_name,
            resource_group,
            subscription_id,
        )

    if content_safety_resource_name:
        keys["content_safety_key"] = get_cognitive_services_key(
            content_safety_resource_name,
            resource_group,
            subscription_id,
            "Content Safety key",
        )

    if speech_resource_name:
        keys["speech_service_key"] = get_cognitive_services_key(
            speech_resource_name,
            resource_group,
            subscription_id,
            "Speech Service key",
        )

    return keys

cosmosEndpoint = os.getenv("var_cosmosDb_uri")
cosmosKey = os.getenv("var_cosmosDb_key")

if cosmosKey:
    client = CosmosClient(cosmosEndpoint, cosmosKey)
else:
    credential.get_token("https://cosmos.azure.com/.default")
    client = CosmosClient(cosmosEndpoint, credential=credential)

database_name = "SimpleChat"
container_name = "settings"

database = client.get_database_client(database_name)
container = database.get_container_client(container_name)

# Read the existing item by ID and partition key
item_id = "app_settings"
partition_key = "app_settings"
try:
    item = container.read_item(item=item_id, partition_key=partition_key)
    print(f"Found existing app_setting document")
except CosmosResourceNotFoundError:
    print(f"app_setting document not found.")
    item = {
        "id": item_id,
        "partition_key": partition_key
    }

# Get values from environment variables
var_authenticationType = os.getenv("var_authenticationType")

var_openAIEndpoint = os.getenv("var_openAIEndpoint")
var_openAISubscriptionId = os.getenv("var_openAISubscriptionId")
var_openAIResourceGroup = os.getenv("var_openAIResourceGroup")
var_subscriptionId = os.getenv("var_subscriptionId")
var_rgName = os.getenv("var_rgName")
var_openAIGPTModels = os.getenv("var_openAIGPTModels")
gpt_models_list = json.loads(var_openAIGPTModels)
var_openAIEmbeddingModels = os.getenv("var_openAIEmbeddingModels")
embedding_models_list = json.loads(var_openAIEmbeddingModels)
var_blobStorageEndpoint = os.getenv("var_blobStorageEndpoint")
var_contentSafetyEndpoint = os.getenv("var_contentSafetyEndpoint")
var_searchServiceEndpoint = os.getenv("var_searchServiceEndpoint")
var_documentIntelligenceServiceEndpoint = os.getenv("var_documentIntelligenceServiceEndpoint")
var_redisCacheHostName = os.getenv("var_redisCacheHostName")
var_videoIndexerName = os.getenv("var_videoIndexerName")
var_videoIndexerLocation = os.getenv("var_deploymentLocation")
var_videoIndexerAccountId = os.getenv("var_videoIndexerAccountId")
var_speechServiceEndpoint = os.getenv("var_speechServiceEndpoint")
var_speechServiceLocation = os.getenv("var_deploymentLocation")

core_service_keys = get_core_service_keys(
    authentication_type=var_authenticationType,
    openai_endpoint=var_openAIEndpoint,
    openai_resource_group=var_openAIResourceGroup,
    openai_subscription_id=var_openAISubscriptionId,
    subscription_id=var_subscriptionId,
    resource_group=var_rgName,
    content_safety_endpoint=var_contentSafetyEndpoint,
    search_service_endpoint=var_searchServiceEndpoint,
    document_intelligence_endpoint=var_documentIntelligenceServiceEndpoint,
    redis_cache_host_name=var_redisCacheHostName,
    speech_service_endpoint=var_speechServiceEndpoint,
)

# 4. Update the Configurations

# General > Health Check
item["enable_external_healthcheck"] = True

# AI Models
item["azure_openai_gpt_endpoint"] = var_openAIEndpoint
item["azure_openai_gpt_authentication_type"] = var_authenticationType
item["azure_openai_gpt_subscription_id"] = var_openAISubscriptionId or var_subscriptionId
item["azure_openai_gpt_resource_group"] = var_openAIResourceGroup
if var_authenticationType == "key":
    item["azure_openai_gpt_key"] = core_service_keys["azure_openai_key"]
item["gpt_model"] = {
    "selected": [
        {
            "deploymentName": gpt_models_list[0]["modelName"],
            "modelName": gpt_models_list[0]["modelName"]
        }
    ],
    "all": [
        {
            "deploymentName": model["modelName"],
            "modelName": model["modelName"]
        }
        for model in gpt_models_list
    ]
}

item["azure_openai_embedding_endpoint"] = var_openAIEndpoint
item["azure_openai_embedding_authentication_type"] = var_authenticationType
item["azure_openai_embedding_subscription_id"] = var_openAISubscriptionId or var_subscriptionId
item["azure_openai_embedding_resource_group"] = var_openAIResourceGroup
if var_authenticationType == "key":
    item["azure_openai_embedding_key"] = core_service_keys["azure_openai_key"]
item["embedding_model"] = {
    "selected": [
        {
            "deploymentName": embedding_models_list[0]["modelName"],
            "modelName": embedding_models_list[0]["modelName"]
        }
    ],
    "all": [
        {
            "deploymentName": model["modelName"],
            "modelName": model["modelName"]
        }
        for model in embedding_models_list
    ]
}

# Agents and Actions  > Agents Configuration
item["enable_semantic_kernel"] = False

# Logging > Application Insights Logging
item["enable_appinsights_global_logging"] = True

# Scale > Redis Cache
# todo support redis cache configuration

# Workspaces > Metadata Extraction
item["enable_extract_meta_data"] = True
item["metadata_extraction_model"] = gpt_models_list[0]["modelName"]

# Workspaces > Multimodal Vision Analysis
item["enable_multimodal_vision"] = True
item["multimodal_vision_model"] = gpt_models_list[0]["modelName"]

# Citations > Enhanced Citations
item["enable_enhanced_citations"] = True
item["office_docs_authentication_type"] = var_authenticationType
item["office_docs_storage_account_blob_endpoint"] = var_blobStorageEndpoint
if var_authenticationType == "key" and var_blobStorageEndpoint and var_blobStorageEndpoint.strip():
    storage_account_name = extract_resource_name_from_endpoint(var_blobStorageEndpoint)
    item["office_docs_storage_account_url"] = get_storage_account_connection_string(
        storage_account_name,
        var_rgName,
        var_subscriptionId,
    )
else:
    item["office_docs_storage_account_url"] = ""

# Safety > Content Safety
if var_contentSafetyEndpoint and var_contentSafetyEndpoint.strip():
    item["enable_content_safety"] = True
item["content_safety_endpoint"] = var_contentSafetyEndpoint
item["content_safety_authentication_type"] = var_authenticationType
if var_authenticationType == "key" and "content_safety_key" in core_service_keys:
    item["content_safety_key"] = core_service_keys["content_safety_key"]

# Redis Cache Configuration
if var_redisCacheHostName and var_redisCacheHostName.strip():
    item["enable_redis_cache"] = True
item["redis_url"] = var_redisCacheHostName
item["redis_auth_type"] = var_authenticationType
if var_authenticationType == "key" and "redis_key" in core_service_keys:
    item["redis_key"] = core_service_keys["redis_key"]

# Safety > Conversation Archiving
item["enable_conversation_archiving"] = True

# Search and Extract > Azure AI Search
item["azure_ai_search_endpoint"] = var_searchServiceEndpoint
item["azure_ai_search_authentication_type"] = var_authenticationType
if var_authenticationType == "key":
    item["azure_ai_search_key"] = core_service_keys["azure_ai_search_key"]

# Search and Extract > Azure Document Intelligence
item["azure_document_intelligence_endpoint"] = var_documentIntelligenceServiceEndpoint
item["azure_document_intelligence_authentication_type"] = var_authenticationType
if var_authenticationType == "key":
    item["azure_document_intelligence_key"] = core_service_keys["azure_document_intelligence_key"]

# Search and Extract > Multimedia Support
# Video Indexer Configuration
if var_videoIndexerName and var_videoIndexerName.strip():
    item["enable_video_file_support"] = True
item["video_indexer_resource_group"] = var_rgName
item["video_indexer_subscription_id"] = var_subscriptionId
item["video_indexer_account_name"] = var_videoIndexerName
item["video_indexer_endpoint"] = os.getenv("var_videoIndexerEndpoint", item.get("video_indexer_endpoint", ""))
item["video_indexer_location"] = var_videoIndexerLocation
item["video_indexer_account_id"] = var_videoIndexerAccountId
item["video_indexer_arm_api_version"] = os.getenv("var_videoIndexerArmApiVersion", item.get("video_indexer_arm_api_version", "2024-01-01"))

# Speech Service Configuration
if var_speechServiceEndpoint and var_speechServiceEndpoint.strip():
    item["enable_audio_file_support"] = True
item["speech_service_endpoint"] = var_speechServiceEndpoint
item["speech_service_location"] = var_speechServiceLocation
if var_authenticationType == "key" and "speech_service_key" in core_service_keys:
    item["speech_service_key"] = core_service_keys["speech_service_key"]

# 5. Upsert the updated items back into Cosmos DB
response = container.upsert_item(item)
print(
    f"Updated item: {response['id']} with enable_external_healthcheck = {response['enable_external_healthcheck']}")
