#!/usr/bin/env python3
# test_public_workspace_storage_fix.py
"""
Test script to verify public workspace storage calculation fix.
Version: 0.230.082
Implemented in: 0.230.082

This script tests the storage calculation logic for public workspaces 
to ensure it matches the group workspace implementation.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Add the parent directory to sys.path to import from the app
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)
sys.path.insert(0, os.path.join(parent_dir, 'application', 'single_app'))

def test_storage_calculation_comparison():
    """Compare storage calculation between groups and public workspaces."""
    print("🔍 Testing Storage Calculation Comparison...")
    
    try:
        # Import required modules
        from route_backend_control_center import enhance_public_workspace_with_activity, enhance_group_with_activity
        import inspect
        
        print("✅ Successfully imported enhancement functions")
        
        # Test 1: Compare storage calculation logic
        print("\n🧪 Test 1: Compare storage calculation patterns")
        
        try:
            # Get source code
            public_source = inspect.getsource(enhance_public_workspace_with_activity)
            group_source = inspect.getsource(enhance_group_with_activity)
            
            # Check that both have storage client retrieval
            assert "storage_account_office_docs_client" in public_source, "Public workspace missing storage client retrieval"
            assert "storage_account_office_docs_client" in group_source, "Group missing storage client retrieval"
            
            # Check blob listing patterns
            assert "list_blobs(name_starts_with=" in public_source, "Public workspace missing blob listing"
            assert "list_blobs(name_starts_with=" in group_source, "Group missing blob listing"
            
            print("✅ Both functions have storage client and blob listing logic")
            
        except Exception as storage_pattern_e:
            print(f"❌ Storage pattern test failed: {storage_pattern_e}")
            return False
        
        # Test 2: Compare folder prefix patterns
        print("\n🧪 Test 2: Compare folder prefix patterns")
        
        try:
            # Check folder prefix patterns
            # Groups should use: group_id/
            # Public workspaces should use: workspace_id/ (not public/workspace_id/)
            
            assert 'f"{group_id}/"' in group_source, "Group should use group_id/ as prefix"
            assert 'f"{workspace_id}/"' in public_source, "Public workspace should use workspace_id/ as prefix"
            
            # Ensure old incorrect pattern is not present
            assert 'f"public/{workspace_id}/"' not in public_source, "Public workspace should not use public/ prefix"
            
            print("✅ Folder prefix patterns are correct")
            
        except Exception as prefix_e:
            print(f"❌ Folder prefix test failed: {prefix_e}")
            return False
        
        # Test 3: Compare fallback estimation logic
        print("\n🧪 Test 3: Compare fallback estimation logic")
        
        try:
            # Check that both have file type based estimation
            file_type_patterns = [
                ".pdf",
                ".docx",
                ".doc", 
                ".pptx",
                ".ppt"
            ]
            
            for pattern in file_type_patterns:
                assert pattern in public_source, f"Public workspace missing {pattern} handling"
                assert pattern in group_source, f"Group missing {pattern} handling"
            
            # Check size estimation values
            size_patterns = [
                "500 * 1024",  # PDF estimation
                "300 * 1024",  # Word estimation  
                "800 * 1024",  # PowerPoint estimation
                "400 * 1024"   # Default estimation
            ]
            
            for pattern in size_patterns:
                assert pattern in public_source, f"Public workspace missing size pattern {pattern}"
                assert pattern in group_source, f"Group missing size pattern {pattern}"
            
            print("✅ Fallback estimation logic is consistent")
            
        except Exception as fallback_e:
            print(f"❌ Fallback estimation test failed: {fallback_e}")
            return False
        
        # Test 4: Compare error handling
        print("\n🧪 Test 4: Compare error handling patterns")
        
        try:
            # Check error handling patterns
            error_patterns = [
                "except Exception as storage_e:",
                "enhanced['activity']['document_metrics']['storage_account_size'] = 0",
                "enhanced['storage_size'] = 0"
            ]
            
            for pattern in error_patterns:
                assert pattern in public_source, f"Public workspace missing error handling: {pattern}"
                assert pattern in group_source, f"Group missing error handling: {pattern}"
            
            print("✅ Error handling patterns are consistent")
            
        except Exception as error_e:
            print(f"❌ Error handling test failed: {error_e}")
            return False
        
        # Test 5: Compare container usage
        print("\n🧪 Test 5: Compare container usage")
        
        try:
            # Check container usage
            assert "storage_account_public_documents_container_name" in public_source, "Public workspace should use public container"
            assert "storage_account_group_documents_container_name" in group_source, "Group should use group container"
            
            print("✅ Container usage is correct for each workspace type")
            
        except Exception as container_e:
            print(f"❌ Container usage test failed: {container_e}")
            return False
        
        print("\n📊 Test Summary:")
        print("   ✅ Storage client retrieval logic matches")
        print("   ✅ Folder prefix patterns corrected (no public/ prefix)")
        print("   ✅ Fallback estimation logic consistent")
        print("   ✅ Error handling patterns match")
        print("   ✅ Container usage appropriate for workspace type")
        
        print("\n🎯 Key Fixes Applied:")
        print("   • Fixed folder prefix from 'public/{workspace_id}/' to '{workspace_id}/'")
        print("   • Added file-type based size estimation fallback")
        print("   • Improved error handling with 0 byte fallback")
        print("   • Consistent blob enumeration logic")
        
        print("\n✅ All storage calculation comparison tests passed!")
        
        print("\n🔧 Expected Results:")
        print("   • Public workspaces should now show actual storage sizes")
        print("   • Fallback estimation should work when Azure Storage unavailable")
        print("   • Error handling prevents crashes on storage access issues")
        print("   • Debug logging shows storage calculation progress")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_storage_calculation_comparison()
    sys.exit(0 if success else 1)