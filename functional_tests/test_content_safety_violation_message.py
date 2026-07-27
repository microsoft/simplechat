# test_content_safety_violation_message.py
#!/usr/bin/env python3
"""
Functional test for configurable Content Safety violation messages.
Version: 0.250.060
Implemented in: 0.250.060

This test ensures that administrators can provide a Markdown safety message
and choose whether blocked-chat trigger information is included.
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

from functions_content_safety import (
    CONTENT_SAFETY_VIOLATION_MESSAGE_DEFAULT,
    CONTENT_SAFETY_VIOLATION_MESSAGE_MAX_LENGTH,
    build_content_safety_violation_message,
    normalize_content_safety_violation_message,
)


BLOCK_REASONS = ['Max severity >= 4', 'Blocklist match']
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


def test_admin_settings_uses_the_markdown_editor_toolbar():
    """The Content Safety message field uses the standard local Markdown toolbar."""
    admin_settings_template = ADMIN_SETTINGS_TEMPLATE_PATH.read_text(encoding='utf-8')

    assert '<script src="/static/js/simplemde/simplemde.min.js"></script>' in admin_settings_template
    assert 'id="content_safety_violation_message"' in admin_settings_template
    assert 'let contentSafetyViolationMessageEditor = null;' in admin_settings_template
    assert 'function initializeContentSafetyViolationMessageEditor()' in admin_settings_template
    assert 'contentSafetyViolationMessageEditor = new SimpleMDE({' in admin_settings_template
    assert 'element: contentSafetyViolationMessageInput,' in admin_settings_template
    assert 'spellChecker: false,' in admin_settings_template
    assert 'autoDownloadFontAwesome: false' in admin_settings_template
    assert 'initializeContentSafetyViolationMessageEditor();' in admin_settings_template


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
        '**Reason**: Max severity >= 4, Blocklist match\n'
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
    test_admin_settings_uses_the_markdown_editor_toolbar()
    test_default_message_preserves_trigger_information()
    test_custom_markdown_message_precedes_trigger_information()
    test_trigger_information_can_be_hidden_and_blank_templates_fall_back()
    print('Content Safety violation message tests passed.')
