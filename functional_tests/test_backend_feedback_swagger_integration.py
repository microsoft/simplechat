#!/usr/bin/env python3
"""
Functional test for backend feedback swagger integration.
Version: 0.250.075
Implemented in: 0.229.069

This test ensures that all feedback endpoints in route_backend_feedback.py 
have proper swagger integration with @swagger_route decorators and authentication security.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

def test_feedback_swagger_imports():
    """Test that swagger imports are properly added to feedback route file."""
    print("🔍 Testing feedback swagger imports...")
    
    try:
        # Read the route file
        route_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            '..', 'application', 'single_app', 
            'route_backend_feedback.py'
        )
        
        with open(route_file_path, 'r') as f:
            content = f.read()
        
        # Verify swagger imports are present
        if 'from swagger_wrapper import swagger_route, get_auth_security' not in content:
            print("❌ Missing swagger wrapper imports")
            return False
            
        print("✅ Swagger imports found successfully")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_feedback_swagger_decorators():
    """Test that all feedback endpoints have proper swagger decorators."""
    print("🔍 Testing feedback swagger decorators...")
    
    try:
        # Read the route file
        route_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            '..', 'application', 'single_app', 
            'route_backend_feedback.py'
        )
        
        with open(route_file_path, 'r') as f:
            content = f.read()
        
        # Expected endpoints that should have swagger decorators
        expected_endpoints = [
            '/feedback/submit',
            '/feedback/review',
            '/feedback/review/stats',
            '/feedback/review/export',
            '/feedback/review/<feedbackId>',  # GET and PATCH versions
            '/feedback/review/<feedbackId>/archive',
            '/feedback/retest/<feedbackId>',
            '/feedback/my',
            '/feedback/my/stats',
            '/feedback/my/export',
        ]
        
        # Track found decorators
        decorated_endpoints = 0
        
        # Split content into lines for analysis
        lines = content.split('\n')
        
        for i, line in enumerate(lines):
            if '@bp.route(' in line:
                # Found a route, check if next line has swagger decorator
                if i + 1 < len(lines) and '@swagger_route(security=get_auth_security())' in lines[i + 1]:
                    decorated_endpoints += 1
                    print(f"✅ Found properly decorated endpoint: {line.strip()}")
                else:
                    print(f"❌ Missing swagger decorator for: {line.strip()}")
                    return False
        
        expected_route_count = 12
        if decorated_endpoints != expected_route_count:
            print(f"❌ Expected {expected_route_count} decorated endpoints, found {decorated_endpoints}")
            return False
            
        print(f"✅ All {decorated_endpoints} feedback endpoints properly decorated")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_feedback_decorator_order():
    """Test that decorators are in correct order: @app.route -> @swagger_route -> @login_required."""
    print("🔍 Testing feedback decorator order...")
    
    try:
        # Read the route file
        route_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            '..', 'application', 'single_app', 
            'route_backend_feedback.py'
        )
        
        with open(route_file_path, 'r') as f:
            content = f.read()
        
        lines = content.split('\n')
        route_count = 0
        
        for i, line in enumerate(lines):
            if '@bp.route(' in line:
                route_count += 1
                
                # Check if decorators are in correct order
                if (i + 1 < len(lines) and '@swagger_route(security=get_auth_security())' in lines[i + 1] and
                    i + 2 < len(lines) and '@login_required' in lines[i + 2]):
                    print(f"✅ Correct decorator order for endpoint {route_count}")
                else:
                    print(f"❌ Incorrect decorator order for endpoint {route_count}")
                    print(f"   Route: {line.strip()}")
                    if i + 1 < len(lines):
                        print(f"   Next: {lines[i + 1].strip()}")
                    if i + 2 < len(lines):
                        print(f"   Then: {lines[i + 2].strip()}")
                    return False
        
        print(f"✅ All {route_count} endpoints have correct decorator order")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_feedback_endpoint_coverage():
    """Test comprehensive coverage of all feedback endpoints."""
    print("🔍 Testing feedback endpoint coverage...")
    
    try:
        # Read the route file
        route_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            '..', 'application', 'single_app', 
            'route_backend_feedback.py'
        )
        
        with open(route_file_path, 'r') as f:
            content = f.read()
        
        # Expected feedback management functions
        expected_functions = [
            'feedback_submit',
            'feedback_review_get',
            'feedback_review_get_single',
            'feedback_review_update',
            'feedback_review_archive',
            'feedback_review_delete',
            'feedback_retest',
            'feedback_my',
            'feedback_my_stats',
            'feedback_my_export',
        ]
        
        found_functions = []
        
        for func_name in expected_functions:
            if f'def {func_name}(' in content:
                found_functions.append(func_name)
                print(f"✅ Found function: {func_name}")
            else:
                print(f"❌ Missing function: {func_name}")
                return False
        
        if len(found_functions) != len(expected_functions):
            print(f"❌ Expected {len(expected_functions)} functions, found {len(found_functions)}")
            return False
            
        print(f"✅ All {len(found_functions)} feedback functions found")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_feedback_auth_security_integration():
    """Test that get_auth_security() is properly integrated in swagger decorators."""
    print("🔍 Testing feedback auth security integration...")
    
    try:
        # Read the route file
        route_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            '..', 'application', 'single_app', 
            'route_backend_feedback.py'
        )
        
        with open(route_file_path, 'r') as f:
            content = f.read()
        
        # Count occurrences of security integration
        security_decorators = content.count('@swagger_route(security=get_auth_security())')
        app_routes = content.count('@bp.route(')
        
        if security_decorators != app_routes:
            print(f"❌ Mismatch: {app_routes} routes but {security_decorators} security decorators")
            return False
            
        # Verify get_auth_security is imported
        if 'get_auth_security' not in content:
            print("❌ get_auth_security function not imported")
            return False
            
        print(f"✅ All {security_decorators} endpoints have proper auth security integration")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_feedback_role_based_access():
    """Test that role-based access decorators are preserved (admin vs user)."""
    print("🔍 Testing feedback role-based access preservation...")
    
    try:
        # Read the route file
        route_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            '..', 'application', 'single_app', 
            'route_backend_feedback.py'
        )
        
        with open(route_file_path, 'r') as f:
            content = f.read()
        
        # Count admin and user required decorators
        admin_required_count = content.count('@feedback_admin_required')
        user_required_count = content.count('@user_required')
        
        expected_admin = 8
        expected_user = 4
        
        if admin_required_count != expected_admin:
            print(f"❌ Expected {expected_admin} @admin_required decorators, found {admin_required_count}")
            return False
            
        if user_required_count != expected_user:
            print(f"❌ Expected {expected_user} @user_required decorators, found {user_required_count}")
            return False
            
        print(f"✅ Role-based access preserved: {admin_required_count} admin, {user_required_count} user endpoints")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_feedback_enabled_required_preservation():
    """Test that @enabled_required decorators are preserved for all endpoints."""
    print("🔍 Testing feedback enabled_required preservation...")
    
    try:
        # Read the route file
        route_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            '..', 'application', 'single_app', 
            'route_backend_feedback.py'
        )
        
        with open(route_file_path, 'r') as f:
            content = f.read()
        
        # All feedback endpoints should have @enabled_required("enable_user_feedback")
        enabled_required_count = content.count('@enabled_required("enable_user_feedback")')
        
        expected_enabled_required = 12
        
        if enabled_required_count != expected_enabled_required:
            print(f"❌ Expected {expected_enabled_required} @enabled_required decorators, found {enabled_required_count}")
            return False
            
        print(f"✅ All {enabled_required_count} feedback endpoints have @enabled_required preservation")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🧪 Running Backend Feedback Swagger Integration Tests...")
    print("=" * 60)
    
    tests = [
        test_feedback_swagger_imports,
        test_feedback_swagger_decorators,
        test_feedback_decorator_order,
        test_feedback_endpoint_coverage,
        test_feedback_auth_security_integration,
        test_feedback_role_based_access,
        test_feedback_enabled_required_preservation
    ]
    
    results = []
    
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    passed = sum(results)
    total = len(results)
    
    print("\n" + "=" * 60)
    print(f"📊 Test Results: {passed}/{total} tests passed")
    
    if success:
        print("✅ All feedback swagger integration tests PASSED!")
        print("🎉 Swagger integration successfully applied to all feedback endpoints")
        print("📚 All endpoints will now appear in /swagger documentation")
        print("🔐 Authentication security properly configured for all endpoints")
        print("👥 Role-based access (admin/user) properly preserved")
        print("🔒 Feedback enabling requirements preserved for all endpoints")
    else:
        print("❌ Some tests FAILED!")
        print("⚠️  Please review the swagger integration implementation")
    
    sys.exit(0 if success else 1)