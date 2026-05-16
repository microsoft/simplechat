# test_chat_document_picker_full_width.py
"""
Functional test for full-width chat document picker controls.
Version: 0.241.030
Implemented in: 0.241.030

This test ensures the shared chat document picker lets the Document dropdown
fill the remaining desktop row for Search, Analyze, and Compare while retaining
the existing full-width mobile drawer behavior.
"""

import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHAT_CSS_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'css',
    'chats.css',
)
CHATS_TEMPLATE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'templates',
    'chats.html',
)
CONFIG_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'config.py',
)


def read_file(path):
    with open(path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def test_document_picker_template_exposes_wide_document_field():
    """Verify the shared document picker identifies the flexible Document field."""
    print('Testing document picker template wide field wiring...')

    content = read_file(CHATS_TEMPLATE)

    required_snippets = [
        'class="chat-search-panel-grid"',
        'id="document-action-select"',
        'value="none"',
        'value="analyze"',
        'value="comparison"',
        'data-chat-document-picker-field="document"',
        'class="flex-grow-1 chat-search-panel-field chat-search-panel-field-wide"',
        'id="document-dropdown-button"',
        'id="document-comparison-picker-controls"',
    ]

    missing = [snippet for snippet in required_snippets if snippet not in content]
    assert not missing, f'Missing document picker template wiring: {missing}'

    print('Document picker template wide field wiring passed')


def test_document_picker_css_stretches_controls_without_breaking_mobile():
    """Verify CSS stretches picker controls on desktop and keeps mobile full-width."""
    print('Testing document picker full-width CSS...')

    content = read_file(CHAT_CSS_FILE)

    required_snippets = [
        '.chat-search-panel-field > .dropdown,',
        '.chat-search-panel-field > .form-select {\n  width: 100%;\n}',
        '.chat-search-panel-field-wide {\n  flex-basis: 32rem;\n  max-width: none !important;\n}',
        '.document-comparison-picker-controls .dropdown,',
        '.document-comparison-picker-controls .form-select {\n  width: 100%;\n}',
        '@media (max-width: 991.98px) {',
        '#search-documents-container .flex-shrink-0,\n  #search-documents-container .flex-grow-1 {\n    max-width: none !important;',
        '#search-documents-container .dropdown,\n  #search-documents-container .form-select {\n    width: 100%;\n  }',
    ]

    missing = [snippet for snippet in required_snippets if snippet not in content]
    assert not missing, f'Missing document picker full-width CSS rules: {missing}'

    print('Document picker full-width CSS passed')


def test_version_bumped_for_document_picker_full_width_fix():
    """Verify config version was bumped for the full-width document picker fix."""
    print('Testing config version bump...')

    config_content = read_file(CONFIG_FILE)
    assert 'VERSION = "0.241.030"' in config_content, 'Expected config.py version 0.241.030'

    print('Config version bump passed')


if __name__ == '__main__':
    tests = [
        test_document_picker_template_exposes_wide_document_field,
        test_document_picker_css_stretches_controls_without_breaking_mobile,
        test_version_bumped_for_document_picker_full_width_fix,
    ]
    results = []

    for test in tests:
        print(f'\nRunning {test.__name__}...')
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f'Test failed: {exc}')
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f'\nResults: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)