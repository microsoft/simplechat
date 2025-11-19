#!/usr/bin/env python3
"""
Functional test for public workspace field name fix.
Version: 0.230.081
Implemented in: 0.230.081

This test verifies that public workspace metrics properly use public_workspace_id 
field name to match the actual document structure in cosmos DB.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Add the parent directory to sys.path to import from the app
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)
sys.path.insert(0, os.path.join(parent_dir, 'application', 'single_app'))

def test_public_workspace_field_name_fix():
    """Test that public workspace queries use correct field names."""
    print("🔍 Testing Public Workspace Field Name Fix...")
    
    try:
        # Import required modules
        from route_backend_control_center import enhance_public_workspace_with_activity
        import inspect
        
        print("✅ Successfully imported enhancement function")
        
        # Test 1: Verify queries use public_workspace_id
        print("\n🧪 Test 1: Verify field name usage in queries")
        
        try:
            # Get the source code of the function
            source = inspect.getsource(enhance_public_workspace_with_activity)
            
            # Check that all queries use public_workspace_id
            expected_patterns = [
                "c.public_workspace_id = @workspace_id",
                "WHERE c.public_workspace_id = @workspace_id"
            ]
            
            for pattern in expected_patterns:
                assert pattern in source, f"Pattern '{pattern}' not found in function source"
            
            # Ensure old incorrect pattern is NOT present
            incorrect_patterns = [
                "c.workspace_id = @workspace_id"
            ]
            
            for pattern in incorrect_patterns:
                assert pattern not in source, f"Incorrect pattern '{pattern}' still found in function source"
            
            print("✅ All queries use correct field name: public_workspace_id")
            
        except Exception as field_e:
            print(f"❌ Field name test failed: {field_e}")
            return False
        
        # Test 2: Verify function structure for cosmos query patterns
        print("\n🧪 Test 2: Verify cosmos query patterns")
        
        try:
            # Check that function has the right query patterns
            queries_to_check = [
                "SELECT VALUE COUNT(1) FROM c WHERE c.public_workspace_id",
                "SELECT VALUE SUM(c.number_of_pages) FROM c",
                "SELECT c.upload_date FROM c WHERE c.public_workspace_id"
            ]
            
            for query_pattern in queries_to_check:
                assert query_pattern in source, f"Query pattern '{query_pattern}' not found"
            
            print("✅ All expected query patterns found")
            
        except Exception as query_e:
            print(f"❌ Query pattern test failed: {query_e}")
            return False
        
        # Test 3: Check debug logging improvements
        print("\n🧪 Test 3: Verify debug logging patterns")
        
        try:
            debug_patterns = [
                "PUBLIC WORKSPACE DEBUG",
                "PUBLIC WORKSPACE BASIC DEBUG", 
                "PUBLIC WORKSPACE STORAGE DEBUG"
            ]
            
            for pattern in debug_patterns:
                assert pattern in source, f"Debug pattern '{pattern}' not found"
            
            print("✅ Debug logging patterns found")
            
        except Exception as debug_e:
            print(f"❌ Debug logging test failed: {debug_e}")
            return False
        
        # Test 4: Verify parameter consistency
        print("\n🧪 Test 4: Verify parameter name consistency")
        
        try:
            # Check that all parameter references are consistent
            param_count = source.count("@workspace_id")
            param_def_count = source.count('"@workspace_id"')
            
            # Should have multiple parameter definitions (one per query)
            assert param_def_count >= 4, f"Expected at least 4 parameter definitions, found {param_def_count}"
            
            # Should have matching parameter usage in queries
            assert param_count >= param_def_count, f"Parameter usage count ({param_count}) should be >= definitions ({param_def_count})"
            
            print(f"✅ Parameter consistency verified: {param_def_count} definitions, {param_count} total uses")
            
        except Exception as param_e:
            print(f"❌ Parameter consistency test failed: {param_e}")
            return False
        
        print("\n📊 Test Summary:")
        print("   ✅ Field name corrected to public_workspace_id")
        print("   ✅ All cosmos queries updated consistently")  
        print("   ✅ Debug logging patterns maintained")
        print("   ✅ Parameter names consistent across queries")
        
        print("\n🎯 Key Fix Applied:")
        print("   • Changed c.workspace_id → c.public_workspace_id in all queries")
        print("   • Matches actual cosmos document structure")
        print("   • Should now properly count documents in public workspaces")
        print("   • Fixed document count, AI search size, and storage calculations")
        
        print("\n✅ All public workspace field name fix tests passed!")
        
        print("\n🔧 Next Steps:")
        print("   1. Clear cached metrics to force fresh calculation")
        print("   2. Access control center to see updated metrics")
        print("   3. Verify public workspace shows correct document counts")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_public_workspace_field_name_fix()
    sys.exit(0 if success else 1)