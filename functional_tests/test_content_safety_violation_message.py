# test_content_safety_violation_message.py
#!/usr/bin/env python3
"""
Functional test for configurable Content Safety violation messages.
Version: 0.261.059
Implemented in: 0.250.061

This test ensures that administrators can provide a Markdown safety message,
choose whether blocked-chat trigger information is included, and configure
category-specific prompt severity thresholds used for blocking and recording
violations.
"""

import os
import sys
from pathlib import Path


APPLICATION_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    '..',
    'application',
    'single_app',
)
ADMIN_SETTINGS_TEMPLATE_PATH = Path(APPLICATION_PATH) / 'templates' / 'admin_settings.html'
sys.path.insert(0, APPLICATION_PATH)

from types import SimpleNamespace
from unittest.mock import Mock

from test_support.templates import read_admin_settings_template

from functions_chat_content_checks import evaluate_chat_content
from functions_content_safety import (
    CONTENT_SAFETY_CATEGORY_THRESHOLD_DEFAULT,
    CONTENT_SAFETY_CATEGORY_THRESHOLD_HIGH,
    CONTENT_SAFETY_CATEGORY_THRESHOLD_LOW,
    CONTENT_SAFETY_VIOLATION_MESSAGE_DEFAULT,
    CONTENT_SAFETY_VIOLATION_MESSAGE_MAX_LENGTH,
    analyze_content_safety_text,
    build_content_safety_violation_message,
    get_content_safety_category_label,
    get_content_safety_category_threshold,
    get_content_safety_category_thresholds,
    normalize_content_safety_category_threshold,
    normalize_content_safety_category_thresholds,
    normalize_content_safety_violation_message,
)


BLOCK_REASONS = ['Hate severity >= 4', 'Blocklist match']
TRIGGERED_CATEGORIES = [{'category': 'Hate', 'severity': 6}]
BLOCKLIST_MATCHES = [
    {
        'blocklistItemText': 'restricted phrase',
        'blocklistName': 'corporate-policy',
    }
]


def test_message_normalization_preserves_safe_admin_defaults():
    """Blank, Windows-style, and oversized form values are normalized safely."""
    assert (
        normalize_content_safety_violation_message(None)
        == CONTENT_SAFETY_VIOLATION_MESSAGE_DEFAULT
    )
    assert normalize_content_safety_violation_message(
        '  **Blocked**\r\n\r\nReview the policy.  '
    ) == '**Blocked**\n\nReview the policy.'
    assert len(
        normalize_content_safety_violation_message(
            'x' * (CONTENT_SAFETY_VIOLATION_MESSAGE_MAX_LENGTH + 1)
        )
    ) == CONTENT_SAFETY_VIOLATION_MESSAGE_MAX_LENGTH


def test_content_safety_category_thresholds_are_bounded_for_admin_storage():
    """Prompt category thresholds stay within Low, Medium, and High values."""
    assert normalize_content_safety_category_threshold(None) == CONTENT_SAFETY_CATEGORY_THRESHOLD_DEFAULT
    assert normalize_content_safety_category_threshold('1') == CONTENT_SAFETY_CATEGORY_THRESHOLD_LOW
    assert normalize_content_safety_category_threshold('2') == 2
    assert normalize_content_safety_category_threshold('3') == 4
    assert normalize_content_safety_category_threshold('5') == CONTENT_SAFETY_CATEGORY_THRESHOLD_HIGH
    assert normalize_content_safety_category_threshold('8') == CONTENT_SAFETY_CATEGORY_THRESHOLD_HIGH
    assert normalize_content_safety_category_thresholds({'Hate': '2'}) == {
        'Violence': 4,
        'Hate': 2,
        'Sexual': 4,
        'SelfHarm': 4,
    }
    assert get_content_safety_category_threshold(
        {'content_safety_category_thresholds': {'SelfHarm': '6'}},
        'SelfHarm',
    ) == 6
    assert get_content_safety_category_thresholds({'content_safety_block_threshold': '6'}) == {
        'Violence': 6,
        'Hate': 6,
        'Sexual': 6,
        'SelfHarm': 6,
    }
    assert get_content_safety_category_label('self-harm') == 'Self-harm'


def test_analyze_and_evaluate_respect_category_thresholds():
    """Low thresholds block severity 2; High thresholds allow severity 4 and block severity 6."""
    client = Mock()
    client.analyze_text.return_value = SimpleNamespace(
        categories_analysis=[
            SimpleNamespace(category='Violence', severity=2),
            SimpleNamespace(category='Hate', severity=4),
            SimpleNamespace(category='Sexual', severity=0),
            SimpleNamespace(category='SelfHarm', severity=0),
        ],
        blocklists_match=[],
    )
    settings = {
        'enable_content_safety': True,
        'enable_content_safety_chat_input': True,
        'content_safety_category_thresholds': {
            'Violence': 2,
            'Hate': 6,
            'Sexual': 4,
            'SelfHarm': 4,
        },
    }
    analysis = analyze_content_safety_text('sample prompt', client, settings=settings)
    assert analysis.status == 'findings'
    categories_by_name = {item['category']: item for item in analysis.categories}
    assert categories_by_name['Violence']['threshold'] == 2
    assert categories_by_name['Hate']['threshold'] == 6

    decision = evaluate_chat_content('sample prompt', 'chat_input', settings, safety_client=client)
    assert decision.blocked is True
    assert 'Violence severity >= 2' in decision.notice
    assert 'Hate severity' not in decision.notice


