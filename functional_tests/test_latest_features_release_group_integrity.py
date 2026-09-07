#!/usr/bin/env python3
# test_latest_features_release_group_integrity.py
"""
Functional test for Latest Features release group integrity.
Version: 0.260.001
Implemented in: 0.260.001

This test guards the user-facing and admin Latest Features catalogs against
structural drift as new release tiers are added. It validates unique feature
ids, required card keys, on-disk screenshot assets, tier ordering and version
metadata, visibility default coverage, and settings gating keys.
"""

import importlib.util
import os
import re
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, '..'))
APP_DIR = os.path.join(REPO_ROOT, 'application', 'single_app')
SUPPORT_CONFIG = os.path.join(APP_DIR, 'support_menu_config.py')
SETTINGS_MODULE = os.path.join(APP_DIR, 'functions_settings.py')
STATIC_DIR = os.path.join(APP_DIR, 'static')

sys.path.append(CURRENT_DIR)

from test_support.versioning import assert_app_version_at_least  # noqa: E402

EXPECTED_TIER_IDS = ['current_release', 'previous_release', 'archive_release']
REQUIRED_FEATURE_KEYS = ['id', 'title', 'icon', 'summary', 'details', 'why', 'guidance', 'actions']
REQUIRED_GROUP_KEYS = ['id', 'label', 'description', 'release_version', 'collapse_id', 'features']
REQUIRED_IMAGE_KEYS = ['path', 'alt', 'title', 'caption', 'label']


def load_support_config():
    """Load support_menu_config.py as an isolated module."""
    spec = importlib.util.spec_from_file_location('support_menu_config_integrity', SUPPORT_CONFIG)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def iter_features(release_groups):
    """Yield every (group, feature) pair across the supplied release groups."""
    for group in release_groups:
        for feature in group.get('features', []):
            yield group, feature


def test_release_group_shape():
    """Both catalogs must expose the same ordered three-tier structure."""
    print('Testing Latest Features release group shape...')

    support_config = load_support_config()
    user_groups = support_config.get_support_latest_feature_release_groups()
    admin_groups = support_config.get_admin_latest_feature_release_groups_for_settings({})

    for label, groups in (('user', user_groups), ('admin', admin_groups)):
        assert [group['id'] for group in groups] == EXPECTED_TIER_IDS, f'Unexpected {label} tier order'
        for group in groups:
            for key in REQUIRED_GROUP_KEYS:
                assert group.get(key), f"Missing '{key}' on {label} group {group.get('id')}"
            assert group['features'], f"Empty feature list on {label} group {group['id']}"

        current, previous, archive = groups
        assert current['default_expanded'] is True, f'{label} current tier should be expanded by default'
        assert previous['default_expanded'] is False, f'{label} previous tier should be collapsed'
        assert archive['default_expanded'] is False, f'{label} archive tier should be collapsed'

    assert user_groups[0]['release_version'] == admin_groups[0]['release_version'], 'User and admin current tiers must name the same release'
    assert user_groups[1]['release_version'] == admin_groups[1]['release_version'], 'User and admin previous tiers must name the same release'

    collapse_ids = [group['collapse_id'] for group in user_groups] + [group['collapse_id'] for group in admin_groups]
    assert len(collapse_ids) == len(set(collapse_ids)), f'Duplicate collapse ids: {collapse_ids}'

    print('Latest Features release group shape is consistent')
    return True


def test_feature_ids_are_unique():
    """Feature ids must be unique within each catalog."""
    print('Testing Latest Features id uniqueness...')

    support_config = load_support_config()

    for label, groups in (
        ('user', support_config.get_support_latest_feature_release_groups()),
        ('admin', support_config.get_admin_latest_feature_release_groups_for_settings({})),
    ):
        feature_ids = [feature['id'] for _group, feature in iter_features(groups)]
        duplicates = sorted({item for item in feature_ids if feature_ids.count(item) > 1})
        assert not duplicates, f'Duplicate {label} feature ids: {duplicates}'

    print('Latest Features ids are unique')
    return True


def test_feature_cards_have_required_content():
    """Every card must carry the keys the templates render."""
    print('Testing Latest Features card content...')

    support_config = load_support_config()
    groups = (
        support_config.get_support_latest_feature_release_groups()
        + support_config.get_admin_latest_feature_release_groups_for_settings({})
    )

    for group, feature in iter_features(groups):
        for key in REQUIRED_FEATURE_KEYS:
            assert key in feature, f"Missing '{key}' on feature {feature.get('id')}"

        feature_id = feature['id']
        assert feature['title'].strip(), f'Empty title for {feature_id}'
        assert feature['summary'].strip(), f'Empty summary for {feature_id}'
        assert feature['why'].strip(), f'Empty why text for {feature_id}'
        assert feature['icon'].startswith('bi-'), f'Icon should be a Bootstrap icon class for {feature_id}'
        assert isinstance(feature['guidance'], list) and feature['guidance'], f'Missing guidance steps for {feature_id}'
        assert isinstance(feature['actions'], list), f'Actions must be a list for {feature_id}'

        # Archived cards predate the current copy conventions, so the stricter
        # phrasing and depth rules apply only to the current release tier.
        if group['id'] == 'current_release':
            assert feature['why'].startswith('This matters because '), f'Unexpected why phrasing for {feature_id}'
            assert len(feature['guidance']) >= 4, f'Expected at least four steps for {feature_id}'

        for action in feature['actions']:
            assert action.get('label'), f'Action missing label on {feature_id}'
            assert action.get('description'), f'Action missing description on {feature_id}'
            assert action.get('icon', '').startswith('bi-'), f'Action icon should be a Bootstrap icon class on {feature_id}'
            assert action.get('href') or action.get('endpoint'), f'Action missing destination on {feature_id}'

    print('Latest Features cards carry required content')
    return True


