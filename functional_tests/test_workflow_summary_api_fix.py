#!/usr/bin/env python3
"""
Functional test for workflow summary generation API parameter fix.
Version: 0.229.070
Implemented in: 0.229.070

This test ensures that the summary generation function uses correct API parameters
for o1 models (no temperature, max_completion_tokens) and regular models (temperature, max_tokens).
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_summary_api_parameters():
    """Test that summary generation uses correct API parameters for different model types."""
    print("🔍 Testing summary generation API parameters...")
    
    try:
        workflow_path = os.path.join('..', 'application', 'single_app', 'route_frontend_workflow.py')
        
        with open(workflow_path, 'r') as f:
            content = f.read()
        
        # Find the generate_document_summary function
        func_start = content.find('def generate_document_summary(')
        if func_start == -1:
            print("   ❌ generate_document_summary function not found")
            return False
        
        func_section = content[func_start:func_start + 8000]  # Get larger chunk
        
        # Check for proper API parameter structure
        if 'model": gpt_model' in func_section and 'messages": messages' in func_section:
            print("   ✅ Basic API parameters properly structured")
        else:
            print("   ❌ Missing basic API parameter structure")
            # Let's debug what we actually have
            if 'model": gpt_model' in func_section:
                print("      - Found model parameter")
            else:
                print("      - Missing model parameter")
            if 'messages": messages' in func_section:
                print("      - Found messages parameter")  
            else:
                print("      - Missing messages parameter")
            return False
        
        # Check for o1 model handling
        if "'o1' in gpt_model.lower()" in func_section:
            print("   ✅ Has o1 model detection logic")
        else:
            print("   ❌ Missing o1 model detection logic")
            return False
        
        # Check for conditional temperature handling
        if 'temperature' in func_section:
            # Check if temperature is only in the else block (non-o1 models)
            if 'else:' in func_section and 'api_params["temperature"]' in func_section:
                print("   ✅ Temperature parameter handled conditionally")
            else:
                print("   ❌ Temperature parameter not properly conditional")
                return False
        else:
            print("   ✅ Temperature parameter handled conditionally (not found, which is correct)")
        
        # Check for max_completion_tokens for o1 models
        if 'max_completion_tokens' in func_section:
            print("   ✅ Has max_completion_tokens for o1 models")
        else:
            print("   ❌ Missing max_completion_tokens for o1 models")
            return False
        
        # Check for max_tokens for regular models
        if 'max_tokens' in func_section:
            print("   ✅ Has max_tokens for regular models")
        else:
            print("   ❌ Missing max_tokens for regular models")
            return False
        
        # Check that the fix includes proper commenting
        if 'o1 models don\'t support temperature' in func_section:
            print("   ✅ Has explanatory comments about o1 model limitations")
        else:
            print("   ❌ Missing explanatory comments")
            return False
        
        return True
        
    except Exception as e:
        print(f"   ❌ Error checking summary API parameters: {e}")
        return False

def test_no_unconditional_temperature():
    """Test that temperature is not unconditionally applied to all models."""
    print("🔍 Testing no unconditional temperature usage...")
    
    try:
        workflow_path = os.path.join('..', 'application', 'single_app', 'route_frontend_workflow.py')
        
        with open(workflow_path, 'r') as f:
            content = f.read()
        
        func_start = content.find('def generate_document_summary(')
        func_section = content[func_start:func_start + 5000]
        
        # Look for the old problematic pattern
        problematic_patterns = [
            '"temperature": 0.3,  # Lower temperature for more consistent, factual summaries',
            'api_params = {\n        "model": gpt_model,\n        "messages": messages,\n        "temperature":'
        ]
        
        for pattern in problematic_patterns:
            if pattern.replace('\n        ', ' ').replace('\n', ' ') in func_section.replace('\n        ', ' ').replace('\n', ' '):
                print(f"   ❌ Found problematic unconditional temperature pattern")
                return False
        
        print("   ✅ No unconditional temperature usage found")
        return True
        
    except Exception as e:
        print(f"   ❌ Error checking temperature usage: {e}")
        return False

def test_version_update():
    """Test that version was updated after the fix."""
    print("🔍 Testing version update...")
    
    try:
        config_path = os.path.join('..', 'application', 'single_app', 'config.py')
        
        with open(config_path, 'r') as f:
            content = f.read()
        
        if 'VERSION = "0.229.070"' in content:
            print("   ✅ Version updated to 0.229.070")
            return True
        else:
            print("   ❌ Version not updated properly")
            return False
            
    except Exception as e:
        print(f"   ❌ Error checking version: {e}")
        return False

def run_summary_api_tests():
    """Run summary generation API parameter fix tests."""
    print("🧪 Running Summary Generation API Parameter Fix Tests")
    print("=" * 60)
    
    tests = [
        test_summary_api_parameters,
        test_no_unconditional_temperature,
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
        print("✅ Summary generation API parameter fix validated successfully!")
        return True
    else:
        print("❌ Some tests failed - fix may be incomplete")
        return False

if __name__ == "__main__":
    success = run_summary_api_tests()
    sys.exit(0 if success else 1)