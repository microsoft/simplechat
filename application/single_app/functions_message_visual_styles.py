# functions_message_visual_styles.py

"""Validation and storage rules for per-block diagram and chart colours.

A reply can contain several ```mermaid or ```simplechart fences. Someone reading it can
recolour one of them, and that choice is kept on the message so the conversation looks the
same when they come back to it. Recolouring one block must never affect another, so a style
is filed under the block's position among blocks of the same kind, together with a fingerprint
of the block's source.

The fingerprint exists because a position on its own is not a stable identity. If the message
is later edited, or a mask removes a whole block, the block at a given position may be
different content. A stored style whose fingerprint no longer matches is ignored by the
client rather than applied to the wrong diagram.

Everything arriving here is treated as untrusted. The values end up in inline styles and in
mermaid's theme configuration in a browser, so colours are reduced to `#rrggbb` and nothing
else is stored. Sizes are capped so a message document cannot be grown without bound by
repeated requests.
"""

import re

# Fence languages a style may be saved against. Matches VISUAL_STYLE_KINDS in
# application/v2_ui/src/lib/visualPalettes.ts.
VISUAL_STYLE_KINDS = ('mermaid', 'simplechart')

# Palette identifiers, matching PALETTE_PRESETS in visualPalettes.ts and CHART_COLOR_PRESETS
# in static/js/chat/chat-inline-charts.js.
VISUAL_STYLE_PALETTES = ('default', 'calm', 'vivid', 'warm', 'contrast')

# Background value meaning "follow the app theme" rather than a fixed colour.
THEME_BACKGROUND = 'theme'

# The message metadata key the whole map lives under.
VISUAL_STYLES_METADATA_KEY = 'visual_styles'

# A reply with more blocks than this is not something anyone is styling by hand.
MAX_BLOCK_INDEX = 199

# Per-series or per-slice colour overrides for one block.
MAX_SERIES_COLOR_OVERRIDES = 24

# Total stored entries across every kind, which bounds the size of the stored map.
MAX_STORED_ENTRIES = 100

HEX_COLOR_PATTERN = re.compile(r'^#[0-9a-fA-F]{6}$')

# Long enough for the 32-bit hex fingerprint the client sends, with room to spare.
MAX_SOURCE_HASH_LENGTH = 64


class VisualStyleError(ValueError):
    """Raised when a request does not describe a storable style."""


def normalize_hex_color(value):
    """Return a lowercase ``#rrggbb`` string, or None when the value is not one."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not HEX_COLOR_PATTERN.match(candidate):
        return None
    return candidate.lower()


def validate_block_kind(value):
    """Return the fence language, rejecting anything that is not a styleable kind."""
    if value not in VISUAL_STYLE_KINDS:
        raise VisualStyleError('Unsupported block kind')
    return value


def validate_block_index(value):
    """Return the block position as an int, rejecting anything out of range."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise VisualStyleError('Block index must be an integer')
    if value < 0 or value > MAX_BLOCK_INDEX:
        raise VisualStyleError('Block index is out of range')
    return value


def validate_source_hash(value):
    """Return the source fingerprint, which is optional but bounded when present."""
    if value is None or value == '':
        return ''
    if not isinstance(value, str):
        raise VisualStyleError('Source hash must be a string')
    candidate = value.strip()
    if len(candidate) > MAX_SOURCE_HASH_LENGTH:
        raise VisualStyleError('Source hash is too long')
    if not candidate.isalnum():
        raise VisualStyleError('Source hash must be alphanumeric')
    return candidate


def sanitize_visual_style(value):
    """Return a storable style dict, rejecting anything that is not one.

    Only the palette, the background and individual colour overrides are kept. Unknown keys are
    dropped rather than stored, so a future field cannot be smuggled into a message document by
    a client that is ahead of the server.

    Note the asymmetry with ``sanitizeVisualStyle`` in visualPalettes.ts, which falls back to
    defaults instead of raising. That function is reading a value that is already stored and
    has to render something; this one is validating a request, where storing something other
    than what was asked for would be worse than refusing it.
    """
    if not isinstance(value, dict):
        raise VisualStyleError('Style must be an object')

    palette = value.get('palette', 'default')
    if palette not in VISUAL_STYLE_PALETTES:
        raise VisualStyleError('Unknown palette')

    background = value.get('background', THEME_BACKGROUND)
    if background != THEME_BACKGROUND:
        background = normalize_hex_color(background)
        if background is None:
            raise VisualStyleError('Background must be a hex colour or the theme default')

    raw_colors = value.get('colors') or {}
    if not isinstance(raw_colors, dict):
        raise VisualStyleError('Colours must be an object keyed by index')
    if len(raw_colors) > MAX_SERIES_COLOR_OVERRIDES:
        raise VisualStyleError('Too many colour overrides')

    colors = {}
    for key, entry in raw_colors.items():
        try:
            index = int(key)
        except (TypeError, ValueError):
            raise VisualStyleError('Colour keys must be indexes')
        if index < 0 or index >= MAX_SERIES_COLOR_OVERRIDES:
            raise VisualStyleError('Colour index is out of range')
        color = normalize_hex_color(entry)
        if color is None:
            raise VisualStyleError('Colours must be hex values')
        colors[str(index)] = color

    return {'palette': palette, 'background': background, 'colors': colors}


def read_visual_styles(message_doc):
    """Return the stored map for a message, or an empty one."""
    metadata = message_doc.get('metadata') or {}
    stored = metadata.get(VISUAL_STYLES_METADATA_KEY)
    if not isinstance(stored, dict):
        return {}

    styles = {}
    for kind, entries in stored.items():
        if kind in VISUAL_STYLE_KINDS and isinstance(entries, dict):
            styles[kind] = dict(entries)
    return styles


def count_entries(styles):
    """Return how many block styles are stored across every kind."""
    return sum(len(entries) for entries in styles.values())


def apply_visual_style(message_doc, block_kind, block_index, style, source_hash=''):
    """Store, replace or remove one block's colours, returning the resulting map.

    ``style`` of None removes the entry, which is different from storing a style that happens
    to equal the reader's current default: the default can change later, and a removed entry
    should follow it.
    """
    kind = validate_block_kind(block_kind)
    index = validate_block_index(block_index)
    fingerprint = validate_source_hash(source_hash)

    styles = read_visual_styles(message_doc)
    entries = dict(styles.get(kind) or {})

    if style is None:
        entries.pop(str(index), None)
    else:
        sanitized = sanitize_visual_style(style)
        if fingerprint:
            sanitized['source_hash'] = fingerprint
        is_new = str(index) not in entries
        if is_new and count_entries(styles) >= MAX_STORED_ENTRIES:
            raise VisualStyleError('Too many styled blocks in this message')
        entries[str(index)] = sanitized

    if entries:
        styles[kind] = entries
    else:
        styles.pop(kind, None)

    metadata = message_doc.setdefault('metadata', {})
    if styles:
        metadata[VISUAL_STYLES_METADATA_KEY] = styles
    else:
        metadata.pop(VISUAL_STYLES_METADATA_KEY, None)

    return styles
