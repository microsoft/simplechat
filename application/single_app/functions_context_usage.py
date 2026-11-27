# functions_context_usage.py
"""Measure what one chat request sends to the model, grouped by where the text came from.

The chat routes assemble a list of messages and send it. This module sizes that list just
before it is sent, so the context usage display can say how much of the model's window the
conversation used and what used it. The sizes are estimates made with the model's tokenizer;
the provider's own count for the same request is stored separately on the reply.

Field names here deliberately avoid the words "token" and "key": several serializers in the
application treat any field whose name contains them as a credential.
"""

import re
import threading

import requests
import tiktoken

from functions_conversation_context import CONVERSATION_CONTEXT_START_MARKER
from functions_model_capabilities import ModelTokenBudgetError, resolve_model_token_budget


CONTEXT_USAGE_VERSION = 1

CATEGORY_MESSAGES = 'messages'
CATEGORY_SUMMARY = 'summary'
CATEGORY_FILES = 'files'
CATEGORY_SEARCH = 'search'
CATEGORY_WEB = 'web'
CATEGORY_MEMORY = 'memory'
CATEGORY_INSTRUCTIONS = 'instructions'
CONTEXT_USAGE_CATEGORIES = (
    CATEGORY_MESSAGES,
    CATEGORY_SUMMARY,
    CATEGORY_FILES,
    CATEGORY_SEARCH,
    CATEGORY_WEB,
    CATEGORY_MEMORY,
    CATEGORY_INSTRUCTIONS,
)

ESTIMATOR_CHARACTERS = 'characters'
DEFAULT_ENCODING_NAME = 'o200k_base'
# Chat formats spend a few units on each message's role and separators.
PER_MESSAGE_OVERHEAD = 4
CHARACTERS_PER_UNIT = 4
MAX_CONTEXT_USAGE_ITEMS = 12
MAX_ITEM_LABEL_CHARS = 120

SUMMARY_PREFIX = '<Summary of previous conversation context>'
UPLOAD_PATTERN = re.compile(
    r"^\[User uploaded (?:a file|a tabular data file|an image) named '(?P<name>[^'\n]*)'"
)
# Web search results and pages fetched for URL access or deep research.
WEB_PREFIXES = ('Web search results', 'Web IQ search results', '[SOURCE_REVIEW_EVIDENCE]')
GENERATED_IMAGE_PREFIX = '[Assistant generated an image'
MEMORY_MARKERS = ('<Fact Memory>', '<Conversation Metadata>')
MEMORY_PREFIX = 'Apply these saved user instruction memories'
# Retrieval steps keep their bookkeeping beside the text they add to the request.
SEARCH_MESSAGE_FIELDS = ('documents', 'mixed_source_coverage', 'assigned_knowledge_inventory')

_ENCODING_LOCK = threading.Lock()
_ENCODING_CACHE = {}


def _load_encoding(model_name):
    """Return (encoding, name), or (None, 'characters') when no vocabulary is available.

    The answer is remembered, including a failure: a deployment that cannot reach the
    vocabulary host must not wait for it again on every chat request.
    """
    cache_name = str(model_name or '').strip().lower()
    with _ENCODING_LOCK:
        if cache_name in _ENCODING_CACHE:
            return _ENCODING_CACHE[cache_name]
    try:
        encoding_name = tiktoken.encoding_name_for_model(cache_name)
    except KeyError:
        encoding_name = DEFAULT_ENCODING_NAME
    try:
        loaded = (tiktoken.get_encoding(encoding_name), encoding_name)
    except (OSError, ValueError, requests.RequestException):
        loaded = (None, ESTIMATOR_CHARACTERS)
    with _ENCODING_LOCK:
        _ENCODING_CACHE[cache_name] = loaded
    return loaded


def reset_context_usage_encoding_cache():
    """Forget remembered tokenizers. Tests use this; the application does not need it."""
    with _ENCODING_LOCK:
        _ENCODING_CACHE.clear()


def _message_text(message):
    """Return the text of a message. Image parts carry no text and are not sized here."""
    content = message.get('content') if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and isinstance(part.get('text'), str):
                parts.append(part['text'])
        return '\n'.join(parts)
    return '' if content is None else str(content)


