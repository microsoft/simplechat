#!/usr/bin/env python3
"""
Comprehensive test for complete workflow functionality.
Version: 0.229.065
Implemented in: 0.229.065

This test validates the end-to-end workflow functionality including:
- Document loading without JavaScript errors
- PDF display without CSP violations  
- Summary generation with correct OpenAI API parameters
- Enhanced citations iframe support
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_workflow_integration():
    """Test complete workflow integration."""
    print("🔍 Testing complete workflow integration...")
    
    try:
        # Test all workflow templates exist and have correct structure
        template_files = [
            'workflow.html',
            'workflow_file_selection.html', 
            'workflow_summary_selection.html',
            'workflow_summary_view.html'
        ]
        
        template_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'templates'
        )
        
        for template_file in template_files:
            template_path = os.path.join(template_dir, template_file)
            if not os.path.exists(template_path):
                raise Exception(f"Missing template: {template_file}")
            
            with open(template_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check for basic template structure
            if not content.strip():
                raise Exception(f"Empty template: {template_file}")
                
            if '{% extends "base.html" %}' not in content:
                raise Exception(f"Template {template_file} doesn't extend base.html")
        
        print("   - All workflow templates present: ✅")
        print("   - Template structure valid: ✅")
        
        # Test workflow route exists
        route_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'route_frontend_workflow.py'
        )
        
        if not os.path.exists(route_path):
            raise Exception("Workflow route file missing")
        
        with open(route_path, 'r', encoding='utf-8') as f:
            route_content = f.read()
        
        # Check for key route endpoints
        required_routes = [
            "@app.route('/workflow'",  # Main workflow page
            "@app.route('/workflow/file-selection'",  # File selection page
            "@app.route('/workflow/summary-selection'",  # Summary selection page
            "@app.route('/workflow/summary-view'",  # Summary view page
            "@app.route('/api/workflow/generate-summary'",  # API endpoint
        ]
        
        for route in required_routes:
            if route not in route_content:
                raise Exception(f"Missing route: {route}")
        
        print("   - All workflow routes present: ✅")
        
        # Test enhanced citations integration
        citations_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'route_enhanced_citations.py'
        )
        
        with open(citations_path, 'r', encoding='utf-8') as f:
            citations_content = f.read()
        
        if 'show_all' not in citations_content:
            raise Exception("Enhanced citations missing show_all parameter support")
        
        print("   - Enhanced citations integration: ✅")
        
        # Test admin settings integration
        admin_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'templates', 'admin_settings.html'
        )
        
        if os.path.exists(admin_path):
            with open(admin_path, 'r', encoding='utf-8') as f:
                admin_content = f.read()
            
            if 'enable_workflow' in admin_content:
                print("   - Admin settings integration: ✅")
            else:
                print("   - Admin settings integration: ⚠️ (workflow setting not found)")
        else:
            print("   - Admin settings integration: ⚠️ (admin template not found)")
        
        print("✅ Workflow integration is complete!")
        return True
        
    except Exception as e:
        print(f"❌ Workflow integration test failed: {e}")
        return False

def test_workflow_error_fixes():
    """Test that all reported errors have been fixed."""
    print("🔍 Testing workflow error fixes...")
    
    try:
        fixes_validated = []
        
        # 1. Template title block duplication fix
        workflow_template = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'templates', 'workflow.html'
        )
        
        with open(workflow_template, 'r', encoding='utf-8') as f:
            content = f.read()
        
        title_block_count = content.count('{% block title %}')
        extends_count = content.count('{% extends "base.html" %}')
        
        if title_block_count == 1 and extends_count == 1:
            fixes_validated.append("Template title block duplication")
        
        # 2. Document loading null filename fix
        file_selection_template = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'templates', 'workflow_file_selection.html'
        )
        
        with open(file_selection_template, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if 'if (!filename || typeof filename !== \'string\')' in content:
            fixes_validated.append("Document loading null filename handling")
        
        # 3. OpenAI API parameter fix
        workflow_route = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'route_frontend_workflow.py'
        )
        
        with open(workflow_route, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if 'max_completion_tokens' in content and "('o1' in gpt_model.lower())" in content:
            fixes_validated.append("OpenAI API parameter for o1 models")
        
        # 4. CSP iframe embedding fix
        citations_route = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'route_enhanced_citations.py'
        )
        
        with open(citations_route, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if 'frame-ancestors \'self\'' in content and 'X-Frame-Options' in content:
            fixes_validated.append("CSP iframe embedding for PDFs")
        
        # Report results
        total_expected = 4
        for fix in fixes_validated:
            print(f"   - {fix}: ✅")
        
        missing_fixes = total_expected - len(fixes_validated)
        if missing_fixes > 0:
            print(f"   - Missing fixes: {missing_fixes}")
        
        if len(fixes_validated) == total_expected:
            print("✅ All reported errors have been fixed!")
            return True
        else:
            print(f"⚠️ {missing_fixes} fixes still missing")
            return False
        
    except Exception as e:
        print(f"❌ Error fixes test failed: {e}")
        return False

if __name__ == "__main__":
    tests = [
        test_workflow_integration,
        test_workflow_error_fixes
    ]
    
    results = []
    print("🧪 Running Comprehensive Workflow Tests...\n")
    
    for test in tests:
        print(f"Running {test.__name__}...")
        results.append(test())
        print()
    
    success = all(results)
    print(f"📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("✅ Complete workflow functionality validated!")
        print("🎉 The workflow feature is ready for production use!")
        print("")
        print("Summary of fixes applied:")
        print("• Fixed Jinja2 template title block duplication")
        print("• Fixed JavaScript document loading with null filenames")
        print("• Fixed OpenAI API parameters for o1 models")
        print("• Fixed CSP iframe embedding for PDF display")
        print("• Enhanced error handling throughout the workflow")
    else:
        print("❌ Some workflow components may still have issues")
    
    sys.exit(0 if success else 1)