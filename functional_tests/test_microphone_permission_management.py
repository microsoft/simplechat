#!/usr/bin/env python3
"""
Functional test for microphone permission management feature.
Version: 0.234.108
Implemented in: 0.234.108

This test validates:
1. Backend route accepts microphone permission settings
2. Profile.html contains microphone settings section
3. JavaScript functions exist for managing microphone permissions
4. chat-speech-input.js contains permission management code
"""

import sys
import os
import re

def test_backend_allowed_keys():
    """Test that microphone settings are in allowed_keys list."""
    print("🔍 Test 1: Checking backend allowed_keys...")
    
    try:
        route_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app', 'route_backend_users.py'
        )
        
        with open(route_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for microphone permission keys
        if 'microphonePermissionPreference' not in content:
            raise Exception("microphonePermissionPreference not found in allowed_keys")
        
        if 'microphonePermissionState' not in content:
            raise Exception("microphonePermissionState not found in allowed_keys")
        
        print("✅ Backend allowed_keys contains microphone settings")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False

def test_profile_html_section():
    """Test that profile.html contains microphone settings section."""
    print("\n🔍 Test 2: Checking profile.html microphone settings section...")
    
    try:
        profile_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app', 'templates', 'profile.html'
        )
        
        with open(profile_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for speech settings section
        if 'id="speech-settings"' not in content:
            raise Exception("speech-settings section not found")
        
        # Check for microphone permission radio buttons
        if 'name="microphonePermissionPreference"' not in content:
            raise Exception("microphonePermissionPreference radio buttons not found")
        
        # Check for saveMicrophoneSettings function
        if 'function saveMicrophoneSettings()' not in content:
            raise Exception("saveMicrophoneSettings function not found")
        
        # Check for loadMicrophoneSettings function
        if 'function loadMicrophoneSettings()' not in content:
            raise Exception("loadMicrophoneSettings function not found")
        
        # Check for updateMicrophoneStatusBadge function
        if 'function updateMicrophoneStatusBadge' not in content:
            raise Exception("updateMicrophoneStatusBadge function not found")
        
        # Check for status badge
        if 'microphone-status-badge' not in content:
            raise Exception("microphone-status-badge not found")
        
        # Check for preference options
        if 'value="remember"' not in content:
            raise Exception("'remember' preference option not found")
        if 'value="ask-every-session"' not in content:
            raise Exception("'ask-every-session' preference option not found")
        if 'value="ask-every-page-load"' not in content:
            raise Exception("'ask-every-page-load' preference option not found")
        
        print("✅ profile.html contains complete microphone settings section")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False

def test_chat_speech_input_js():
    """Test that chat-speech-input.js contains permission management code."""
    print("\n🔍 Test 3: Checking chat-speech-input.js permission management...")
    
    try:
        js_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app', 'static', 'js', 'chat', 'chat-speech-input.js'
        )
        
        with open(js_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for import of saveUserSetting
        if 'saveUserSetting' not in content:
            raise Exception("saveUserSetting import not found")
        
        # Check for permission state variables
        if 'microphonePermissionState' not in content:
            raise Exception("microphonePermissionState variable not found")
        if 'userMicrophonePreference' not in content:
            raise Exception("userMicrophonePreference variable not found")
        if 'sessionPermissionRequested' not in content:
            raise Exception("sessionPermissionRequested variable not found")
        
        # Check for key functions
        if 'handleSpeechButtonClick' not in content:
            raise Exception("handleSpeechButtonClick function not found")
        if 'loadMicrophonePreference' not in content:
            raise Exception("loadMicrophonePreference function not found")
        if 'checkMicrophonePermissionState' not in content:
            raise Exception("checkMicrophonePermissionState function not found")
        if 'updateMicrophoneIconState' not in content:
            raise Exception("updateMicrophoneIconState function not found")
        if 'shouldRequestPermission' not in content:
            raise Exception("shouldRequestPermission function not found")
        if 'savePermissionState' not in content:
            raise Exception("savePermissionState function not found")
        
        # Check for icon color classes
        if 'text-success' not in content or 'text-danger' not in content or 'text-secondary' not in content:
            raise Exception("Icon color classes not found")
        
        # Check for navigation to profile on denied
        if "window.location.href = '/profile#speech-settings'" not in content:
            raise Exception("Profile navigation on denied permission not found")
        
        print("✅ chat-speech-input.js contains complete permission management code")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False

def test_config_version():
    """Test that config.py version was updated."""
    print("\n🔍 Test 4: Checking config.py version...")
    
    try:
        config_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app', 'config.py'
        )
        
        with open(config_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for version update
        version_match = re.search(r'VERSION\s*=\s*["\']([^"\']+)["\']', content)
        if not version_match:
            raise Exception("VERSION not found in config.py")
        
        version = version_match.group(1)
        print(f"   Found version: {version}")
        
        # Verify version is 0.234.108 or higher
        version_parts = version.split('.')
        if len(version_parts) != 3:
            raise Exception(f"Invalid version format: {version}")
        
        major, minor, patch = map(int, version_parts)
        expected_version = (0, 234, 108)
        current_version = (major, minor, patch)
        
        if current_version < expected_version:
            raise Exception(f"Version {version} is older than expected {'.'.join(map(str, expected_version))}")
        
        print(f"✅ config.py version is {version} (>= 0.234.108)")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False

if __name__ == "__main__":
    print("\n" + "="*60)
    print("🧪 Microphone Permission Management Functional Test")
    print("="*60)
    
    # Run tests
    test1_passed = test_backend_allowed_keys()
    test2_passed = test_profile_html_section()
    test3_passed = test_chat_speech_input_js()
    test4_passed = test_config_version()
    
    success = test1_passed and test2_passed and test3_passed and test4_passed
    
    print("\n" + "="*60)
    if success:
        print("✅ All tests completed successfully!")
        print("="*60)
        print("\n📋 Summary:")
        print("  ✅ Backend route accepts microphone permission settings")
        print("  ✅ Profile page contains microphone settings UI")
        print("  ✅ JavaScript implements permission management")
        print("  ✅ Version updated correctly")
    else:
        print("❌ Some tests failed!")
        print("="*60)
    
    sys.exit(0 if success else 1)
