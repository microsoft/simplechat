#!/usr/bin/env python3
"""
Functional test for SQL Schema Plugin sys.* catalog view migration.
Version: 0.239.016
Implemented in: 0.239.016

This test ensures that the SQL Schema Plugin uses sys.tables, sys.columns,
sys.indexes (catalog views) instead of INFORMATION_SCHEMA views for SQL Server,
fixing the issue where get_database_schema returned empty tables dict ('tables': {})
despite the database having tables. The sys.* views are proven to work since the
relationships query (which uses sys.foreign_keys) always returned valid data.

Also validates robust pyodbc.Row handling (no isinstance(tuple) checks).
"""

import sys
import os
import inspect

# Add the application directory to the path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))


def test_tables_query_uses_sys_views():
    """Test that SQL Server tables query uses sys.tables instead of INFORMATION_SCHEMA."""
    print("🔍 Testing SQL Server tables query uses sys.tables...")

    try:
        from semantic_kernel_plugins.sql_schema_plugin import SQLSchemaPlugin

        source = inspect.getsource(SQLSchemaPlugin._get_tables_query)

        # Should use sys.tables
        assert "sys.tables" in source, \
            "_get_tables_query should reference sys.tables"
        assert "sys.schemas" in source, \
            "_get_tables_query should reference sys.schemas"

        # Should NOT use INFORMATION_SCHEMA.TABLES for sqlserver
        # (other DB types still use their own patterns)
        assert "INFORMATION_SCHEMA.TABLES" not in source, \
            "_get_tables_query should NOT use INFORMATION_SCHEMA.TABLES (use sys.tables instead)"

        print("✅ Tables query uses sys.tables!")
        return True
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_columns_query_uses_sys_views():
    """Test that SQL Server columns query uses sys.columns instead of INFORMATION_SCHEMA."""
    print("🔍 Testing SQL Server columns query uses sys.columns...")

    try:
        from semantic_kernel_plugins.sql_schema_plugin import SQLSchemaPlugin

        source = inspect.getsource(SQLSchemaPlugin._get_columns_query)

        # Should use sys.columns
        assert "sys.columns" in source, \
            "_get_columns_query should reference sys.columns"
        assert "TYPE_NAME" in source, \
            "_get_columns_query should use TYPE_NAME() for data type resolution"

        # Should NOT use INFORMATION_SCHEMA.COLUMNS for sqlserver
        assert "INFORMATION_SCHEMA.COLUMNS" not in source, \
            "_get_columns_query should NOT use INFORMATION_SCHEMA.COLUMNS (use sys.columns instead)"

        print("✅ Columns query uses sys.columns!")
        return True
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_primary_keys_query_uses_sys_views():
    """Test that SQL Server PK query uses sys.indexes instead of INFORMATION_SCHEMA."""
    print("🔍 Testing SQL Server primary keys query uses sys.indexes...")

    try:
        from semantic_kernel_plugins.sql_schema_plugin import SQLSchemaPlugin

        source = inspect.getsource(SQLSchemaPlugin._get_primary_keys_query)

        # Should use sys.indexes with is_primary_key
        assert "sys.indexes" in source, \
            "_get_primary_keys_query should reference sys.indexes"
        assert "is_primary_key" in source, \
            "_get_primary_keys_query should filter on is_primary_key"
        assert "sys.index_columns" in source, \
            "_get_primary_keys_query should reference sys.index_columns"

        # Should NOT use INFORMATION_SCHEMA.KEY_COLUMN_USAGE for sqlserver section
        # Note: PostgreSQL/MySQL sections may still use INFORMATION_SCHEMA (that's fine)
        # We check that the sqlserver branch uses sys.* by verifying sys.indexes is present
        assert "sys.index_columns" in source, \
            "_get_primary_keys_query should reference sys.index_columns for SQL Server"

        print("✅ Primary keys query uses sys.indexes!")
        return True
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_robust_row_handling_no_isinstance_tuple():
    """Test that table row parsing doesn't rely on isinstance(tuple) checks."""
    print("🔍 Testing robust pyodbc.Row handling...")

    try:
        from semantic_kernel_plugins.sql_schema_plugin import SQLSchemaPlugin

        # Check get_database_schema table iteration
        schema_source = inspect.getsource(SQLSchemaPlugin.get_database_schema)

        # Should NOT use isinstance(table, tuple) pattern
        assert "isinstance(table, tuple)" not in schema_source, \
            "get_database_schema should not use isinstance(table, tuple) — pyodbc.Row may not be a tuple"

        # Should use try/except for robust indexing
        assert "except (TypeError, IndexError)" in schema_source, \
            "get_database_schema should handle TypeError/IndexError for row parsing"

        # Check get_table_list too
        list_source = inspect.getsource(SQLSchemaPlugin.get_table_list)
        assert "isinstance(table_row, (list, tuple))" not in list_source, \
            "get_table_list should not use isinstance tuple check"

        # Check primary keys list comprehension
        schema_data_source = inspect.getsource(SQLSchemaPlugin._get_table_schema_data)
        assert "isinstance(pk, (list, tuple))" not in schema_data_source, \
            "Primary key parsing should not use isinstance tuple check"

        print("✅ Robust Row handling — no isinstance(tuple) dependencies!")
        return True
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_consistency_with_relationships_query():
    """Test that all SQL Server queries use sys.* views consistently (like relationships)."""
    print("🔍 Testing consistency: all SQL Server queries use sys.* views...")

    try:
        from semantic_kernel_plugins.sql_schema_plugin import SQLSchemaPlugin

        # The relationships query already used sys.* — verify it still does
        rel_source = inspect.getsource(SQLSchemaPlugin._get_relationships_data)
        assert "sys.foreign_keys" in rel_source, \
            "Relationships query should use sys.foreign_keys"
        assert "sys.tables" in rel_source, \
            "Relationships query should reference sys.tables"

        # Tables query should also use sys.*
        tables_source = inspect.getsource(SQLSchemaPlugin._get_tables_query)
        assert "sys.tables" in tables_source

        # Columns query should also use sys.*
        cols_source = inspect.getsource(SQLSchemaPlugin._get_columns_query)
        assert "sys.columns" in cols_source

        # PK query should also use sys.*
        pk_source = inspect.getsource(SQLSchemaPlugin._get_primary_keys_query)
        assert "sys.indexes" in pk_source

        print("✅ All SQL Server queries consistently use sys.* catalog views!")
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
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   '..', 'application', 'single_app', 'config.py')
        with open(config_path, 'r') as f:
            config_content = f.read()

        assert 'VERSION = "0.239.016"' in config_content, \
            f"config.py should contain VERSION = \"0.239.016\""

        print("✅ Version correctly updated to 0.239.016!")
        return True
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_tables_query_uses_sys_views,
        test_columns_query_uses_sys_views,
        test_primary_keys_query_uses_sys_views,
        test_robust_row_handling_no_isinstance_tuple,
        test_consistency_with_relationships_query,
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