def test_admin_settings_uses_the_markdown_editor_toolbar():
    """The Content Safety message field uses the standard local Markdown toolbar."""
    admin_settings_template = read_admin_settings_template()

    assert 'id="content-safety-category-thresholds"' in admin_settings_template
    assert 'Prompt Category Block Thresholds' in admin_settings_template
    assert 'name="content_safety_threshold_violence"' in admin_settings_template
    assert 'name="content_safety_threshold_hate"' in admin_settings_template
    assert 'name="content_safety_threshold_sexual"' in admin_settings_template
    assert 'name="content_safety_threshold_self_harm"' in admin_settings_template
    assert 'class="form-range content-safety-category-threshold-range"' in admin_settings_template
    assert 'min="2"' in admin_settings_template
    assert 'max="6"' in admin_settings_template
    assert 'step="2"' in admin_settings_template
    assert 'Block Low, Medium and High' in admin_settings_template
    assert 'Allow Low / Block Medium and High' in admin_settings_template
    assert 'Allow Low and Medium / Block High' in admin_settings_template
    assert 'Higher threshold levels don’t override the model deployment guardrails.' in admin_settings_template
    assert '<script src="/static/js/simplemde/simplemde.min.js"></script>' in admin_settings_template
    assert 'id="content_safety_violation_message"' in admin_settings_template
    assert 'let contentSafetyViolationMessageEditor = null;' in admin_settings_template
    assert 'function initializeContentSafetyViolationMessageEditor()' in admin_settings_template
    assert 'contentSafetyViolationMessageEditor = new SimpleMDE({' in admin_settings_template
    assert 'element: contentSafetyViolationMessageInput,' in admin_settings_template
    assert 'spellChecker: false,' in admin_settings_template
    assert 'autoDownloadFontAwesome: false' in admin_settings_template
    assert 'forceSync: true' in admin_settings_template
    assert 'contentSafetyViolationMessageEditor.codemirror.on("change", () => {' in admin_settings_template
    assert 'window.markFormAsModified();' in admin_settings_template
    assert 'initializeContentSafetyViolationMessageEditor();' in admin_settings_template
    assert 'function refreshContentSafetyViolationMessageEditor()' in admin_settings_template
    assert 'contentSafetyViolationMessageEditor.codemirror.refresh();' in admin_settings_template
    assert 'window.setTimeout(() => {' in admin_settings_template
    assert '}, 100);' in admin_settings_template
    assert 'safetyTab.addEventListener("shown.bs.tab", refreshContentSafetyViolationMessageEditor);' in admin_settings_template
    assert 'window.addEventListener("load", refreshContentSafetyViolationMessageEditor);' in admin_settings_template


def test_default_message_preserves_trigger_information():
    """The default settings retain the legacy detailed safety response."""
    message = build_content_safety_violation_message(
        {},
        BLOCK_REASONS,
        TRIGGERED_CATEGORIES,
        BLOCKLIST_MATCHES,
    )

    assert message == (
        'Your message was blocked by Content Safety.\n\n'
        '**Reason**: Hate severity >= 4, Blocklist match\n'
        'Triggered categories:\n'
        ' - Hate (severity=6)\n\n'
        'Blocklist Matches:\n'
        ' - restricted phrase (in corporate-policy)'
    )


def test_custom_markdown_message_precedes_trigger_information():
    """A saved Markdown template remains intact before the trigger details."""
    markdown_template = (
        '**Message blocked**\n\n'
        'Review the [acceptable-use policy](/acceptable_use_policy).'
    )
    message = build_content_safety_violation_message(
        {
            'content_safety_violation_message': markdown_template,
            'content_safety_include_trigger_information': True,
        },
        BLOCK_REASONS,
        TRIGGERED_CATEGORIES,
        BLOCKLIST_MATCHES,
    )

    assert message.startswith(markdown_template + '\n\n**Reason**:')
    assert 'Blocklist Matches:' in message


def test_trigger_information_can_be_hidden_and_blank_templates_fall_back():
    """Admins can hide details, while blank templates use the default message."""
    hidden_details_message = build_content_safety_violation_message(
        {
            'content_safety_violation_message': 'Please review the acceptable-use policy.',
            'content_safety_include_trigger_information': False,
        },
        BLOCK_REASONS,
        TRIGGERED_CATEGORIES,
        BLOCKLIST_MATCHES,
    )
    blank_template_message = build_content_safety_violation_message(
        {
            'content_safety_violation_message': '   ',
            'content_safety_include_trigger_information': False,
        },
        BLOCK_REASONS,
        TRIGGERED_CATEGORIES,
        BLOCKLIST_MATCHES,
    )

    assert hidden_details_message == 'Please review the acceptable-use policy.'
    assert blank_template_message == 'Your message was blocked by Content Safety.'


if __name__ == '__main__':
    test_message_normalization_preserves_safe_admin_defaults()
    test_content_safety_category_thresholds_are_bounded_for_admin_storage()
    test_analyze_and_evaluate_respect_category_thresholds()
    test_admin_settings_uses_the_markdown_editor_toolbar()
    test_default_message_preserves_trigger_information()
    test_custom_markdown_message_precedes_trigger_information()
    test_trigger_information_can_be_hidden_and_blank_templates_fall_back()
    print('Content Safety violation message tests passed.')
