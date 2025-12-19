#!/usr/bin/env python3
"""
Functional test for Multi-Modal Vision Analysis parameter fix.
Version: 0.233.201
Implemented in: 0.233.201

This test ensures that vision analysis correctly uses max_completion_tokens 
for o-series and gpt-5 models instead of max_tokens.
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

def test_vision_test_parameter_handling():
    """Test that vision test in route_backend_settings.py uses correct parameter."""
    print("🔍 Testing vision test parameter handling...")
    
    try:
        settings_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'route_backend_settings.py'
        )
        
        with open(settings_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for correct parameter handling
        required_patterns = [
            'vision_model_lower = vision_model.lower()',  # Model name lowercasing
            'api_params = {',  # Dynamic parameter building
            '"model": vision_model,',  # Model parameter
            'api_params["max_completion_tokens"] = 50',  # o-series/gpt-5 parameter
            'api_params["max_tokens"] = 50',  # Other models parameter
            "if ('o1' in vision_model_lower or 'o3' in vision_model_lower or 'gpt-5' in vision_model_lower):",  # Model detection
            'gpt_client.chat.completions.create(**api_params)'  # Dynamic parameter usage
        ]
        
        missing_patterns = []
        for pattern in required_patterns:
            if pattern not in content:
                missing_patterns.append(pattern)
        
        if missing_patterns:
            raise Exception(f"Missing vision test parameter patterns: {missing_patterns}")
        
        # Check that old static max_tokens parameter is removed from vision test
        if 'max_tokens=50\n        )' in content:
            raise Exception("Old static max_tokens parameter still present in vision test")
        
        print("   ✅ Vision test uses dynamic API parameter building")
        print("   ✅ Model detection for o-series and gpt-5")
        print("   ✅ max_completion_tokens for o-series/gpt-5 models")
        print("   ✅ max_tokens for other models")
        print("   ✅ Old static parameter removed")
        print("✅ Vision test parameter handling is correct!")
        return True
        
    except Exception as e:
        print(f"❌ Vision test parameter test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_vision_analysis_parameter_handling():
    """Test that vision analysis in functions_documents.py uses correct parameter."""
    print("\n🔍 Testing vision analysis parameter handling...")
    
    try:
        functions_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'functions_documents.py'
        )
        
        with open(functions_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for correct parameter handling in analyze_image_with_vision_model
        required_patterns = [
            'vision_model_lower = vision_model.lower()',  # Model name lowercasing
            'api_params = {',  # Dynamic parameter building
            '"model": vision_model,',  # Model parameter
            'api_params["max_completion_tokens"] = 1000',  # o-series/gpt-5 parameter
            'api_params["max_tokens"] = 1000',  # Other models parameter
            "if ('o1' in vision_model_lower or 'o3' in vision_model_lower or 'gpt-5' in vision_model_lower):",  # Model detection
            'gpt_client.chat.completions.create(**api_params)'  # Dynamic parameter usage
        ]
        
        missing_patterns = []
        for pattern in required_patterns:
            if pattern not in content:
                missing_patterns.append(pattern)
        
        if missing_patterns:
            raise Exception(f"Missing vision analysis parameter patterns: {missing_patterns}")
        
        # Check that old static max_tokens parameter is removed from vision analysis
        if 'max_tokens=1000\n        )' in content:
            raise Exception("Old static max_tokens parameter still present in vision analysis")
        
        print("   ✅ Vision analysis uses dynamic API parameter building")
        print("   ✅ Model detection for o-series and gpt-5")
        print("   ✅ max_completion_tokens for o-series/gpt-5 models")
        print("   ✅ max_tokens for other models")
        print("   ✅ Old static parameter removed")
        print("✅ Vision analysis parameter handling is correct!")
        return True
        
    except Exception as e:
        print(f"❌ Vision analysis parameter test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_model_detection_coverage():
    """Test that model detection covers all necessary model families."""
    print("\n🔍 Testing model detection coverage...")
    
    try:
        # Define test cases
        test_models = [
            # Should use max_completion_tokens
            ('o1', True, 'o1 base model'),
            ('o1-preview', True, 'o1-preview'),
            ('o1-mini', True, 'o1-mini'),
            ('o3', True, 'o3 base model'),
            ('o3-mini', True, 'o3-mini'),
            ('gpt-5', True, 'gpt-5 base model'),
            ('gpt-5-turbo', True, 'gpt-5-turbo'),
            ('gpt-5-nano', True, 'gpt-5-nano'),
            ('GPT-5-NANO', True, 'GPT-5-NANO (uppercase)'),
            ('O1-PREVIEW', True, 'O1-PREVIEW (uppercase)'),
            
            # Should use max_tokens
            ('gpt-4o', False, 'gpt-4o'),
            ('gpt-4o-mini', False, 'gpt-4o-mini'),
            ('gpt-4-vision-preview', False, 'gpt-4-vision-preview'),
            ('gpt-4-turbo-vision', False, 'gpt-4-turbo-vision'),
            ('gpt-4.1', False, 'gpt-4.1'),
            ('gpt-4.5', False, 'gpt-4.5'),
        ]
        
        # Test the detection logic
        failed_tests = []
        for model, should_use_completion_tokens, description in test_models:
            model_lower = model.lower()
            uses_completion_tokens = ('o1' in model_lower or 'o3' in model_lower or 'gpt-5' in model_lower)
            
            if uses_completion_tokens != should_use_completion_tokens:
                failed_tests.append(f"{description}: expected {'max_completion_tokens' if should_use_completion_tokens else 'max_tokens'}, got {'max_completion_tokens' if uses_completion_tokens else 'max_tokens'}")
        
        if failed_tests:
            raise Exception(f"Model detection failures: {', '.join(failed_tests)}")
        
        print(f"   ✅ Tested {len(test_models)} model patterns")
        print("   ✅ o-series models correctly detected")
        print("   ✅ gpt-5 models correctly detected")
        print("   ✅ Other vision models use standard parameter")
        print("   ✅ Case-insensitive detection works")
        print("✅ Model detection coverage is complete!")
        return True
        
    except Exception as e:
        print(f"❌ Model detection coverage test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all vision parameter fix tests."""
    print("🚀 Testing Multi-Modal Vision Analysis Parameter Fix")
    print("=" * 65)
    
    results = []
    
    # Run tests
    results.append(test_vision_test_parameter_handling())
    results.append(test_vision_analysis_parameter_handling())
    results.append(test_model_detection_coverage())
    
    print("\n" + "=" * 65)
    if all(results):
        print("🎉 All vision parameter fix tests passed!")
        print("\n📝 Summary:")
        print("   - Vision test uses correct parameters based on model type")
        print("   - Vision analysis uses correct parameters based on model type")
        print("   - o-series models (o1, o3) use max_completion_tokens")
        print("   - gpt-5 models use max_completion_tokens")
        print("   - Other vision models use max_tokens")
        print("   - Detection is case-insensitive")
        print("\n✅ GPT-5 and o-series models will now work with vision analysis!")
        return True
    else:
        print("⚠️ Some vision parameter fix tests failed - check output above")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
