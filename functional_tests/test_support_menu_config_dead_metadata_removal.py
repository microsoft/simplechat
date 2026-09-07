#!/usr/bin/env python3
# test_support_menu_config_dead_metadata_removal.py
"""
Functional test for support menu dead metadata removal.
Version: 0.260.001
Implemented in: 0.260.001

This test ensures orphaned per-feature metadata lookup tables do not drift away
from the real Latest Features catalogs and verifies the removed current-feature
metadata tables stay deleted.
"""

import importlib.util
import os
import re
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, '..'))
APP_DIR = os.path.join(REPO_ROOT, 'application', 'single_app')
SUPPORT_CONFIG = os.path.join(APP_DIR, 'support_menu_config.py')
FEATURE_ID_PATTERN = re.compile(r'^(?:admin_)?(?:release_\d+_[a-z0-9_]+|[a-z][a-z0-9]*(?:_[a-z0-9]+)+)$')


def load_support_config():
    """Load support_menu_config.py as an isolated module."""
    spec = importlib.util.spec_from_file_location('support_menu_config_dead_metadata', SUPPORT_CONFIG)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def iter_catalog_feature_ids(support_config):
    """Yield every feature id from user and admin release group catalogs."""
    for groups_name in ('_SUPPORT_LATEST_FEATURE_RELEASE_GROUPS', '_ADMIN_LATEST_FEATURE_RELEASE_GROUPS'):
        for group in getattr(support_config, groups_name):
            for feature in group.get('features', []):
                feature_id = feature.get('id')
                if feature_id:
                    yield feature_id


def looks_like_feature_metadata_table(value):
    """Return True when a module-level dict looks like an id-keyed metadata table."""
    if not isinstance(value, dict) or not value:
        return False

    if not all(isinstance(key, str) and FEATURE_ID_PATTERN.match(key) for key in value):
        return False

    return all(isinstance(item, (dict, list, tuple, set)) for item in value.values())


def test_removed_metadata_names_are_absent():
    """The deleted current-feature metadata tables must not return."""
    print('Testing removed support metadata names are absent...')

    support_config = load_support_config()
    removed_names = [
        '_SUPPORT_CURRENT_FEATURE_IMAGE_METADATA',
        '_SUPPORT_CURRENT_FEATURE_USER_METADATA',
    ]
    present = [name for name in removed_names if hasattr(support_config, name)]

    assert not present, f'Removed support metadata names are still present: {present}'

    print('Removed support metadata names are absent')
    return True


def test_feature_metadata_tables_match_catalog_ids():
    """Every id-keyed metadata table must reference real catalog feature ids."""
    print('Testing support metadata tables match catalog ids...')

    support_config = load_support_config()
    catalog_ids = set(iter_catalog_feature_ids(support_config))
    orphaned_tables = {}
    orphaned_keys = {}

    for name, value in vars(support_config).items():
        if not name.startswith('_') or name.startswith('__'):
            continue
        if not looks_like_feature_metadata_table(value):
            continue

        table_keys = set(value.keys())
        intersection = table_keys & catalog_ids
        if not intersection:
            orphaned_tables[name] = sorted(table_keys)
            continue

        unknown_keys = table_keys - catalog_ids
        if unknown_keys:
            orphaned_keys[name] = sorted(unknown_keys)

    assert not orphaned_tables, f'Per-feature metadata tables without catalog matches: {orphaned_tables}'
    assert not orphaned_keys, f'Per-feature metadata keys without catalog matches: {orphaned_keys}'

    print('Support metadata tables match catalog ids')
    return True


if __name__ == '__main__':
    tests = [
        test_removed_metadata_names_are_absent,
        test_feature_metadata_tables_match_catalog_ids,
    ]

    results = []
    for test in tests:
        print(f'\nRunning {test.__name__}...')
        try:
            results.append(test())
        except Exception as exc:  # noqa: BLE001
            print(f'Failed {test.__name__}: {exc}')
            import traceback
            traceback.print_exc()
            results.append(False)

    print(f'\nResults: {sum(1 for result in results if result)}/{len(results)} tests passed')
    sys.exit(0 if all(results) else 1)
