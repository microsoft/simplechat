#!/usr/bin/env python3
"""
Functional test for Enhanced Document Metrics database queries.
Version: 0.230.024
Implemented in: 0.230.024

This test validates the document metrics calculation logic by directly
testing the database queries and calculations without requiring a running Flask app.
"""

import sys
import os
from datetime import datetime
from azure.cosmos import CosmosClient

def test_document_metrics_queries():
    """Test the document metrics database queries directly."""
    print("🔍 Testing Document Metrics Database Queries...")
    
    try:
        # Connection string for testing (from .env)
        endpoint = os.getenv('AZURE_COSMOS_ENDPOINT', '')
        key = os.getenv('AZURE_COSMOS_KEY', '')

        client = CosmosClient(endpoint, key, consistency_level="Session")
        
        # Test user ID
        test_user_id = "07e61033-ea1a-4472-a1e7-6b9ac874984a"
        print(f"📋 Testing document metrics queries for user: {test_user_id}")
        
        # Get documents container
        print("🗄️ Connecting to Cosmos DB documents container...")
        documents_container = client.get_database_client("SimpleChat").get_container_client("documents")
        
        # Test 1: Count total documents
        print("\n📊 Test 1: Counting total documents...")
        count_query = "SELECT VALUE COUNT(1) FROM c WHERE c.user_id = @user_id"
        count_parameters = [{"name": "@user_id", "value": test_user_id}]
        
        count_items = list(documents_container.query_items(
            query=count_query,
            parameters=count_parameters,
            enable_cross_partition_query=True
        ))
        
        total_documents = count_items[0] if count_items else 0
        print(f"✅ Total documents: {total_documents}")
        
        # Test 2: Sum total pages for AI search size
        print("\n📊 Test 2: Calculating AI search size...")
        pages_query = "SELECT VALUE SUM(c.number_of_pages) FROM c WHERE c.user_id = @user_id"
        pages_parameters = [{"name": "@user_id", "value": test_user_id}]
        
        pages_items = list(documents_container.query_items(
            query=pages_query,
            parameters=pages_parameters,
            enable_cross_partition_query=True
        ))
        
        total_pages = pages_items[0] if pages_items else 0
        ai_search_size = total_pages * 80 * 1024  # 80KB per page
        print(f"✅ Total pages: {total_pages}")
        print(f"✅ AI search size: {ai_search_size:,} bytes ({ai_search_size / (1024*1024):.2f} MB)")
        
        # Test 3: Get most recent last_updated for last day upload
        print("\n📊 Test 3: Finding most recent upload date...")
        recent_query = """
        SELECT TOP 1 c.last_updated 
        FROM c 
        WHERE c.user_id = @user_id 
        ORDER BY c.last_updated DESC
        """
        recent_parameters = [{"name": "@user_id", "value": test_user_id}]
        
        recent_items = list(documents_container.query_items(
            query=recent_query,
            parameters=recent_parameters,
            enable_cross_partition_query=True
        ))
        
        if recent_items and recent_items[0].get('last_updated'):
            last_updated = recent_items[0]['last_updated']
            # Parse the date and format as MM/DD/YYYY
            if isinstance(last_updated, str):
                # Try different date formats
                try:
                    dt = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                except:
                    try:
                        dt = datetime.strptime(last_updated, '%Y-%m-%d')
                    except:
                        dt = datetime.strptime(last_updated, '%Y-%m-%dT%H:%M:%S')
            else:
                dt = last_updated
                
            last_day_upload = dt.strftime('%m/%d/%Y')
            print(f"✅ Most recent upload: {last_day_upload}")
        else:
            last_day_upload = "N/A"
            print("✅ No documents found - last day upload: N/A")
        
        # Test 4: Create document metrics structure
        print("\n📊 Test 4: Creating document metrics structure...")
        document_metrics = {
            'last_day_upload': last_day_upload,
            'total_documents': total_documents,
            'ai_search_size': ai_search_size,
            'storage_account_size': 0  # Would be calculated from Azure Storage when enhanced citations enabled
        }
        
        print("✅ Document metrics structure created:")
        print(f"   📅 Last Day Upload: {document_metrics['last_day_upload']}")
        print(f"   📄 Total Documents: {document_metrics['total_documents']:,}")
        print(f"   🔍 AI Search Size: {document_metrics['ai_search_size']:,} bytes")
        print(f"   💾 Storage Account Size: {document_metrics['storage_account_size']:,} bytes")
        
        # Validate structure
        print("\n🔍 Validating document metrics structure...")
        
        # Check required fields
        required_fields = ['last_day_upload', 'total_documents', 'ai_search_size', 'storage_account_size']
        for field in required_fields:
            if field not in document_metrics:
                print(f"❌ Missing required field: {field}")
                return False
        print("✅ All required fields present")
        
        # Check data types
        if not isinstance(document_metrics['last_day_upload'], str):
            print("❌ last_day_upload should be string")
            return False
        
        if not isinstance(document_metrics['total_documents'], int):
            print("❌ total_documents should be integer")
            return False
            
        if not isinstance(document_metrics['ai_search_size'], int):
            print("❌ ai_search_size should be integer")
            return False
            
        if not isinstance(document_metrics['storage_account_size'], (int, float)):
            print("❌ storage_account_size should be number")
            return False
            
        print("✅ All data types correct")
        
        # Check date format
        if document_metrics['last_day_upload'] != "N/A":
            try:
                datetime.strptime(document_metrics['last_day_upload'], '%m/%d/%Y')
                print("✅ Date format valid (MM/DD/YYYY)")
            except ValueError:
                print(f"❌ Invalid date format: {document_metrics['last_day_upload']}")
                return False
        else:
            print("✅ Date is N/A (no documents)")
            
        print("\n🎉 All document metrics tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_document_metrics_queries()
    if success:
        print("\n✅ Document metrics database queries working correctly!")
        print("💡 Next step: Test with running Flask app using test_control_center_document_metrics_endpoint.py")
    else:
        print("\n❌ Document metrics tests failed!")
    sys.exit(0 if success else 1)