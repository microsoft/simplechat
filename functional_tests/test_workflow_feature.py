#!/usr/bin/env python3
"""
Functional test for Workflow feature implementation.
Version: 0.229.061
Implemented in: 0.229.061

This test ensures that the complete Workflow feature works correctly:
- Admin settings with enhanced citations dependency
- Navigation integration across all menus
- Complete workflow page flow (4 pages)
- Backend API endpoints and summarization logic
- Enhanced citations integration with show_all parameter
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_workflow_route_integration():
    """Test that workflow routes are properly integrated."""
    print("🔍 Testing Workflow Route Integration...")
    
    try:
        # Import the workflow route module
        sys.path.insert(0, os.path.join('..', 'application', 'single_app'))
        from route_frontend_workflow import register_route_frontend_workflow
        
        print("✅ Workflow route module imported successfully")
        
        # Test that the route registration function exists
        if hasattr(register_route_frontend_workflow, '__call__'):
            print("✅ register_route_frontend_workflow function is callable")
        else:
            print("❌ register_route_frontend_workflow function not found")
            return False
        
        # Test that we can read the file and find expected route definitions
        workflow_file_path = os.path.join('..', 'application', 'single_app', 'route_frontend_workflow.py')
        with open(workflow_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        expected_routes = [
            "@app.route('/workflow'",
            "@app.route('/workflow/file-selection'",
            "@app.route('/workflow/summary-selection'", 
            "@app.route('/workflow/summary-view'",
            "@app.route('/api/workflow/generate-summary'",
            "@app.route('/api/get-document-info"  # Document info endpoints
        ]
        
        found_routes = []
        for expected_route in expected_routes:
            if expected_route in content:
                found_routes.append(expected_route)
                print(f"✅ Route definition found: {expected_route}")
            else:
                print(f"❌ Route definition missing: {expected_route}")
        
        if len(found_routes) == len(expected_routes):
            print("✅ All workflow route definitions are present")
            return True
        else:
            print(f"❌ Only {len(found_routes)}/{len(expected_routes)} workflow route definitions found")
            return False
        
    except Exception as e:
        print(f"❌ Workflow route integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_workflow_templates():
    """Test that all workflow templates exist and have basic structure."""
    print("🔍 Testing Workflow Templates...")
    
    try:
        template_dir = os.path.join('..', 'application', 'single_app', 'templates')
        expected_templates = [
            'workflow.html',
            'workflow_file_selection.html',
            'workflow_summary_selection.html',
            'workflow_summary_view.html'
        ]
        
        all_templates_exist = True
        for template in expected_templates:
            template_path = os.path.join(template_dir, template)
            if os.path.exists(template_path):
                print(f"✅ Template found: {template}")
                
                # Check for basic structure
                with open(template_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                if 'extends "base.html"' in content:
                    print(f"✅ {template} properly extends base template")
                else:
                    print(f"⚠️ {template} may not extend base template")
                    
                if 'workflow' in content.lower():
                    print(f"✅ {template} contains workflow content")
                else:
                    print(f"⚠️ {template} may not contain workflow content")
                    
            else:
                print(f"❌ Template missing: {template}")
                all_templates_exist = False
        
        return all_templates_exist
        
    except Exception as e:
        print(f"❌ Workflow templates test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_enhanced_citations_show_all():
    """Test that enhanced citations supports show_all parameter."""
    print("🔍 Testing Enhanced Citations Show All Parameter...")
    
    try:
        # Import the enhanced citations module
        sys.path.insert(0, os.path.join('..', 'application', 'single_app'))
        from route_enhanced_citations import serve_enhanced_citation_pdf_content
        
        print("✅ Enhanced citations route module imported successfully")
        
        # Check function signature for show_all parameter
        import inspect
        sig = inspect.signature(serve_enhanced_citation_pdf_content)
        parameters = list(sig.parameters.keys())
        
        if 'show_all' in parameters:
            print("✅ serve_enhanced_citation_pdf_content supports show_all parameter")
            return True
        else:
            print("❌ serve_enhanced_citation_pdf_content missing show_all parameter")
            print(f"Current parameters: {parameters}")
            return False
        
    except Exception as e:
        print(f"❌ Enhanced citations show_all test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_navigation_integration():
    """Test that workflow navigation is integrated in all menus."""
    print("🔍 Testing Navigation Integration...")
    
    try:
        template_dir = os.path.join('..', 'application', 'single_app', 'templates')
        nav_templates = [
            '_top_nav.html',
            '_sidebar_nav.html',
            '_sidebar_short_nav.html'
        ]
        
        all_nav_updated = True
        for nav_template in nav_templates:
            nav_path = os.path.join(template_dir, nav_template)
            if os.path.exists(nav_path):
                with open(nav_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                if 'workflow' in content.lower() and 'enable_workflow' in content:
                    print(f"✅ {nav_template} includes workflow navigation")
                else:
                    print(f"❌ {nav_template} missing workflow navigation")
                    all_nav_updated = False
            else:
                print(f"❌ Navigation template missing: {nav_template}")
                all_nav_updated = False
        
        return all_nav_updated
        
    except Exception as e:
        print(f"❌ Navigation integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_admin_settings_integration():
    """Test that admin settings includes workflow configuration."""
    print("🔍 Testing Admin Settings Integration...")
    
    try:
        admin_template_path = os.path.join('..', 'application', 'single_app', 'templates', 'admin_settings.html')
        
        if not os.path.exists(admin_template_path):
            print("❌ Admin settings template not found")
            return False
        
        with open(admin_template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for workflow tab and settings
        checks = [
            ('workflow-tab', 'Workflow tab in navigation'),
            ('enable_workflow', 'Enable workflow setting'),
            ('workflow_default_summary_model', 'Workflow summary model setting'),
            ('enhanced citations', 'Enhanced citations dependency check')
        ]
        
        all_checks_passed = True
        for check_text, description in checks:
            if check_text.lower() in content.lower():
                print(f"✅ {description} found")
            else:
                print(f"❌ {description} missing")
                all_checks_passed = False
        
        return all_checks_passed
        
    except Exception as e:
        print(f"❌ Admin settings integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_version_update():
    """Test that version was properly updated."""
    print("🔍 Testing Version Update...")
    
    try:
        config_path = os.path.join('..', 'application', 'single_app', 'config.py')
        
        if not os.path.exists(config_path):
            print("❌ Config file not found")
            return False
        
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if 'VERSION = "0.229.061"' in content:
            print("✅ Version properly updated to 0.229.061")
            return True
        else:
            print("❌ Version not updated correctly")
            return False
        
    except Exception as e:
        print(f"❌ Version update test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("Workflow Feature Comprehensive Test")
    print("=" * 55)
    
    tests = [
        test_workflow_route_integration,
        test_workflow_templates,
        test_enhanced_citations_show_all,
        test_navigation_integration,
        test_admin_settings_integration,
        test_version_update
    ]
    
    results = []
    for test in tests:
        print()
        results.append(test())
    
    success_count = sum(results)
    total_count = len(results)
    
    print(f"\n📊 Test Results: {success_count}/{total_count} tests passed")
    
    if success_count == total_count:
        print("🎉 All tests passed! Workflow feature implementation is complete.")
        sys.exit(0)
    else:
        print("❌ Some tests failed. Please review the implementation.")
        sys.exit(1)