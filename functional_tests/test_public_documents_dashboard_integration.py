#!/usr/bin/env python3
"""
Functional test for public documents dashboard integration.
Version: 0.230.083
Implemented in: 0.230.083

This test verifies that public workspace documents are properly integrated 
into the dashboard activity trends with appropriate color differentiation.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Add the parent directory to sys.path to import from the app
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)
sys.path.insert(0, os.path.join(parent_dir, 'application', 'single_app'))

def test_public_documents_dashboard_integration():
    """Test that public documents are integrated into dashboard charts."""
    print("🔍 Testing Public Documents Dashboard Integration...")
    
    try:
        # Import required modules  
        import inspect
        
        # Test 1: Check backend activity trends structure
        print("\n🧪 Test 1: Verify backend activity trends structure")
        
        try:
            from route_backend_control_center import get_activity_trends
            
            # Check the source code for proper structure
            source = inspect.getsource(get_activity_trends)
            
            # Verify public_documents is tracked separately
            assert "'public_documents': 0" in source, "Backend should track public_documents separately"
            assert "('public_documents', cosmos_public_documents_container, 'public_documents')" in source, "Backend should map public container to public_documents category"
            
            # Ensure it's not treated as personal anymore
            assert "('public_documents', cosmos_public_documents_container, 'personal_documents')" not in source, "Backend should not treat public as personal documents"
            
            print("✅ Backend properly tracks public documents separately")
            
        except Exception as backend_e:
            print(f"❌ Backend structure test failed: {backend_e}")
            return False
        
        # Test 2: Check frontend chart integration 
        print("\n🧪 Test 2: Verify frontend chart integration")
        
        try:
            # Read the frontend JavaScript file
            js_file_path = os.path.join(parent_dir, 'application', 'single_app', 'static', 'js', 'control-center.js')
            
            with open(js_file_path, 'r', encoding='utf-8') as f:
                js_source = f.read()
            
            # Check that frontend expects public documents data
            assert "activityData.public_documents" in js_source, "Frontend should log public_documents data"
            assert "public: activityData.public_documents" in js_source, "Frontend should pass public documents to chart"
            
            # Check date range calculation includes public
            assert "publicDates = Object.keys(documentsData.public" in js_source, "Frontend should include public dates"
            assert "...publicDates" in js_source, "Frontend should merge public dates with others"
            
            # Check data preparation includes public
            assert "publicData = allDates.map(date => (documentsData.public" in js_source, "Frontend should prepare public data"
            
            print("✅ Frontend properly integrates public documents data")
            
        except Exception as frontend_e:
            print(f"❌ Frontend integration test failed: {frontend_e}")
            return False
        
        # Test 3: Verify color scheme differentiation
        print("\n🧪 Test 3: Verify green color scheme differentiation")
        
        try:
            # Check that all three green shades are defined
            color_patterns = [
                "rgba(144, 238, 144, 0.4)",  # Light green for Personal
                "rgba(34, 139, 34, 0.4)",    # Medium green for Group  
                "rgba(0, 100, 0, 0.4)"       # Dark green for Public
            ]
            
            border_patterns = [
                "#90EE90",  # Light green border for Personal
                "#228B22",  # Medium green border for Group
                "#006400"   # Dark green border for Public
            ]
            
            for pattern in color_patterns:
                assert pattern in js_source, f"Missing color pattern: {pattern}"
            
            for pattern in border_patterns:
                assert pattern in js_source, f"Missing border color: {pattern}"
            
            # Check labels
            assert "label: 'Personal'" in js_source, "Missing Personal label"
            assert "label: 'Group'" in js_source, "Missing Group label" 
            assert "label: 'Public'" in js_source, "Missing Public label"
            
            print("✅ Color scheme properly differentiated")
            print("   • Personal: Light Green (#90EE90)")
            print("   • Group: Medium Green (#228B22)")
            print("   • Public: Dark Green (#006400)")
            
        except Exception as color_e:
            print(f"❌ Color scheme test failed: {color_e}")
            return False
        
        # Test 4: Verify chart structure consistency
        print("\n🧪 Test 4: Verify chart structure consistency")
        
        try:
            # Check that all datasets have consistent properties
            dataset_properties = [
                "backgroundColor:",
                "borderColor:",
                "borderWidth: 2",
                "fill: false",
                "tension: 0.1"
            ]
            
            for prop in dataset_properties:
                count = js_source.count(prop)
                assert count >= 3, f"Property {prop} should appear at least 3 times (once per dataset), found {count}"
            
            print("✅ Chart structure is consistent across all datasets")
            
        except Exception as structure_e:
            print(f"❌ Chart structure test failed: {structure_e}")
            return False
        
        print("\n📊 Test Summary:")
        print("   ✅ Backend tracks public documents separately")
        print("   ✅ Frontend integrates public documents data")  
        print("   ✅ Three differentiated green colors implemented")
        print("   ✅ Chart structure consistent across datasets")
        
        print("\n🎯 Integration Features:")
        print("   • Public documents counted separately from personal/group")
        print("   • Three-tier green color scheme for visual differentiation")
        print("   • Date range calculation includes all document types")
        print("   • Consistent chart properties and styling")
        
        print("\n✅ All public documents dashboard integration tests passed!")
        
        print("\n📈 Expected Dashboard Behavior:")
        print("   • Documents chart shows three lines: Personal, Group, Public")
        print("   • Public documents appear in dark green (#006400)")
        print("   • Legend differentiates between all three document types")
        print("   • Activity trends include public workspace document uploads")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_public_documents_dashboard_integration()
    sys.exit(0 if success else 1)