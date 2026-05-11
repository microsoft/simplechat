#!/usr/bin/env python3
"""
Functional test for workflow PDF viewer height layout fix.
Version: 0.229.069
Implemented in: 0.229.069

This test ensures that the PDF viewer takes up the full height of the left pane
by using proper flexbox layout and container styling.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_pdf_viewer_height_layout():
    """Test that PDF viewer uses proper flexbox layout for full height."""
    print("🔍 Testing PDF viewer height layout...")
    
    try:
        template_path = os.path.join('..', 'application', 'single_app', 'templates', 'workflow_summary_view.html')
        
        with open(template_path, 'r') as f:
            content = f.read()
        
        # Check for left-pane flexbox setup
        if 'display: flex;' in content and 'flex-direction: column;' in content:
            print("   ✅ Left-pane uses flexbox layout")
        else:
            print("   ❌ Left-pane missing flexbox layout")
            return False
        
        # Check for pdfContainer CSS
        if '#pdfContainer {' in content:
            print("   ✅ Has pdfContainer CSS definition")
        else:
            print("   ❌ Missing pdfContainer CSS definition")
            return False
        
        # Check for pdfContainer flex properties
        container_start = content.find('#pdfContainer {')
        container_section = content[container_start:container_start + 500]
        
        if 'flex: 1;' in container_section:
            print("   ✅ pdfContainer has flex: 1 to take available space")
        else:
            print("   ❌ pdfContainer missing flex: 1 property")
            return False
        
        if 'min-height: 0;' in container_section:
            print("   ✅ pdfContainer has min-height: 0 for proper flex behavior")
        else:
            print("   ❌ pdfContainer missing min-height: 0 property")
            return False
        
        # Check for updated PDF viewer CSS
        viewer_start = content.find('.pdf-viewer {')
        viewer_section = content[viewer_start:viewer_start + 300]
        
        if 'height: 100%;' in viewer_section and 'flex: 1;' in viewer_section:
            print("   ✅ PDF viewer uses height: 100% and flex: 1")
        else:
            print("   ❌ PDF viewer missing proper height/flex properties")
            return False
        
        # Check that old calc() height is removed
        if 'height: calc(100% - 60px);' in content:
            print("   ❌ Still uses old calc() height instead of flexbox")
            return False
        else:
            print("   ✅ No longer uses problematic calc() height")
        
        # Check for header flex-shrink
        if 'flex-shrink: 0;' in content:
            print("   ✅ Header has flex-shrink: 0 to maintain size")
        else:
            print("   ❌ Header missing flex-shrink: 0 property")
            return False
        
        return True
        
    except Exception as e:
        print(f"   ❌ Error checking PDF viewer height layout: {e}")
        return False

def test_version_update():
    """Test that version was updated after the fix."""
    print("🔍 Testing version update...")
    
    try:
        config_path = os.path.join('..', 'application', 'single_app', 'config.py')
        
        with open(config_path, 'r') as f:
            content = f.read()
        
        if 'VERSION = "0.229.069"' in content:
            print("   ✅ Version updated to 0.229.069")
            return True
        else:
            print("   ❌ Version not updated properly")
            return False
            
    except Exception as e:
        print(f"   ❌ Error checking version: {e}")
        return False

def run_height_layout_tests():
    """Run PDF viewer height layout fix tests."""
    print("🧪 Running PDF Viewer Height Layout Fix Tests")
    print("=" * 55)
    
    tests = [
        test_pdf_viewer_height_layout,
        test_version_update
    ]
    
    results = []
    for test in tests:
        print(f"\n🔬 {test.__name__.replace('test_', '').replace('_', ' ').title()}:")
        results.append(test())
    
    success_count = sum(results)
    total_count = len(results)
    
    print(f"\n📊 Test Results: {success_count}/{total_count} tests passed")
    
    if success_count == total_count:
        print("✅ PDF viewer height layout fix validated successfully!")
        return True
    else:
        print("❌ Some tests failed - fix may be incomplete")
        return False

if __name__ == "__main__":
    success = run_height_layout_tests()
    sys.exit(0 if success else 1)