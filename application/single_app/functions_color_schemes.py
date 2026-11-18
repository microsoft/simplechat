# functions_color_schemes.py

"""Validation rules for V2 color schemes, custom color modes and Theme Card codes.

Administrators can set the colors V2 uses in light mode and dark mode, and users (when an
administrator allows it) can build a custom color mode of their own and share it as a Theme
Card image. Every one of those values ends up in a stylesheet in someone's browser, so all of
them are treated as untrusted and reduced to a fixed set of named colors, each a plain
``#RRGGBB`` value. Nothing else is stored: no CSS, no names of other properties, no URLs.

A palette has exactly the keys in ``PALETTE_TOKENS``. The V2 client derives the rest of its
design tokens (hover shades, translucent surfaces, soft status fills) from these, which keeps
what a person can set small enough to validate completely.

Theme Card codes
----------------
A Theme Card carries one custom color mode as text::

    SCTHEME1.<payload>.<checksum>

``payload`` is base64url (no padding) of compact JSON
``{"v": 1, "n": name, "b": "light"|"dark", "c": {token: "RRGGBB", ...}}``.
``checksum`` is base64url (no padding) of the first 16 bytes of
``SHA-256("SCTHEME1." + payload)``.

The checksum is deliberately unkeyed so a card made on one SimpleChat deployment imports on
any other. It catches edits made to a card after it was produced; it is not a signature, and
the server never trusts a card for that reason alone. Whatever a card decodes to is still
validated here, field by field, before it is saved.

The encoder and decoder used by the V2 interface live in
``application/v2_ui/src/lib/colorScheme.ts``; this module documents and tests the format.
"""

import base64
import hashlib
import json
import re

PALETTE_TOKENS = (
    'accent',
    'onAccent',
    'backdrop',
    'panel',
    'border',
    'text1',
    'text2',
    'ok',
    'warn',
    'danger',
    'info',
)

COLOR_MODES = ('light', 'dark', 'system', 'custom')
COLOR_MODE_BASES = ('light', 'dark')

CUSTOM_COLOR_MODE_NAME_MAX = 40
READABLE_CONTRAST_MIN = 4.5

THEME_CARD_PREFIX = 'SCTHEME1'
THEME_CARD_VERSION = 1
THEME_CARD_CODE_MAX = 2048
THEME_CARD_CHECKSUM_BYTES = 16

_HEX_COLOR = re.compile(r'^#?([0-9A-Fa-f]{6})$')
_CONTROL_CHARACTERS = re.compile(r'[\x00-\x1f\x7f-\x9f]')

# Text and fills judged against the panel they sit on, and the label judged against the
# accent it sits on. The labels are what a person reads in an error message.
_READABILITY_PAIRS = (
    ('text1', 'panel', 'Primary text'),
    ('text2', 'panel', 'Secondary text'),
    ('accent', 'panel', 'Accent'),
    ('onAccent', 'accent', 'Text on accent'),
)


class ColorSchemeError(ValueError):
    """Raised when a color scheme, custom color mode or Theme Card is not valid."""


def normalize_hex_color(value, label='Color'):
    """Return ``value`` as ``#RRGGBB`` in upper case, or raise ``ColorSchemeError``."""
    if not isinstance(value, str):
        raise ColorSchemeError(f'{label} must be a #RRGGBB color.')
    match = _HEX_COLOR.match(value.strip())
    if not match:
        raise ColorSchemeError(f'{label} must be a #RRGGBB color.')
    return f'#{match.group(1).upper()}'


def normalize_palette(value):
    """Return a palette with exactly ``PALETTE_TOKENS``, each a ``#RRGGBB`` color."""
    if not isinstance(value, dict):
        raise ColorSchemeError('A palette must be an object of colors.')
    unknown = sorted(set(value.keys()) - set(PALETTE_TOKENS))
    if unknown:
        raise ColorSchemeError(f'Unknown color: {unknown[0]}.')
    missing = [token for token in PALETTE_TOKENS if token not in value]
    if missing:
        raise ColorSchemeError(f'Missing color: {missing[0]}.')
    return {token: normalize_hex_color(value[token], token) for token in PALETTE_TOKENS}


