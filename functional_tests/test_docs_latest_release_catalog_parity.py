#!/usr/bin/env python3
# test_docs_latest_release_catalog_parity.py
"""
Functional test for Latest Release documentation parity.
Version: 0.261.002
Implemented in: 0.261.002

This test ensures the documentation site's Latest Release catalog stays in step
with the in-app Latest Features catalogs. It catches the drift class that let the
docs site describe an older, smaller feature set than the application shipped, and
the broken-image class where a card referenced a screenshot that was never
published to the docs site.
"""

import importlib.util
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import yaml

from test_support.versioning import assert_app_version_at_least


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, '..'))

SUPPORT_CONFIG = os.path.join(REPO_ROOT, 'application', 'single_app', 'support_menu_config.py')
DATA_PATH = os.path.join(REPO_ROOT, 'docs', '_data', 'latest_release_features.yml')
PAGES_DIR = os.path.join(REPO_ROOT, 'docs', 'latest-release')
DOCS_IMAGE_DIR = os.path.join(REPO_ROOT, 'docs', 'images', 'latest-release')
INDEX_LAYOUT = os.path.join(REPO_ROOT, 'docs', '_layouts', 'latest-release-index.html')

USER_GROUP_KEY = 'current_release'
ADMIN_GROUP_KEY = 'current_release_admin'


