from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
import os
import json

credential = DefaultAzureCredential()
token = credential.get_token("https://cosmos.azure.com/.default")

cosmosEndpoint = os.getenv("var_cosmosDb_uri")
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
var_keyVaultUri = os.getenv("var_keyVaultUri")

var_openAIEndpoint = os.getenv("var_openAIEndpoint")
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
var_documentIntelligenceServiceEndpoint = os.getenv(
    "var_documentIntelligenceServiceEndpoint")
var_videoIndexerName = os.getenv("var_videoIndexerName")
var_videoIndexerLocation = os.getenv("var_deploymentLocation")
var_videoIndexerAccountId = os.getenv("var_videoIndexerAccountId")
var_speechServiceEndpoint = os.getenv("var_speechServiceEndpoint")
var_speechServiceLocation = os.getenv("var_deploymentLocation")

# Initialize Key Vault client if Key Vault URI is provided
if var_keyVaultUri:
    keyvault_client = SecretClient(
        vault_url=var_keyVaultUri, credential=credential)
else:
    keyvault_client = None

# 4. Update the Configurations

# General > Health Check
item["enable_external_healthcheck"] = True

# AI Models
item["azure_openai_gpt_endpoint"] = var_openAIEndpoint
item["azure_openai_gpt_authentication_type"] = var_authenticationType
item["azure_openai_gpt_subscription_id"] = var_subscriptionId
item["azure_openai_gpt_resource_group"] = var_openAIResourceGroup
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
item["azure_openai_embedding_subscription_id"] = var_subscriptionId
item["azure_openai_embedding_resource_group"] = var_openAIResourceGroup
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

# Safety > Content Safety
if var_contentSafetyEndpoint and var_contentSafetyEndpoint.strip():
    item["enable_content_safety"] = True
item["content_safety_endpoint"] = var_contentSafetyEndpoint
item["content_safety_authentication_type"] = var_authenticationType
if keyvault_client:
    try:
        contentSafety_key_secret = keyvault_client.get_secret(
            "content-safety-key")
        item["content_safety_key"] = contentSafety_key_secret.value
        print("Retrieved contentSafety service key from Key Vault")
    except Exception as e:
        print(
            f"Warning: Could not retrieve content-safety-key from Key Vault: {e}")

# Safety > Conversation Archiving
item["enable_conversation_archiving"] = True

# Search and Extract > Azure AI Search
item["azure_ai_search_endpoint"] = var_searchServiceEndpoint
item["azure_ai_search_authentication_type"] = var_authenticationType
if keyvault_client:
    try:
        search_key_secret = keyvault_client.get_secret("search-service-key")
        item["azure_ai_search_key"] = search_key_secret.value
        print("Retrieved search service key from Key Vault")
    except Exception as e:
        print(
            f"Warning: Could not retrieve search-service-key from Key Vault: {e}")

# Search and Extract > Azure Document Intelligence
item["azure_document_intelligence_endpoint"] = var_documentIntelligenceServiceEndpoint
item["azure_document_intelligence_authentication_type"] = var_authenticationType
if keyvault_client:
    try:
        documentIntelligence_key_secret = keyvault_client.get_secret(
            "document-intelligence-key")
        item["azure_document_intelligence_key"] = documentIntelligence_key_secret.value
        print("Retrieved document intelligence service key from Key Vault")
    except Exception as e:
        print(
            f"Warning: Could not retrieve document-intelligence-key from Key Vault: {e}")

# Search and Extract > Multimedia Support
# Video Indexer Configuration
if var_videoIndexerName and var_videoIndexerName.strip():
    item["enable_video_file_support"] = True
item["video_indexer_resource_group"] = var_rgName
item["video_indexer_subscription_id"] = var_subscriptionId
item["video_indexer_account_name"] = var_videoIndexerName
item["video_indexer_location"] = var_videoIndexerLocation
item["video_indexer_account_id"] = var_videoIndexerAccountId

# Speech Service Configuration
if var_speechServiceEndpoint and var_speechServiceEndpoint.strip():
    item["enable_audio_file_support"] = True
item["speech_service_endpoint"] = var_speechServiceEndpoint
item["speech_service_location"] = var_speechServiceLocation
if keyvault_client:
    try:
        speech_key_secret = keyvault_client.get_secret("speech-service-key")
        item["speech_service_key"] = speech_key_secret.value
        print("Retrieved speech service key from Key Vault")
    except Exception as e:
        print(
            f"Warning: Could not retrieve speech-service-key from Key Vault: {e}")

# 5. Upsert the updated items back into Cosmos DB
response = container.upsert_item(item)
print(
    f"Updated item: {response['id']} with enable_external_healthcheck = {response['enable_external_healthcheck']}")
