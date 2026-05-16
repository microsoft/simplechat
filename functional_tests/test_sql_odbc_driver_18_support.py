#!/usr/bin/env python3
# test_sql_odbc_driver_18_support.py
"""
Functional test for SQL Server ODBC Driver 18 support.
Version: 0.241.018
Implemented in: 0.241.009

This test ensures that the application container installs the Microsoft ODBC
Driver 18 runtime, new SQL Server connection strings default to Driver 18, and
saved Driver 17 SQL actions retry with Driver 18 when the legacy driver is
missing.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
APP_ROOT = os.path.join(REPO_ROOT, 'application', 'single_app')


def read_repo_file(*parts):
    """Read a repository file as UTF-8 text."""
    with open(os.path.join(REPO_ROOT, *parts), 'r', encoding='utf-8') as file:
        return file.read()


def test_dockerfile_installs_driver_18_runtime():
    """Test that the application image installs and copies native ODBC runtime files."""
    print("Testing Dockerfile ODBC Driver 18 runtime support...")

    try:
        dockerfile = read_repo_file('application', 'single_app', 'Dockerfile')

        assert 'ACCEPT_EULA=Y' in dockerfile, 'Docker build should accept the Microsoft ODBC driver EULA'
        assert 'packages.microsoft.com/azurelinux/3.0/prod/ms-non-oss' in dockerfile, \
            'Docker build should register the Microsoft Azure Linux ms-non-oss feed'
        assert 'msodbcsql18' in dockerfile, 'Docker build should install Microsoft ODBC Driver 18'
        assert 'unixODBC' in dockerfile, 'Docker build should install unixODBC runtime support'
        assert "find /opt/microsoft/msodbcsql18/lib64 -name 'libmsodbcsql-*.so*'" in dockerfile, \
            'Docker build should resolve the installed Driver 18 shared library path'
        assert "UsageCount=1" in dockerfile, 'Docker build should create a deterministic odbcinst.ini registration'
        assert '/odbc-runtime/usr/lib64' in dockerfile, \
            'Docker build should stage unixODBC libraries from Azure Linux library paths before runtime copy'
        assert "/usr/lib64/libodbc* /usr/lib/libodbc*" in dockerfile, \
            'Docker build should support unixODBC libraries installed under /usr/lib64 or /usr/lib'
        assert '/opt/microsoft' in dockerfile, 'Distroless runtime should include Microsoft driver files'
        assert '/etc/odbcinst.ini' in dockerfile, 'Distroless runtime should include ODBC driver registration'
        assert 'libodbc' in dockerfile, 'Distroless runtime should include unixODBC shared libraries'
        assert 'LD_LIBRARY_PATH' in dockerfile, 'Runtime should expose ODBC library paths'

        print("Dockerfile installs and copies ODBC Driver 18 runtime support.")
        return True
    except Exception as ex:
        print(f"Test failed: {ex}")
        import traceback
        traceback.print_exc()
        return False


def test_new_connection_strings_default_to_driver_18():
    """Test that generated SQL Server connection strings prefer Driver 18."""
    print("Testing SQL Server connection string default driver...")

    try:
        from semantic_kernel_plugins.sql_odbc_utils import build_sql_server_odbc_connection_string

        conn_str = build_sql_server_odbc_connection_string(
            server='example.database.windows.net',
            database='exampledb',
        )

        assert 'DRIVER={ODBC Driver 18 for SQL Server}' in conn_str, 'New SQL Server strings should default to Driver 18'
        assert 'ODBC Driver 17 for SQL Server' not in conn_str, 'New SQL Server strings should not default to Driver 17'

        print("New SQL Server connection strings default to Driver 18.")
        return True
    except Exception as ex:
        print(f"Test failed: {ex}")
        import traceback
        traceback.print_exc()
        return False


def test_saved_driver_17_connections_retry_driver_18():
    """Test that saved Driver 17 SQL actions retry with Driver 18 on missing-driver errors."""
    print("Testing legacy Driver 17 fallback behavior...")

    try:
        from semantic_kernel_plugins import sql_odbc_utils

        sql_odbc_utils.log_event = lambda *args, **kwargs: None
        calls = []

        def fake_connect(connection_string, **kwargs):
            calls.append((connection_string, kwargs))
            if len(calls) == 1:
                raise RuntimeError("[unixODBC][Driver Manager]Can't open lib 'ODBC Driver 17 for SQL Server' : file not found")
            return 'connected'

        original_connection_string = (
            'DRIVER={ODBC Driver 17 for SQL Server};'
            'SERVER=example.database.windows.net;DATABASE=exampledb'
        )

        result = sql_odbc_utils.connect_with_sql_server_odbc_fallback(
            fake_connect,
            original_connection_string,
            connect_kwargs={'timeout': 5},
            log_source='FunctionalTest',
        )

        assert result == 'connected', 'Fallback connection should return the retry result'
        assert len(calls) == 2, 'Missing Driver 17 should trigger exactly one Driver 18 retry'
        assert 'ODBC Driver 17 for SQL Server' in calls[0][0], 'First attempt should use saved Driver 17 string'
        assert 'ODBC Driver 18 for SQL Server' in calls[1][0], 'Retry should use Driver 18'
        assert calls[1][1] == {'timeout': 5}, 'Retry should preserve pyodbc connection kwargs'

        print("Saved Driver 17 strings retry with Driver 18 when the legacy driver is missing.")
        return True
    except Exception as ex:
        print(f"Test failed: {ex}")
        import traceback
        traceback.print_exc()
        return False


def test_non_driver_errors_do_not_retry():
    """Test that login/query errors are not retried as driver fallback failures."""
    print("Testing fallback does not hide non-driver errors...")

    try:
        from semantic_kernel_plugins import sql_odbc_utils

        calls = []

        def fake_connect(connection_string, **kwargs):
            calls.append(connection_string)
            raise RuntimeError("Login failed for user 'example'")

        original_connection_string = (
            'DRIVER={ODBC Driver 17 for SQL Server};'
            'SERVER=example.database.windows.net;DATABASE=exampledb'
        )

        try:
            sql_odbc_utils.connect_with_sql_server_odbc_fallback(fake_connect, original_connection_string)
        except RuntimeError as ex:
            assert 'Login failed' in str(ex), 'Original non-driver error should be preserved'
        else:
            raise AssertionError('Expected login failure to be raised')

        assert len(calls) == 1, 'Non-driver errors should not trigger Driver 18 retry'

        print("Non-driver errors are not retried as ODBC fallback failures.")
        return True
    except Exception as ex:
        print(f"Test failed: {ex}")
        import traceback
        traceback.print_exc()
        return False


def test_sql_defaults_reference_driver_18():
    """Test that SQL action defaults and examples use Driver 18."""
    print("Testing SQL action defaults reference Driver 18...")

    try:
        files_to_check = [
            ('application', 'single_app', 'semantic_kernel_plugins', 'sql_schema_plugin.py'),
            ('application', 'single_app', 'semantic_kernel_plugins', 'sql_query_plugin.py'),
            ('application', 'single_app', 'semantic_kernel_plugins', 'sql_plugin_factory.py'),
            ('application', 'single_app', 'route_backend_plugins.py'),
            ('application', 'single_app', 'static', 'js', 'plugin_modal_stepper.js'),
        ]

        for parts in files_to_check:
            content = read_repo_file(*parts)
            assert 'ODBC Driver 18 for SQL Server' in content or 'DEFAULT_SQL_SERVER_ODBC_DRIVER' in content, \
                f"{'/'.join(parts)} should reference Driver 18 default handling"

        route_content = read_repo_file('application', 'single_app', 'route_backend_plugins.py')
        assert "driver or 'ODBC Driver 17 for SQL Server'" not in route_content, \
            'SQL connection test should not default to Driver 17'

        js_content = read_repo_file('application', 'single_app', 'static', 'js', 'plugin_modal_stepper.js')
        assert "additionalFields.driver || 'ODBC Driver 18 for SQL Server'" in js_content, \
            'SQL action wizard should default new actions to Driver 18'

        print("SQL action defaults and examples reference Driver 18.")
        return True
    except Exception as ex:
        print(f"Test failed: {ex}")
        import traceback
        traceback.print_exc()
        return False


def test_version_updated():
    """Test that the version has been updated for this fix."""
    print("Testing version update...")

    try:
        config_content = read_repo_file('application', 'single_app', 'config.py')
        assert 'VERSION = "0.241.018"' in config_content, 'config.py should contain VERSION = "0.241.018"'

        print("Version updated to 0.241.018.")
        return True
    except Exception as ex:
        print(f"Test failed: {ex}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_dockerfile_installs_driver_18_runtime,
        test_new_connection_strings_default_to_driver_18,
        test_saved_driver_17_connections_retry_driver_18,
        test_non_driver_errors_do_not_retry,
        test_sql_defaults_reference_driver_18,
        test_version_updated,
    ]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)