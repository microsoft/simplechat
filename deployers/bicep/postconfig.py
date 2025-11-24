from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential
import os

credential = DefaultAzureCredential()
token = credential.get_token("https://cosmos.azure.com/.default")

#endpoint = "https://bicepchat-demo-cosmos.documents.azure.com:443/"
cosmosEndpoint = os.getenv("var_cosmosDb_uri")
client = CosmosClient(cosmosEndpoint, credential=credential)

database_name = "SimpleChat"
container_name = "settings"

database = client.get_database_client(database_name)
container = database.get_container_client(container_name)

# 3. Read the existing item by ID and partition key
item_id = "app_settings"
partition_key = "app_settings"  # Use the actual partition key value for this item
item = container.read_item(item=item_id, partition_key=partition_key)

var_openAIEndpoint=os.getenv("var_openAIEndpoint")
var_openAIResourceGroup=os.getenv("var_openAIResourceGroup")
var_subscriptionId = os.getenv("var_subscriptionId")
var_rgName = os.getenv("var_rgName")
var_openAIGPTModel = os.getenv("var_openAIGPTModel")
var_openAITextEmbeddingModel = os.getenv("var_openAITextEmbeddingModel")
var_blobStorageEndpoint = os.getenv("var_blobStorageEndpoint")
var_contentSafetyEndpoint = os.getenv("var_contentSafetyEndpoint")  
var_searchServiceEndpoint = os.getenv("var_searchServiceEndpoint")
var_documentIntelligenceServiceEndpoint = os.getenv("var_documentIntelligenceServiceEndpoint")

# 4. Update the property
item["enable_external_healthcheck"] = True

item["azure_openai_gpt_endpoint"] = var_openAIEndpoint
item["azure_openai_gpt_authentication_type"] = "managed_identity"
item["azure_openai_gpt_subscription_id"] = var_subscriptionId
item["azure_openai_gpt_resource_group"] = var_openAIResourceGroup
item["gpt_model"] = {
    "selected": [
        {
            "deploymentName": var_openAIGPTModel,
            "modelName": var_openAIGPTModel
        }
    ],
    "all": [
        {
            "deploymentName": var_openAIGPTModel,
            "modelName": var_openAIGPTModel
        }
    ]
}

item["azure_openai_embedding_endpoint"] = var_openAIEndpoint
item["azure_openai_embedding_authentication_type"] = "managed_identity"
item["azure_openai_embedding_subscription_id"] = var_subscriptionId
item["azure_openai_embedding_resource_group"] = var_openAIResourceGroup
item["embedding_model"] = {
    "selected": [
        {
            "deploymentName": var_openAITextEmbeddingModel,
            "modelName": var_openAITextEmbeddingModel
        }
    ],
    "all": [
        {
            "deploymentName": var_openAITextEmbeddingModel,
            "modelName": var_openAITextEmbeddingModel
        }
    ]
}

item["enable_semantic_kernel"] = True

item["enable_appinsights_global_logging"] = True

item["enable_extract_meta_data"] = True
item["metadata_extraction_model"] = var_openAIGPTModel

item["enable_multimodal_vision"] = True
item["multimodal_vision_model"] = var_openAIGPTModel

item["enable_enhanced_citations"] = True
item["office_docs_storage_account_blob_endpoint"] = var_blobStorageEndpoint

# if contentSafetyEndpoint is not blank then set enable_content_safety to true
if var_contentSafetyEndpoint and var_contentSafetyEndpoint.strip():
    item["enable_content_safety"] = True
    item["content_safety_endpoint"] = var_contentSafetyEndpoint
    item["content_safety_authentication_type"] = "managed_identity"

item["enable_conversation_archiving"] = True

item["azure_ai_search_endpoint"] = var_searchServiceEndpoint
item["azure_ai_search_authentication_type"] = "managed_identity"

item["azure_document_intelligence_endpoint"] = var_documentIntelligenceServiceEndpoint
item["azure_document_intelligence_authentication_type"] = "managed_identity"

# 5. Upsert the updated items back into Cosmos DB
response = container.upsert_item(item)
print(f"Updated item: {response['id']} with enable_external_healthcheck = {response['enable_external_healthcheck']}")
