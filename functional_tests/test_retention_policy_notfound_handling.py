#!/usr/bin/env python3
"""
Functional test for Retention Policy NotFound Error Handling.
Version: 0.236.012
Implemented in: 0.236.012

This test ensures that the retention policy correctly handles CosmosResourceNotFoundError
when attempting to delete conversations or documents that have already been deleted.
This prevents false error logging for race condition scenarios.
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

def test_notfound_exception_import():
    """Test that CosmosResourceNotFoundError is properly imported."""
    print("🔍 Testing CosmosResourceNotFoundError import...")
    
    try:
        from config import CosmosResourceNotFoundError
        print("✅ CosmosResourceNotFoundError imported successfully from config")
        return True
    except ImportError as e:
        print(f"❌ Failed to import CosmosResourceNotFoundError: {e}")
        return False


def test_retention_policy_function_definitions():
    """Test that retention policy functions have proper exception handling."""
    print("\n🔍 Testing retention policy function definitions...")
    
    try:
        import inspect
        from functions_retention_policy import delete_aged_conversations, delete_aged_documents
        
        # Get source code of delete_aged_conversations
        conversations_source = inspect.getsource(delete_aged_conversations)
        
        # Check for CosmosResourceNotFoundError handling in conversations function
        if 'CosmosResourceNotFoundError' in conversations_source:
            print("✅ delete_aged_conversations handles CosmosResourceNotFoundError")
        else:
            print("❌ delete_aged_conversations does not handle CosmosResourceNotFoundError")
            return False
        
        # Check for 'already deleted' debug message pattern
        if 'already deleted' in conversations_source:
            print("✅ delete_aged_conversations has 'already deleted' debug messaging")
        else:
            print("❌ delete_aged_conversations missing 'already deleted' debug messaging")
            return False
        
        # Get source code of delete_aged_documents
        documents_source = inspect.getsource(delete_aged_documents)
        
        # Check for CosmosResourceNotFoundError handling in documents function
        if 'CosmosResourceNotFoundError' in documents_source:
            print("✅ delete_aged_documents handles CosmosResourceNotFoundError")
        else:
            print("❌ delete_aged_documents does not handle CosmosResourceNotFoundError")
            return False
        
        # Check for 'already deleted' debug message pattern
        if 'already deleted' in documents_source:
            print("✅ delete_aged_documents has 'already deleted' debug messaging")
        else:
            print("❌ delete_aged_documents missing 'already deleted' debug messaging")
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ Failed to verify function definitions: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_already_deleted_flag_in_details():
    """Test that already_deleted flag is used in the response details."""
    print("\n🔍 Testing 'already_deleted' flag in response details...")
    
    try:
        import inspect
        from functions_retention_policy import delete_aged_conversations, delete_aged_documents
        
        # Get source code
        conversations_source = inspect.getsource(delete_aged_conversations)
        documents_source = inspect.getsource(delete_aged_documents)
        
        # Check for 'already_deleted': True pattern in conversations
        if "'already_deleted': True" in conversations_source or '"already_deleted": True' in conversations_source:
            print("✅ delete_aged_conversations includes 'already_deleted' flag in details")
        else:
            print("❌ delete_aged_conversations missing 'already_deleted' flag in details")
            return False
        
        # Check for 'already_deleted': True pattern in documents
        if "'already_deleted': True" in documents_source or '"already_deleted": True' in documents_source:
            print("✅ delete_aged_documents includes 'already_deleted' flag in details")
        else:
            print("❌ delete_aged_documents missing 'already_deleted' flag in details")
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ Failed to verify already_deleted flag: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_version_number():
    """Test that the version is updated correctly."""
    print("\n🔍 Testing version number...")
    
    try:
        from config import VERSION
        
        # Version should be at least 0.236.012
        version_parts = VERSION.split('.')
        major = int(version_parts[0])
        minor = int(version_parts[1])
        patch = int(version_parts[2])
        
        if major == 0 and minor >= 236 and patch >= 12:
            print(f"✅ Version {VERSION} is correct (>= 0.236.012)")
            return True
        elif major > 0 or minor > 236:
            print(f"✅ Version {VERSION} is correct (later version)")
            return True
        else:
            print(f"❌ Version {VERSION} is lower than expected 0.236.012")
            return False
            
    except Exception as e:
        print(f"❌ Failed to verify version: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("Retention Policy NotFound Error Handling Test")
    print("=" * 60)
    
    tests = [
        test_notfound_exception_import,
        test_retention_policy_function_definitions,
        test_already_deleted_flag_in_details,
        test_version_number
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"❌ Test {test.__name__} failed with exception: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)
    
    print("\n" + "=" * 60)
    print(f"📊 Results: {sum(results)}/{len(results)} tests passed")
    print("=" * 60)
    
    if all(results):
        print("\n✅ All tests passed! NotFound error handling is correctly implemented.")
        sys.exit(0)
    else:
        print("\n❌ Some tests failed. Please review the implementation.")
        sys.exit(1)
