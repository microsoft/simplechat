#!/usr/bin/env python3
"""
Functional test for workflow CSP and OpenAI API parameter fixes.
Version: 0.229.065
Implemented in: 0.229.065

This test ensures that:
1. Workflow uses correct OpenAI API parameters for o1 models
2. Enhanced citations endpoint allows iframe embedding when show_all=true
3. PDF viewing in workflow should work without CSP violations
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_workflow_openai_api_parameters():
    """Test that workflow uses correct API parameters for different models."""
    print("🔍 Testing workflow OpenAI API parameter handling...")
    
    try:
        workflow_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'route_frontend_workflow.py'
        )
        
        with open(workflow_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for correct parameter handling
        required_patterns = [
            'api_params = {',  # Dynamic parameter building
            'api_params["max_completion_tokens"] = 2000',  # o1 model parameter
            'api_params["max_tokens"] = 2000',  # Other models parameter
            "if gpt_model and ('o1' in gpt_model.lower()):",  # Model detection
            'gpt_client.chat.completions.create(**api_params)'  # Dynamic parameter usage
        ]
        
        missing_patterns = []
        for pattern in required_patterns:
            if pattern not in content:
                missing_patterns.append(pattern)
        
        if missing_patterns:
            raise Exception(f"Missing OpenAI API parameter patterns: {missing_patterns}")
        
        # Check that old static parameters are removed
        if 'max_tokens=2000   # Allow for comprehensive summary' in content:
            raise Exception("Old static max_tokens parameter still present")
        
        print("   - Dynamic API parameter building: ✅")
        print("   - o1 model detection: ✅")
        print("   - max_completion_tokens for o1 models: ✅")
        print("   - max_tokens for other models: ✅")
        print("   - Old static parameters removed: ✅")
        print("✅ OpenAI API parameter handling is correct!")
        return True
        
    except Exception as e:
        print(f"❌ OpenAI API parameter test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_enhanced_citations_iframe_support():
    """Test that enhanced citations supports iframe embedding for workflow."""
    print("🔍 Testing enhanced citations iframe support...")
    
    try:
        citations_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'route_enhanced_citations.py'
        )
        
        with open(citations_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for iframe support when show_all=True
        required_patterns = [
            'if show_all:',  # Check for show_all condition
            '"frame-ancestors \'self\'; "',  # Allow same-origin framing
            "headers['X-Frame-Options'] = 'SAMEORIGIN'",  # X-Frame-Options header
            "headers['Content-Security-Policy'] = (",  # CSP header setting
            'headers = {',  # Dynamic headers building
        ]
        
        missing_patterns = []
        for pattern in required_patterns:
            if pattern not in content:
                missing_patterns.append(pattern)
        
        if missing_patterns:
            raise Exception(f"Missing iframe support patterns: {missing_patterns}")
        
        print("   - show_all parameter handling: ✅")
        print("   - frame-ancestors 'self' CSP: ✅")
        print("   - X-Frame-Options SAMEORIGIN: ✅")
        print("   - Dynamic headers building: ✅")
        print("✅ Enhanced citations iframe support is implemented!")
        return True
        
    except Exception as e:
        print(f"❌ Enhanced citations iframe test failed: {e}")
        return False

def test_workflow_pdf_endpoint_usage():
    """Test that workflow uses correct enhanced citations endpoint."""
    print("🔍 Testing workflow PDF endpoint usage...")
    
    try:
        template_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'templates', 'workflow_summary_view.html'
        )
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that workflow uses enhanced citations endpoint with show_all parameter
        required_patterns = [
            '/api/enhanced_citations/pdf',  # Correct endpoint
            'show_all=true',  # show_all parameter for full document
            'encodeURIComponent(fileId)',  # Proper doc_id encoding
        ]
        
        missing_patterns = []
        for pattern in required_patterns:
            if pattern not in content:
                missing_patterns.append(pattern)
        
        if missing_patterns:
            raise Exception(f"Missing PDF endpoint patterns: {missing_patterns}")
        
        print("   - Enhanced citations PDF endpoint: ✅")
        print("   - show_all=true parameter: ✅")
        print("   - Proper URL encoding: ✅")
        print("✅ Workflow PDF endpoint usage is correct!")
        return True
        
    except Exception as e:
        print(f"❌ Workflow PDF endpoint test failed: {e}")
        return False

def test_version_update():
    """Test that version was updated."""
    print("🔍 Testing version update...")
    
    try:
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'config.py'
        )
        
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if 'VERSION = "0.229.065"' in content:
            print("   - Version updated to 0.229.065")
            print("✅ Version update confirmed!")
            return True
        else:
            raise Exception("Version not updated to 0.229.065")
        
    except Exception as e:
        print(f"❌ Version update test failed: {e}")
        return False

if __name__ == "__main__":
    tests = [
        test_workflow_openai_api_parameters,
        test_enhanced_citations_iframe_support,
        test_workflow_pdf_endpoint_usage,
        test_version_update
    ]
    
    results = []
    print("🧪 Running Workflow CSP and API Parameter Fix Tests...\n")
    
    for test in tests:
        print(f"Running {test.__name__}...")
        results.append(test())
        print()
    
    success = all(results)
    print(f"📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("✅ All workflow fixes validated successfully!")
        print("🎉 The workflow should now:")
        print("   - Generate summaries without OpenAI API errors")
        print("   - Display PDFs in iframe without CSP violations")
        print("   - Work properly with o1 models using max_completion_tokens")
    else:
        print("❌ Some tests failed - workflow may still have issues")
    
    sys.exit(0 if success else 1)