#!/usr/bin/env python3
"""
Test the fixed query approach - separate count and size queries.
"""

import os
import sys
from azure.cosmos import CosmosClient

def test_fixed_queries():
    """Test the fixed query approach with separate count and size queries."""
    
    # Connection string for testing (from .env)
    endpoint = os.getenv('AZURE_COSMOS_ENDPOINT', '')
    key = os.getenv('AZURE_COSMOS_KEY', '')

    client = CosmosClient(endpoint, key, consistency_level="Session")
    
    database = client.get_database_client("SimpleChat")
    conversations_container = database.get_container_client("conversations")
    messages_container = database.get_container_client("messages")
    
    test_user_id = "07e61033-ea1a-4472-a1e7-6b9ac874984a"
    
    print(f"🔍 Testing FIXED query approach for user: {test_user_id}")
    
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
        # Test with first 5 conversations using FIXED approach
        conversation_ids = [conv['id'] for conv in conversations[:5]]
        
        print(f"Testing with first 5 conversation IDs: {conversation_ids}")
        
        # Use FIXED approach - separate queries
        in_params = []
        param_placeholders = []
        for j, conv_id in enumerate(conversation_ids):
            param_name = f"@conv_id_{j}"
            param_placeholders.append(param_name)
            in_params.append({"name": param_name, "value": conv_id})
        
        print(f"🔍 Parameters: {in_params}")
        
        try:
            # First query: Get message count (FIXED)
            messages_count_query = f"""
                SELECT VALUE COUNT(1)
                FROM m
                WHERE m.conversation_id IN ({', '.join(param_placeholders)})
            """
            
            print(f"🔍 Count Query: {messages_count_query}")
            
            count_result = list(messages_container.query_items(
                query=messages_count_query,
                parameters=in_params,
                enable_cross_partition_query=True
            ))
            
            print(f"✅ Count result: {count_result}")
            message_count = count_result[0] if count_result else 0
            
            # Second query: Get message size (FIXED) 
            messages_size_query = f"""
                SELECT VALUE SUM(LENGTH(TO_STRING(m)))
                FROM m
                WHERE m.conversation_id IN ({', '.join(param_placeholders)})
            """
            
            print(f"🔍 Size Query: {messages_size_query}")
            
            size_result = list(messages_container.query_items(
                query=messages_size_query,
                parameters=in_params,
                enable_cross_partition_query=True
            ))
            
            print(f"✅ Size result: {size_result}")
            message_size = size_result[0] if size_result and size_result[0] else 0
            
            print(f"📊 FINAL RESULTS:")
            print(f"   Messages: {message_count}")
            print(f"   Size: {message_size} bytes")
            
            if message_count > 0:
                print(f"🎉 SUCCESS! Fixed queries are working!")
            else:
                print(f"❌ Still getting 0 messages")
                
        except Exception as e:
            print(f"❌ Query failed: {e}")
            print(f"Exception type: {type(e)}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    test_fixed_queries()