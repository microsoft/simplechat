# test_pillow_psd_upload_hardening.py
"""
Functional test for Pillow PSD upload hardening.
Version: 0.239.136
Implemented in: 0.239.134

This test ensures the application pins Pillow to a patched version and limits
admin image uploads to the PNG and JPEG formats that the route already allows.
"""

import os
import sys


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIREMENTS_PATH = os.path.join(ROOT_DIR, 'application', 'single_app', 'requirements.txt')
ROUTE_PATH = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_frontend_admin_settings.py')
CONFIG_PATH = os.path.join(ROOT_DIR, 'application', 'single_app', 'config.py')


def read_text(path):
    with open(path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def test_pillow_version_is_patched():
    print('Testing patched Pillow dependency pin...')

    content = read_text(REQUIREMENTS_PATH)
    if 'pillow==12.1.1' not in content:
        print('Patched Pillow version pin not found in requirements.txt')
        return False

    print('Patched Pillow version pin found in requirements.txt')
    return True


def test_admin_image_uploads_allowlist_formats():
    print('Testing admin image upload format allowlist...')

    content = read_text(ROUTE_PATH)
    checks = [
        "ALLOWED_PIL_IMAGE_UPLOAD_FORMATS = ('PNG', 'JPEG')",
        'Image.open(BytesIO(file_bytes), formats=list(ALLOWED_PIL_IMAGE_UPLOAD_FORMATS))',
        'open_allowed_uploaded_image(file_bytes, logo_file.filename)',
        'open_allowed_uploaded_image(file_bytes, logo_dark_file.filename)',
        'open_allowed_uploaded_image(file_bytes, favicon_file.filename)'
    ]

    missing_checks = [check for check in checks if check not in content]
    if missing_checks:
        print('Missing upload hardening checks:')
        for missing_check in missing_checks:
            print(f'  - {missing_check}')
        return False

    print('Admin image upload route restricts Pillow to PNG and JPEG parsing')
    return True


def test_config_version_updated():
    print('Testing config version bump...')

    content = read_text(CONFIG_PATH)
    if 'VERSION = "0.239.136"' not in content:
        print('Expected config version 0.239.136 not found')
        return False

    print('Config version updated to 0.239.136')
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