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

# 4. Update the property
item["enable_external_healthcheck"] = True

# 5. Upsert the updated item back into Cosmos DB
response = container.upsert_item(item)
print(f"Updated item: {response['id']} with enable_external_healthcheck = {response['enable_external_healthcheck']}")
