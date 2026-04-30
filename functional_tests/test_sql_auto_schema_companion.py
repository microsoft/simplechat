#!/usr/bin/env python3
"""
Functional test for SQL Auto Schema Companion Plugin creation.
Version: 0.239.015
Implemented in: 0.239.015

This test ensures that when a SQL Query plugin is loaded via LoggedPluginLoader,
a companion SQL Schema plugin is automatically created and registered in the kernel.
This fixes the issue where agents with only a sql_query action configured would have
no schema awareness, causing the LLM to ask for clarification instead of querying.

Additionally validates that:
- SQLQueryPlugin @kernel_function descriptions are resilient (don't demand non-existent functions)
- The _extract_sql_schema_for_instructions fallback detects SQLQueryPlugin instances
"""

import sys
import os
import inspect

# Add the application directory to the path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))


def test_companion_schema_plugin_method_exists():
    """Test that LoggedPluginLoader has the _auto_create_companion_schema_plugin method."""
    print("🔍 Testing _auto_create_companion_schema_plugin method exists...")
    
    try:
        from semantic_kernel_plugins.logged_plugin_loader import LoggedPluginLoader
        
        assert hasattr(LoggedPluginLoader, '_auto_create_companion_schema_plugin'), \
            "LoggedPluginLoader must have _auto_create_companion_schema_plugin method"
        
        method = getattr(LoggedPluginLoader, '_auto_create_companion_schema_plugin')
        assert callable(method), "_auto_create_companion_schema_plugin must be callable"
        
        # Verify method signature includes query_manifest and query_plugin_name
        sig = inspect.signature(method)
        param_names = list(sig.parameters.keys())
        assert 'query_manifest' in param_names, "Method must accept query_manifest parameter"
        assert 'query_plugin_name' in param_names, "Method must accept query_plugin_name parameter"
        
        print("✅ _auto_create_companion_schema_plugin method exists with correct signature!")
        return True
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_companion_creation_triggered_for_sql_query():
    """Test that load_plugin_from_manifest triggers companion creation for sql_query type."""
    print("🔍 Testing companion creation trigger in load_plugin_from_manifest...")
    
    try:
        from semantic_kernel_plugins.logged_plugin_loader import LoggedPluginLoader
        
        source = inspect.getsource(LoggedPluginLoader.load_plugin_from_manifest)
        
        # The method should check for sql_query type and call companion creation
        assert "plugin_type == 'sql_query'" in source, \
            "load_plugin_from_manifest must check for sql_query plugin type"
        assert "_auto_create_companion_schema_plugin" in source, \
            "load_plugin_from_manifest must call _auto_create_companion_schema_plugin"
        
        print("✅ load_plugin_from_manifest triggers companion creation for sql_query!")
        return True
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_schema_plugin_name_derivation():
    """Test that the companion schema plugin name is correctly derived."""
    print("🔍 Testing schema plugin name derivation logic...")
    
    try:
        from semantic_kernel_plugins.logged_plugin_loader import LoggedPluginLoader
        
        source = inspect.getsource(LoggedPluginLoader._auto_create_companion_schema_plugin)
        
        # Should handle _query suffix replacement
        assert "endswith('_query')" in source, \
            "Method should check for _query suffix"
        assert "'_schema'" in source, \
            "Method should derive _schema suffix"
        
        # Should check if schema plugin already exists
        assert "self.kernel.plugins" in source, \
            "Method should check kernel.plugins for existing schema plugin"
        
        # Should create SQLSchemaPlugin
        assert "SQLSchemaPlugin" in source, \
            "Method should create a SQLSchemaPlugin instance"
        
        # Should register with kernel
        assert "_register_plugin_with_kernel" in source, \
            "Method should register the companion plugin with the kernel"
        
        print("✅ Schema plugin name derivation and creation logic is correct!")
        return True
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_resilient_query_plugin_descriptions():
    """Test that SQLQueryPlugin descriptions don't demand non-existent schema functions."""
    print("🔍 Testing SQLQueryPlugin @kernel_function descriptions are resilient...")
    
    try:
        from semantic_kernel_plugins.sql_query_plugin import SQLQueryPlugin
        
        source = inspect.getsource(SQLQueryPlugin)
        
        # Descriptions should NOT contain "you MUST first call" which creates a hard dependency
        assert "you MUST first call" not in source, \
            "Descriptions should not contain 'you MUST first call' (creates hard dependency on non-existent functions)"
        assert "You MUST first discover" not in source, \
            "Descriptions should not contain 'You MUST first discover' (creates hard dependency)"
        
        # Descriptions SHOULD contain resilient language
        assert "If the database schema is provided in your instructions" in source, \
            "Descriptions should reference schema from instructions as primary source"
        
        # Should still mention the schema plugin as a fallback
        assert "get_database_schema" in source, \
            "Descriptions should still reference get_database_schema as a fallback option"
        
        print("✅ SQLQueryPlugin descriptions are resilient and don't demand non-existent functions!")
        return True
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_schema_extraction_fallback():
    """Test that _extract_sql_schema_for_instructions has a fallback for SQLQueryPlugin."""
    print("🔍 Testing _extract_sql_schema_for_instructions fallback...")
    
    try:
        from semantic_kernel_loader import _extract_sql_schema_for_instructions
        
        source = inspect.getsource(_extract_sql_schema_for_instructions)
        
        # Should have fallback logic
        assert "Fallback" in source or "fallback" in source, \
            "Function should contain fallback logic"
        
        # Should check for SQLQueryPlugin
        assert "SQLQueryPlugin" in source, \
            "Fallback should check for SQLQueryPlugin instances"
        
        # Should create temporary schema extractor
        assert "temp_manifest" in source or "temp_schema" in source, \
            "Fallback should create a temporary schema extractor"
        
        print("✅ _extract_sql_schema_for_instructions has SQLQueryPlugin fallback!")
        return True
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_version_updated():
    """Test that the version has been updated for this fix."""
    print("🔍 Testing version update...")
    
    try:
        # Read config.py directly to check version
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 
                                   '..', 'application', 'single_app', 'config.py')
        with open(config_path, 'r') as f:
            config_content = f.read()
        
        assert 'VERSION = "0.239.015"' in config_content, \
            f"config.py should contain VERSION = \"0.239.015\""
        
        print("✅ Version correctly updated to 0.239.015!")
        return True
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_companion_schema_plugin_method_exists,
        test_companion_creation_triggered_for_sql_query,
        test_schema_plugin_name_derivation,
        test_resilient_query_plugin_descriptions,
        test_schema_extraction_fallback,
        test_version_updated,
    ]
    results = []
    
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    passed = sum(results)
    total = len(results)
    print(f"\n📊 Results: {passed}/{total} tests passed")
    
    if not success:
        failed_tests = [t.__name__ for t, r in zip(tests, results) if not r]
        print(f"❌ Failed tests: {', '.join(failed_tests)}")
    
    sys.exit(0 if success else 1)
