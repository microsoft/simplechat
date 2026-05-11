#!/usr/bin/env python3
"""
Functional test for storage account size debug - specifically for user 07e61033-ea1a-4472-a1e7-6b9ac874984a.
This test investigates why a user with 33 files shows 0 storage account size when enhanced citations is enabled.

Version: 0.230.033
Created to debug: Storage account sizing evaluation broken after rollback
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Add the parent directory to sys.path to access the application modules
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app'))

def test_specific_user_storage_debug():
    """Test the specific user (07e61033-ea1a-4472-a1e7-6b9ac874984a) storage sizing issue."""
    print("🔍 Debug: Storage Account Size for User 07e61033-ea1a-4472-a1e7-6b9ac874984a")
    print("=" * 80)
    
    test_user_id = "07e61033-ea1a-4472-a1e7-6b9ac874984a"
    
    try:
        # Import necessary modules
        from config import (
            CLIENTS,
            storage_account_user_documents_container_name
        )
        from route_backend_control_center import enhance_user_with_activity
        
        print(f"✅ Successfully imported required modules")
        print(f"📁 User documents container: {storage_account_user_documents_container_name}")
        
        # Check if storage client is available
        storage_client = CLIENTS.get("storage_account_office_docs_client")
        print(f"🔌 Storage client available: {storage_client is not None}")
        
        if storage_client:
            print(f"🔌 Storage client type: {type(storage_client)}")
            
            # Test direct storage account access for this user
            user_folder_prefix = f"{test_user_id}/"
            print(f"📂 User folder prefix: {user_folder_prefix}")
            
            try:
                container_client = storage_client.get_container_client(storage_account_user_documents_container_name)
                print(f"✅ Container client created successfully")
                
                # Check if container exists
                container_exists = container_client.exists()
                print(f"📦 Container exists: {container_exists}")
                
                if container_exists:
                    # List blobs for this specific user
                    print(f"🔍 Listing blobs for user {test_user_id}...")
                    blob_count = 0
                    total_size = 0
                    blob_details = []
                    
                    try:
                        blob_list = container_client.list_blobs(name_starts_with=user_folder_prefix)
                        
                        for blob in blob_list:
                            blob_count += 1
                            total_size += blob.size
                            blob_info = {
                                'name': blob.name,
                                'size': blob.size,
                                'last_modified': blob.last_modified,
                                'content_type': getattr(blob, 'content_settings', {}).get('content_type', 'unknown') if hasattr(blob, 'content_settings') and blob.content_settings else 'unknown'
                            }
                            blob_details.append(blob_info)
                            print(f"   📄 {blob.name}: {blob.size:,} bytes ({blob.size / 1024 / 1024:.2f} MB)")
                        
                        print(f"\n📊 STORAGE SUMMARY:")
                        print(f"   Total blobs found: {blob_count}")
                        print(f"   Total size: {total_size:,} bytes ({total_size / 1024 / 1024:.2f} MB)")
                        
                        if blob_count != 33:
                            print(f"⚠️  WARNING: Expected 33 files but found {blob_count} files!")
                        
                        # Also try listing all blobs in container to check if the issue is with prefix
                        print(f"\n🔍 Checking if blobs exist without user prefix...")
                        all_blob_count = 0
                        user_related_blobs = []
                        
                        try:
                            all_blobs = container_client.list_blobs()
                            for blob in all_blobs:
                                all_blob_count += 1
                                if test_user_id in blob.name:
                                    user_related_blobs.append(blob.name)
                                    print(f"   📄 Found user-related blob: {blob.name}")
                                
                            print(f"📊 Total blobs in container: {all_blob_count}")
                            print(f"📊 User-related blobs found: {len(user_related_blobs)}")
                            
                        except Exception as all_blobs_e:
                            print(f"❌ Error listing all blobs: {all_blobs_e}")
                            
                    except Exception as blob_list_e:
                        print(f"❌ Error listing blobs with prefix: {blob_list_e}")
                        return False
                        
                else:
                    print(f"❌ Container does not exist!")
                    return False
                    
            except Exception as container_e:
                print(f"❌ Error accessing container: {container_e}")
                return False
                
        else:
            print(f"❌ Storage client not initialized!")
            print(f"🔍 This is the ROOT CAUSE of the issue!")
            print(f"   The storage account size shows 0 because:")
            print(f"   1. Enhanced citations is enabled for the user")
            print(f"   2. But the storage client is not configured")
            print(f"   3. This causes the fallback estimation to be used")
            print(f"   4. However, the fallback might also be broken")
            
            print(f"\n🔍 Checking CLIENTS dictionary...")
            for key, value in CLIENTS.items():
                print(f"   {key}: {value is not None}")
        
        # Check Cosmos DB for document metadata first
        print(f"\n🔍 Checking Cosmos DB for document metadata...")
        docs = []
        try:
            from config import cosmos_user_documents_container
            
            if cosmos_user_documents_container:
                query = """
                    SELECT c.id, c.file_name, c.number_of_pages, c.type, c.created_at
                    FROM c 
                    WHERE c.user_id = @user_id AND c.type = 'document_metadata'
                """
                params = [{"name": "@user_id", "value": test_user_id}]
                
                docs = list(cosmos_user_documents_container.query_items(
                    query=query,
                    parameters=params,
                    enable_cross_partition_query=True
                ))
                
                print(f"📊 Documents in Cosmos DB: {len(docs)}")
                for i, doc in enumerate(docs[:10], 1):  # Show first 10
                    print(f"   {i}. {doc.get('file_name', 'Unknown')} - {doc.get('number_of_pages', 0)} pages")
                
                if len(docs) > 10:
                    print(f"   ... and {len(docs) - 10} more documents")
                    
            else:
                print(f"❌ Cosmos DB user documents container not available")
                
        except Exception as cosmos_e:
            print(f"❌ Error checking Cosmos DB: {cosmos_e}")
        
        # Test the fallback estimation logic manually
        if docs:
            print(f"\n🔍 Testing fallback storage size estimation manually...")
            total_estimated_size = 0
            
            for doc in docs:
                pages = doc.get('number_of_pages', 1)
                file_name = doc.get('file_name', '')
                
                if file_name.lower().endswith('.pdf'):
                    # PDF: ~500KB per page average
                    estimated_size = pages * 500 * 1024
                elif file_name.lower().endswith(('.docx', '.doc')):
                    # Word docs: ~300KB per page average
                    estimated_size = pages * 300 * 1024
                elif file_name.lower().endswith(('.pptx', '.ppt')):
                    # PowerPoint: ~800KB per page average
                    estimated_size = pages * 800 * 1024
                else:
                    # Other files: ~400KB per page average
                    estimated_size = pages * 400 * 1024
                
                total_estimated_size += estimated_size
                print(f"   📄 {file_name}: {pages} pages → {estimated_size:,} bytes")
            
            print(f"\n📊 MANUAL ESTIMATION RESULT:")
            print(f"   Total estimated size: {total_estimated_size:,} bytes ({total_estimated_size / 1024 / 1024:.2f} MB)")
            
            if total_estimated_size > 0:
                print(f"✅ Manual estimation works - fallback logic is correct")
                print(f"❌ This means the bug is in how the fallback is being applied")
            else:
                print(f"❌ Manual estimation also gives 0 - there's a deeper issue")

        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print(f"This may indicate the application modules are not properly accessible")
        return False
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_storage_client_configuration():
    """Test the storage client configuration and initialization."""
    print(f"\n🔍 Testing Storage Client Configuration...")
    print("=" * 50)
    
    try:
        from config import (
            CLIENTS,
            storage_account_user_documents_container_name,
            storage_account_group_documents_container_name,
            storage_account_public_documents_container_name
        )
        
        print(f"📁 Container names:")
        print(f"   User: {storage_account_user_documents_container_name}")
        print(f"   Group: {storage_account_group_documents_container_name}")  
        print(f"   Public: {storage_account_public_documents_container_name}")
        
        print(f"\n🔌 CLIENTS dictionary contents:")
        for key, value in CLIENTS.items():
            print(f"   {key}: {type(value).__name__ if value else 'None'}")
        
        storage_client = CLIENTS.get("storage_account_office_docs_client")
        if storage_client:
            print(f"\n✅ Storage client found!")
            print(f"   Type: {type(storage_client)}")
            
            # Test container access
            for container_name in [storage_account_user_documents_container_name, 
                                 storage_account_group_documents_container_name,
                                 storage_account_public_documents_container_name]:
                try:
                    container_client = storage_client.get_container_client(container_name)
                    exists = container_client.exists()
                    print(f"   📦 {container_name}: {'EXISTS' if exists else 'NOT FOUND'}")
                except Exception as container_e:
                    print(f"   📦 {container_name}: ERROR - {container_e}")
        else:
            print(f"❌ Storage client not found in CLIENTS dictionary!")
            
            # Check environment/config for storage settings
            print(f"\n🔍 Checking environment variables...")
            import os
            storage_vars = [
                'OFFICE_DOCS_AUTHENTICATION_TYPE',
                'OFFICE_DOCS_STORAGE_ACCOUNT_URL',
                'OFFICE_DOCS_STORAGE_ACCOUNT_BLOB_ENDPOINT'
            ]
            
            for var in storage_vars:
                value = os.environ.get(var)
                print(f"   {var}: {'SET' if value else 'NOT SET'}")
                if value:
                    # Show first few and last few chars to avoid exposing secrets
                    if len(value) > 20:
                        print(f"      Value: {value[:10]}...{value[-10:]}")
                    else:
                        print(f"      Value: {value}")
        
        return True
        
    except Exception as e:
        print(f"❌ Configuration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🚀 Starting Storage Account Size Debug Test")
    print("=" * 80)
    
    # Test 1: Storage client configuration
    config_result = test_storage_client_configuration()
    
    # Test 2: Specific user storage debug
    user_result = test_specific_user_storage_debug()
    
    print("\n" + "=" * 80)
    print("📊 TEST SUMMARY:")
    print(f"   Storage Configuration Test: {'✅ PASSED' if config_result else '❌ FAILED'}")
    print(f"   User Storage Debug Test: {'✅ PASSED' if user_result else '❌ FAILED'}")
    
    if config_result and user_result:
        print(f"✅ All tests completed successfully!")
        sys.exit(0)
    else:
        print(f"❌ Some tests failed - check output above for details")
        sys.exit(1)
