# functions_rate_limit.py
"""Helpers for the user-visible rate limiting (HTTP 429) response message.

SimpleChat returns 429 from several unrelated places: chat streaming when
provider retries are exhausted, text to speech, the Swagger spec endpoints and
inbound MCP tool calls. Each of those used to carry its own hard-coded string,
so a throttled user got a different and usually unhelpful explanation depending
on which surface they happened to hit.

Resolution lives here so every surface renders the same admin-authored message,
and so the fallback rules are defined exactly once.
"""

RATE_LIMIT_MESSAGE_DEFAULT = (
    "**You have reached the request limit.**\n\n"
    "Too many requests were sent in a short period of time. "
    "Please wait a moment and try again."
)
RATE_LIMIT_MESSAGE_MAX_LENGTH = 3000


def normalize_rate_limit_message(value):
    """Return a non-empty, bounded Markdown message."""
    candidate = str(value or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    if not candidate:
        return RATE_LIMIT_MESSAGE_DEFAULT
    return candidate[:RATE_LIMIT_MESSAGE_MAX_LENGTH]


def build_rate_limit_message(settings):
    """Return the Markdown message shown when a request is rate limited.

    Falls back to the built-in default when an admin has not opted in to a
    custom message, so a throttled user is never left with an empty response.
    """
    rate_limit_settings = settings if isinstance(settings, dict) else {}

    if not rate_limit_settings.get('enable_custom_rate_limit_message', False):
        return RATE_LIMIT_MESSAGE_DEFAULT

    return normalize_rate_limit_message(rate_limit_settings.get('rate_limit_message'))


def build_rate_limit_error_payload(settings, **extra):
    """Return the JSON body for a rate limited response.

    The message stays raw Markdown because callers render it differently: the
    chat client parses it with marked, while server-rendered pages run it
    through the Jinja markdown filter.
    """
    payload = {
        'error': build_rate_limit_message(settings),
        'rate_limited': True,
    }

    for key, value in extra.items():
        if value is not None:
            payload[key] = value

    return payload
