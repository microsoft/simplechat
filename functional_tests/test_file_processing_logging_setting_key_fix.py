#!/usr/bin/env python3
# test_file_processing_logging_setting_key_fix.py
"""
Functional test for file processing logging setting key alignment.
Version: 0.239.141
Implemented in: 0.239.141

This test ensures that the file processing logging helper reads the same
pluralized setting key that the application settings defaults define.
"""

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS_LOGGING_PATH = REPO_ROOT / 'application' / 'single_app' / 'functions_logging.py'
FUNCTIONS_SETTINGS_PATH = REPO_ROOT / 'application' / 'single_app' / 'functions_settings.py'
CONFIG_PATH = REPO_ROOT / 'application' / 'single_app' / 'config.py'


def test_file_processing_logging_setting_key_alignment():
    """Verify the helper and defaults use the same pluralized setting key."""
    print('🔍 Checking file processing logging setting key alignment...')

    functions_logging_source = FUNCTIONS_LOGGING_PATH.read_text(encoding='utf-8')
    functions_settings_source = FUNCTIONS_SETTINGS_PATH.read_text(encoding='utf-8')
    config_source = CONFIG_PATH.read_text(encoding='utf-8')

    assert "settings.get('enable_file_processing_logs', True)" in functions_logging_source, (
        'functions_logging.py should read the pluralized enable_file_processing_logs key.'
    )
    assert "settings.get('enable_file_processing_log', True)" not in functions_logging_source, (
        'functions_logging.py should not use the legacy singular enable_file_processing_log lookup.'
    )
    assert "'enable_file_processing_logs': True" in functions_settings_source, (
        'functions_settings.py should define the pluralized enable_file_processing_logs default.'
    )
    assert 'VERSION = "0.239.141"' in config_source, (
        'config.py should be bumped to version 0.239.141 for this fix.'
    )

    print('✅ File processing logging setting keys are aligned.')


if __name__ == '__main__':
    try:
        test_file_processing_logging_setting_key_alignment()
    except AssertionError as exc:
        print(f'❌ Test failed: {exc}')
        sys.exit(1)
    except Exception as exc:
        print(f'❌ Unexpected error: {exc}')
        import traceback
        traceback.print_exc()
        sys.exit(1)

    sys.exit(0)