def load_support_config():
    """Import the app catalog module without booting the Flask app."""
    spec = importlib.util.spec_from_file_location(
        'support_menu_config_for_docs_parity_test', SUPPORT_CONFIG
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_docs_data():
    """Load the committed documentation catalog."""
    with open(DATA_PATH, 'r', encoding='utf-8') as handle:
        return yaml.safe_load(handle) or {}


def slug_for(feature_id):
    """Map an app catalog id onto its documentation slug."""
    return str(feature_id).replace('_', '-')


def app_current_groups(support_config):
    """Return the user and admin current-release groups from the app catalogs."""
    return (
        support_config._SUPPORT_LATEST_FEATURE_RELEASE_GROUPS[0],
        support_config._ADMIN_LATEST_FEATURE_RELEASE_GROUPS[0],
    )


def test_group_membership_matches_app():
    """Docs release groups must list exactly the app catalog cards, in order."""
    print('Testing Latest Release group membership...')

    try:
        support_config = load_support_config()
        docs_data = load_docs_data()
        user_group, admin_group = app_current_groups(support_config)

        for group_key, app_group in ((USER_GROUP_KEY, user_group), (ADMIN_GROUP_KEY, admin_group)):
            docs_group = docs_data.get(group_key)
            assert docs_group, f'Docs catalog is missing the {group_key} group'

            expected = [slug_for(feature['id']) for feature in app_group['features']]
            actual = list(docs_group.get('slugs') or [])
            assert actual == expected, (
                f'{group_key} slugs drifted from the app catalog.\n'
                f'  missing from docs: {sorted(set(expected) - set(actual))}\n'
                f'  stale in docs:     {sorted(set(actual) - set(expected))}'
            )

            assert docs_group.get('release_version') == app_group.get('release_version'), (
                f"{group_key} release_version is {docs_group.get('release_version')!r} "
                f"but the app catalog says {app_group.get('release_version')!r}"
            )

        print(
            f'  {len(user_group["features"])} user cards and '
            f'{len(admin_group["features"])} admin cards match the app catalog'
        )
        print('Latest Release group membership matches the app')
        return True

    except Exception as e:
        print(f'Test failed: {e}')
        import traceback
        traceback.print_exc()
        return False


def test_every_card_has_a_page_and_images():
    """Every current-release card needs a docs page and resolvable screenshots."""
    print('Testing Latest Release pages and screenshot assets...')

    try:
        support_config = load_support_config()
        docs_data = load_docs_data()
        lookup = docs_data.get('lookup') or {}

        missing_lookup = []
        missing_pages = []
        missing_images = []
        checked_images = 0

        for app_group in app_current_groups(support_config):
            for feature in app_group['features']:
                slug = slug_for(feature['id'])

                entry = lookup.get(slug)
                if not entry:
                    missing_lookup.append(slug)
                    continue

                if not os.path.isfile(os.path.join(PAGES_DIR, f'{slug}.md')):
                    missing_pages.append(slug)

                # A card that ships without media is legitimate; a card that names an
                # image the docs site never published is a broken image on the page.
                for image in entry.get('images') or []:
                    path = str(image.get('path') or '')
                    name = os.path.basename(path)
                    assert path.startswith('/images/latest-release/'), (
                        f'{slug} references an unexpected image root: {path}'
                    )
                    checked_images += 1
                    if not os.path.isfile(os.path.join(DOCS_IMAGE_DIR, name)):
                        missing_images.append(f'{slug} -> {name}')

        assert not missing_lookup, f'Cards with no docs lookup entry: {missing_lookup}'
        assert not missing_pages, f'Cards with no docs page: {missing_pages}'
        assert not missing_images, f'Cards referencing unpublished screenshots: {missing_images}'

        print(f'  {checked_images} screenshot references all resolve under docs/images/latest-release')
        print('Latest Release pages and screenshots are complete')
        return True

    except Exception as e:
        print(f'Test failed: {e}')
        import traceback
        traceback.print_exc()
        return False


def test_page_front_matter_parses():
    """Every current-release page must have front matter Jekyll can parse.

    Card titles and summaries contain quotes, so a page built with hand-quoted
    YAML scalars silently drops out of the build with a YAML Exception.
    """
    print('Testing Latest Release page front matter...')

    try:
        support_config = load_support_config()
        broken = []
        checked = 0

        for app_group in app_current_groups(support_config):
            for feature in app_group['features']:
                slug = slug_for(feature['id'])
                path = os.path.join(PAGES_DIR, f'{slug}.md')
                if not os.path.isfile(path):
                    continue

                with open(path, 'r', encoding='utf-8') as handle:
                    text = handle.read()

                if not text.startswith('---'):
                    broken.append(f'{slug}: no front matter block')
                    continue

                _, _, remainder = text.partition('---')
                block, delimiter, _ = remainder.partition('\n---')
                if not delimiter:
                    broken.append(f'{slug}: unterminated front matter block')
                    continue

                checked += 1
                try:
                    parsed = yaml.safe_load(block)
                except yaml.YAMLError as exc:
                    broken.append(f'{slug}: {exc}')
                    continue

                if not isinstance(parsed, dict) or not parsed.get('title'):
                    broken.append(f'{slug}: front matter has no title')

        assert not broken, 'Pages with unparseable front matter:\n  ' + '\n  '.join(broken)

        print(f'  {checked} page front matter blocks parse cleanly')
        print('Latest Release page front matter is valid')
        return True

    except Exception as e:
        print(f'Test failed: {e}')
        import traceback
        traceback.print_exc()
        return False


def test_index_layout_renders_admin_group():
    """The index layout must render the admin group, not just the user group."""
    print('Testing Latest Release index layout...')

    try:
        with open(INDEX_LAYOUT, 'r', encoding='utf-8') as handle:
            layout = handle.read()

        assert 'feature_data.current_release.slugs' in layout, (
            'Index layout no longer renders the user-facing current release group'
        )
        assert 'feature_data.current_release_admin.slugs' in layout, (
            'Index layout does not render the admin-managed current release group'
        )

        print('Index layout renders both the user and admin release groups')
        return True

    except Exception as e:
        print(f'Test failed: {e}')
        import traceback
        traceback.print_exc()
        return False


def test_generated_docs_are_current():
    """The committed docs catalog must match what the generator produces."""
    print('Testing generated Latest Release docs are current...')

    try:
        sys.path.insert(0, os.path.join(REPO_ROOT, 'scripts'))
        spec = importlib.util.spec_from_file_location(
            'build_latest_release_docs_for_parity_test',
            os.path.join(REPO_ROOT, 'scripts', 'build_latest_release_docs.py'),
        )
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)

        exit_code = generator.main(['--check'])
        assert exit_code == 0, (
            'Committed Latest Release docs are stale. '
            'Run: python scripts/build_latest_release_docs.py'
        )

        print('Committed Latest Release docs match the generator output')
        return True

    except Exception as e:
        print(f'Test failed: {e}')
        import traceback
        traceback.print_exc()
        return False


def test_version_floor():
    """The parity contract shipped in 0.261.002."""
    print('Testing application version floor...')

    try:
        assert_app_version_at_least('0.261.002')
        print('Application version is at or above the parity contract version')
        return True

    except Exception as e:
        print(f'Test failed: {e}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_group_membership_matches_app,
        test_every_card_has_a_page_and_images,
        test_page_front_matter_parses,
        test_index_layout_renders_admin_group,
        test_generated_docs_are_current,
        test_version_floor,
    ]

    results = []
    for test in tests:
        print(f'\nRunning {test.__name__}...')
        results.append(test())

    print(f'\nResults: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if all(results) else 1)
