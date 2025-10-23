#!/usr/bin/env python3
"""
Functional test for unused schema cleanup.
Version: 0.230.045
Implemented in: 0.230.045

This test ensures that the unused hardcoded schemas (BulkIdsRequest, ChatRequest, SimpleIdRequest)
have been removed from the OpenAPI specification generation, leaving only essential schemas.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_unused_schema_removal():
    """Test that unused hardcoded schemas have been removed."""
    print("🧪 Testing unused schema cleanup...")
    
    try:
        # Import from the application directory
        sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app'))
        
        from swagger_wrapper import _generate_dynamic_schemas, extract_route_info
        from flask import Flask
        
        # Test basic schema generation
        app = Flask(__name__)
        app.config['VERSION'] = '0.230.045'
        
        print("  🔍 Testing schema generation...")
        schemas = _generate_dynamic_schemas(app)
        
        print(f"  📊 Generated {len(schemas)} schemas: {list(schemas.keys())}")
        
        # Check that unused schemas are not generated
        unused_schemas = ['BulkIdsRequest', 'ChatRequest', 'SimpleIdRequest']
        found_unused = []
        
        for schema_name in unused_schemas:
            if schema_name in schemas:
                found_unused.append(schema_name)
        
        if found_unused:
            print(f"  ❌ Found unused schemas that should have been removed: {found_unused}")
            return False
            
        print("  ✅ No unused hardcoded schemas found in generation")
        
        # Test full OpenAPI spec generation
        print("  🔍 Testing full OpenAPI spec generation...")
        spec = extract_route_info(app)
        
        spec_schemas = spec.get('components', {}).get('schemas', {})
        spec_unused = []
        
        for schema_name in unused_schemas:
            if schema_name in spec_schemas:
                spec_unused.append(schema_name)
        
        if spec_unused:
            print(f"  ❌ Found unused schemas in OpenAPI spec: {spec_unused}")
            return False
            
        print("  ✅ No unused schemas in OpenAPI specification")
        
        # Check that essential schemas remain
        essential_schemas = ['ErrorResponse']
        missing_essential = []
        
        for schema_name in essential_schemas:
            if schema_name not in spec_schemas:
                missing_essential.append(schema_name)
                
        if missing_essential:
            print(f"  ❌ Missing essential schemas: {missing_essential}")
            return False
            
        print("  ✅ Essential schemas are present")
        
        # Test with actual routes
        print("  🔍 Testing with real routes...")
        try:
            import route_frontend_admin_settings
            import route_api_admin_settings
            
            spec_with_routes = extract_route_info(app)
            routes_schemas = spec_with_routes.get('components', {}).get('schemas', {})
            
            print(f"  📊 With routes: {len(routes_schemas)} schemas")
            
            # Still no unused schemas should appear
            routes_unused = []
            for schema_name in unused_schemas:
                if schema_name in routes_schemas:
                    routes_unused.append(schema_name)
            
            if routes_unused:
                print(f"  ❌ Found unused schemas with routes: {routes_unused}")
                return False
                
            print("  ✅ No unused schemas even with routes loaded")
            
        except ImportError as e:
            print(f"  ⚠️  Could not import routes (expected in test environment): {e}")
            
        print("\n🎉 All tests passed!")
        print("✅ Unused schema cleanup successful")
        print(f"✅ Only essential schemas remain: {list(spec_schemas.keys())}")
        return True
        
    except Exception as e:
        print(f"  ❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_removed_functions():
    """Test that unused functions have been removed from the codebase."""
    print("\n🧪 Testing removed functions...")
    
    try:
        sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app'))
        import swagger_wrapper
        
        # Check that removed functions are no longer available
        removed_functions = [
            '_get_schema_ref_for_route',
            '_analyze_route_patterns', 
            '_route_matches_pattern',
            '_generate_minimal_required_schemas'
        ]
        
        found_removed = []
        for func_name in removed_functions:
            if hasattr(swagger_wrapper, func_name):
                found_removed.append(func_name)
                
        if found_removed:
            print(f"  ❌ Found functions that should have been removed: {found_removed}")
            return False
            
        print("  ✅ All unused functions have been removed")
        return True
        
    except Exception as e:
        print(f"  ❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🔧 Testing Unused Schema Cleanup")
    print("=" * 50)
    
    success1 = test_unused_schema_removal()
    success2 = test_removed_functions()
    
    overall_success = success1 and success2
    
    print("\n" + "=" * 50)
    if overall_success:
        print("🎉 ALL TESTS PASSED! Unused schema cleanup is complete.")
        print("✅ OpenAPI spec generation is now more efficient and accurate.")
    else:
        print("❌ Some tests failed. Please review the cleanup.")
        
    sys.exit(0 if overall_success else 1)