#!/usr/bin/env python3
"""
Test to verify that the "Find a Group to Join" modal enhancements work correctly.

This test ensures that:
1. The modal is wider (modal-xl instead of modal-lg)
2. The table has the correct columns: Name, Description, Owner, Members, Actions
3. The JavaScript properly renders the new columns
4. The backend API returns owner and member_count data

Enhancement: Added Owner and Members columns to the Find Group modal
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_modal_width_enhancement():
    """Test that the modal has been made wider."""
    print("🔍 Testing modal width enhancement...")
    
    try:
        # Read the my_groups template
        template_path = os.path.join(os.path.dirname(__file__), "../templates/my_groups.html")
        with open(template_path, 'r') as f:
            content = f.read()
        
        # Check for modal-xl class
        if 'modal-xl' in content and 'id="findGroupModal"' in content:
            # Verify it's using modal-xl and not modal-lg
            if 'modal-lg' not in content or content.find('modal-xl') > content.find('modal-lg'):
                print("✅ Modal width enhanced to modal-xl")
                return True
            else:
                print("❌ Modal still using modal-lg instead of modal-xl")
                return False
        else:
            print("❌ modal-xl class not found for findGroupModal")
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_table_columns():
    """Test that the table has the correct column headers."""
    print("🔍 Testing table column headers...")
    
    try:
        # Read the my_groups template
        template_path = os.path.join(os.path.dirname(__file__), "../templates/my_groups.html")
        with open(template_path, 'r') as f:
            content = f.read()
        
        # Check for the correct table headers
        expected_headers = ['Name', 'Description', 'Owner', 'Members', 'Actions']
        
        # Find the globalGroupResultsTable
        table_start = content.find('id="globalGroupResultsTable"')
        if table_start == -1:
            print("❌ globalGroupResultsTable not found")
            return False
        
        # Find the thead section after the table
        thead_start = content.find('<thead>', table_start)
        thead_end = content.find('</thead>', thead_start)
        if thead_start == -1 or thead_end == -1:
            print("❌ Table header section not found")
            return False
        
        thead_content = content[thead_start:thead_end]
        
        # Check if all expected headers are present
        missing_headers = []
        for header in expected_headers:
            if f'<th>{header}</th>' not in thead_content:
                missing_headers.append(header)
        
        if not missing_headers:
            print("✅ All required column headers found: Name, Description, Owner, Members, Actions")
            return True
        else:
            print(f"❌ Missing column headers: {missing_headers}")
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_javascript_rendering():
    """Test that the JavaScript properly handles the new columns."""
    print("🔍 Testing JavaScript rendering function...")
    
    try:
        # Read the my_groups template
        template_path = os.path.join(os.path.dirname(__file__), "../templates/my_groups.html")
        with open(template_path, 'r') as f:
            content = f.read()
        
        # Find the renderGlobalGroupResults function
        function_start = content.find('function renderGlobalGroupResults')
        if function_start == -1:
            print("❌ renderGlobalGroupResults function not found")
            return False
        
        # Find the function end (next function or script end)
        function_end = content.find('function ', function_start + 1)
        if function_end == -1:
            function_end = content.find('</script>', function_start)
        
        function_content = content[function_start:function_end]
        
        # Check for owner and member_count handling
        checks = [
            'g.owner?.displayName',  # Owner column handling
            'g.member_count',        # Member count column handling
            'colspan="5"'            # Updated colspan for error messages
        ]
        
        missing_features = []
        for check in checks:
            if check not in function_content:
                missing_features.append(check)
        
        if not missing_features:
            print("✅ JavaScript properly handles owner and member count columns")
            return True
        else:
            print(f"❌ Missing JavaScript features: {missing_features}")
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_backend_api_enhancement():
    """Test that the backend API returns owner and member_count data."""
    print("🔍 Testing backend API enhancement...")
    
    try:
        # Read the route_backend_groups.py file
        route_file = os.path.join(os.path.dirname(__file__), "../route_backend_groups.py")
        with open(route_file, 'r') as f:
            content = f.read()
        
        # Check for the specific patterns we added
        has_owner = '"owner": g.get("owner", {})' in content
        has_member_count = '"member_count": len(g.get("users", []))' in content
        
        if has_owner and has_member_count:
            print("✅ Backend API returns owner and member_count data")
            return True
        else:
            missing = []
            if not has_owner:
                missing.append("owner field")
            if not has_member_count:
                missing.append("member_count field")
            print(f"❌ Backend API missing: {', '.join(missing)}")
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🧪 Testing Find Group Modal Enhancements...")
    print("=" * 60)
    
    tests = [
        test_modal_width_enhancement,
        test_table_columns,
        test_javascript_rendering,
        test_backend_api_enhancement
    ]
    
    results = []
    
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("✅ All tests passed! Find Group modal enhancements are working correctly.")
        print("\n🎯 Enhancement Summary:")
        print("   • Modal width increased from modal-lg to modal-xl")
        print("   • Added Owner column showing group owner's display name")
        print("   • Added Members column showing current member count")
        print("   • Updated JavaScript to properly render new columns")
        print("   • Backend API enhanced to return owner and member_count data")
    else:
        print("❌ Some tests failed. Please review the enhancements.")
    
    sys.exit(0 if success else 1)
