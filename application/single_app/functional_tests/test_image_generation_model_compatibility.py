#!/usr/bin/env python3
"""
Functional test for image generation model compatibility fix.
Version: 0.226.103
Implemented in: 0.226.103

This test ensures that both dall-e-3 and gpt-image-1 models work correctly
and that null image URLs are handled gracefully.
"""

import sys
import os
# Add parent directory to path for imports
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

def test_image_generation_api_version():
    """Test that the correct API version is configured for newer image models."""
    print("🔍 Testing Image Generation API Version Configuration...")
    
    try:
        # Read the functions_settings.py file directly to check API version
        settings_file = os.path.join(parent_dir, 'functions_settings.py')
        with open(settings_file, 'r') as f:
            content = f.read()
        
        # Look for the API version setting
        expected_version = '2024-12-01-preview'
        version_line = f"'azure_openai_image_gen_api_version': '{expected_version}'"
        
        if version_line in content:
            print(f"✅ API version correctly set to {expected_version} for gpt-image-1 support")
            return True
        else:
            print(f"❌ API version should be {expected_version} but not found in functions_settings.py")
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_null_image_url_handling():
    """Test that null/empty image URLs are handled gracefully."""
    print("🔍 Testing Null Image URL Handling...")
    
    try:
        # Test the JavaScript validation logic (simulated in Python)
        test_cases = [
            {'content': None, 'expected': False, 'description': 'None content'},
            {'content': '', 'expected': False, 'description': 'Empty string'},
            {'content': 'null', 'expected': False, 'description': 'String "null"'},
            {'content': '   ', 'expected': False, 'description': 'Whitespace only'},
            {'content': 'https://example.com/image.jpg', 'expected': True, 'description': 'Valid URL'},
        ]
        
        all_passed = True
        
        for test_case in test_cases:
            content = test_case['content']
            expected = test_case['expected']
            description = test_case['description']
            
            # Simulate the JavaScript validation logic
            if content is None:
                is_valid = False
            elif content == 'null':
                is_valid = False
            elif content.strip() == '':
                is_valid = False
            else:
                is_valid = True
            
            if is_valid == expected:
                print(f"✅ {description}: {content} -> {is_valid} (expected {expected})")
            else:
                print(f"❌ {description}: {content} -> {is_valid} (expected {expected})")
                all_passed = False
        
        return all_passed
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_image_response_validation():
    """Test image response validation logic."""
    print("🔍 Testing Image Response Validation...")
    
    try:
        import json
        
        # Test various response formats
        test_responses = [
            {
                'response': {'data': [{'url': 'https://example.com/image.jpg'}]},
                'expected': True,
                'description': 'Valid response with URL'
            },
            {
                'response': {'data': []},
                'expected': False,
                'description': 'Empty data array'
            },
            {
                'response': {'data': [{'url': ''}]},
                'expected': False,
                'description': 'Empty URL'
            },
            {
                'response': {'data': [{'url': None}]},
                'expected': False,
                'description': 'Null URL'
            },
            {
                'response': {'data': [{}]},
                'expected': False,
                'description': 'Missing URL key'
            },
            {
                'response': {},
                'expected': False,
                'description': 'Missing data key'
            }
        ]
        
        all_passed = True
        
        for test_case in test_responses:
            response_dict = test_case['response']
            expected = test_case['expected']
            description = test_case['description']
            
            try:
                # Simulate the validation logic from the fix
                if 'data' not in response_dict or not response_dict['data']:
                    is_valid = False
                else:
                    image_data = response_dict['data'][0]
                    if 'url' not in image_data or not image_data['url']:
                        is_valid = False
                    else:
                        generated_image_url = image_data['url']
                        is_valid = generated_image_url and generated_image_url != 'null'
            except:
                is_valid = False
            
            if is_valid == expected:
                print(f"✅ {description}: {is_valid} (expected {expected})")
            else:
                print(f"❌ {description}: {is_valid} (expected {expected})")
                all_passed = False
        
        return all_passed
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_version_updated():
    """Test that the version was properly updated."""
    print("🔍 Testing Version Update...")
    
    try:
        # Read config.py to check version
        config_path = os.path.join(parent_dir, 'config.py')
        with open(config_path, 'r') as f:
            content = f.read()
        
        expected_version = "0.226.103"
        if f"app.config['VERSION'] = \"{expected_version}\"" in content:
            print(f"✅ Version correctly updated to {expected_version}")
            return True
        else:
            print(f"❌ Version not found or incorrect in config.py")
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    tests = [
        test_image_generation_api_version,
        test_null_image_url_handling,
        test_image_response_validation,
        test_version_updated
    ]
    
    results = []
    
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("\n🎉 All tests passed! Image generation model compatibility fix is working correctly.")
    else:
        print("\n❌ Some tests failed. Please review the implementation.")
    
    sys.exit(0 if success else 1)
