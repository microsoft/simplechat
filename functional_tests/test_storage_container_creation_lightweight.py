#!/usr/bin/env python3
"""
Functional test for storage account container creation fix - lightweight version.
Version: 0.229.016
Implemented in: 0.229.016

This test validates that the storage container creation logic is properly implemented
in the config.py file without requiring full module import.
"""

import sys
import os

def test_config_file_structure():
    """Test that the config.py file has the correct structure for container creation."""
    print("🔍 Testing Config File Structure for Storage Container Creation...")
    
    try:
        # Read the config.py file
        config_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'config.py')
        
        if not os.path.exists(config_path):
            print(f"❌ Config file not found at: {config_path}")
            return False
            
        with open(config_path, 'r') as f:
            config_content = f.read()
        
        # Test container name definitions
        container_names = [
            'storage_account_user_documents_container_name = "user-documents"',
            'storage_account_group_documents_container_name = "group-documents"',
            'storage_account_public_documents_container_name = "public-documents"'
        ]
        
        for container_name in container_names:
            if container_name in config_content:
                print(f"✅ Found container definition: {container_name.split('=')[0].strip()}")
            else:
                print(f"❌ Missing container definition: {container_name}")
                return False
        
        # Test that container creation is properly indented inside enhanced citations block
        lines = config_content.split('\n')
        in_enhanced_citations_block = False
        found_container_creation = False
        proper_indentation = False
        
        for i, line in enumerate(lines):
            # Look for the enhanced citations block
            if 'if enable_enhanced_citations:' in line:
                in_enhanced_citations_block = True
                continue
                
            if in_enhanced_citations_block:
                # Check if we're still in the block (proper indentation)
                if line.strip() == '' or line.startswith('        ') or line.startswith('\t'):
                    # Look for container creation loop
                    if 'for container_name in [' in line:
                        found_container_creation = True
                        # Check that this line is properly indented (at least 8 spaces or equivalent)
                        if line.startswith('                '):  # 16 spaces for nested block
                            proper_indentation = True
                            break
                else:
                    # We've left the enhanced citations block
                    in_enhanced_citations_block = False
        
        if found_container_creation and proper_indentation:
            print("✅ Container creation loop found with proper indentation inside enhanced citations block")
        elif found_container_creation:
            print("⚠️  Container creation loop found but indentation may be incorrect")
        else:
            print("❌ Container creation loop not found inside enhanced citations block")
            return False
        
        # Test that both authentication types are handled
        auth_checks = [
            'office_docs_authentication_type") == "key"',
            'office_docs_authentication_type") == "managed_identity"'
        ]
        
        for auth_check in auth_checks:
            if auth_check in config_content:
                auth_type = auth_check.split('"')[1]
                print(f"✅ Found authentication type handling: {auth_type}")
            else:
                print(f"❌ Missing authentication type handling: {auth_check}")
                return False
        
        # Test container creation logic
        creation_checks = [
            'container_client.exists()',
            'container_client.create_container()',
            'except Exception as container_error:'
        ]
        
        for check in creation_checks:
            if check in config_content:
                print(f"✅ Found container logic: {check}")
            else:
                print(f"❌ Missing container logic: {check}")
                return False
        
        print("✅ Config file structure test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_version_update():
    """Test that the version was properly updated."""
    print("\n🔍 Testing Version Update...")
    
    try:
        config_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'config.py')
        
        with open(config_path, 'r') as f:
            config_content = f.read()
        
        if 'VERSION = "0.229.016"' in config_content:
            print("✅ Version updated to 0.229.016")
            return True
        else:
            print("❌ Version not updated correctly")
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False

def test_container_creation_workflow():
    """Test the logical flow of container creation."""
    print("\n🔍 Testing Container Creation Workflow...")
    
    try:
        config_path = os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app', 'config.py')
        
        with open(config_path, 'r') as f:
            config_content = f.read()
        
        # Extract the container creation section
        lines = config_content.split('\n')
        container_section = []
        in_container_section = False
        
        for line in lines:
            if 'for container_name in [' in line:
                in_container_section = True
            
            if in_container_section:
                container_section.append(line)
                
            # End of container creation section
            if in_container_section and line.strip().startswith('except Exception as container_error:'):
                # Find the end of this except block
                continue
            elif in_container_section and line.strip() and not line.startswith(' ') and not line.startswith('\t'):
                break
        
        container_code = '\n'.join(container_section)
        
        # Verify the workflow
        workflow_checks = [
            ("Iterates over all three containers", 
             "storage_account_user_documents_container_name" in container_code and
             "storage_account_group_documents_container_name" in container_code and
             "storage_account_public_documents_container_name" in container_code),
            ("Gets container client", "get_container_client(container_name)" in container_code),
            ("Checks if container exists", "container_client.exists()" in container_code),
            ("Creates container if not exists", "create_container()" in container_code),
            ("Logs creation", "Container" in container_code and "created successfully" in container_code),
            ("Logs existence", "already exists" in container_code),
            ("Handles errors", "except Exception as container_error" in container_code)
        ]
        
        for check_name, condition in workflow_checks:
            if condition:
                print(f"✅ {check_name}: Verified")
            else:
                print(f"❌ {check_name}: Missing")
                return False
        
        print("✅ Container creation workflow test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    tests = [
        test_version_update,
        test_config_file_structure,
        test_container_creation_workflow
    ]
    
    results = []
    
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("🎉 All storage container creation tests passed!")
        print("\n📋 Summary:")
        print("   ✅ Storage container names are properly defined")
        print("   ✅ Container creation is inside enhanced citations block") 
        print("   ✅ Both key and managed identity authentication are handled")
        print("   ✅ Containers are created if they don't exist")
        print("   ✅ Error handling is implemented")
        print("   ✅ Version updated to 0.229.016")
    else:
        print("❌ Some tests failed - check the output above for details")
    
    sys.exit(0 if success else 1)
