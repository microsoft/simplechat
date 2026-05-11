#!/usr/bin/env python3
"""
Test improved document metrics implementation.
Version: 0.230.024
Implemented in: 0.230.024

This script tests the improved document metrics for Control Center.
"""

import os
from azure.cosmos import CosmosClient
from datetime import datetime, timezone, timedelta

def test_improved_document_metrics():
    """Test the improved document metrics implementation."""
    
    # Connection string for testing (from .env)
    endpoint = os.getenv('AZURE_COSMOS_ENDPOINT', '')
    key = os.getenv('AZURE_COSMOS_KEY', '')

    client = CosmosClient(endpoint, key, consistency_level="Session")
    database = client.get_database_client("SimpleChat")
    
    # Get containers
    user_documents_container = database.get_container_client("documents")
    settings_container = database.get_container_client("settings")
    
    test_user_id = "07e61033-ea1a-4472-a1e7-6b9ac874984a"
    
    print(f"🔍 Testing IMPROVED document metrics for user: {test_user_id}")
    
    # Test 1: Document count (separate query)
    print(f"\n📊 Test 1: Document count...")
    doc_count_query = """
        SELECT VALUE COUNT(1)
        FROM c 
        WHERE c.user_id = @user_id AND c.type = 'document_metadata'
    """
    doc_metrics_params = [{"name": "@user_id", "value": test_user_id}]
    doc_count_result = list(user_documents_container.query_items(
        query=doc_count_query,
        parameters=doc_metrics_params,
        enable_cross_partition_query=True
    ))
    
    total_docs = doc_count_result[0] if doc_count_result else 0
    print(f"✅ Total documents: {total_docs}")
    
    # Test 2: Total pages (separate query)
    print(f"\n📄 Test 2: Total pages...")
    doc_pages_query = """
        SELECT VALUE SUM(c.number_of_pages)
        FROM c 
        WHERE c.user_id = @user_id AND c.type = 'document_metadata'
    """
    doc_pages_result = list(user_documents_container.query_items(
        query=doc_pages_query,
        parameters=doc_metrics_params,
        enable_cross_partition_query=True
    ))
    
    total_pages = doc_pages_result[0] if doc_pages_result and doc_pages_result[0] else 0
    ai_search_size = total_pages * 80 * 1024  # 80KB per page
    print(f"✅ Total pages: {total_pages}")
    print(f"✅ AI Search size: {ai_search_size} bytes ({total_pages * 80} KB)")
    
    # Test 3: Last day document upload (MM/DD/YYYY format)
    print(f"\n📅 Test 3: Last day document upload...")
    last_doc_query = """
        SELECT TOP 1 c.last_updated, c.file_name
        FROM c 
        WHERE c.user_id = @user_id AND c.type = 'document_metadata'
        ORDER BY c.last_updated DESC
    """
    last_doc_result = list(user_documents_container.query_items(
        query=last_doc_query,
        parameters=doc_metrics_params,
        enable_cross_partition_query=True
    ))
    
    last_day_upload = 'Never'
    if last_doc_result and last_doc_result[0]:
        last_updated = last_doc_result[0].get('last_updated')
        file_name = last_doc_result[0].get('file_name')
        if last_updated:
            try:
                date_obj = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                last_day_upload = date_obj.strftime('%m/%d/%Y')
                print(f"✅ Last day upload: {last_day_upload} (file: {file_name})")
            except Exception as e:
                print(f"❌ Date formatting error: {e}")
                last_day_upload = 'Invalid date'
    else:
        print(f"✅ Last day upload: {last_day_upload}")
    
    # Test 4: Enhanced citations setting
    print(f"\n🔧 Test 4: Enhanced citations setting...")
    settings_query = """
        SELECT c.enable_enhanced_citations
        FROM c 
        WHERE c.id = 'app_settings'
    """
    
    settings_result = list(settings_container.query_items(
        query=settings_query,
        enable_cross_partition_query=True
    ))
    
    enhanced_citations_enabled = False
    if settings_result:
        enhanced_citations_enabled = settings_result[0].get('enable_enhanced_citations', False)
    
    print(f"✅ Enhanced citations enabled: {enhanced_citations_enabled}")
    
    # Test 5: Storage account size (would need Azure Storage SDK in real implementation)
    print(f"\n💾 Test 5: Storage account size...")
    if enhanced_citations_enabled:
        print(f"✅ Enhanced citations enabled - would query Azure Storage for actual file sizes")
        print(f"    Storage path: user-documents/{test_user_id}/")
        print(f"    Would sum all blob sizes in that folder")
        
        # Show what the estimation fallback would calculate
        storage_size_query = """
            SELECT c.file_name, c.number_of_pages FROM c 
            WHERE c.user_id = @user_id AND c.type = 'document_metadata'
        """
        storage_docs = list(user_documents_container.query_items(
            query=storage_size_query,
            parameters=doc_metrics_params,
            enable_cross_partition_query=True
        ))
        
        total_estimated_size = 0
        for doc in storage_docs[:5]:  # Show first 5 as examples
            pages = doc.get('number_of_pages', 1)
            file_name = doc.get('file_name', '')
            
            if file_name.lower().endswith('.pdf'):
                estimated_size = pages * 500 * 1024  # 500KB per page
            elif file_name.lower().endswith(('.docx', '.doc')):
                estimated_size = pages * 300 * 1024  # 300KB per page
            elif file_name.lower().endswith(('.pptx', '.ppt')):
                estimated_size = pages * 800 * 1024  # 800KB per page
            else:
                estimated_size = pages * 400 * 1024  # 400KB per page
            
            total_estimated_size += estimated_size
            print(f"    📄 {file_name} ({pages} pages): ~{estimated_size} bytes")
        
        print(f"    📊 Estimated size (first 5 files): {total_estimated_size} bytes")
    else:
        print(f"✅ Enhanced citations disabled - no storage account size needed")
    
    # Summary
    print(f"\n📋 SUMMARY - Enhanced Document Metrics:")
    print(f"   📅 Last Day Upload: {last_day_upload}")
    print(f"   📊 Total Documents: {total_docs}")
    print(f"   🔍 AI Search Size: {ai_search_size} bytes")
    if enhanced_citations_enabled:
        print(f"   💾 Storage Account Size: Would be calculated from Azure Storage")
    
    print(f"\n🎉 All document metrics tests completed successfully!")

if __name__ == "__main__":
    test_improved_document_metrics()