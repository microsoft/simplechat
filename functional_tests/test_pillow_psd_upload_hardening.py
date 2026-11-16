# test_pillow_psd_upload_hardening.py
"""
Functional test for Pillow PSD upload hardening.
Version: 0.261.039
Implemented in: 0.239.134

This test ensures the application pins Pillow to a patched version and limits
admin image uploads to the PNG and JPEG formats that the admin surfaces allow.

The decoding allowlist moved into ``functions_branding_images.py`` in 0.261.039
so the V2 admin surface shares it. That makes the property to assert stronger
than before: every upload path must reach Pillow through the one helper that
passes an explicit ``formats`` allowlist, so no route can decode a PSD by
accepting a renamed file.
"""

import os
import re
import sys


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least, assert_version_at_least


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIREMENTS_PATH = os.path.join(ROOT_DIR, 'application', 'single_app', 'requirements.txt')
ROUTE_PATH = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_frontend_admin_settings.py')
BRANDING_IMAGES_PATH = os.path.join(
    ROOT_DIR, 'application', 'single_app', 'functions_branding_images.py'
)


PILLOW_PIN_RE = re.compile(r'^pillow==([0-9.]+)\s*$', re.MULTILINE | re.IGNORECASE)

# The PSD decoder advisory this test was written for was fixed in 12.1.1.
# Asserting a floor rather than an exact pin means an ordinary dependency
# upgrade does not fail the test, while a downgrade past the fix still does.
MINIMUM_PILLOW_VERSION = '12.1.1'


def read_text(path):
    with open(path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def test_pillow_version_is_patched():
    print('Testing patched Pillow dependency pin...')

    content = read_text(REQUIREMENTS_PATH)
    pin_match = PILLOW_PIN_RE.search(content)
    if not pin_match:
        print('No pinned pillow== requirement found in requirements.txt')
        return False

    pinned_version = pin_match.group(1)
    try:
        assert_version_at_least(
            pinned_version,
            MINIMUM_PILLOW_VERSION,
            label='pinned pillow version',
            reason='Earlier releases carry the PSD decoder advisory.',
        )
    except AssertionError as exc:
        print(f'Pillow pin check failed: {exc}')
        return False

    print(f'Pillow pinned at {pinned_version}, at or beyond the patched release')
    return True


def test_admin_image_uploads_allowlist_formats():
    print('Testing admin image upload format allowlist...')

    branding_content = read_text(BRANDING_IMAGES_PATH)
    route_content = read_text(ROUTE_PATH)

    branding_checks = [
        "ALLOWED_PIL_IMAGE_UPLOAD_FORMATS = ('PNG', 'JPEG')",
        'Image.open(BytesIO(file_bytes), formats=list(ALLOWED_PIL_IMAGE_UPLOAD_FORMATS))',
        # Both preparers must go through the allowlisted open, or one asset
        # type would decode with Pillow's full decoder set.
        'def prepare_logo_image_for_storage',
        'def prepare_favicon_image_for_storage',
    ]

    route_checks = [
        'prepare_logo_image_for_storage(file_bytes, logo_file.filename)',
        'prepare_logo_image_for_storage(file_bytes, logo_dark_file.filename)',
        'prepare_favicon_image_for_storage(file_bytes, favicon_file.filename)',
    ]

    missing_checks = [check for check in branding_checks if check not in branding_content]
    missing_checks += [check for check in route_checks if check not in route_content]

    if branding_content.count('open_allowed_uploaded_image(file_bytes, filename)') < 2:
        missing_checks.append(
            'both branding preparers calling open_allowed_uploaded_image'
        )

    if missing_checks:
        print('Missing upload hardening checks:')
        for missing_check in missing_checks:
            print(f'  - {missing_check}')
        return False

    print('Admin image uploads restrict Pillow to PNG and JPEG parsing')
    return True


def test_config_version_updated():
    print('Testing config version bump...')

    try:
        assert_app_version_at_least('0.239.136')
    except AssertionError as exc:
        print(f'Config version check failed: {exc}')
        return False

    print('Config version is at or beyond the hardening release')
    return True


if __name__ == '__main__':
    test_results = [
        test_pillow_version_is_patched(),
        test_admin_image_uploads_allowlist_formats(),
        test_config_version_updated()
    ]

    passed_tests = sum(test_results)
    total_tests = len(test_results)

    print(f'Passed {passed_tests}/{total_tests} checks')
    sys.exit(0 if all(test_results) else 1)