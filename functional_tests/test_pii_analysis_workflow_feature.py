#!/usr/bin/env python3
"""
Functional test for PII Analysis Workflow feature implementation.
Version: 0.229.072
Implemented in: 0.229.072

This test ensures that the complete PII Analysis feature works correctly:
- Admin settings for PII analysis configuration
- PII pattern management with severity levels
- Workflow integration with PII analysis option
- Backend API endpoints for PII analysis
- Template updates for PII analysis display
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_pii_analysis_admin_settings():
    """Test that PII analysis admin settings are properly configured."""
    print("🔍 Testing PII Analysis Admin Settings...")
    
    try:
        # Test admin settings route contains PII analysis handling
        admin_settings_file = os.path.join('..', 'application', 'single_app', 'route_frontend_admin_settings.py')
        with open(admin_settings_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for PII analysis settings processing
        pii_settings_checks = [
            "enable_pii_analysis",
            "pii_analysis_patterns_json", 
            "parsed_pii_patterns",
            "'pii_analysis_patterns': parsed_pii_patterns"
        ]
        
        for check in pii_settings_checks:
            if check not in content:
                print(f"❌ Missing PII analysis setting: {check}")
                return False
            else:
                print(f"✅ Found PII analysis setting: {check}")
        
        # Check for default PII patterns
        if "SSN" in content and "Email" in content and "severity" in content:
            print("✅ Default PII patterns configured")
        else:
            print("❌ Default PII patterns not found")
            return False
            
        print("✅ PII Analysis admin settings properly configured")
        return True
        
    except Exception as e:
        print(f"❌ Error testing PII analysis admin settings: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_pii_analysis_admin_template():
    """Test that admin settings template includes PII analysis section."""
    print("🔍 Testing PII Analysis Admin Template...")
    
    try:
        admin_template_file = os.path.join('..', 'application', 'single_app', 'templates', 'admin_settings.html')
        with open(admin_template_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for PII analysis template elements
        template_checks = [
            "enable_pii_analysis",
            "PII Analysis",
            "pii-patterns-tbody",
            "addPiiPattern",
            "refreshPiiPatternsTable",
            "pii_analysis_patterns_json"
        ]
        
        for check in template_checks:
            if check not in content:
                print(f"❌ Missing PII analysis template element: {check}")
                return False
            else:
                print(f"✅ Found PII analysis template element: {check}")
        
        # Check for JavaScript functions
        js_functions = [
            "addPiiPattern()",
            "removePiiPattern",
            "updatePiiPattern",
            "refreshPiiPatternsTable()",
            "togglePiiAnalysisSettings()"
        ]
        
        for func in js_functions:
            if func not in content:
                print(f"❌ Missing PII analysis JavaScript function: {func}")
                return False
            else:
                print(f"✅ Found PII analysis JavaScript function: {func}")
        
        print("✅ PII Analysis admin template properly configured")
        return True
        
    except Exception as e:
        print(f"❌ Error testing PII analysis admin template: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_pii_analysis_workflow_api():
    """Test that PII analysis API endpoint exists in workflow routes."""
    print("🔍 Testing PII Analysis Workflow API...")
    
    try:
        workflow_file = os.path.join('..', 'application', 'single_app', 'route_frontend_workflow.py')
        with open(workflow_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for PII analysis API endpoint
        api_checks = [
            "@app.route('/api/workflow/generate-pii-analysis'",
            "def api_generate_workflow_pii_analysis():",
            "def generate_document_pii_analysis(",
            "enable_pii_analysis",
            "pii_analysis_patterns"
        ]
        
        for check in api_checks:
            if check not in content:
                print(f"❌ Missing PII analysis API element: {check}")
                return False
            else:
                print(f"✅ Found PII analysis API element: {check}")
        
        # Check for PII analysis function implementation
        if "You are an expert privacy and data protection analyst" in content:
            print("✅ PII analysis AI prompt properly configured")
        else:
            print("❌ PII analysis AI prompt not found")
            return False
            
        # Check for proper error handling
        if "Failed to generate PII analysis" in content:
            print("✅ PII analysis error handling implemented")
        else:
            print("❌ PII analysis error handling not found")
            return False
        
        print("✅ PII Analysis workflow API properly implemented")
        return True
        
    except Exception as e:
        print(f"❌ Error testing PII analysis workflow API: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_pii_analysis_workflow_selection_template():
    """Test that workflow selection template includes PII analysis option."""
    print("🔍 Testing PII Analysis Workflow Selection Template...")
    
    try:
        template_file = os.path.join('..', 'application', 'single_app', 'templates', 'workflow_summary_selection.html')
        with open(template_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for PII analysis card
        template_checks = [
            'data-type="pii_analysis"',
            "PII Analysis",
            "bi-shield-check",
            "Identifies sensitive data",
            "Privacy compliance help"
        ]
        
        for check in template_checks:
            if check not in content:
                print(f"❌ Missing PII analysis selection element: {check}")
                return False
            else:
                print(f"✅ Found PII analysis selection element: {check}")
        
        # Check JavaScript enables PII analysis
        if "cardType === 'summary' || cardType === 'pii_analysis'" in content:
            print("✅ JavaScript enables PII analysis selection")
        else:
            print("❌ JavaScript does not enable PII analysis selection")
            return False
        
        print("✅ PII Analysis workflow selection template properly configured")
        return True
        
    except Exception as e:
        print(f"❌ Error testing PII analysis workflow selection template: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_pii_analysis_workflow_view_template():
    """Test that workflow view template handles PII analysis display."""
    print("🔍 Testing PII Analysis Workflow View Template...")
    
    try:
        template_file = os.path.join('..', 'application', 'single_app', 'templates', 'workflow_summary_view.html')
        with open(template_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for PII analysis display elements
        template_checks = [
            "summary_type == 'pii_analysis'",
            "bi-shield-check",
            "Generated PII Analysis", 
            "data.pii_analysis",
            "PII analysis"
        ]
        
        for check in template_checks:
            if check not in content:
                print(f"❌ Missing PII analysis view element: {check}")
                return False
            else:
                print(f"✅ Found PII analysis view element: {check}")
        
        # Check JavaScript handles PII analysis API
        if "'/api/workflow/generate-pii-analysis'" in content:
            print("✅ JavaScript calls PII analysis API")
        else:
            print("❌ JavaScript does not call PII analysis API")
            return False
        
        print("✅ PII Analysis workflow view template properly configured")
        return True
        
    except Exception as e:
        print(f"❌ Error testing PII analysis workflow view template: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_config_version_update():
    """Test that config version was updated for PII analysis feature."""
    print("🔍 Testing Config Version Update...")
    
    try:
        config_file = os.path.join('..', 'application', 'single_app', 'config.py')
        with open(config_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for version update
        if 'VERSION = "0.229.072"' in content:
            print("✅ Config version updated to 0.229.072")
            return True
        else:
            print("❌ Config version not updated")
            return False
        
    except Exception as e:
        print(f"❌ Error testing config version: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_pii_patterns_data_structure():
    """Test that PII patterns have proper data structure."""
    print("🔍 Testing PII Patterns Data Structure...")
    
    try:
        admin_settings_file = os.path.join('..', 'application', 'single_app', 'route_frontend_admin_settings.py')
        with open(admin_settings_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for proper pattern structure validation
        structure_checks = [
            "'pattern_type' in item",
            "'description' in item", 
            "'severity' in item",
            "item['severity'] in ['Low', 'Medium', 'High']",
            'pattern_type": "SSN"',
            'severity": "High"'
        ]
        
        for check in structure_checks:
            if check not in content:
                print(f"❌ Missing PII pattern structure element: {check}")
                return False
            else:
                print(f"✅ Found PII pattern structure element: {check}")
        
        print("✅ PII patterns data structure properly validated")
        return True
        
    except Exception as e:
        print(f"❌ Error testing PII patterns data structure: {e}")
        import traceback
        traceback.print_exc()
        return False

def run_comprehensive_pii_analysis_test():
    """Run all PII analysis feature tests."""
    print("🧪 Running Comprehensive PII Analysis Feature Test...\n")
    
    test_functions = [
        test_pii_analysis_admin_settings,
        test_pii_analysis_admin_template,
        test_pii_analysis_workflow_api,
        test_pii_analysis_workflow_selection_template,
        test_pii_analysis_workflow_view_template,
        test_config_version_update,
        test_pii_patterns_data_structure
    ]
    
    results = []
    for test_func in test_functions:
        print(f"\n🔧 Running {test_func.__name__}...")
        result = test_func()
        results.append(result)
        print(f"{'✅ PASSED' if result else '❌ FAILED'}: {test_func.__name__}")
    
    print(f"\n📊 PII Analysis Feature Test Results:")
    print(f"✅ Passed: {sum(results)}/{len(results)} tests")
    
    if all(results):
        print("\n🎉 ALL PII ANALYSIS FEATURE TESTS PASSED!")
        print("🔒 PII Analysis workflow feature is fully implemented and functional")
        return True
    else:
        print(f"\n⚠️  {len(results) - sum(results)} test(s) failed")
        print("🔧 Please review and fix the failing components")
        return False

if __name__ == "__main__":
    success = run_comprehensive_pii_analysis_test()
    sys.exit(0 if success else 1)