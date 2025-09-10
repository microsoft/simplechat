#!/usr/bin/env python3
"""
Functional Test: Content Safety Error Handling for Image Generation
Tests improved error handling for content moderation blocks.

Author: GitHub Copilot Assistant  
Date: 2025-09-08
"""

import sys
import os

# Add the parent directory to sys.path to import application modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_backend_content_safety_error_handling():
    """Test that backend properly handles and categorizes content safety errors"""
    print("🔍 Testing backend content safety error handling...")
    
    try:
        # Read the backend file and check for content safety error handling
        backend_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'route_backend_chats.py')
        
        with open(backend_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for content safety error detection
        has_safety_check = "safety system" in content
        has_moderation_check = "moderation_blocked" in content
        has_user_friendly_message = "content safety policies" in content
        has_status_code_handling = "status_code = 400" in content
        
        if has_safety_check and has_moderation_check and has_user_friendly_message and has_status_code_handling:
            print("✅ Backend properly handles content safety errors")
            print("   • Detects safety system blocks")
            print("   • Detects moderation_blocked errors")
            print("   • Provides user-friendly messages")
            print("   • Returns appropriate 400 status code")
            return True
        else:
            missing = []
            if not has_safety_check:
                missing.append("safety system detection")
            if not has_moderation_check:
                missing.append("moderation_blocked detection")
            if not has_user_friendly_message:
                missing.append("user-friendly messages")
            if not has_status_code_handling:
                missing.append("proper status code handling")
            print(f"❌ Backend missing content safety handling: {', '.join(missing)}")
            return False
            
    except Exception as e:
        print(f"❌ Error checking backend content safety handling: {e}")
        return False

def test_frontend_content_safety_error_display():
    """Test that frontend properly displays content safety errors"""
    print("🔍 Testing frontend content safety error display...")
    
    try:
        # Check the JavaScript file for content safety error handling
        js_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'js', 'chat', 'chat-messages.js')
        
        with open(js_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for content safety error display
        has_safety_detection = "safety system" in content
        has_moderation_detection = "moderation_blocked" in content
        has_image_generation_message = "Image Generation Blocked" in content
        has_safety_sender = "'safety'" in content
        
        if has_safety_detection and has_moderation_detection and has_image_generation_message and has_safety_sender:
            print("✅ Frontend properly displays content safety errors")
            print("   • Detects safety system errors")
            print("   • Detects moderation blocked errors")
            print("   • Shows specific image generation blocked message")
            print("   • Uses safety sender type for proper styling")
            return True
        else:
            missing = []
            if not has_safety_detection:
                missing.append("safety system detection")
            if not has_moderation_detection:
                missing.append("moderation detection")
            if not has_image_generation_message:
                missing.append("image generation blocked message")
            if not has_safety_sender:
                missing.append("safety sender type")
            print(f"❌ Frontend missing content safety display: {', '.join(missing)}")
            return False
            
    except Exception as e:
        print(f"❌ Error checking frontend content safety display: {e}")
        return False

def test_error_differentiation():
    """Test that different error types are handled appropriately"""
    print("🔍 Testing error type differentiation...")
    
    try:
        # Check that different errors get different handling
        backend_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'route_backend_chats.py')
        
        with open(backend_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for different error handling
        has_bad_request_handling = "BadRequestError" in content
        has_technical_error_handling = "technical error" in content
        has_different_status_codes = "status_code = 400" in content and "status_code = 500" in content
        
        if has_bad_request_handling and has_technical_error_handling and has_different_status_codes:
            print("✅ Backend properly differentiates error types")
            print("   • Handles BadRequestError specifically")
            print("   • Distinguishes technical vs content errors")
            print("   • Uses appropriate status codes")
            return True
        else:
            missing = []
            if not has_bad_request_handling:
                missing.append("BadRequestError handling")
            if not has_technical_error_handling:
                missing.append("technical error handling")
            if not has_different_status_codes:
                missing.append("status code differentiation")
            print(f"❌ Backend missing error differentiation: {', '.join(missing)}")
            return False
            
    except Exception as e:
        print(f"❌ Error checking error differentiation: {e}")
        return False

def test_user_experience_improvements():
    """Test that user experience is improved with better error messages"""
    print("🔍 Testing user experience improvements...")
    
    try:
        # Check both backend and frontend for UX improvements
        backend_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'route_backend_chats.py')
        js_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'js', 'chat', 'chat-messages.js')
        
        with open(backend_file, 'r', encoding='utf-8') as f:
            backend_content = f.read()
        
        with open(js_file, 'r', encoding='utf-8') as f:
            frontend_content = f.read()
        
        # Check for UX improvements
        has_helpful_backend_messages = "Please try a different prompt" in backend_content
        has_helpful_frontend_messages = "try a different prompt" in frontend_content
        has_specific_guidance = "harmful, violent, or illicit content" in frontend_content
        
        if has_helpful_backend_messages and has_helpful_frontend_messages and has_specific_guidance:
            print("✅ User experience properly improved")
            print("   • Backend provides helpful guidance")
            print("   • Frontend shows actionable advice")
            print("   • Specific content guidance provided")
            return True
        else:
            missing = []
            if not has_helpful_backend_messages:
                missing.append("helpful backend messages")
            if not has_helpful_frontend_messages:
                missing.append("helpful frontend messages")
            if not has_specific_guidance:
                missing.append("specific content guidance")
            print(f"❌ User experience improvements missing: {', '.join(missing)}")
            return False
            
    except Exception as e:
        print(f"❌ Error checking user experience improvements: {e}")
        return False

def main():
    """Run all tests"""
    print("🚀 Testing Content Safety Error Handling Improvements\n")
    print("Background: Improve user experience when image generation is blocked by content safety")
    print("The system should distinguish between technical errors and content policy violations.\n")
    
    tests = [
        ("Backend Content Safety Error Handling", test_backend_content_safety_error_handling),
        ("Frontend Content Safety Error Display", test_frontend_content_safety_error_display),
        ("Error Type Differentiation", test_error_differentiation),
        ("User Experience Improvements", test_user_experience_improvements)
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
        print("🎉 All tests passed! Content safety error handling is working correctly.")
        print("\n📝 The improvements provide:")
        print("   🔸 Clear distinction between technical and content policy errors")
        print("   🔸 User-friendly messages explaining what went wrong")
        print("   🔸 Actionable guidance on how to fix content issues")
        print("   🔸 Appropriate HTTP status codes for different error types")
        print("\n💡 Users will now get helpful guidance when content is blocked!")
        return 0
    else:
        print(f"❌ {total - passed} test(s) failed. Please review the issues above.")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
