#!/usr/bin/env python3
# test_latest_feature_action_targets.py
"""
Functional test for Latest Features card action targets.
Version: 0.261.001
Implemented in: 0.261.001

Latest Feature cards render shortcut buttons whose `admin_tab` value is pushed
onto the URL hash and resolved to a tab pane. Resolution passes through
LEGACY_TAB_REDIRECTS in admin_sidebar_nav.js, which keeps pre-rework ids such as
`#general` and `#scale` working after the information architecture changed.

A target that is neither a live tab id nor a legacy alias fails silently: the
hash changes, no pane activates, and the admin stays where they were. This test
ensures every action target still resolves, that the alias table only points at
tabs that exist, and that current-release cards name their destination directly
rather than inheriting whichever tab happened to absorb an old id.
"""

import importlib.util
import os
import re
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.nav import get_tab_ids
from test_support.versioning import assert_app_version_at_least


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, '..'))
APP_ROOT = os.path.join(REPO_ROOT, 'application', 'single_app')
SUPPORT_CONFIG = os.path.join(APP_ROOT, 'support_menu_config.py')
SIDEBAR_NAV_JS = os.path.join(APP_ROOT, 'static', 'js', 'admin', 'admin_sidebar_nav.js')

REDIRECT_BLOCK_RE = re.compile(r'const LEGACY_TAB_REDIRECTS = \{(?P<body>.*?)\};', re.DOTALL)
REDIRECT_ENTRY_RE = re.compile(r"'(?P<alias>[^']+)':\s*'(?P<target>[^']+)'")


def load_support_config():
    """Import the catalog module without booting the Flask app."""
    spec = importlib.util.spec_from_file_location(
        'support_menu_config_for_action_target_test', SUPPORT_CONFIG
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_legacy_tab_redirects():
    """Read the alias table from the app so the test cannot drift from it."""
    with open(SIDEBAR_NAV_JS, 'r', encoding='utf-8') as handle:
        source = handle.read()

    block = REDIRECT_BLOCK_RE.search(source)
    assert block, 'LEGACY_TAB_REDIRECTS not found in admin_sidebar_nav.js'
    return {
        match.group('alias'): match.group('target')
        for match in REDIRECT_ENTRY_RE.finditer(block.group('body'))
    }


def iter_catalog_actions(support_config):
    """Yield (card_id, action) for every admin and user catalog card action."""
    groups = (
        support_config._ADMIN_LATEST_FEATURE_RELEASE_GROUPS
        + support_config._SUPPORT_LATEST_FEATURE_RELEASE_GROUPS
    )
    for group in groups:
        for feature in group.get('features') or []:
            for action in feature.get('actions') or []:
                yield feature['id'], action


def test_admin_tab_targets_resolve():
    """Every admin_tab value must resolve to a real tab, directly or by alias."""
    print('Testing Latest Features admin_tab targets...')

    try:
        support_config = load_support_config()
        tab_ids = set(get_tab_ids())
        redirects = load_legacy_tab_redirects()
        broken = []
        checked = 0

        for card_id, action in iter_catalog_actions(support_config):
            target = str(action.get('admin_tab') or '').strip()
            if not target:
                continue

            checked += 1
            fragment = target.lstrip('#')
            resolved = redirects.get(fragment, fragment)
            if resolved not in tab_ids:
                broken.append(f"{card_id}: '{action.get('label')}' -> #{fragment}")

        assert not broken, (
            'Card actions pointing at a tab that neither exists nor has a legacy '
            'alias:\n  ' + '\n  '.join(broken)
        )

        print(f'  {checked} admin_tab targets resolve to real tabs')
        print('Latest Features admin_tab targets are valid')
        return True

    except Exception as e:
        print(f'Test failed: {e}')
        import traceback
        traceback.print_exc()
        return False


def test_legacy_aliases_point_at_real_tabs():
    """The alias table must not outlive the tabs it redirects to."""
    print('Testing legacy admin tab alias table...')

    try:
        tab_ids = set(get_tab_ids())
        redirects = load_legacy_tab_redirects()
        assert redirects, 'Legacy alias table parsed as empty'

        dangling = [
            f'{alias} -> {target}'
            for alias, target in sorted(redirects.items())
            if target not in tab_ids
        ]
        assert not dangling, (
            'Legacy aliases redirecting to a tab that no longer exists:\n  '
            + '\n  '.join(dangling)
        )

        shadowed = sorted(set(redirects) & tab_ids)
        assert not shadowed, (
            'These ids are both a live tab and a legacy alias, so the alias '
            f'hijacks the real tab: {shadowed}'
        )

        print(f'  {len(redirects)} aliases all resolve to live tabs')
        print('Legacy admin tab alias table is consistent')
        return True

    except Exception as e:
        print(f'Test failed: {e}')
        import traceback
        traceback.print_exc()
        return False


def test_current_release_actions_land_on_their_own_tab():
    """Current-release admin cards should name their destination tab directly.

    Aliases keep old links working, but they resolve to whichever tab inherited
    the old id, which is not always the tab holding the setting. `#general`
    lands on Branding, for example, while the Terms of Use controls live on
    Notices & Agreements.
    """
    print('Testing current release admin card action targets...')

    try:
        support_config = load_support_config()
        redirects = load_legacy_tab_redirects()
        current_group = support_config._ADMIN_LATEST_FEATURE_RELEASE_GROUPS[0]
        indirect = []

        for feature in current_group.get('features') or []:
            for action in feature.get('actions') or []:
                fragment = str(action.get('admin_tab') or '').strip().lstrip('#')
                if fragment and fragment in redirects:
                    indirect.append(
                        f"{feature['id']}: '{action.get('label')}' -> #{fragment} "
                        f"(lands on #{redirects[fragment]})"
                    )

        assert not indirect, (
            'Current release admin cards routing through a legacy alias:\n  '
            + '\n  '.join(indirect)
            + '\n\nName the destination tab directly so the shortcut lands on the '
            'tab that holds the setting.'
        )

        print('Current release admin cards name their destination tab directly')
        return True

    except Exception as e:
        print(f'Test failed: {e}')
        import traceback
        traceback.print_exc()
        return False


def test_version_floor():
    """The action target contract shipped in 0.261.001."""
    print('Testing application version floor...')

    try:
        assert_app_version_at_least('0.261.001')
        print('Application version is at or above the contract version')
        return True

    except Exception as e:
        print(f'Test failed: {e}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_admin_tab_targets_resolve,
        test_legacy_aliases_point_at_real_tabs,
        test_current_release_actions_land_on_their_own_tab,
        test_version_floor,
    ]

    results = []
    for test in tests:
        print(f'\nRunning {test.__name__}...')
        results.append(test())

    print(f'\nResults: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if all(results) else 1)
