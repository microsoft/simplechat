#!/usr/bin/env python3
"""
Simple debug script for message counting issue.
Version: To be checked against config.py
Implemented in: 0.230.022

This script debugs why message counts show 0 for users with conversations.
"""
import os
import sys
from azure.cosmos import CosmosClient

# Set up environment
os.environ['ENVIRONMENT'] = 'development'

def debug_message_count():
    """Debug message counting for specific user."""
    
   
    # Connection string for testing (from .env)
    endpoint = os.getenv('AZURE_COSMOS_ENDPOINT', '')
    key = os.getenv('AZURE_COSMOS_KEY', '')

    client = CosmosClient(endpoint, key, consistency_level="Session")
    
    database = client.get_database_client("SimpleChat")
    conversations_container = database.get_container_client("conversations")
    messages_container = database.get_container_client("messages")
    
    # Test user ID
    test_user_id = "07e61033-ea1a-4472-a1e7-6b9ac874984a"
    
    print(f"🔍 Testing message count for user: {test_user_id}")
    
    # Step 1: Get conversations for this user
    print("\n📋 Step 1: Getting conversations...")
    conv_query = """
    SELECT c.id, c.user_id, c.last_updated, c.title
    FROM c 
    WHERE c.user_id = @user_id
    ORDER BY c.last_updated DESC
    """
    
    conversations = list(conversations_container.query_items(
        query=conv_query,
        parameters=[{"name": "@user_id", "value": test_user_id}],
        enable_cross_partition_query=True
    ))
    
    print(f"Found {len(conversations)} conversations")
    if conversations:
        print(f"Sample conversations:")
        for i, conv in enumerate(conversations[:3]):  # Show first 3
            print(f"  {i+1}. ID: {conv['id']}, Title: {conv.get('title', 'No title')}")
    
    # Step 2: Test message counting methods
    print(f"\n🔢 Step 2: Testing message counting methods...")
    
    if not conversations:
        print("❌ No conversations found - cannot test message counting")
        return
    
    # Method 1: Count all messages for the user directly
    print("\n🔍 Method 1: Direct message count for user")
    direct_query = """
    SELECT VALUE COUNT(1)
    FROM c 
    WHERE c.user_id = @user_id
    """
    
    try:
        direct_result = list(messages_container.query_items(
            query=direct_query,
            parameters=[{"name": "@user_id", "value": test_user_id}],
            enable_cross_partition_query=True
        ))
        print(f"Direct count result: {direct_result}")
    except Exception as e:
        print(f"❌ Direct count failed: {e}")
    
    # Method 2: Count messages by conversation IDs (current approach)
    print("\n🔍 Method 2: Count by conversation IDs (current approach)")
    conversation_ids = [conv['id'] for conv in conversations]
    print(f"Using {len(conversation_ids)} conversation IDs")
    
    if conversation_ids:
        # Try with first few conversation IDs to test
        test_ids = conversation_ids[:5]  # Test with first 5
        print(f"Testing with first {len(test_ids)} conversation IDs: {test_ids}")
        
        conv_query = """
        SELECT VALUE COUNT(1)
        FROM c 
        WHERE c.conversation_id IN ({})
        """.format(','.join([f'"{conv_id}"' for conv_id in test_ids]))
        
        try:
            conv_result = list(messages_container.query_items(
                query=conv_query,
                enable_cross_partition_query=True
            ))
            print(f"Conversation ID count result: {conv_result}")
        except Exception as e:
            print(f"❌ Conversation ID count failed: {e}")
    
    # Method 3: Sample individual conversation messages
    print(f"\n🔍 Method 3: Sample individual conversation messages")
    for i, conv in enumerate(conversations[:3]):  # Check first 3 conversations
        conv_id = conv['id']
        print(f"\n  Checking conversation {i+1}: {conv_id}")
        
        sample_query = """
        SELECT c.id, c.conversation_id, c.user_id
        FROM c 
        WHERE c.conversation_id = @conv_id
        """
        
        try:
            messages = list(messages_container.query_items(
                query=sample_query,
                parameters=[{"name": "@conv_id", "value": conv_id}],
                enable_cross_partition_query=True
            ))
            print(f"    Found {len(messages)} messages")
            if messages:
                print(f"    Sample message: {messages[0]}")
        except Exception as e:
            print(f"    ❌ Failed to get messages: {e}")
    
    print(f"\n✅ Debug complete!")

if __name__ == "__main__":
    debug_message_count()