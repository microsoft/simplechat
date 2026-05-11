#!/usr/bin/env python3
"""
Debug document metrics for Control Center.
Version: 0.230.023
Implemented in: 0.230.023

This script debugs document metrics to understand structure and implement improvements.
"""

import os
from azure.cosmos import CosmosClient
from datetime import datetime, timezone, timedelta

def debug_document_metrics():
    """Debug document metrics for specific user."""
    
    # Connection from .env
    endpoint = os.getenv('AZURE_COSMOS_ENDPOINT', '')
    key = os.getenv('AZURE_COSMOS_KEY', '')
    
    client = CosmosClient(endpoint, key, consistency_level="Session")
    database = client.get_database_client("SimpleChat")
    
    # Get user documents container
    user_documents_container = database.get_container_client("documents")
    
    test_user_id = "07e61033-ea1a-4472-a1e7-6b9ac874984a"
    
    print(f"🔍 Testing document metrics for user: {test_user_id}")
    
    # Step 1: Get sample documents to understand structure
    print(f"\n📋 Step 1: Getting sample documents...")
    sample_query = """
        SELECT TOP 5 c.id, c.file_name, c.number_of_pages, c.upload_date, c.last_updated, c.type
        FROM c 
        WHERE c.user_id = @user_id AND c.type = 'document_metadata'
        ORDER BY c.last_updated DESC
    """
    
    sample_docs = list(user_documents_container.query_items(
        query=sample_query,
        parameters=[{"name": "@user_id", "value": test_user_id}],
        enable_cross_partition_query=True
    ))
    
    print(f"Found {len(sample_docs)} sample documents:")
    for i, doc in enumerate(sample_docs):
        print(f"  {i+1}. File: {doc.get('file_name')}")
        print(f"      Pages: {doc.get('number_of_pages')}")
        print(f"      Upload: {doc.get('upload_date')}")
        print(f"      Updated: {doc.get('last_updated')}")
        print(f"      Type: {doc.get('type')}")
    
    # Step 2: Get document count and pages
    print(f"\n📊 Step 2: Getting document count and pages...")
    count_pages_query = """
        SELECT VALUE COUNT(1)
        FROM c 
        WHERE c.user_id = @user_id AND c.type = 'document_metadata'
    """
    
    pages_sum_query = """
        SELECT VALUE SUM(c.number_of_pages)
        FROM c 
        WHERE c.user_id = @user_id AND c.type = 'document_metadata'
    """
    
    doc_count = list(user_documents_container.query_items(
        query=count_pages_query,
        parameters=[{"name": "@user_id", "value": test_user_id}],
        enable_cross_partition_query=True
    ))
    
    total_pages = list(user_documents_container.query_items(
        query=pages_sum_query,
        parameters=[{"name": "@user_id", "value": test_user_id}],
        enable_cross_partition_query=True
    ))
    
    doc_count_val = doc_count[0] if doc_count else 0
    total_pages_val = total_pages[0] if total_pages and total_pages[0] else 0
    
    print(f"📈 Total documents: {doc_count_val}")
    print(f"📈 Total pages: {total_pages_val}")
    print(f"📈 AI Search size: {total_pages_val * 80 * 1024} bytes ({total_pages_val * 80} KB)")
    
    # Step 3: Get most recent document upload date for "last day"
    print(f"\n📅 Step 3: Getting most recent document upload...")
    most_recent_query = """
        SELECT TOP 1 c.last_updated, c.upload_date, c.file_name
        FROM c 
        WHERE c.user_id = @user_id AND c.type = 'document_metadata'
        ORDER BY c.last_updated DESC
    """
    
    most_recent = list(user_documents_container.query_items(
        query=most_recent_query,
        parameters=[{"name": "@user_id", "value": test_user_id}],
        enable_cross_partition_query=True
    ))
    
    if most_recent:
        doc = most_recent[0]
        last_updated = doc.get('last_updated')
        upload_date = doc.get('upload_date')
        file_name = doc.get('file_name')
        
        print(f"📄 Most recent document: {file_name}")
        print(f"📅 Last updated: {last_updated}")
        print(f"📅 Upload date: {upload_date}")
        
        # Format as MM/DD/YYYY
        if last_updated:
            try:
                date_obj = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                formatted_date = date_obj.strftime('%m/%d/%Y')
                print(f"📅 Formatted last day: {formatted_date}")
            except Exception as e:
                print(f"❌ Date formatting error: {e}")
    else:
        print(f"📭 No documents found")
    
    # Step 4: Check for enhanced citations settings (from settings container)
    print(f"\n🔧 Step 4: Checking enhanced citations setting...")
    settings_container = database.get_container_client("settings")
    
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
    
    print(f"🔧 Enhanced citations enabled: {enhanced_citations_enabled}")
    
    # Step 5: If enhanced citations enabled, show what we'd need for storage account size
    if enhanced_citations_enabled:
        print(f"\n💾 Step 5: Enhanced citations is enabled - would need to query Azure Storage")
        print(f"    Storage path would be: user-documents/{test_user_id}/")
        print(f"    Would need to get actual file sizes from Azure Storage SDK")
        print(f"    Currently using file estimation instead")
    else:
        print(f"\n💾 Step 5: Enhanced citations is disabled - no storage account size needed")
    
    print(f"\n✅ Document debug complete!")

if __name__ == "__main__":
    debug_document_metrics()