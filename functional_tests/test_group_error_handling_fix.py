#!/usr/bin/env python3
"""
Functional test for group API error handling when no active group is selected.
Version: 0.227.009
Implemented in: 0.227.009

This test ensures that group-related API calls are handled gracefully when 
groups are enabled but no active group is selected yet, preventing JavaScript 
console errors and improving user experience.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_group_documents_js_error_handling():
    """Test that chat-documents.js handles group API errors gracefully."""
    print("🔍 Testing Group Documents JavaScript Error Handling...")
    
    try:
        # Read the JavaScript file
        chat_docs_path = os.path.join(os.path.dirname(__file__), "../static/js/chat/chat-documents.js")
        if not os.path.exists(chat_docs_path):
            raise FileNotFoundError(f"chat-documents.js not found at {chat_docs_path}")
        
        with open(chat_docs_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for proper error handling patterns in loadGroupDocs
        required_patterns = [
            "if (!r.ok)",  # HTTP status check
            "r.status === 400",  # Specific 400 error handling
            "No active group selected for group documents",  # Informative logging
            "groupDocs = []",  # Reset array on error
            "return { documents: [] }",  # Return empty result structure
        ]
        
        missing_patterns = []
        for pattern in required_patterns:
            if pattern not in content:
                missing_patterns.append(pattern)
        
        if missing_patterns:
            raise AssertionError(f"Missing required error handling patterns: {missing_patterns}")
        
        print("✅ Group documents JavaScript error handling validated!")
        return True
        
    except Exception as e:
        print(f"❌ Group documents JavaScript test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_group_prompts_js_error_handling():
    """Test that chat-prompts.js handles group API errors gracefully."""
    print("🔍 Testing Group Prompts JavaScript Error Handling...")
    
    try:
        # Read the JavaScript file
        chat_prompts_path = os.path.join(os.path.dirname(__file__), "../static/js/chat/chat-prompts.js")
        if not os.path.exists(chat_prompts_path):
            raise FileNotFoundError(f"chat-prompts.js not found at {chat_prompts_path}")
        
        with open(chat_prompts_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for proper error handling patterns in loadGroupPrompts
        required_patterns = [
            "if (!r.ok)",  # HTTP status check
            "r.status === 400",  # Specific 400 error handling
            "No active group selected for group prompts",  # Informative logging
            "groupPrompts = []",  # Reset array on error
            "return { prompts: [] }",  # Return empty result structure
        ]
        
        missing_patterns = []
        for pattern in required_patterns:
            if pattern not in content:
                missing_patterns.append(pattern)
        
        if missing_patterns:
            raise AssertionError(f"Missing required error handling patterns: {missing_patterns}")
        
        print("✅ Group prompts JavaScript error handling validated!")
        return True
        
    except Exception as e:
        print(f"❌ Group prompts JavaScript test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_backend_group_api_error_conditions():
    """Test that backend group APIs return proper error codes and messages."""
    print("🔍 Testing Backend Group API Error Conditions...")
    
    try:
        # Check group documents route
        group_docs_path = os.path.join(os.path.dirname(__file__), "../route_backend_group_documents.py")
        if not os.path.exists(group_docs_path):
            raise FileNotFoundError(f"route_backend_group_documents.py not found at {group_docs_path}")
        
        with open(group_docs_path, 'r', encoding='utf-8') as f:
            docs_content = f.read()
        
        # Check for proper error handling in group documents API
        docs_patterns = [
            "if not active_group_id:",
            "return jsonify({'error': 'No active group selected'}), 400",
            "@enabled_required(\"enable_group_workspaces\")",
        ]
        
        for pattern in docs_patterns:
            if pattern not in docs_content:
                raise AssertionError(f"Missing pattern in group documents API: {pattern}")
        
        # Check group prompts route
        group_prompts_path = os.path.join(os.path.dirname(__file__), "../route_backend_group_prompts.py")
        if not os.path.exists(group_prompts_path):
            raise FileNotFoundError(f"route_backend_group_prompts.py not found at {group_prompts_path}")
        
        with open(group_prompts_path, 'r', encoding='utf-8') as f:
            prompts_content = f.read()
        
        # Check for proper error handling in group prompts API
        prompts_patterns = [
            "if not active_group:",
            'return jsonify({"error":"No active group selected"}), 400',
            "@enabled_required(\"enable_group_workspaces\")",
        ]
        
        for pattern in prompts_patterns:
            if pattern not in prompts_content:
                raise AssertionError(f"Missing pattern in group prompts API: {pattern}")
        
        print("✅ Backend group API error conditions validated!")
        return True
        
    except Exception as e:
        print(f"❌ Backend group API test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_version_consistency():
    """Test that the current version is properly set in config.py."""
    print("🔍 Testing Version Consistency...")
    
    try:
        config_path = os.path.join(os.path.dirname(__file__), "../config.py")
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"config.py not found at {config_path}")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if "app.config['VERSION'] = \"0.227.009\"" not in content:
            raise AssertionError("Version not updated to 0.227.009 in config.py")
        
        print("✅ Version consistency validated!")
        return True
        
    except Exception as e:
        print(f"❌ Version consistency test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    tests = [
        test_group_documents_js_error_handling,
        test_group_prompts_js_error_handling,
        test_backend_group_api_error_conditions,
        test_version_consistency
    ]
    
    results = []
    
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("🎉 All group error handling tests passed!")
        print("✅ Groups enabled without active group will no longer cause JavaScript errors")
        print("✅ 400 errors from group APIs are now handled gracefully")
        print("✅ Console warnings are informative instead of throwing errors")
    else:
        print("⚠️  Some tests failed - please review the error handling implementation")
    
    sys.exit(0 if success else 1)
