#!/usr/bin/env python3
"""
Debug script for message count issue with specific user ID
Version: 0.230.022

This script will test the actual queries against the database containers.
"""

import sys
import os
from azure.cosmos import CosmosClient

def debug_message_count_for_user():
    """Debug message count queries for specific user"""
    
    print("🔍 Debugging Message Count for User")
    print("=" * 50)
    
    user_id = "07e61033-ea1a-4472-a1e7-6b9ac874984a"
    print(f"Testing User ID: {user_id}")
    
    try:
        # Step 1: Test conversations query
        print(f"\n📋 Step 1: Querying Conversations")
        conversations_query = """
            SELECT c.id, c.last_updated FROM c WHERE c.user_id = @user_id
        """
        conversations_params = [{"name": "@user_id", "value": user_id}]
        
        print(f"Query: {conversations_query}")
        print(f"Parameters: {conversations_params}")

        # Connection string for testing (from .env)
        endpoint = os.getenv('AZURE_COSMOS_ENDPOINT', '')
        key = os.getenv('AZURE_COSMOS_KEY', '')

        client = CosmosClient(endpoint, key, consistency_level="Session")

        conversations = list(client.get_database_client("SimpleChat").get_container_client("conversations").query_items(
            query=conversations_query,
            parameters=conversations_params,
            enable_cross_partition_query=True
        ))
        
        print(f"✅ Found {len(conversations)} conversations")
        
        if conversations:
            print(f"First 3 conversations:")
            for i, conv in enumerate(conversations[:3], 1):
                print(f"   {i}. ID: {conv.get('id')}")
                print(f"      Last Updated: {conv.get('last_updated')}")
        
        # Step 2: Test messages query with first few conversation IDs
        if conversations:
            print(f"\n💬 Step 2: Querying Messages")
            
            # Test with first 3 conversations
            test_conv_ids = [conv['id'] for conv in conversations[:3]]
            print(f"Testing with conversation IDs: {test_conv_ids}")
            
            # Build parameterized query
            in_params = []
            param_placeholders = []
            for j, conv_id in enumerate(test_conv_ids):
                param_name = f"@conv_id_{j}"
                param_placeholders.append(param_name)
                in_params.append({"name": param_name, "value": conv_id})
            
            messages_query = f"""
                SELECT 
                    SUM(LENGTH(TO_STRING(m))) AS totalBytes,
                    COUNT(1) AS messageCount
                FROM m
                WHERE m.conversation_id IN ({', '.join(param_placeholders)})
            """
            
            print(f"Query: {messages_query}")
            print(f"Parameters: {in_params}")
            
            try:
                messages_result = list(client.get_database_client("SimpleChat").get_container_client("messages").query_items(
                    query=messages_query,
                    parameters=in_params,
                    enable_cross_partition_query=True
                ))
                
                print(f"✅ Messages query executed successfully")
                print(f"Result: {messages_result}")
                
                if messages_result and messages_result[0]:
                    result = messages_result[0]
                    msg_count = result.get('messageCount', 0)
                    total_bytes = result.get('totalBytes', 0)
                    print(f"   Messages: {msg_count}")
                    print(f"   Total Bytes: {total_bytes}")
                else:
                    print(f"❌ No message results returned")
                    
            except Exception as msg_e:
                print(f"❌ Messages query failed: {msg_e}")
                print(f"Trying individual conversation queries...")
                
                # Test individual queries
                for conv_id in test_conv_ids[:1]:  # Just test first one
                    try:
                        individual_query = """
                            SELECT 
                                SUM(LENGTH(TO_STRING(m))) AS totalBytes,
                                COUNT(1) AS messageCount
                            FROM m
                            WHERE m.conversation_id = @conv_id
                        """
                        individual_params = [{"name": "@conv_id", "value": conv_id}]
                        
                        print(f"\nTesting individual conversation: {conv_id}")
                        print(f"Query: {individual_query}")

                        individual_result = list(client.get_database_client("SimpleChat").get_container_client("messages").query_items(
                            query=individual_query,
                            parameters=individual_params,
                            enable_cross_partition_query=True
                        ))
                        
                        print(f"✅ Individual query result: {individual_result}")
                        
                        # Also try a simple count query
                        simple_query = """
                            SELECT * FROM m WHERE m.conversation_id = @conv_id
                        """
                        simple_result = list(client.get_database_client("SimpleChat").get_container_client("messages").query_items(
                            query=simple_query,
                            parameters=individual_params,
                            enable_cross_partition_query=True
                        ))
                        
                        print(f"📝 Raw messages for this conversation: {len(simple_result)}")
                        if simple_result:
                            print(f"   Sample message: {simple_result[0]}")
                        
                    except Exception as individual_e:
                        print(f"❌ Individual query failed: {individual_e}")
        else:
            print(f"❌ No conversations found for user")
            
    except Exception as e:
        print(f"❌ Query failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("🚀 Message Count Debug Tool")
    print("=" * 40)
    
    try:
        debug_message_count_for_user()
        
    except Exception as e:
        print(f"\n❌ Debug failed: {e}")
        import traceback
        traceback.print_exc()