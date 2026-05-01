# test_sql_container_odbc_runtime.py
"""
Functional test for SQL container ODBC runtime packaging.
Version: 0.241.095
Implemented in: 0.241.081

This test ensures that the application container packages the unixODBC runtime
and Microsoft ODBC Driver 18 for SQL Server, preserves the package-selected
unixODBC driver registry path, and keeps fresh SQL defaults on ODBC Driver 18
across the backend and frontend surfaces.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def read_workspace_file(relative_path: str) -> str:
    """Read a workspace file as UTF-8 text."""
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_dockerfile_packages_odbc_runtime() -> bool:
    """Validate the container build includes the SQL Server ODBC runtime."""
    print("🔍 Testing Dockerfile ODBC runtime packaging...")

    dockerfile = read_workspace_file("application/single_app/Dockerfile")
    expected_snippets = [
        "tdnf install -y unixODBC unixODBC-devel msodbcsql18",
        "COPY --from=builder /odbc-runtime/ /",
        'LD_LIBRARY_PATH="/usr/lib64:/opt/microsoft/msodbcsql18/lib64"',
        'driver_config_path="$(odbcinst -j | while IFS= read -r line; do case "$line" in DRIVERS*) printf \'%s\\n\' "${line##*: }"; break ;; esac; done)"',
        'test -n "${driver_config_path}"',
        'case "${driver_config_path}" in',
        '*/odbcinst.ini) driver_config_file="${driver_config_path}" ;;',
        '*) driver_config_file="${driver_config_path}/odbcinst.ini" ;;',
        'driver_config_dir="${driver_config_file%/odbcinst.ini}"',
        'test -f "${driver_config_file}"',
        'cp -a "${driver_config_file}" "/odbc-runtime${driver_config_dir}/"',
        'if [ "${driver_config_dir}" != "/etc" ]; then cp -a "${driver_config_file}" /odbc-runtime/etc/; fi;',
    ]

    missing = [snippet for snippet in expected_snippets if snippet not in dockerfile]
    if missing:
        raise AssertionError(f"Dockerfile is missing expected ODBC runtime snippets: {missing}")

    assert "cp -a /etc/odbcinst.ini /odbc-runtime/etc/" not in dockerfile, (
        "Dockerfile should not hard-code /etc/odbcinst.ini because Azure Linux 3 registers the driver under the path reported by odbcinst -j"
    )

    print("✅ Dockerfile packages unixODBC and msodbcsql18 runtime artifacts.")
    print("✅ Dockerfile preserves the package-selected unixODBC driver registry path.")
    return True


def test_sql_defaults_use_odbc_driver_18() -> bool:
    """Validate fresh SQL defaults point to ODBC Driver 18."""
    print("🔍 Testing SQL defaults use ODBC Driver 18...")

    expected_defaults = {
        "application/single_app/route_backend_plugins.py": "driver or 'ODBC Driver 18 for SQL Server'",
        "application/single_app/semantic_kernel_plugins/sql_query_plugin.py": "'default_driver': 'ODBC Driver 18 for SQL Server'",
        "application/single_app/semantic_kernel_plugins/sql_schema_plugin.py": "'default_driver': 'ODBC Driver 18 for SQL Server'",
        "application/single_app/semantic_kernel_plugins/sql_plugin_factory.py": '"driver": "ODBC Driver 18 for SQL Server"',
        "application/single_app/static/js/plugin_modal_stepper.js": "additionalFields.driver || 'ODBC Driver 18 for SQL Server'",
        "application/single_app/semantic_kernel_plugins/SQL_Plugins_Configuration_Guide.md": 'DRIVER={ODBC Driver 18 for SQL Server}',
    }

    for relative_path, expected_text in expected_defaults.items():
        file_text = read_workspace_file(relative_path)
        assert expected_text in file_text, f"Expected {relative_path} to contain {expected_text!r}"

    print("✅ Fresh SQL defaults and examples use ODBC Driver 18.")
    return True


def test_sql_driver_picker_prioritizes_odbc_driver_18() -> bool:
    """Validate the SQL driver picker shows ODBC Driver 18 first."""
    print("🔍 Testing SQL driver picker ordering...")

    template = read_workspace_file("application/single_app/templates/_plugin_modal.html")
    option_18 = '<option value="ODBC Driver 18 for SQL Server">ODBC Driver 18 for SQL Server</option>'
    option_17 = '<option value="ODBC Driver 17 for SQL Server">ODBC Driver 17 for SQL Server</option>'

    assert option_18 in template, "Driver 18 option should be present in the SQL driver picker"
    assert option_17 in template, "Driver 17 option should remain available for older custom images"
    assert template.index(option_18) < template.index(option_17), "Driver 18 should appear before Driver 17 in the SQL driver picker"

    print("✅ SQL driver picker prioritizes ODBC Driver 18 while retaining Driver 17.")
    return True


if __name__ == "__main__":
    tests = [
        test_dockerfile_packages_odbc_runtime,
        test_sql_defaults_use_odbc_driver_18,
        test_sql_driver_picker_prioritizes_odbc_driver_18,
    ]
    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        try:
            results.append(test())
        except Exception as ex:
            print(f"❌ Test failed: {ex}")
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    raise SystemExit(0 if success else 1)