def _size_text(text, encoding):
    if not text:
        return 0
    if encoding is None:
        return -(-len(text) // CHARACTERS_PER_UNIT)
    return len(encoding.encode(text, disallowed_special=()))


def classify_context_message(message):
    """Return (category, label) for one message of the request. The label names a file."""
    if not isinstance(message, dict):
        return CATEGORY_INSTRUCTIONS, ''
    role = str(message.get('role') or '').strip().lower()
    text = _message_text(message)
    if role == 'assistant':
        return CATEGORY_MESSAGES, ''
    if role == 'user':
        # The application's own context note travels as a user message beside the real one.
        if text.startswith(CONVERSATION_CONTEXT_START_MARKER):
            return CATEGORY_INSTRUCTIONS, ''
        return CATEGORY_MESSAGES, ''
    if role != 'system':
        return CATEGORY_INSTRUCTIONS, ''
    if text.startswith(SUMMARY_PREFIX):
        return CATEGORY_SUMMARY, ''
    upload = UPLOAD_PATTERN.match(text)
    if upload:
        return CATEGORY_FILES, upload.group('name')[:MAX_ITEM_LABEL_CHARS]
    if any(message.get(field) for field in SEARCH_MESSAGE_FIELDS):
        return CATEGORY_SEARCH, ''
    if text.startswith(WEB_PREFIXES):
        return CATEGORY_WEB, ''
    if text.startswith(GENERATED_IMAGE_PREFIX):
        # The note that stands in for an image the assistant made is part of the conversation.
        return CATEGORY_MESSAGES, ''
    if text.startswith(MEMORY_PREFIX) or any(marker in text for marker in MEMORY_MARKERS):
        return CATEGORY_MEMORY, ''
    return CATEGORY_INSTRUCTIONS, ''


def _positive_int(value):
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def resolve_context_limits(model=None, endpoint=None, *, provider=None, response_length=None):
    """Return the model's window and how much of it a request may fill, or {} if unknown.

    ``input_ceiling`` is what the display measures against: the window less the space held
    back for the reply, and never more than the model's own input limit.
    """
    try:
        budget = resolve_model_token_budget(model, endpoint, provider=provider)
    except (ModelTokenBudgetError, TypeError, ValueError):
        return {}
    windows = [
        value for value in (budget.context_window, budget.effective_context_window)
        if value is not None
    ]
    window = min(windows) if windows else None
    reply_reserve = _positive_int(response_length) or budget.output_limit
    if window is not None and reply_reserve is not None and reply_reserve >= window:
        # A reply allowance as large as the window says nothing about the room for input.
        reply_reserve = None
    bounds = []
    if budget.input_limit is not None:
        bounds.append(budget.input_limit)
    if window is not None:
        bounds.append(window - (reply_reserve or 0))
    if not bounds:
        return {}
    return {
        'window': window,
        'input_limit': budget.input_limit,
        'reply_reserve': reply_reserve,
        'input_ceiling': max(0, min(bounds)),
    }


def measure_context_usage(messages, *, model_name=None, limits=None):
    """Size a request's messages by category. Never raises for odd message shapes."""
    encoding, estimator = _load_encoding(model_name)
    sizes = {}
    counts = {}
    files = {}
    total = 0
    message_count = 0
    for message in messages or ():
        if not isinstance(message, dict):
            continue
        message_count += 1
        category, label = classify_context_message(message)
        size = _size_text(_message_text(message), encoding) + PER_MESSAGE_OVERHEAD
        sizes[category] = sizes.get(category, 0) + size
        counts[category] = counts.get(category, 0) + 1
        total += size
        if category == CATEGORY_FILES and label:
            files[label] = files.get(label, 0) + size
    items = [
        {'category': CATEGORY_FILES, 'label': label, 'size': size}
        for label, size in sorted(files.items(), key=lambda entry: (-entry[1], entry[0]))
    ][:MAX_CONTEXT_USAGE_ITEMS]
    return {
        'version': CONTEXT_USAGE_VERSION,
        'estimator': estimator,
        'model': str(model_name or '') or None,
        'estimated_total': total,
        'message_count': message_count,
        'categories': {name: sizes[name] for name in CONTEXT_USAGE_CATEGORIES if sizes.get(name)},
        'counts': {name: counts[name] for name in CONTEXT_USAGE_CATEGORIES if counts.get(name)},
        'items': items,
        'limits': dict(limits or {}),
    }
