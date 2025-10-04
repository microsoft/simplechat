#!/usr/bin/env python3
"""
Test script to debug login activity data for Control Center
"""

import sys
import os
from datetime import datetime, timedelta
from azure.cosmos import CosmosClient

def test_login_activity():
    """Test what login activity data is available"""
    
    print("🔍 Testing login activity data...")
    
    # Check what's in the activity_logs container
    print("\n--- Sample records from activity_logs container ---")
    sample_query = """
        SELECT TOP 10 c.id, c.activity_type, c.login_method, c.timestamp, c.created_at, c.user_id
        FROM c 
        ORDER BY c.timestamp DESC
    """
    
    try:
        # Connection string for testing (from .env)
        endpoint = os.getenv('AZURE_COSMOS_ENDPOINT', '')
        key = os.getenv('AZURE_COSMOS_KEY', '')

        client = CosmosClient(endpoint, key, consistency_level="Session")

        sample_records = list(client.get_database_client("SimpleChat").get_container_client("activity_logs").query_items(
            query=sample_query,
            enable_cross_partition_query=True
        ))
        
        print(f"Found {len(sample_records)} sample records:")
        for record in sample_records:
            print(f"  - ID: {record.get('id')}")
            print(f"    Activity Type: {record.get('activity_type')}")
            print(f"    Login Method: {record.get('login_method')}")
            print(f"    Timestamp: {record.get('timestamp')}")
            print(f"    Created At: {record.get('created_at')}")
            print(f"    User ID: {record.get('user_id')}")
            print()
            
    except Exception as e:
        print(f"Error querying sample records: {e}")
    
    # Check for login activities specifically
    print("\n--- Login activities with activity_type='user_login' ---")
    login_query_1 = """
        SELECT c.id, c.activity_type, c.login_method, c.timestamp, c.created_at, c.user_id
        FROM c 
        WHERE c.activity_type = 'user_login'
        ORDER BY c.timestamp DESC
    """
    
    try:
        login_records = list(client.get_database_client("SimpleChat").get_container_client("activity_logs").query_items(
            query=login_query_1,
            enable_cross_partition_query=True
        ))
        
        print(f"Found {len(login_records)} login records with activity_type='user_login':")
        for record in login_records[:5]:  # Show first 5
            print(f"  - ID: {record.get('id')}")
            print(f"    Login Method: {record.get('login_method')}")
            print(f"    Timestamp: {record.get('timestamp')}")
            print(f"    User ID: {record.get('user_id')}")
            print()
            
    except Exception as e:
        print(f"Error querying login records: {e}")
    
    # Check for records with login_method
    print("\n--- Records with login_method field ---")
    login_query_2 = """
        SELECT c.id, c.activity_type, c.login_method, c.timestamp, c.created_at, c.user_id
        FROM c 
        WHERE c.login_method != null
        ORDER BY c.timestamp DESC
    """
    
    try:
        method_records = list(client.get_database_client("SimpleChat").get_container_client("activity_logs").query_items(
            query=login_query_2,
            enable_cross_partition_query=True
        ))
        
        print(f"Found {len(method_records)} records with login_method field:")
        for record in method_records[:5]:  # Show first 5
            print(f"  - ID: {record.get('id')}")
            print(f"    Activity Type: {record.get('activity_type')}")
            print(f"    Login Method: {record.get('login_method')}")
            print(f"    Timestamp: {record.get('timestamp')}")
            print(f"    User ID: {record.get('user_id')}")
            print()
            
    except Exception as e:
        print(f"Error querying method records: {e}")

if __name__ == "__main__":
    test_login_activity()