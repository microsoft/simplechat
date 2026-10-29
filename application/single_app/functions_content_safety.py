# functions_content_safety.py
"""Helpers for formatting user-visible Content Safety violation messages."""

CONTENT_SAFETY_VIOLATION_MESSAGE_DEFAULT = 'Your message was blocked by Content Safety.'
CONTENT_SAFETY_VIOLATION_MESSAGE_MAX_LENGTH = 3000
CONTENT_SAFETY_CATEGORY_THRESHOLD_DEFAULT = 4
CONTENT_SAFETY_CATEGORY_THRESHOLD_LOW = 2
CONTENT_SAFETY_CATEGORY_THRESHOLD_MEDIUM = 4
CONTENT_SAFETY_CATEGORY_THRESHOLD_HIGH = 6
CONTENT_SAFETY_CATEGORY_KEYS = ('Violence', 'Hate', 'Sexual', 'SelfHarm')
CONTENT_SAFETY_CATEGORY_LABELS = {
    'Violence': 'Violence',
    'Hate': 'Hate',
    'Sexual': 'Sexual',
    'SelfHarm': 'Self-harm',
}
CONTENT_SAFETY_CATEGORY_KEY_ALIASES = {
    'violence': 'Violence',
    'hate': 'Hate',
    'sexual': 'Sexual',
    'selfharm': 'SelfHarm',
}


def normalize_content_safety_violation_message(value):
    """Return a non-empty, bounded Markdown message template."""
    candidate = str(value or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    if not candidate:
        return CONTENT_SAFETY_VIOLATION_MESSAGE_DEFAULT
    return candidate[:CONTENT_SAFETY_VIOLATION_MESSAGE_MAX_LENGTH]


def normalize_content_safety_category_key(value):
    """Return a supported Azure Content Safety category key."""
    candidate = str(value or '').strip()
    if candidate in CONTENT_SAFETY_CATEGORY_KEYS:
        return candidate
    normalized = (
        candidate.lower()
        .replace(' ', '')
        .replace('-', '')
        .replace('_', '')
    )
    if '.' in normalized:
        normalized = normalized.rsplit('.', 1)[-1]
    return CONTENT_SAFETY_CATEGORY_KEY_ALIASES.get(normalized)


def normalize_content_safety_category_threshold(value):
    """Return a trimmed Azure Content Safety threshold: low, medium, or high."""
    try:
        candidate = int(value)
    except (TypeError, ValueError):
        return CONTENT_SAFETY_CATEGORY_THRESHOLD_DEFAULT

    if candidate <= CONTENT_SAFETY_CATEGORY_THRESHOLD_LOW:
        return CONTENT_SAFETY_CATEGORY_THRESHOLD_LOW
    if candidate <= CONTENT_SAFETY_CATEGORY_THRESHOLD_MEDIUM:
        return CONTENT_SAFETY_CATEGORY_THRESHOLD_MEDIUM
    return CONTENT_SAFETY_CATEGORY_THRESHOLD_HIGH


def normalize_content_safety_category_thresholds(value, legacy_threshold=None):
    """Return category-specific Content Safety block thresholds."""
    legacy_default = normalize_content_safety_category_threshold(legacy_threshold)
    raw_thresholds = value if isinstance(value, dict) else {}
    return {
        category_key: normalize_content_safety_category_threshold(
            raw_thresholds.get(category_key, legacy_default)
        )
        for category_key in CONTENT_SAFETY_CATEGORY_KEYS
    }


def get_content_safety_category_thresholds(settings):
    """Read category-specific severity thresholds from the settings document."""
    if not isinstance(settings, dict):
        return normalize_content_safety_category_thresholds({})
    return normalize_content_safety_category_thresholds(
        settings.get('content_safety_category_thresholds'),
        legacy_threshold=settings.get('content_safety_block_threshold'),
    )


def get_content_safety_category_threshold(settings, category):
    """Read the severity threshold for one Content Safety category."""
    category_key = normalize_content_safety_category_key(category)
    if not category_key:
        return CONTENT_SAFETY_CATEGORY_THRESHOLD_DEFAULT
    return get_content_safety_category_thresholds(settings).get(
        category_key,
        CONTENT_SAFETY_CATEGORY_THRESHOLD_DEFAULT,
    )


def get_content_safety_category_label(category):
    """Return a user-facing Content Safety category label."""
    category_key = normalize_content_safety_category_key(category)
    if not category_key:
        return str(category or '').strip() or 'Unknown'
    return CONTENT_SAFETY_CATEGORY_LABELS[category_key]


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
