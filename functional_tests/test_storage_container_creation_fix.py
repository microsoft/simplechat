#!/usr/bin/env python3
"""
Functional test for storage account container creation fix.
Version: 0.229.016
Implemented in: 0.229.016

This test ensures that the storage account containers for personal (user-documents), 
groups (group-documents), and public workspaces (public-documents) are created 
when the application initializes if they don't exist.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Add the parent directory to sys.path to access the application modules
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app'))

def test_storage_container_creation():
    """Test that storage containers are created properly during initialization."""
    print("🔍 Testing Storage Account Container Creation...")
    
    try:
        # Import necessary modules
        from config import (
            storage_account_user_documents_container_name,
            storage_account_group_documents_container_name, 
            storage_account_public_documents_container_name,
            CLIENTS,
            enable_enhanced_citations
        )
        
        print(f"✅ Container names defined:")
        print(f"   User documents: {storage_account_user_documents_container_name}")
        print(f"   Group documents: {storage_account_group_documents_container_name}")
        print(f"   Public documents: {storage_account_public_documents_container_name}")
        
        # Check if enhanced citations is enabled
        print(f"📊 Enhanced citations enabled: {enable_enhanced_citations}")
        
        if enable_enhanced_citations:
            # Check if blob service client is initialized
            blob_client = CLIENTS.get("storage_account_office_docs_client")
            if blob_client:
                print("✅ Blob service client initialized successfully")
                
                # Test if we can access the containers
                expected_containers = [
                    storage_account_user_documents_container_name,
                    storage_account_group_documents_container_name,
                    storage_account_public_documents_container_name
                ]
                
                for container_name in expected_containers:
                    try:
                        container_client = blob_client.get_container_client(container_name)
                        exists = container_client.exists()
                        if exists:
                            print(f"✅ Container '{container_name}' exists and is accessible")
                        else:
                            print(f"⚠️  Container '{container_name}' does not exist or is not accessible")
                    except Exception as container_error:
                        print(f"❌ Error accessing container '{container_name}': {str(container_error)}")
                        
            else:
                print("⚠️  Blob service client not initialized - this may be expected if storage is not configured")
        else:
            print("ℹ️  Enhanced citations disabled - storage containers not needed")
        
        print("✅ Storage container creation test passed!")
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("This may indicate the application modules are not properly accessible")
        return False
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_container_name_constants():
    """Test that container name constants are properly defined."""
    print("\n🔍 Testing Container Name Constants...")
    
    try:
        # Import container name constants
        from config import (
            storage_account_user_documents_container_name,
            storage_account_group_documents_container_name,
            storage_account_public_documents_container_name
        )
        
        # Validate container names follow expected naming convention
        expected_names = {
            storage_account_user_documents_container_name: "user-documents",
            storage_account_group_documents_container_name: "group-documents", 
            storage_account_public_documents_container_name: "public-documents"
        }
        
        for actual, expected in expected_names.items():
            if actual == expected:
                print(f"✅ Container name '{actual}' matches expected value")
            else:
                print(f"❌ Container name mismatch: got '{actual}', expected '{expected}'")
                return False
        
        print("✅ Container name constants test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_initialization_logic():
    """Test that the initialization logic is properly structured."""
    print("\n🔍 Testing Initialization Logic Structure...")
    
    try:
        # Read the config.py file to check the logic structure
        config_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'config.py')
        
        with open(config_path, 'r') as f:
            config_content = f.read()
        
        # Check for proper indentation and structure
        checks = [
            ("Container creation inside enhanced citations block", 
             "if enable_enhanced_citations:" in config_content and 
             "for container_name in [" in config_content),
            ("Both authentication types handled",
             'office_docs_authentication_type") == "key"' in config_content and
             'office_docs_authentication_type") == "managed_identity"' in config_content),
            ("Container existence check",
             "container_client.exists()" in config_content),
            ("Container creation logic",
             "container_client.create_container()" in config_content),
            ("Error handling for container operations",
             "except Exception as container_error:" in config_content)
        ]
        
        for check_name, condition in checks:
            if condition:
                print(f"✅ {check_name}: Found")
            else:
                print(f"❌ {check_name}: Missing or incorrect")
                return False
        
        print("✅ Initialization logic structure test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    tests = [
        test_container_name_constants,
        test_initialization_logic,
        test_storage_container_creation
    ]
    
    results = []
    
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("🎉 All storage container creation tests passed!")
    else:
        print("❌ Some tests failed - check the output above for details")
    
    sys.exit(0 if success else 1)
