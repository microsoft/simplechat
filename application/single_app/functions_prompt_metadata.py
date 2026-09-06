# functions_prompt_metadata.py
"""Validate turn-local prompt snapshots without accessing settings, storage or the clock."""

import re


def _active_template_keys(template):
    """Mirror the placeholder/code-region rules in V2's promptVariables.ts."""
    regions = []
    open_fence = None
    for match in re.finditer(r'^[ \t]{0,3}(`{3,}|~{3,})[^\n]*$', template, re.MULTILINE):
        marker = match.group(1)
        if open_fence is None:
            open_fence = (marker, match.start())
        elif marker[0] == open_fence[0][0] and len(marker) >= len(open_fence[0]):
            regions.append((open_fence[1], match.end()))
            open_fence = None
    if open_fence is not None:
        regions.append((open_fence[1], len(template)))

    def in_code(index):
        return any(start <= index < end for start, end in regions)

    open_ticks = None
    for match in re.finditer(r'`+', template):
        if in_code(match.start()):
            continue
        if open_ticks is None:
            open_ticks = (len(match.group()), match.start())
        elif len(match.group()) == open_ticks[0]:
            regions.append((open_ticks[1], match.end()))
            open_ticks = None

    keys = set()
    for match in re.finditer(r'(\\?)\{\{([^{}]*)\}\}', template):
        if match.group(1) or in_code(match.start()):
            continue
        name = match.group(2).split('|', 1)[0].strip()
        if re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_ -]{0,39}', name):
            keys.add(re.sub(r'[\s-]+', '_', name.lower()))
    return keys


def _optional_text(value):
    return value if isinstance(value, str) else None


def parse_prompt_variable_keys(template):
    """Return active normalized placeholders, excluding escaped and Markdown-literal text."""
    return _active_template_keys(template)


def build_prompt_selection_metadata(prompt_info, message_content):
    """Return compatible prompt metadata only when the stored message supports its split.

    The resolved text is authoritative: historical prompts are never resolved from the
    library or current context. Legacy clients without a recorded tail may use the exact
    composition delimiter; a present but stale snapshot is not repaired heuristically.
    """
    if not isinstance(prompt_info, dict) or not isinstance(message_content, str):
        return None
    prompt_text = _optional_text(prompt_info.get('content'))
    if not prompt_text or not prompt_text.strip():
        return None

    prompt = prompt_text.strip()
    content = message_content.strip()
    recorded = prompt_info.get('user_text')
    has_snapshot = any(
        key in prompt_info for key in ('template_content', 'composer_text', 'composer_embedded')
    )
    active_keys = None
    if has_snapshot:
        template = prompt_info.get('template_content')
        composer = prompt_info.get('composer_text')
        embedded = prompt_info.get('composer_embedded')
        if (
            not isinstance(template, str)
            or not isinstance(composer, str)
            or not isinstance(embedded, bool)
            or not isinstance(recorded, str)
        ):
            return None
        composer = composer.strip()
        active_keys = _active_template_keys(template)
        tail = '' if embedded else composer
        if (
            embedded != ('composer' in active_keys)
            or recorded.strip() != tail
            or (embedded and composer and composer not in prompt)
        ):
            return None
    elif isinstance(recorded, str):
        tail = recorded.strip()
    elif recorded is None:
        if content != prompt and not content.startswith(f'{prompt}\n\n'):
            return None
        tail = content[len(prompt):].strip()
    else:
        return None

    expected = f'{prompt}\n\n{tail}' if tail else prompt
    if recorded is not None and content != expected:
        return None

    variables = prompt_info.get('variables')
    variables = variables if isinstance(variables, dict) else {}
    index = prompt_info.get('index')
    metadata = {
        'selected_prompt_index': index if type(index) in (str, int) else None,
        'selected_prompt_text': prompt_text,
        'prompt_name': _optional_text(prompt_info.get('name')),
        'prompt_id': _optional_text(prompt_info.get('id')),
        'original_prompt_text': _optional_text(prompt_info.get('original_content')),
        'prompt_variables': {
            key: value for key, value in variables.items()
            if isinstance(key, str) and isinstance(value, str) and value.strip()
            and (active_keys is None or key in active_keys)
        },
        'prompt_edited': prompt_info.get('edited') is True,
        'user_text': recorded.strip() if isinstance(recorded, str) else None,
    }
    if has_snapshot:
        metadata.update({
            'template_content': template,
            'composer_text': composer,
            'composer_embedded': embedded,
        })
    for key in ('scope_type', 'scope_name'):
        if key in prompt_info:
            metadata[key] = _optional_text(prompt_info[key])
    return metadata
