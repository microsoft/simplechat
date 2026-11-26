#!/usr/bin/env python3
# test_storage_fallback_isolation.py
"""
Focused test to isolate the storage account sizing bug.
This will test the exact code path that should execute when enhanced citations is enabled
but storage client is not configured.
Version: 0.261.474
Implemented in: 0.230.034
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app'))

def test_fallback_logic_isolation():
    """Test the fallback storage calculation logic in isolation."""
    print("🔍 Testing Storage Account Fallback Logic Isolation")
    print("=" * 60)
    
    test_user_id = "07e61033-ea1a-4472-a1e7-6b9ac874984a"
    
    try:
        from config import cosmos_user_documents_container, CLIENTS
        
        # Step 1: Verify storage client is not available
        storage_client = CLIENTS.get("storage_account_office_docs_client")
        print(f"📊 Storage client available: {storage_client is not None}")
        
        if storage_client:
            print("❌ Test invalid - storage client is available")
            return False
        
        # Step 2: Query documents exactly as the production code does
        print(f"\n🔍 Querying documents for user {test_user_id}...")
        
        doc_metrics_params = [{"name": "@user_id", "value": test_user_id}]
        
        storage_size_query = """
            SELECT c.file_name, c.number_of_pages FROM c 
            WHERE c.user_id = @user_id AND c.type = 'document_metadata'
        """
        
        storage_docs = list(cosmos_user_documents_container.query_items(
            query=storage_size_query,
            parameters=doc_metrics_params,
            enable_cross_partition_query=True
        ))
        
        print(f"📊 Documents retrieved: {len(storage_docs)}")
        
        # Step 3: Calculate storage size exactly as production code does
        total_storage_size = 0
        for doc in storage_docs:
            # Estimate file size based on pages and file type
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
            
            total_storage_size += estimated_size
            print(f"   📄 {file_name}: {pages} pages → {estimated_size:,} bytes")
        
        print(f"\n📊 FALLBACK CALCULATION RESULT:")
        print(f"   Total estimated size: {total_storage_size:,} bytes ({total_storage_size / 1024 / 1024:.2f} MB)")
        
        if total_storage_size > 0:
            print(f"✅ Fallback calculation works in isolation!")
            print(f"❌ The bug must be in the enhance_user_with_activity function itself")
        else:
            print(f"❌ Fallback calculation fails even in isolation")
        
        return total_storage_size > 0
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_production_code_path():
    """Test the exact production code path with detailed logging."""
    print(f"\n🔍 Testing Production Code Path")
    print("=" * 40)
    
    test_user_id = "07e61033-ea1a-4472-a1e7-6b9ac874984a"
    
    try:
        from config import CLIENTS, storage_account_user_documents_container_name, cosmos_user_documents_container
        
        # Create mock user exactly as the test suggests
        mock_user = {
            'id': test_user_id,
            'name': 'Test User',
            'email': f'{test_user_id}@test.com',
            'settings': {
                'enable_enhanced_citation': True
            }
        }
        
        print(f"📊 Mock user created with enhanced citations enabled")
        
        # Step 1: Check what enhanced['activity']['document_metrics']['enhanced_citation_enabled'] would be
        enhanced_citation_enabled = mock_user.get('settings', {}).get('enable_enhanced_citation', False)
        print(f"📊 Enhanced citation enabled: {enhanced_citation_enabled}")
        
        # Step 2: Check storage client availability
        storage_client = CLIENTS.get("storage_account_office_docs_client")
        print(f"📊 Storage client available: {storage_client is not None}")
        
        # Step 3: Simulate the exact code path from the production function
        if enhanced_citation_enabled:
            print(f"✅ Enhanced citations enabled - entering storage calculation")
            
            try:
                if storage_client:
                    print(f"✅ Storage client available - would calculate actual size")
                else:
                    print(f"❌ Storage client not available - entering fallback")
                    
                    # This is the exact fallback code
                    doc_metrics_params = [{"name": "@user_id", "value": test_user_id}]
                    
                    storage_size_query = """
                        SELECT c.file_name, c.number_of_pages FROM c 
                        WHERE c.user_id = @user_id AND c.type = 'document_metadata'
                    """
                    storage_docs = list(cosmos_user_documents_container.query_items(
                        query=storage_size_query,
                        parameters=doc_metrics_params,
                        enable_cross_partition_query=True
                    ))
                    
                    total_storage_size = 0
                    for doc in storage_docs:
                        # Estimate file size based on pages and file type
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
                        
                        total_storage_size += estimated_size
                    
                    print(f"📊 Fallback calculated: {total_storage_size:,} bytes ({total_storage_size / 1024 / 1024:.2f} MB)")
                    
                    if total_storage_size > 0:
                        print(f"✅ Fallback logic works correctly!")
                        print(f"❌ Bug must be elsewhere in the code")
                    else:
                        print(f"❌ Fallback logic returns 0 - this is the bug!")
                        
                    return total_storage_size
                    
            except Exception as storage_e:
                print(f"❌ Exception in storage calculation: {storage_e}")
                print(f"🔍 This might be where the bug is!")
                import traceback
                traceback.print_exc()
                return 0
                
        else:
            print(f"❌ Enhanced citations not enabled - would not calculate storage")
            return 0
        
    except Exception as e:
        print(f"❌ Production code path test failed: {e}")
        import traceback
        traceback.print_exc()
        return 0

if __name__ == "__main__":
    print("🚀 Starting Storage Account Fallback Logic Test")
    print("=" * 60)
    
    # Test 1: Isolated fallback logic
    fallback_result = test_fallback_logic_isolation()
    
    # Test 2: Production code path
    production_result = test_production_code_path()
    
    print("\n" + "=" * 60)
    print("📊 TEST SUMMARY:")
    print(f"   Fallback Logic Test: {'✅ PASSED' if fallback_result else '❌ FAILED'}")
    print(f"   Production Code Test: {'✅ PASSED' if production_result > 0 else '❌ FAILED'}")
    
    if fallback_result and production_result > 0:
        print(f"✅ All fallback tests passed!")
        print(f"🔍 The bug is likely in the enhance_user_with_activity function integration")
    else:
        print(f"❌ Fallback logic has issues - root cause identified")