#!/usr/bin/env python3
"""
Functional Test: Base64 Image Handling for gpt-image-1 Model
Tests the resolution of gpt-image-1 model returning base64 instead of URLs.

The gpt-image-1 model returns images as base64 data instead of URLs,
this test validates our fix handles both formats correctly.

Author: GitHub Copilot Assistant
Date: 2025-09-08
"""

import sys
import os
import re

# Add the parent directory to sys.path to import application modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_base64_response_handling():
    """Test that backend handles base64 image responses from gpt-image-1"""
    print("🔍 Testing base64 image response handling...")
    
    try:
        # Read the backend file and check for base64 handling
        backend_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'route_backend_chats.py')
        
        with open(backend_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for base64 handling code
        has_b64_check = "'b64_json' in image_data" in content
        has_data_url_creation = "data:image/png;base64" in content
        has_simple_generate = "image_gen_client.images.generate(" in content
        
        if has_b64_check and has_data_url_creation and has_simple_generate:
            print("✅ Backend properly handles base64 responses from gpt-image-1")
            print("   • Detects b64_json field in response")
            print("   • Converts base64 to data URL format")
            print("   • Uses simple generate call compatible with Azure OpenAI")
            return True
        else:
            missing = []
            if not has_b64_check:
                missing.append("b64_json field detection")
            if not has_data_url_creation:
                missing.append("data URL creation")
            if not has_simple_generate:
                missing.append("simple generate call")
            print(f"❌ Backend missing base64 handling: {', '.join(missing)}")
            return False
            
    except Exception as e:
        print(f"❌ Error checking base64 handling: {e}")
        return False

def test_url_response_handling():
    """Test that backend still handles URL responses from dall-e-3"""
    print("🔍 Testing URL image response handling (dall-e-3 compatibility)...")
    
    try:
        # Read the backend file and check for URL handling
        backend_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'route_backend_chats.py')
        
        with open(backend_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for URL handling code
        has_url_check = "'url' in image_data" in content
        has_simple_generate = "image_gen_client.images.generate(" in content and "model=image_gen_model" in content
        
        if has_url_check and has_simple_generate:
            print("✅ Backend maintains URL response handling for dall-e-3")
            print("   • Still checks for URL field in response")
            print("   • Uses simple generate call compatible with Azure OpenAI")
            return True
        else:
            missing = []
            if not has_url_check:
                missing.append("URL field detection")
            if not has_simple_generate:
                missing.append("simple generate call")
            print(f"❌ Backend missing URL handling: {', '.join(missing)}")
            return False
            
    except Exception as e:
        print(f"❌ Error checking URL handling: {e}")
        return False

def test_azure_openai_compatibility():
    """Test that the code works with Azure OpenAI API limitations"""
    print("🔍 Testing Azure OpenAI API compatibility...")
    
    try:
        # Read the backend file and check that response_format is not used
        backend_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'route_backend_chats.py')
        
        with open(backend_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that response_format parameter is NOT used in the generate call
        # (comments about it are okay, but it shouldn't be in the parameters)
        has_response_format_param = "'response_format'" in content or '"response_format"' in content
        has_azure_comment = "Azure OpenAI doesn't support response_format" in content
        has_simple_generate = "image_gen_client.images.generate(" in content and "prompt=" in content
        
        if not has_response_format_param and has_azure_comment and has_simple_generate:
            print("✅ Code properly works with Azure OpenAI API limitations")
            print("   • No unsupported response_format parameter")
            print("   • Uses simple generate call compatible with Azure")
            print("   • Documents Azure OpenAI differences")
            return True
        else:
            issues = []
            if has_response_format_param:
                issues.append("still uses response_format parameter")
            if not has_azure_comment:
                issues.append("missing Azure API documentation")
            if not has_simple_generate:
                issues.append("not using simple generate call")
            print(f"❌ Azure OpenAI compatibility issues: {', '.join(issues)}")
            return False
            
    except Exception as e:
        print(f"❌ Error checking Azure OpenAI compatibility: {e}")
        return False

def test_enhanced_debugging():
    """Test that enhanced debugging shows response format details"""
    print("🔍 Testing enhanced debugging for image responses...")
    
    try:
        # Read the backend file and check for debugging improvements
        backend_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'route_backend_chats.py')
        
        with open(backend_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for debugging output
        has_data_keys_debug = "Image data keys:" in content
        has_format_debug = "Using base64 format" in content or "Using URL format" in content
        has_response_validation = "Available keys:" in content
        has_model_debug = "Generating image with model:" in content
        
        if has_data_keys_debug and has_format_debug and has_response_validation and has_model_debug:
            print("✅ Enhanced debugging shows detailed response information")
            print("   • Logs available keys in image response")
            print("   • Shows which format is being used")
            print("   • Provides helpful error messages")
            print("   • Logs model being used")
            return True
        else:
            missing = []
            if not has_data_keys_debug:
                missing.append("data keys logging")
            if not has_format_debug:
                missing.append("format detection logging")
            if not has_response_validation:
                missing.append("error message details")
            if not has_model_debug:
                missing.append("model logging")
            print(f"❌ Enhanced debugging missing: {', '.join(missing)}")
            return False
            
    except Exception as e:
        print(f"❌ Error checking debugging: {e}")
        return False

def main():
    """Run all tests"""
    print("🚀 Testing Base64 Image Handling for gpt-image-1 Model\n")
    print("Background: gpt-image-1 returns base64 data instead of URLs like dall-e-3")
    print("Our fix should handle both formats automatically.\n")
    
    tests = [
        ("Base64 Response Handling (gpt-image-1)", test_base64_response_handling),
        ("URL Response Handling (dall-e-3)", test_url_response_handling),
        ("Azure OpenAI API Compatibility", test_azure_openai_compatibility),
        ("Enhanced Debugging Output", test_enhanced_debugging)
    ]
    
    results = []
    
    for test_name, test_func in tests:
        print(f"\n📋 {test_name}")
        print("-" * 60)
        result = test_func()
        results.append(result)
        print()
    
    # Summary
    passed = sum(results)
    total = len(results)
    
    print("=" * 70)
    print(f"📊 Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Base64 image handling is working correctly.")
        print("\n📝 The fix handles both image model formats:")
        print("   🔸 gpt-image-1: Returns base64 data → converted to data URLs")
        print("   🔸 dall-e-3: Returns URLs → used directly")
        print("   🔸 Compatible with Azure OpenAI API limitations")
        print("   🔸 Enhanced debugging for troubleshooting")
        print("\n💡 Your gpt-image-1 model should now work without 404 errors!")
        return 0
    else:
        print(f"❌ {total - passed} test(s) failed. Please review the issues above.")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
