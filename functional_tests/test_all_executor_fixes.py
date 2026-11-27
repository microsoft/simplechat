#!/usr/bin/env python3
# test_all_executor_fixes.py
"""
Test all executor fixes across multiple route files.
Version: 0.228.007

This test validates that all executor references have been properly fixed
across all route files that use background task processing.
Implemented in: 0.229.001
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

def test_executor_imports():
    """Test that all route files can import without executor errors."""
    print("🔍 Testing executor imports across all route files...")
    
    import_results = {}
    
    route_files = [
        'route_backend_documents',
        'route_backend_group_documents', 
        'route_backend_public_documents',
        'route_external_public_documents'
    ]
    
    for route_file in route_files:
        try:
            print(f"   Testing {route_file}...")
            __import__(route_file)
            import_results[route_file] = True
            print(f"   ✅ {route_file} imported successfully")
        except Exception as e:
            import_results[route_file] = False
            print(f"   ❌ {route_file} failed: {e}")
    
    return all(import_results.values())

def test_app_initialization():
    """Test that the app initializes properly with all routes."""
    print("\n🔍 Testing full app initialization...")
    
    try:
        import app
        print(f"   ✅ App initialized successfully")
        print(f"   Flask app: {app.app}")
        print(f"   Executor in extensions: {'executor' in app.app.extensions}")
        
        if 'executor' in app.app.extensions:
            executor = app.app.extensions['executor']
            print(f"   Executor type: {type(executor)}")
            print(f"   ✅ Executor properly accessible")
            return True
        else:
            print(f"   ❌ Executor not found in app extensions")
            return False
            
    except Exception as e:
        print(f"   ❌ App initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_background_task_submission():
    """Test that background tasks can be submitted properly."""
    print("\n🔍 Testing background task submission...")
    
    try:
        import app
        from flask import Flask
        
        # Create test client to have application context
        with app.app.app_context():
            executor = app.current_app.extensions['executor']
            
            # Test a simple background task
            def test_task():
                return "Background task completed"
            
            # Submit the task
            future = executor.submit(test_task)
            result = future.result(timeout=5)  # Wait up to 5 seconds
            
            if result == "Background task completed":
                print("   ✅ Background task submission working")
                return True
            else:
                print(f"   ❌ Unexpected task result: {result}")
                return False
                
    except Exception as e:
        print(f"   ❌ Background task test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_route_registration():
    """Test that all routes are properly registered."""
    print("\n🔍 Testing route registration...")
    
    try:
        import app
        
        # Check for upload-related routes
        upload_routes = []
        metadata_routes = []
        
        for rule in app.app.url_map.iter_rules():
            rule_str = str(rule.rule)
            if 'upload' in rule_str:
                upload_routes.append(rule_str)
            elif 'metadata' in rule_str:
                metadata_routes.append(rule_str)
        
        print(f"   Upload routes found: {len(upload_routes)}")
        for route in upload_routes[:3]:  # Show first 3
            print(f"     {route}")
            
        print(f"   Metadata routes found: {len(metadata_routes)}")
        for route in metadata_routes[:3]:  # Show first 3
            print(f"     {route}")
        
        if len(upload_routes) > 0 and len(metadata_routes) > 0:
            print("   ✅ Routes properly registered")
            return True
        else:
            print("   ⚠️  Some expected routes missing")
            return False
            
    except Exception as e:
        print(f"   ❌ Route registration test failed: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Testing executor fixes across all route files...")
    
    # Run all tests
    import_success = test_executor_imports()
    app_success = test_app_initialization()
    task_success = test_background_task_submission()
    route_success = test_route_registration()
    
    # Summary
    print(f"\n📊 Test Results:")
    print(f"  Route imports: {'✅ PASSED' if import_success else '❌ FAILED'}")
    print(f"  App initialization: {'✅ PASSED' if app_success else '❌ FAILED'}")
    print(f"  Background tasks: {'✅ PASSED' if task_success else '❌ FAILED'}")
    print(f"  Route registration: {'✅ PASSED' if route_success else '❌ FAILED'}")
    
    overall_success = all([import_success, app_success, task_success, route_success])
    print(f"  Overall: {'✅ PASSED' if overall_success else '❌ FAILED'}")
    
    if overall_success:
        print("\n🎉 All executor fixes working properly!")
        print("   File uploads should now work across all workspace types:")
        print("   - Personal workspace documents")
        print("   - Group documents") 
        print("   - Public workspace documents")
        print("   - External public documents")
    else:
        print("\n⚠️  Some issues remain - check individual test results above")
    
    sys.exit(0 if overall_success else 1)
