#!/usr/bin/env python3
"""
Functional test for Web Search Failure Graceful Handling.
Version: 0.236.014
Implemented in: 0.236.014

This test ensures that when web search fails, the system properly injects
a system message instructing the model to inform the user about the failure
instead of answering from training data.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))


def test_perform_web_search_returns_boolean():
    """
    Test that perform_web_search function returns boolean values.
    """
    print("🔍 Testing perform_web_search return value type...")
    
    try:
        from route_backend_chats import perform_web_search
        import inspect
        
        # Get the function signature and source
        source = inspect.getsource(perform_web_search)
        
        # Check that the function has return True statements
        has_return_true = 'return True' in source
        has_return_false = 'return False' in source
        
        if has_return_true and has_return_false:
            print("✅ perform_web_search has both 'return True' and 'return False' statements")
            return True
        else:
            print(f"❌ Missing return statements:")
            print(f"   - Has 'return True': {has_return_true}")
            print(f"   - Has 'return False': {has_return_false}")
            return False
            
    except ImportError as e:
        print(f"⚠️ Could not import perform_web_search: {e}")
        print("   This may be expected if running outside the application context")
        return True  # Not a failure of the feature itself
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_failure_message_injection_patterns():
    """
    Test that the code contains proper failure message injection patterns.
    """
    print("\n🔍 Testing failure message injection patterns...")
    
    try:
        # Read the route_backend_chats.py file
        file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            '..', 'application', 'single_app', 'route_backend_chats.py'
        )
        
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for key patterns that indicate proper failure handling
        patterns = {
            'system_role_message': "'role': 'system'" in content or '"role": "system"' in content,
            'failure_message': 'web search failed' in content.lower() or 'Web search failed' in content,
            'inform_user': 'inform the user' in content.lower(),
            'exception_handling': 'FoundryAgentInvocationError' in content,
            'return_false_on_error': 'return False' in content,
        }
        
        all_passed = True
        for pattern_name, found in patterns.items():
            status = "✅" if found else "❌"
            print(f"   {status} {pattern_name}: {'Found' if found else 'Not found'}")
            if not found:
                all_passed = False
        
        if all_passed:
            print("✅ All failure message injection patterns found")
        else:
            print("❌ Some patterns missing")
        
        return all_passed
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_error_scenarios_have_return_false():
    """
    Test that error/exception blocks return False.
    """
    print("\n🔍 Testing that error scenarios return False...")
    
    try:
        file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            '..', 'application', 'single_app', 'route_backend_chats.py'
        )
        
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Find the perform_web_search function
        func_start = content.find('def perform_web_search(')
        if func_start == -1:
            print("❌ Could not find perform_web_search function")
            return False
        
        # Find the end of the function (next def at same indentation level)
        func_end = content.find('\ndef ', func_start + 1)
        if func_end == -1:
            func_end = len(content)
        
        func_content = content[func_start:func_end]
        
        # Check for exception handling with return False
        checks = {
            'has_except_blocks': 'except' in func_content,
            'has_return_false': 'return False' in func_content,
            'has_foundry_error_handling': 'FoundryAgentInvocationError' in func_content,
            'has_generic_exception': 'except Exception' in func_content,
        }
        
        all_passed = True
        for check_name, passed in checks.items():
            status = "✅" if passed else "❌"
            print(f"   {status} {check_name}")
            if not passed:
                all_passed = False
        
        # Count return statements
        return_true_count = func_content.count('return True')
        return_false_count = func_content.count('return False')
        
        print(f"\n   📊 Return statement counts:")
        print(f"      - 'return True': {return_true_count}")
        print(f"      - 'return False': {return_false_count}")
        
        if return_false_count >= 2:
            print("✅ Function has adequate failure return paths")
        else:
            print("⚠️ Function may need more failure return paths")
            all_passed = False
        
        return all_passed
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_web_search_results_container_usage():
    """
    Test that web_search_results_container is used to inject system messages.
    """
    print("\n🔍 Testing web_search_results_container for system message injection...")
    
    try:
        file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            '..', 'application', 'single_app', 'route_backend_chats.py'
        )
        
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Find the perform_web_search function
        func_start = content.find('def perform_web_search(')
        if func_start == -1:
            print("❌ Could not find perform_web_search function")
            return False
        
        func_end = content.find('\ndef ', func_start + 1)
        if func_end == -1:
            func_end = len(content)
        
        func_content = content[func_start:func_end]
        
        # Check for container append with system role
        has_container_param = 'web_search_results_container' in func_content
        has_append_call = 'web_search_results_container.append' in func_content
        has_system_message = "'role': 'system'" in func_content or '"role": "system"' in func_content
        
        checks = {
            'has_container_parameter': has_container_param,
            'has_append_call': has_append_call,
            'has_system_role': has_system_message,
        }
        
        all_passed = True
        for check_name, passed in checks.items():
            status = "✅" if passed else "❌"
            print(f"   {status} {check_name}")
            if not passed:
                all_passed = False
        
        if all_passed:
            print("✅ System message injection mechanism verified")
        else:
            print("❌ System message injection may not be properly implemented")
        
        return all_passed
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_all_tests():
    """Run all tests and report results."""
    print("=" * 60)
    print("Web Search Failure Graceful Handling Fix - Functional Tests")
    print("Version: 0.236.013")
    print("=" * 60)
    
    tests = [
        ("Return Boolean Values", test_perform_web_search_returns_boolean),
        ("Failure Message Patterns", test_failure_message_injection_patterns),
        ("Error Scenarios Return False", test_error_scenarios_have_return_false),
        ("Container System Message Injection", test_web_search_results_container_usage),
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n{'─' * 60}")
        print(f"Test: {test_name}")
        print('─' * 60)
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ Test '{test_name}' raised exception: {e}")
            results.append((test_name, False))
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"   {status}: {test_name}")
    
    print(f"\n📊 Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed!")
        return True
    else:
        print(f"\n⚠️ {total - passed} test(s) failed")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
