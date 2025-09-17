#!/usr/bin/env python3
"""
Functional test for workspace scope affecting prompts functionality.
Version: 0.229.042
Implemented in: 0.229.042

This test ensures that workspace scope selection (All, Personal, Group, Public) 
properly filters prompts in the same way it filters documents. When scope is 
changed, only prompts from the selected scope should be visible.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_prompt_scope_filtering_javascript_implementation():
    """Test that the JavaScript implementation properly handles prompt scope filtering."""
    print("🔍 Testing Workspace Scope Prompts Fix...")
    
    try:
        # Read the updated chat-prompts.js file
        chat_prompts_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "application",
            "single_app",
            "static",
            "js",
            "chat",
            "chat-prompts.js"
        )
        
        if not os.path.exists(chat_prompts_path):
            raise Exception(f"Chat prompts file not found: {chat_prompts_path}")
            
        with open(chat_prompts_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Test 1: Check if publicPrompts variable is declared in global
        chat_global_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "application",
            "single_app",
            "static",
            "js",
            "chat",
            "chat-global.js"
        )
        
        with open(chat_global_path, 'r', encoding='utf-8') as f:
            global_content = f.read()
            
        if "let publicPrompts = [];" not in global_content:
            raise Exception("❌ publicPrompts variable not declared in chat-global.js")
        print("✅ publicPrompts variable properly declared in global scope")
        
        # Test 2: Check if loadPublicPrompts function exists
        if "export function loadPublicPrompts()" not in content:
            raise Exception("❌ loadPublicPrompts function not found")
        print("✅ loadPublicPrompts function implemented")
        
        # Test 3: Check if loadPublicPrompts fetches from correct API endpoint
        if '"/api/public_prompts"' not in content:
            raise Exception("❌ loadPublicPrompts not using correct API endpoint")
        print("✅ loadPublicPrompts uses correct API endpoint (/api/public_prompts)")
        
        # Test 4: Check if populatePromptSelectScope function exists
        if "export function populatePromptSelectScope()" not in content:
            raise Exception("❌ populatePromptSelectScope function not found")
        print("✅ populatePromptSelectScope function implemented")
        
        # Test 5: Check if scope filtering logic is implemented
        scope_conditions = [
            'scopeVal === "all"',
            'scopeVal === "personal"', 
            'scopeVal === "group"',
            'scopeVal === "public"'
        ]
        
        for condition in scope_conditions:
            if condition not in content:
                raise Exception(f"❌ Scope filtering condition missing: {condition}")
        print("✅ All scope filtering conditions implemented (all, personal, group, public)")
        
        # Test 6: Check if prompts are properly labeled by scope
        scope_labels = [
            'scope: "Personal"',
            'scope: "Group"',
            'scope: "Public"'
        ]
        
        for label in scope_labels:
            if label not in content:
                raise Exception(f"❌ Scope label missing: {label}")
        print("✅ Prompts properly labeled with scope (Personal, Group, Public)")
        
        # Test 7: Check if loadAllPrompts function exists
        if "export function loadAllPrompts()" not in content:
            raise Exception("❌ loadAllPrompts function not found")
        print("✅ loadAllPrompts function implemented")
        
        # Test 8: Check if loadAllPrompts loads all three types of prompts
        all_loads = [
            "loadUserPrompts()",
            "loadGroupPrompts()", 
            "loadPublicPrompts()"
        ]
        
        for load_func in all_loads:
            if load_func not in content:
                raise Exception(f"❌ loadAllPrompts missing: {load_func}")
        print("✅ loadAllPrompts loads all prompt types (user, group, public)")
        
        # Test 9: Check if scope change event listener is added
        if 'docScopeSelect.addEventListener("change"' not in content:
            raise Exception("❌ Scope change event listener not added")
        print("✅ Scope change event listener properly added")
        
        # Test 10: Check if imports include docScopeSelect
        if 'import { docScopeSelect } from "./chat-documents.js";' not in content:
            raise Exception("❌ docScopeSelect import missing")
        print("✅ docScopeSelect properly imported from chat-documents.js")
        
        # Test 11: Check version update in config.py
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "application",
            "single_app",
            "config.py"
        )
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config_content = f.read()
            
        if 'VERSION = "0.229.042"' not in config_content:
            raise Exception("❌ Version not updated in config.py")
        print("✅ Version properly updated to 0.229.042 in config.py")
        
        print("✅ All workspace scope prompts functionality tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_api_endpoints_exist():
    """Test that required API endpoints exist for public prompts."""
    print("\n🔍 Testing API Endpoints...")
    
    try:
        # Check if public prompts route file exists
        route_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "application",
            "single_app",
            "route_backend_public_prompts.py"
        )
        
        if not os.path.exists(route_path):
            raise Exception("❌ route_backend_public_prompts.py not found")
        
        with open(route_path, 'r', encoding='utf-8') as f:
            route_content = f.read()
        
        # Check for required API endpoints
        required_endpoints = [
            "'/api/public_prompts', methods=['GET']",
            "'/api/public_prompts', methods=['POST']",
            "'/api/public_prompts/<prompt_id>', methods=['GET']"
        ]
        
        for endpoint in required_endpoints:
            if endpoint not in route_content:
                raise Exception(f"❌ API endpoint missing: {endpoint}")
        
        print("✅ All required API endpoints exist for public prompts")
        return True
        
    except Exception as e:
        print(f"❌ API endpoint test failed: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Running Workspace Scope Prompts Fix Tests...\n")
    
    test1_result = test_prompt_scope_filtering_javascript_implementation()
    test2_result = test_api_endpoints_exist()
    
    success = test1_result and test2_result
    
    print(f"\n📊 Results: {'2/2' if success else '0/2 or 1/2'} tests passed")
    
    if success:
        print("\n🎉 Workspace scope prompts fix implementation verified!")
        print("📋 Summary of changes:")
        print("   • Added publicPrompts variable to chat-global.js")
        print("   • Implemented loadPublicPrompts() function")
        print("   • Created populatePromptSelectScope() for scope-aware filtering")
        print("   • Added loadAllPrompts() to load all prompt types")
        print("   • Added scope change event listener")
        print("   • Updated version to 0.229.042")
        print("\n🔧 How it works:")
        print("   • When scope is 'All': shows Personal + Group + Public prompts")
        print("   • When scope is 'Personal': shows only Personal prompts")
        print("   • When scope is 'Group': shows only Group prompts") 
        print("   • When scope is 'Public': shows only Public prompts")
        print("   • Scope changes automatically update prompt list")
    else:
        print("\n❌ Some tests failed. Please review the implementation.")
    
    sys.exit(0 if success else 1)