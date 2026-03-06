#!/usr/bin/env python3
"""
Functional test for SQL Query Plugin Schema Awareness improvements.
Version: 0.239.014
Implemented in: 0.239.014

This test ensures that the SQL Query and SQL Schema plugins have proper
workflow-guiding descriptions in their @kernel_function decorators, metadata
properties, and that the new query_database convenience function exists.
These improvements ensure agents discover database schema before attempting
to generate and execute SQL queries.
"""

import sys
import os

# Add the application directory to the path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))


def test_sql_schema_plugin_descriptions():
    """Test that SQL Schema Plugin has prescriptive workflow descriptions."""
    print("🔍 Testing SQL Schema Plugin @kernel_function descriptions...")
    
    try:
        from semantic_kernel_plugins.sql_schema_plugin import SQLSchemaPlugin
        import inspect
        
        source = inspect.getsource(SQLSchemaPlugin)
        
        # Check get_database_schema has workflow guidance
        assert "ALWAYS call this function FIRST" in source, \
            "get_database_schema description should contain 'ALWAYS call this function FIRST'"
        
        assert "before executing any SQL queries" in source, \
            "get_database_schema description should guide calling before queries"
        
        # Check get_table_list has workflow guidance
        assert "Use this function first to discover which tables are available" in source, \
            "get_table_list description should guide discovery workflow"
        
        # Check get_table_schema has workflow guidance
        assert "Call this after discovering tables" in source, \
            "get_table_schema description should reference discovery step"
        
        # Check get_relationships has workflow guidance
        assert "JOIN conditions" in source, \
            "get_relationships description should mention JOIN conditions"
        
        print("✅ SQL Schema Plugin descriptions contain workflow guidance!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_sql_query_plugin_descriptions():
    """Test that SQL Query Plugin has prescriptive workflow descriptions."""
    print("🔍 Testing SQL Query Plugin @kernel_function descriptions...")
    
    try:
        from semantic_kernel_plugins.sql_query_plugin import SQLQueryPlugin
        import inspect
        
        source = inspect.getsource(SQLQueryPlugin)
        
        # Check execute_query has schema requirement
        assert "you MUST first call get_database_schema or get_table_list" in source, \
            "execute_query description should require schema discovery first"
        
        assert "fully qualified table names" in source, \
            "execute_query description should mention fully qualified table names"
        
        # Check execute_scalar has schema requirement
        assert "MUST first discover the database schema" in source, \
            "execute_scalar description should require schema discovery"
        
        # Check validate_query has useful guidance
        assert "pre-check complex queries" in source, \
            "validate_query description should guide pre-checking"
        
        print("✅ SQL Query Plugin descriptions contain workflow guidance!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_query_database_function_exists():
    """Test that the new query_database convenience function exists."""
    print("🔍 Testing query_database function existence...")
    
    try:
        from semantic_kernel_plugins.sql_query_plugin import SQLQueryPlugin
        
        # Check the function exists on the class
        assert hasattr(SQLQueryPlugin, 'query_database'), \
            "SQLQueryPlugin should have a query_database method"
        
        # Check it's in get_functions list
        # We need to create a minimal instance to test, but we can check the class method
        import inspect
        source = inspect.getsource(SQLQueryPlugin.query_database)
        
        assert "question" in source, \
            "query_database should accept a 'question' parameter"
        
        assert "query" in source, \
            "query_database should accept a 'query' parameter"
        
        assert "@kernel_function" in inspect.getsource(SQLQueryPlugin), \
            "query_database should be decorated with @kernel_function"
        
        print("✅ query_database function exists with correct parameters!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_metadata_descriptions_updated():
    """Test that metadata property descriptions include workflow guidance."""
    print("🔍 Testing metadata property descriptions...")
    
    try:
        from semantic_kernel_plugins.sql_query_plugin import SQLQueryPlugin
        from semantic_kernel_plugins.sql_schema_plugin import SQLSchemaPlugin
        import inspect
        
        # Check SQL Query Plugin metadata
        query_source = inspect.getsource(SQLQueryPlugin)
        assert "WORKFLOW: Before executing any query" in query_source, \
            "SQL Query Plugin metadata should contain workflow guidance"
        
        # Check SQL Schema Plugin metadata
        schema_source = inspect.getsource(SQLSchemaPlugin)
        assert "ALWAYS call get_database_schema" in schema_source, \
            "SQL Schema Plugin metadata should contain workflow guidance"
        
        print("✅ Metadata descriptions include workflow guidance!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_sql_plugin_creation_path_enabled():
    """Test that the SQL plugin creation path is enabled in logged_plugin_loader."""
    print("🔍 Testing SQL plugin creation path is enabled...")
    
    try:
        from semantic_kernel_plugins.logged_plugin_loader import LoggedPluginLoader
        import inspect
        
        source = inspect.getsource(LoggedPluginLoader._create_plugin_instance)
        
        # Check the SQL path is NOT commented out
        assert "elif plugin_type in ['sql_schema', 'sql_query']:" in source, \
            "SQL plugin creation path should be enabled (not commented out)"
        
        assert "return self._create_sql_plugin(manifest)" in source, \
            "SQL plugin creation should call _create_sql_plugin"
        
        # Make sure it's not still commented
        lines = source.split('\n')
        for line in lines:
            stripped = line.strip()
            if "sql_schema" in stripped and "sql_query" in stripped and "elif" in stripped:
                assert not stripped.startswith('#'), \
                    "SQL plugin creation path should NOT be commented out"
                break
        
        print("✅ SQL plugin creation path is enabled!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_schema_injection_function_exists():
    """Test that the schema injection helper function exists in semantic_kernel_loader."""
    print("🔍 Testing schema injection function exists...")
    
    try:
        # Read the file and check for the function
        loader_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            '..', 'application', 'single_app', 'semantic_kernel_loader.py'
        )
        
        with open(loader_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        assert "def _extract_sql_schema_for_instructions(kernel)" in content, \
            "_extract_sql_schema_for_instructions function should exist in semantic_kernel_loader.py"
        
        assert "sql_schema_summary = _extract_sql_schema_for_instructions(kernel)" in content, \
            "Schema injection should be called in the agent loading flow"
        
        assert "Available Database Schema" in content, \
            "Schema injection should add 'Available Database Schema' header to instructions"
        
        assert "Do NOT ask the user for table or column names" in content, \
            "Schema injection should instruct agent not to ask user for schema info"
        
        print("✅ Schema injection function exists and is integrated!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_sql_schema_plugin_descriptions,
        test_sql_query_plugin_descriptions,
        test_query_database_function_exists,
        test_metadata_descriptions_updated,
        test_sql_plugin_creation_path_enabled,
        test_schema_injection_function_exists,
    ]
    results = []
    
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
