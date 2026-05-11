#!/usr/bin/env python3
"""
Debug script to check container structure and data.
"""

import os
import sys
from azure.cosmos import CosmosClient

def debug_containers():
    """Debug containers and data structure."""
    
    # Connection string for testing (from .env)
    endpoint = os.getenv('AZURE_COSMOS_ENDPOINT', '')
    key = os.getenv('AZURE_COSMOS_KEY', '')

    client = CosmosClient(endpoint, key, consistency_level="Session")
    
    database = client.get_database_client("SimpleChat")
    
    print("🔍 Listing all containers in SimpleChat database:")
    
    # List all containers
    for container in database.list_containers():
        container_name = container['id']
        print(f"  📦 Container: {container_name}")
        
        # Get a sample document from each container
        try:
            container_client = database.get_container_client(container_name)
            sample_query = "SELECT TOP 1 * FROM c"
            
            sample_docs = list(container_client.query_items(
                query=sample_query,
                enable_cross_partition_query=True
            ))
            
            if sample_docs:
                sample_doc = sample_docs[0]
                print(f"    Sample document keys: {list(sample_doc.keys())}")
                if 'user_id' in sample_doc:
                    print(f"    ✅ Has user_id field")
                else:
                    print(f"    ❌ No user_id field")
                    
                if 'conversation_id' in sample_doc:
                    print(f"    ✅ Has conversation_id field")
                else:
                    print(f"    ❌ No conversation_id field")
            else:
                print(f"    📭 No documents found")
                
        except Exception as e:
            print(f"    ❌ Error accessing container: {e}")
    
    print(f"\n🔍 Now testing message count with exact production query...")
    
    # Test user ID
    test_user_id = "07e61033-ea1a-4472-a1e7-6b9ac874984a"
    
    # Get the containers we need
    conversations_container = database.get_container_client("conversations")
    messages_container = database.get_container_client("messages")
    
    # Step 1: Get conversations for user
    conv_query = """
        SELECT c.id FROM c 
        WHERE c.user_id = @user_id
    """
    
    conversations = list(conversations_container.query_items(
        query=conv_query,
        parameters=[{"name": "@user_id", "value": test_user_id}],
        enable_cross_partition_query=True
    ))
    
    print(f"Found {len(conversations)} conversations for user")
    
    if conversations:
        # Test with first 5 conversations using exact production code
        conversation_ids = [conv['id'] for conv in conversations[:5]]
        
        print(f"Testing with first 5 conversation IDs: {conversation_ids}")
        
        # Use exact production query format
        in_params = []
        param_placeholders = []
        for j, conv_id in enumerate(conversation_ids):
            param_name = f"@conv_id_{j}"
            param_placeholders.append(param_name)
            in_params.append({"name": param_name, "value": conv_id})
        
        messages_size_query = f"""
            SELECT 
                SUM(LENGTH(TO_STRING(m))) AS totalBytes,
                COUNT(1) AS messageCount
            FROM m
            WHERE m.conversation_id IN ({', '.join(param_placeholders)})
        """
        
        print(f"🔍 Query: {messages_size_query}")
        print(f"🔍 Parameters: {in_params}")
        
        try:
            size_result = list(messages_container.query_items(
                query=messages_size_query,
                parameters=in_params,
                enable_cross_partition_query=True
            ))
            
            print(f"✅ Query result: {size_result}")
            
            if size_result and size_result[0]:
                batch_size_info = size_result[0]
                batch_messages = batch_size_info.get('messageCount') or 0
                batch_bytes = batch_size_info.get('totalBytes') or 0
                
                print(f"📊 Messages: {batch_messages}, Bytes: {batch_bytes}")
            else:
                print(f"❌ No results returned")
                
        except Exception as e:
            print(f"❌ Query failed: {e}")
            print(f"Exception type: {type(e)}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    debug_containers()