def normalize_color_scheme(value):
    """Return ``None`` (the SimpleChat default) or ``{"light": palette, "dark": palette}``."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ColorSchemeError('The color scheme must be an object with light and dark palettes.')
    unknown = sorted(set(value.keys()) - set(COLOR_MODE_BASES))
    if unknown:
        raise ColorSchemeError(f'Unknown color scheme mode: {unknown[0]}.')
    return {
        'light': normalize_palette(value.get('light')),
        'dark': normalize_palette(value.get('dark')),
    }


def normalize_color_mode_name(value):
    """Return a plain-text color mode name, stripped of control characters."""
    if value is None:
        return ''
    if not isinstance(value, str):
        raise ColorSchemeError('The color mode name must be text.')
    cleaned = _CONTROL_CHARACTERS.sub('', value).strip()
    if len(cleaned) > CUSTOM_COLOR_MODE_NAME_MAX:
        raise ColorSchemeError(
            f'The color mode name can be at most {CUSTOM_COLOR_MODE_NAME_MAX} characters.'
        )
    return cleaned


def _channel(value):
    channel = value / 255
    return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4


def _luminance(color):
    hex_value = normalize_hex_color(color)[1:]
    red, green, blue = (int(hex_value[index:index + 2], 16) for index in (0, 2, 4))
    return 0.2126 * _channel(red) + 0.7152 * _channel(green) + 0.0722 * _channel(blue)


def contrast_ratio(foreground, background):
    """Return the WCAG contrast ratio between two colors."""
    first = _luminance(foreground)
    second = _luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def readability_problems(palette):
    """Return a message for each text pair in ``palette`` below the readable minimum."""
    problems = []
    for foreground, background, label in _READABILITY_PAIRS:
        # Judged on the ratio as people see it, to one decimal place, so a pair shown as
        # 4.5:1 is never refused for being 4.48:1.
        ratio = round(contrast_ratio(palette[foreground], palette[background]), 1)
        if ratio < READABLE_CONTRAST_MIN:
            problems.append(
                f'{label} is hard to read ({ratio:.1f}:1, needs {READABLE_CONTRAST_MIN}:1).'
            )
    return problems


def normalize_custom_color_mode(value, require_readable=False):
    """Return ``{"name", "base", "colors"}`` for a user's custom color mode, or ``None``."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ColorSchemeError('A custom color mode must be an object.')
    unknown = sorted(set(value.keys()) - {'name', 'base', 'colors'})
    if unknown:
        raise ColorSchemeError(f'Unknown custom color mode field: {unknown[0]}.')
    base = value.get('base')
    if base not in COLOR_MODE_BASES:
        raise ColorSchemeError('A custom color mode must start from light or dark.')
    colors = normalize_palette(value.get('colors'))
    if require_readable:
        problems = readability_problems(colors)
        if problems:
            raise ColorSchemeError(problems[0])
    return {
        'name': normalize_color_mode_name(value.get('name')) or 'My color mode',
        'base': base,
        'colors': colors,
    }


def normalize_color_mode(value):
    """Return one of ``COLOR_MODES``."""
    if value not in COLOR_MODES:
        raise ColorSchemeError('Choose light, dark, system or custom.')
    return value


def _b64url_encode(raw):
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def _b64url_decode(text):
    padding = '=' * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def theme_card_checksum(payload):
    """Return the checksum segment for a base64url ``payload`` segment."""
    digest = hashlib.sha256(f'{THEME_CARD_PREFIX}.{payload}'.encode('ascii')).digest()
    return _b64url_encode(digest[:THEME_CARD_CHECKSUM_BYTES])


def encode_theme_card_code(name, base, colors):
    """Return the Theme Card code for a custom color mode. Used by tests and docs."""
    mode = normalize_custom_color_mode({'name': name, 'base': base, 'colors': colors})
    body = {
        'v': THEME_CARD_VERSION,
        'n': mode['name'],
        'b': mode['base'],
        'c': {token: mode['colors'][token][1:] for token in PALETTE_TOKENS},
    }
    payload = _b64url_encode(
        json.dumps(body, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    )
    return f'{THEME_CARD_PREFIX}.{payload}.{theme_card_checksum(payload)}'


def decode_theme_card_code(code):
    """Return the validated custom color mode a Theme Card code holds."""
    if not isinstance(code, str):
        raise ColorSchemeError('This is not a Theme Card.')
    code = code.strip()
    if len(code) > THEME_CARD_CODE_MAX:
        raise ColorSchemeError('This is not a Theme Card.')
    parts = code.split('.')
    if len(parts) != 3 or parts[0] != THEME_CARD_PREFIX:
        raise ColorSchemeError('This is not a Theme Card.')
    payload, checksum = parts[1], parts[2]
    if theme_card_checksum(payload) != checksum:
        raise ColorSchemeError('This card was changed after it was made.')
    try:
        body = json.loads(_b64url_decode(payload).decode('utf-8'))
    except (ValueError, UnicodeDecodeError) as error:
        raise ColorSchemeError('This is not a Theme Card.') from error
    if not isinstance(body, dict) or body.get('v') != THEME_CARD_VERSION:
        raise ColorSchemeError('This Theme Card was made by a newer version of SimpleChat.')
    raw_colors = body.get('c')
    if not isinstance(raw_colors, dict):
        raise ColorSchemeError('This Theme Card has no colors.')
    return normalize_custom_color_mode(
        {
            'name': body.get('n'),
            'base': body.get('b'),
            'colors': {token: f'#{value}' if isinstance(value, str) else value
                       for token, value in raw_colors.items()},
        }
    )