def test_feature_images_exist_on_disk():
    """Every referenced screenshot must exist so no card renders a broken image."""
    print('Testing Latest Features image assets...')

    support_config = load_support_config()
    groups = (
        support_config.get_support_latest_feature_release_groups()
        + support_config.get_admin_latest_feature_release_groups_for_settings({})
    )

    missing = []
    for group, feature in iter_features(groups):
        images = feature.get('images') or []
        for image in images:
            for key in REQUIRED_IMAGE_KEYS:
                assert image.get(key), f"Missing image '{key}' on {feature['id']}"
            asset_path = os.path.join(STATIC_DIR, image['path'].replace('/', os.sep))
            if not os.path.isfile(asset_path):
                missing.append(image['path'])

        # Archived cards may promote a different gallery entry as the card
        # thumbnail, so the first-entry rule applies to the current tier only.
        if images and group['id'] == 'current_release':
            assert feature.get('image') == images[0]['path'], f"Primary image should match first gallery entry for {feature['id']}"
            assert feature.get('image_alt'), f"Missing primary image alt text for {feature['id']}"

        if images:
            assert feature.get('image_alt') or not feature.get('image'), f"Missing primary image alt text for {feature['id']}"
            if feature.get('image'):
                assert feature['image'] in [image['path'] for image in images], f"Primary image must be part of the gallery for {feature['id']}"

        primary = feature.get('image')
        if primary:
            asset_path = os.path.join(STATIC_DIR, primary.replace('/', os.sep))
            if not os.path.isfile(asset_path):
                missing.append(primary)

    assert not missing, f'Missing Latest Features image assets: {sorted(set(missing))}'

    print('Latest Features image assets are present')
    return True


def test_visibility_defaults_cover_every_user_feature():
    """Admin visibility toggles must exist for every user-facing feature id."""
    print('Testing Latest Features visibility defaults...')

    support_config = load_support_config()
    user_groups = support_config.get_support_latest_feature_release_groups()
    feature_ids = [feature['id'] for _group, feature in iter_features(user_groups)]

    defaults = support_config.get_default_support_latest_features_visibility()
    missing = [feature_id for feature_id in feature_ids if feature_id not in defaults]
    assert not missing, f'Feature ids without a visibility default: {missing}'

    extra = [feature_id for feature_id in defaults if feature_id not in feature_ids]
    assert not extra, f'Visibility defaults reference unknown feature ids: {extra}'

    current_ids = [feature['id'] for feature in user_groups[0]['features']]
    assert all(defaults[feature_id] is True for feature_id in current_ids), 'Current release features ship visible now that every screenshot is a real capture'

    previous_ids = [feature['id'] for feature in user_groups[1]['features']]
    assert any(defaults[feature_id] is True for feature_id in previous_ids), 'Previously published features should remain visible by default'

    normalized = support_config.normalize_support_latest_features_visibility({current_ids[0]: False})
    assert normalized[current_ids[0]] is False, 'Stored visibility choices must be preserved'
    assert normalized[current_ids[1]] is defaults[current_ids[1]], 'Unstored features must fall back to their default'

    print('Latest Features visibility defaults cover every feature')
    return True


def test_action_settings_keys_are_known():
    """Settings-gated action links must reference real settings keys."""
    print('Testing Latest Features settings gating keys...')

    support_config = load_support_config()
    groups = (
        support_config.get_support_latest_feature_release_groups()
        + support_config.get_admin_latest_feature_release_groups_for_settings({})
    )

    with open(SETTINGS_MODULE, 'r', encoding='utf-8') as handle:
        settings_source = handle.read()
    known_keys = set(re.findall(r"'([a-z0-9_]+)':", settings_source))

    unknown = set()
    for _group, feature in iter_features(groups):
        for action in feature.get('actions', []):
            for settings_key in action.get('requires_settings', []) or []:
                if settings_key not in known_keys:
                    unknown.add(f"{feature['id']}:{settings_key}")

    assert not unknown, f'Action links reference unknown settings keys: {sorted(unknown)}'

    print('Latest Features settings gating keys are known')
    return True


def test_current_release_matches_app_version():
    """The current tier must not claim a release newer than the running app."""
    print('Testing Latest Features release version alignment...')

    assert_app_version_at_least('0.260.001')

    support_config = load_support_config()
    current_version = support_config.get_support_latest_feature_release_groups()[0]['release_version']
    assert_app_version_at_least(
        current_version,
        reason='The current Latest Features tier must not advertise a release newer than config.py VERSION.',
    )

    print('Latest Features release version is aligned with the app version')
    return True


if __name__ == '__main__':
    tests = [
        test_release_group_shape,
        test_feature_ids_are_unique,
        test_feature_cards_have_required_content,
        test_feature_images_exist_on_disk,
        test_visibility_defaults_cover_every_user_feature,
        test_action_settings_keys_are_known,
        test_current_release_matches_app_version,
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
