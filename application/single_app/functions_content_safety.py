# functions_content_safety.py
"""Helpers for formatting user-visible Content Safety violation messages."""

CONTENT_SAFETY_VIOLATION_MESSAGE_DEFAULT = 'Your message was blocked by Content Safety.'
CONTENT_SAFETY_VIOLATION_MESSAGE_MAX_LENGTH = 3000


def normalize_content_safety_violation_message(value):
    """Return a non-empty, bounded Markdown message template."""
    candidate = str(value or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    if not candidate:
        return CONTENT_SAFETY_VIOLATION_MESSAGE_DEFAULT
    return candidate[:CONTENT_SAFETY_VIOLATION_MESSAGE_MAX_LENGTH]


def build_content_safety_violation_message(
    settings,
    block_reasons,
    triggered_categories,
    blocklist_matches,
):
    """Build the Markdown message shown after a blocked chat request."""
    safety_settings = settings if isinstance(settings, dict) else {}
    message_template = normalize_content_safety_violation_message(
        safety_settings.get('content_safety_violation_message')
    )

    if safety_settings.get('content_safety_include_trigger_information', True) is False:
        return message_template

    normalized_reasons = [
        str(reason).strip()
        for reason in (block_reasons or [])
        if str(reason or '').strip()
    ]
    trigger_lines = [
        f"**Reason**: {', '.join(normalized_reasons)}",
        'Triggered categories:',
    ]

    for category in triggered_categories or []:
        if not isinstance(category, dict):
            continue
        category_name = str(category.get('category') or '').strip()
        if category_name:
            trigger_lines.append(
                f" - {category_name} (severity={category.get('severity')})"
            )

    formatted_blocklist_matches = []
    for match in blocklist_matches or []:
        if not isinstance(match, dict):
            continue
        item_text = str(match.get('blocklistItemText') or '').strip()
        blocklist_name = str(match.get('blocklistName') or '').strip()
        if item_text and blocklist_name:
            formatted_blocklist_matches.append(
                f" - {item_text} (in {blocklist_name})"
            )

    if formatted_blocklist_matches:
        trigger_lines.extend(['', 'Blocklist Matches:', *formatted_blocklist_matches])

    return f"{message_template}\n\n" + '\n'.join(trigger_lines)
