#!/usr/bin/env python3
# test_admin_update_banner_version_comparison.py
"""
Functional test for Admin Settings update banner version comparison.
Version: 0.250.004
Implemented in: 0.250.003

This test ensures cached update-check settings cannot display an older release
as a newer available version after the running app version advances.
"""

import ast
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT_DIR / 'application' / 'single_app' / 'config.py'
ROUTE_FILE = ROOT_DIR / 'application' / 'single_app' / 'route_frontend_admin_settings.py'


def read_config_version() -> str:
    """Read the current app version from config.py."""
    for line in CONFIG_FILE.read_text(encoding='utf-8').splitlines():
        if line.startswith('VERSION = '):
            return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def compare_versions_stub(version_1, version_2):
    """Compare dotted numeric versions using the same contract as functions_settings.compare_versions."""
    if not version_1 or not version_2:
        return None
    parts_1 = [int(part) for part in str(version_1).strip().lstrip('vV').split('.')]
    parts_2 = [int(part) for part in str(version_2).strip().lstrip('vV').split('.')]
    max_length = max(len(parts_1), len(parts_2))
    parts_1.extend([0] * (max_length - len(parts_1)))
    parts_2.extend([0] * (max_length - len(parts_2)))
    if parts_1 > parts_2:
        return 1
    if parts_1 < parts_2:
        return -1
    return 0


def load_update_helper():
    """Load only the pure update-version helper from the Admin Settings route module source."""
    source = ROUTE_FILE.read_text(encoding='utf-8')
    tree = ast.parse(source, filename=str(ROUTE_FILE))
    helper_node = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == '_is_update_version_newer'
    )
    module = ast.Module(body=[helper_node], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {'compare_versions': compare_versions_stub}
    exec(compile(module, str(ROUTE_FILE), 'exec'), namespace)
    return namespace['_is_update_version_newer']


def test_update_banner_suppresses_stale_cached_older_release() -> None:
    """Cached latest release must not show when it is older than the running app version."""
    is_update_version_newer = load_update_helper()

    assert read_config_version() == '0.250.004'
    assert is_update_version_newer('0.250.001', '0.250.004') is False
    assert is_update_version_newer('v0.250.001', '0.250.004') is False
    assert is_update_version_newer('0.250.004', '0.250.004') is False
    assert is_update_version_newer('0.250.005', '0.250.004') is True


def test_admin_settings_render_path_recomputes_cached_update_flag() -> None:
    """Admin Settings must recompute update_available from latest and current versions before rendering."""
    source = ROUTE_FILE.read_text(encoding='utf-8')

    assert "update_available = _is_update_version_newer(latest_version, current_version)" in source
    assert "settings.get('update_available') != update_available" in source
    assert "update_settings({'update_available': update_available})" in source


if __name__ == '__main__':
    tests = [
        test_update_banner_suppresses_stale_cached_older_release,
        test_admin_settings_render_path_recomputes_cached_update_flag,
    ]
    results = []
    for test in tests:
        print(f'Running {test.__name__}...')
        try:
            test()
            print('PASS')
            results.append(True)
        except Exception as exc:
            print(f'FAIL: {exc}')
            results.append(False)

    print(f'Results: {sum(results)}/{len(results)} tests passed')
    raise SystemExit(0 if all(results) else 1)
