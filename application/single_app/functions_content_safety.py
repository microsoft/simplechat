# functions_content_safety.py
"""Import-safe Content Safety evaluation and user-visible message formatting."""

import math
import time
from dataclasses import dataclass, field
from typing import Literal

CONTENT_SAFETY_VIOLATION_MESSAGE_DEFAULT = 'Your message was blocked by Content Safety.'
CONTENT_SAFETY_VIOLATION_MESSAGE_MAX_LENGTH = 3000
CONTENT_SAFETY_MAX_CHARACTERS = 10000
CONTENT_SAFETY_WINDOW_OVERLAP = 500
CONTENT_SAFETY_MAX_WINDOWS = 32
CONTENT_SAFETY_RUNTIME_SECONDS = 30.0
CONTENT_SAFETY_CATEGORIES = frozenset({"Hate", "SelfHarm", "Sexual", "Violence"})


@dataclass
class ContentSafetyAnalysis:
    status: Literal["passed", "findings", "not_checked"]
    complete: bool = False
    categories: list[dict] = field(default_factory=list)
    blocklist_match_count: int = 0
    completed_windows: int = 0
    required_windows: int = 0
    error_code: str | None = None


def analyze_content_safety_text(text, client, *, runtime_seconds=CONTENT_SAFETY_RUNTIME_SECONDS):
    """Cover all text in bounded service windows; callers log explicit incomplete outcomes."""
    result = ContentSafetyAnalysis("not_checked")
    if not isinstance(text, str) or not text.strip():
        result.error_code = "content_safety_empty_text"
        return result
    if client is None:
        result.error_code = "content_safety_unavailable"
        return result
    step = CONTENT_SAFETY_MAX_CHARACTERS - CONTENT_SAFETY_WINDOW_OVERLAP
    result.required_windows = 1 + max(0, math.ceil((len(text) - CONTENT_SAFETY_MAX_CHARACTERS) / step))
    if result.required_windows > CONTENT_SAFETY_MAX_WINDOWS:
        result.error_code = "content_safety_window_limit"
        return result
    deadline = time.monotonic() + max(0.0, min(float(runtime_seconds), CONTENT_SAFETY_RUNTIME_SECONDS))
    severities = {}
    # Settings imports this module for defaults; only an executing scanner needs the SDK.
    from azure.ai.contentsafety.models import AnalyzeTextOptions

    for index in range(result.required_windows):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            result.error_code = "content_safety_timeout"
            break
        window = text[index * step:index * step + CONTENT_SAFETY_MAX_CHARACTERS]
        try:
            response = client.analyze_text(
                AnalyzeTextOptions(text=window),
                connection_timeout=min(5.0, remaining),
                read_timeout=remaining,
                retry_total=0,
            )
            window_categories = {}
            for category in response.categories_analysis or []:
                name = getattr(category.category, "value", category.category)
                severity = category.severity
                if (
                    name not in CONTENT_SAFETY_CATEGORIES or name in window_categories
                    or type(severity) is not int or severity not in (0, 2, 4, 6)
                ):
                    raise ValueError("Invalid Content Safety categories.")
                window_categories[name] = severity
                severities[name] = max(severities.get(name, 0), severity)
            if set(window_categories) != CONTENT_SAFETY_CATEGORIES:
                raise ValueError("Incomplete Content Safety categories.")
            matches = response.blocklists_match or []
            if not isinstance(matches, (list, tuple)):
                raise ValueError("Invalid Content Safety blocklist results.")
            result.blocklist_match_count += len(matches)
            result.completed_windows += 1
        except TimeoutError:
            result.error_code = "content_safety_timeout"
            break
        except (AttributeError, TypeError, ValueError):
            result.error_code = "content_safety_invalid_response"
            break
        except Exception:
            result.error_code = "content_safety_request_failed"
            break
    result.categories = [
        {"category": name, "severity": severity} for name, severity in sorted(severities.items())
    ]
    result.complete = (
        result.completed_windows == result.required_windows
        and result.error_code is None and time.monotonic() <= deadline
    )
    if not result.complete and result.error_code is None:
        result.error_code = "content_safety_timeout"
    if result.blocklist_match_count or any(severity >= 4 for severity in severities.values()):
        result.status = "findings"
    elif result.complete:
        result.status = "passed"
    return result


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
