# functions_message_block_revisions.py

"""Revision history for the editable diagrams inside a chat message.

A reply can contain ```mermaid fences. Once the reply has landed, the only way to change one
has been to ask again in the thread, which produces a whole new message with a whole new
diagram. This module lets a block be edited in place instead, and keeps every version it has
had so a reader can see what changed and go back.

Named for *blocks* rather than artifacts because ``functions_message_artifacts`` already owns
that word here, for the tool-call payloads behind agent citations, which are a different thing
entirely. The sibling this belongs beside is ``functions_message_visual_styles``: both store a
per-block choice against a message, addressed the same way.

Storage is an *overlay*. The message's own ``content`` is never rewritten; the revisions live
in metadata beside ``visual_styles`` and are substituted in when the content is read. Splicing
the new source straight into ``content`` was considered and rejected: ``masked_ranges`` are
character offsets into that string, so rewriting a fence body shifts every mask after it, and
silently unmasking something a user chose to mask is a confidentiality bug rather than a
rendering one. The overlay never touches those offsets, and it keeps the original recoverable
for nothing.

A block has no identity of its own, so an entry is filed under the block's position among
blocks of the same kind, together with a fingerprint of the block's *original* source — the
same addressing ``functions_message_visual_styles`` already uses, so the two agree about what
a block is.

That addressing carries one risk worth stating plainly. The client numbers fences by walking
the parsed tree, which is the markdown parser's own answer to what a code block is; the server
has no parser and scans text. Where the two disagree, substituting by position alone would put
one diagram's source into another diagram's fence. So position is only ever a *guess* here:
the fence found at a position must also match the stored fingerprint, and when it does not,
the fingerprint is searched for across the message instead. If that is ambiguous, nothing is
substituted and the original stands. Every failure mode degrades to showing the original.

The revision list is append-only. Restoring an older revision moves a pointer rather than
discarding the newer ones, because the reader asked to *see the history* and an undo that
destroyed history would contradict that.

Everything arriving here is untrusted. Sources are length-capped, and a source containing a
line that would close the enclosing fence is refused outright: accepting one would let an edit
break out of its own code block and inject arbitrary markdown into someone else's message.
"""

import re
import uuid
from datetime import datetime, timezone

# Fence languages a revision may be stored against. The storage below is deliberately
# kind-agnostic so charts and images can be added without a migration, but only diagrams are
# wired up, and admitting a kind the client cannot edit would be storing something nothing
# reads.
BLOCK_REVISION_KINDS = ('mermaid',)

# The message metadata key the whole map lives under.
BLOCK_REVISIONS_METADATA_KEY = 'block_revisions'

# How a revision came about, which is shown in the history list.
ORIGIN_ORIGINAL = 'original'
ORIGIN_MANUAL = 'manual'
ORIGIN_CONTROL = 'control'
ORIGIN_AI = 'ai'
BLOCK_REVISION_ORIGINS = (ORIGIN_ORIGINAL, ORIGIN_MANUAL, ORIGIN_CONTROL, ORIGIN_AI)

# Roles in the scoped sub-conversation attached to a block.
CHAT_ROLE_USER = 'user'
CHAT_ROLE_ASSISTANT = 'assistant'
BLOCK_CHAT_ROLES = (CHAT_ROLE_USER, CHAT_ROLE_ASSISTANT)

# A reply with more blocks than this is not something anyone is editing by hand. Matches
# MAX_BLOCK_INDEX in functions_message_visual_styles.py.
MAX_BLOCK_INDEX = 199

# Stored revisions per block, including the original. The original is pinned at index 0 and
# never pruned, so this is one original plus nineteen edits.
MAX_REVISIONS = 20

# A mermaid diagram far larger than this is not being hand-edited, and the cap is what stops a
# message document being grown without bound by repeated edits.
MAX_SOURCE_LENGTH = 20000

# Turns kept in a block's sub-conversation, oldest dropped first.
MAX_CHAT_TURNS = 20
MAX_CHAT_CONTENT_LENGTH = 4000

# Blocks with revisions across every kind in one message.
MAX_STORED_BLOCKS = 50

MAX_NOTE_LENGTH = 200
MAX_AUTHOR_NAME_LENGTH = 200
MAX_AUTHOR_ID_LENGTH = 200

# Long enough for the 32-bit hex fingerprint the client sends, with room to spare. Matches
# MAX_SOURCE_HASH_LENGTH in functions_message_visual_styles.py.
MAX_SOURCE_HASH_LENGTH = 64

# The exact set `String.prototype.trim` removes: WhiteSpace plus LineTerminator. Spelled out
# rather than relying on `str.strip()`, whose idea of whitespace differs at the edges — it
# leaves U+FEFF, which JavaScript strips — and a fingerprint that disagrees with the client's
# by one character silently stops every stored revision from resolving.
_JS_TRIM_CHARS = (
    '\t\n\x0b\x0c\r \xa0\u1680'
    '\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a'
    '\u2028\u2029\u202f\u205f\u3000\ufeff'
)

# An opening or closing code fence, per CommonMark: up to three spaces of indentation, then at
# least three backticks or tildes, then an info string.
_FENCE_LINE_PATTERN = re.compile(r'^( {0,3})(`{3,}|~{3,})[ \t]*(.*)$')

# A line anywhere in a candidate source that would be read as a fence. Mermaid never contains
# one legitimately, so this is refused rather than escaped.
_FENCE_BREAKOUT_PATTERN = re.compile(r'^ {0,3}(?:`{3,}|~{3,})', re.MULTILINE)

_WHITESPACE_RUN_PATTERN = re.compile(r'\s+')


class BlockRevisionError(ValueError):
    """Raised when a request does not describe a storable revision."""


class BlockRevisionConflictError(BlockRevisionError):
    """Raised when the stored revisions moved on since the caller last read them."""


def utc_now_iso():
    """Return a timezone-aware UTC timestamp string."""
    return datetime.now(timezone.utc).isoformat()


def fingerprint_source(source):
    """Return the 32-bit FNV-1a fingerprint of a block's source, as eight hex digits.

    A port of ``fingerprintSource`` in application/v2_ui/src/lib/visualPalettes.ts, which is the
    reference implementation because the client is what computes the hashes that get stored.

    The hash is taken over UTF-16 code units, because the original hashes ``charCodeAt`` values.
    Iterating Python characters instead would agree for the whole Basic Multilingual Plane and
    then disagree for anything above it, so a diagram containing an emoji would hash differently
    on the two sides and its revisions would quietly stop resolving.
    """
    normalized = str(source or '').replace('\r\n', '\n').strip(_JS_TRIM_CHARS)
    encoded = normalized.encode('utf-16-le', errors='surrogatepass')

    hash_value = 0x811C9DC5
    for position in range(0, len(encoded), 2):
        hash_value ^= encoded[position] | (encoded[position + 1] << 8)
        hash_value = (hash_value * 0x01000193) & 0xFFFFFFFF
    return format(hash_value, '08x')


def validate_block_kind(value):
    """Return the fence language, rejecting anything that is not an editable kind."""
    if value not in BLOCK_REVISION_KINDS:
        raise BlockRevisionError('Unsupported block kind')
    return value


def validate_block_index(value):
    """Return the block position as an int, rejecting anything out of range."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise BlockRevisionError('Block index must be an integer')
    if value < 0 or value > MAX_BLOCK_INDEX:
        raise BlockRevisionError('Block index is out of range')
    return value


def validate_source_hash(value, required=False):
    """Return the source fingerprint, bounded and reduced to the characters a hash uses."""
    if value is None or value == '':
        if required:
            raise BlockRevisionError('Source hash is required')
        return ''
    if not isinstance(value, str):
        raise BlockRevisionError('Source hash must be a string')
    candidate = value.strip()
    if len(candidate) > MAX_SOURCE_HASH_LENGTH:
        raise BlockRevisionError('Source hash is too long')
    if not candidate.isalnum():
        raise BlockRevisionError('Source hash must be alphanumeric')
    return candidate


def validate_block_source(value):
    """Return a storable block source, rejecting anything that could escape its own fence."""
    if not isinstance(value, str):
        raise BlockRevisionError('Source must be a string')
    candidate = value.replace('\r\n', '\n').replace('\r', '\n').strip()
    if not candidate:
        raise BlockRevisionError('Source cannot be empty')
    if len(candidate) > MAX_SOURCE_LENGTH:
        raise BlockRevisionError('Source is too long')
    if _FENCE_BREAKOUT_PATTERN.search(candidate):
        raise BlockRevisionError('Source cannot contain a code fence')
    return candidate


def validate_origin(value):
    """Return how a revision came about, rejecting an unknown origin."""
    if value not in BLOCK_REVISION_ORIGINS:
        raise BlockRevisionError('Unknown revision origin')
    return value


def _bounded_text(value, max_length):
    """Collapse whitespace and cap length, for the short labels stored alongside a revision."""
    return _WHITESPACE_RUN_PATTERN.sub(' ', str(value or '')).strip()[:max_length]


def read_block_revisions(message_doc):
    """Return the stored map for a message, or an empty one."""
    if not isinstance(message_doc, dict):
        return {}
    metadata = message_doc.get('metadata') or {}
    if not isinstance(metadata, dict):
        return {}
    stored = metadata.get(BLOCK_REVISIONS_METADATA_KEY)
    if not isinstance(stored, dict):
        return {}

    revisions = {}
    for kind, entries in stored.items():
        if kind in BLOCK_REVISION_KINDS and isinstance(entries, dict):
            revisions[kind] = {
                key: entry for key, entry in entries.items() if isinstance(entry, dict)
            }
    return revisions


def count_stored_blocks(revisions):
    """Return how many blocks have revisions stored across every kind."""
    return sum(len(entries) for entries in revisions.values())


def read_block_entry(message_doc, block_kind, block_index, source_hash=''):
    """Return the stored entry for one block, or None when none of it still applies.

    An entry whose fingerprint no longer matches describes different content — the message was
    edited, or a mask removed a block and shifted the positions — and is reported as absent
    rather than applied to whatever now sits at that position.
    """
    revisions = read_block_revisions(message_doc)
    entry = (revisions.get(block_kind) or {}).get(str(block_index))
    if not isinstance(entry, dict):
        return None

    stored_hash = entry.get('source_hash')
    if isinstance(stored_hash, str) and stored_hash and source_hash and stored_hash != source_hash:
        return None
    return entry


def resolve_block_source(entry):
    """Return the source the current revision holds, or None when the original still applies.

    ``current`` of zero is the original, which needs no substitution: the original is pinned at
    index zero and never pruned, so the meaning of zero does not drift as revisions are dropped.
    """
    if not isinstance(entry, dict):
        return None

    revisions = entry.get('revisions')
    if not isinstance(revisions, list) or not revisions:
        return None

    current = entry.get('current')
    if isinstance(current, bool) or not isinstance(current, int):
        return None
    if current <= 0 or current >= len(revisions):
        return None

    revision = revisions[current]
    if not isinstance(revision, dict):
        return None
    source = revision.get('source')
    return source if isinstance(source, str) and source else None


def _dedent(line, width):
    """Strip up to ``width`` leading spaces, the way a fence's indentation is removed."""
    removed = 0
    while removed < width and removed < len(line) and line[removed] == ' ':
        removed += 1
    return line[removed:]


def scan_markdown_fences(content):
    """Return the fenced code blocks in a message, numbered per language in document order.

    A deliberately partial CommonMark implementation: top-level fences, backtick and tilde,
    indented up to three spaces. Fences nested in a blockquote or indented into a list item are
    not recognised, and the numbering here can therefore drift from the client's. That is
    tolerated rather than solved because the fingerprint check in ``_locate_fence`` makes a
    disagreement produce *no* substitution rather than the wrong one, and shipping a second
    markdown parser on the server to close a gap that already fails safe is not worth it.
    """
    lines = str(content or '').split('\n')
    total = len(lines)
    fences = []
    counts = {}

    line_number = 0
    while line_number < total:
        opening = _FENCE_LINE_PATTERN.match(lines[line_number])
        if not opening:
            line_number += 1
            continue

        indent, marker, info = opening.group(1), opening.group(2), opening.group(3)

        # A backtick fence's info string may not contain a backtick, so a line like ```a`b``` is
        # inline code in a paragraph rather than the start of a block.
        if marker[0] == '`' and '`' in info:
            line_number += 1
            continue

        stripped_info = info.strip()
        language = stripped_info.split()[0].lower() if stripped_info else ''

        body_start = line_number + 1
        body_end = total
        cursor = body_start
        while cursor < total:
            closing = _FENCE_LINE_PATTERN.match(lines[cursor])
            if (
                closing
                and closing.group(2)[0] == marker[0]
                and len(closing.group(2)) >= len(marker)
                and closing.group(3).strip() == ''
            ):
                body_end = cursor
                break
            cursor += 1

        position = counts.get(language, 0)
        counts[language] = position + 1
        fences.append({
            'language': language,
            'index': position,
            'body_start_line': body_start,
            'body_end_line': body_end,
            'indent': indent,
            'body': '\n'.join(_dedent(line, len(indent)) for line in lines[body_start:body_end]),
        })

        line_number = body_end + 1

    return fences


def _locate_fence(fences, block_kind, block_index, source_hash):
    """Return the fence a stored entry belongs to, or None when it cannot be identified.

    Position is checked first and confirmed by fingerprint. When that fails the fingerprint is
    searched for across the message, which recovers the case where the server's numbering has
    drifted from the client's; an ambiguous or absent match returns None, leaving the original
    in place.
    """
    candidates = [fence for fence in fences if fence['language'] == block_kind]
    if not candidates or not source_hash:
        return None

    if 0 <= block_index < len(candidates):
        at_position = candidates[block_index]
        if fingerprint_source(at_position['body']) == source_hash:
            return at_position

    matches = [
        candidate
        for candidate in candidates
        if fingerprint_source(candidate['body']) == source_hash
    ]
    return matches[0] if len(matches) == 1 else None


def resolve_message_content(message_doc):
    """Return a message's stored content with each block's current revision substituted in.

    This is the single seam every reader of a message's content goes through — the export, the
    shared view, the model's history — so that they cannot disagree about which version of a
    diagram is the real one.
    """
    if not isinstance(message_doc, dict):
        return ''
    content = message_doc.get('content')
    if not isinstance(content, str):
        return ''
    return resolve_block_sources_in_content(message_doc, content)


def resolve_block_sources_in_content(message_doc, content):
    """Substitute each block's current revision into ``content``.

    Split from ``resolve_message_content`` so a caller that has already transformed the content
    can still resolve against it. The conversation history is exactly that caller: masked ranges
    are character offsets into the *stored* content, so masks have to be applied first, and
    resolving against the stored string and then masking by offset would cut the wrong text.

    Resolving second is also why a masked diagram simply stops resolving rather than resolving
    wrongly. If a mask has altered a fence's body its fingerprint no longer matches, and the
    substitution is skipped; if a mask removed some other block entirely and shifted the
    positions, the fingerprint search in ``_locate_fence`` still finds the right fence.
    """
    if not isinstance(message_doc, dict) or not isinstance(content, str) or not content:
        return content if isinstance(content, str) else ''

    stored = read_block_revisions(message_doc)
    if not stored:
        return content

    fences = None
    replacements = []
    claimed = set()

    for kind, entries in stored.items():
        for raw_index, entry in entries.items():
            source = resolve_block_source(entry)
            if source is None:
                continue
            try:
                block_index = int(raw_index)
            except (TypeError, ValueError):
                continue

            if fences is None:
                fences = scan_markdown_fences(content)

            target = _locate_fence(fences, kind, block_index, entry.get('source_hash') or '')
            # A fence already claimed by another entry is left alone: two entries resolving to
            # one fence means the addressing is ambiguous, and splicing both would corrupt the
            # message rather than merely show the wrong diagram.
            if target is None or target['body_start_line'] in claimed:
                continue

            claimed.add(target['body_start_line'])
            replacements.append((
                target['body_start_line'],
                target['body_end_line'],
                target['indent'],
                source,
            ))

    if not replacements:
        return content

    lines = content.split('\n')
    # Applied last-first so the earlier line numbers stay valid as the list is spliced.
    for body_start, body_end, indent, source in sorted(replacements, reverse=True):
        lines[body_start:body_end] = [
            f'{indent}{line}' if line else line for line in source.split('\n')
        ]
    return '\n'.join(lines)


def _build_revision(source, origin, author_id='', author_name='', note=''):
    """Return one stored revision record."""
    return {
        'id': str(uuid.uuid4()),
        'source': source,
        'origin': origin,
        'author_id': _bounded_text(author_id, MAX_AUTHOR_ID_LENGTH),
        'author_name': _bounded_text(author_name, MAX_AUTHOR_NAME_LENGTH),
        'note': _bounded_text(note, MAX_NOTE_LENGTH),
        'timestamp': utc_now_iso(),
    }


def _prune_revisions(entry):
    """Drop the oldest edits until the entry is within the cap, keeping the original.

    Index zero is the original and is never dropped, because "restore the diagram I was actually
    given" has to keep working however many times a block has been edited. ``current`` follows
    whatever it was pointing at.
    """
    revisions = entry['revisions']
    current = entry.get('current', 0)

    while len(revisions) > MAX_REVISIONS:
        del revisions[1]
        if current >= 1:
            current -= 1

    entry['current'] = max(0, min(current, len(revisions) - 1))


def _write_entry(message_doc, block_kind, block_index, entry):
    """Store an entry back onto the message, removing the map when nothing is left."""
    revisions = read_block_revisions(message_doc)
    entries = dict(revisions.get(block_kind) or {})

    if entry is None:
        entries.pop(str(block_index), None)
    else:
        entries[str(block_index)] = entry

    if entries:
        revisions[block_kind] = entries
    else:
        revisions.pop(block_kind, None)

    metadata = message_doc.setdefault('metadata', {})
    if revisions:
        metadata[BLOCK_REVISIONS_METADATA_KEY] = revisions
    else:
        metadata.pop(BLOCK_REVISIONS_METADATA_KEY, None)

    return revisions


def _mutable_entry(entry, source_hash):
    """Return a copy of a stored entry that can be modified without aliasing the document."""
    copied = dict(entry)
    copied['revisions'] = [
        dict(revision)
        for revision in (entry.get('revisions') or [])
        if isinstance(revision, dict)
    ]
    copied['chat'] = [turn for turn in (entry.get('chat') or []) if isinstance(turn, dict)]
    if source_hash:
        copied['source_hash'] = source_hash
    return copied


def apply_block_revision(
    message_doc,
    block_kind,
    block_index,
    source,
    source_hash,
    original_source='',
    author_id='',
    author_name='',
    origin=ORIGIN_MANUAL,
    note='',
    expected_revision_count=None,
):
    """Append a new revision for one block and make it current, returning the stored entry.

    ``original_source`` seeds revision zero the first time a block is edited. It is verified
    against ``source_hash`` rather than trusted, because a mismatch would pin the wrong content
    as the thing "restore original" restores.

    ``expected_revision_count`` is the guard against two people in a shared conversation editing
    the same diagram: a caller that read three revisions and writes against four has not seen the
    other edit, and is told so instead of silently overwriting it.
    """
    kind = validate_block_kind(block_kind)
    index = validate_block_index(block_index)
    new_source = validate_block_source(source)
    fingerprint = validate_source_hash(source_hash, required=True)
    revision_origin = validate_origin(origin)
    if revision_origin == ORIGIN_ORIGINAL:
        raise BlockRevisionError('Cannot store a revision as the original')

    entry = read_block_entry(message_doc, kind, index, fingerprint)
    if entry is None:
        seed = validate_block_source(original_source) if original_source else ''
        if not seed:
            raise BlockRevisionError('The original source is required for the first edit')
        if fingerprint_source(seed) != fingerprint:
            raise BlockRevisionError('The original source does not match its fingerprint')

        stored = read_block_revisions(message_doc)
        if count_stored_blocks(stored) >= MAX_STORED_BLOCKS:
            raise BlockRevisionError('Too many edited blocks in this message')

        entry = {
            'source_hash': fingerprint,
            'current': 0,
            'revisions': [_build_revision(seed, ORIGIN_ORIGINAL)],
            'chat': [],
        }
    else:
        entry = _mutable_entry(entry, fingerprint)

    if not entry['revisions']:
        raise BlockRevisionError('Stored revisions are unreadable')

    if expected_revision_count is not None and expected_revision_count != len(entry['revisions']):
        raise BlockRevisionConflictError('This diagram was changed by someone else')

    entry['revisions'].append(
        _build_revision(new_source, revision_origin, author_id, author_name, note)
    )
    entry['current'] = len(entry['revisions']) - 1
    _prune_revisions(entry)

    _write_entry(message_doc, kind, index, entry)
    return entry


def set_current_revision(message_doc, block_kind, block_index, revision_id, source_hash=''):
    """Point a block at one of its stored revisions, returning the stored entry.

    Addressed by revision id rather than position, because positions shift when the oldest edits
    are pruned and an undo that moved by index would eventually undo to the wrong version.
    Nothing is discarded: the list stays a record of everything that happened, and editing after
    restoring an older version appends rather than truncating.
    """
    kind = validate_block_kind(block_kind)
    index = validate_block_index(block_index)
    fingerprint = validate_source_hash(source_hash)

    entry = read_block_entry(message_doc, kind, index, fingerprint)
    if entry is None:
        raise BlockRevisionError('This diagram has no stored revisions')

    entry = _mutable_entry(entry, '')
    target = next(
        (
            position
            for position, revision in enumerate(entry['revisions'])
            if revision.get('id') == revision_id
        ),
        None,
    )
    if target is None:
        raise BlockRevisionError('That revision no longer exists')

    entry['current'] = target
    _write_entry(message_doc, kind, index, entry)
    return entry


def append_block_chat_turn(
    message_doc,
    block_kind,
    block_index,
    role,
    content,
    source_hash='',
):
    """Add one turn to a block's scoped sub-conversation, returning the stored entry.

    The transcript is kept with the block rather than in the message list, which is the whole
    point of the feature: refining a diagram should not fill the thread with near-duplicates,
    and none of these turns are ever sent as conversation history.
    """
    kind = validate_block_kind(block_kind)
    index = validate_block_index(block_index)
    fingerprint = validate_source_hash(source_hash)

    if role not in BLOCK_CHAT_ROLES:
        raise BlockRevisionError('Unsupported chat role')
    if not isinstance(content, str):
        raise BlockRevisionError('Chat content must be a string')
    text = content.strip()[:MAX_CHAT_CONTENT_LENGTH]
    if not text:
        raise BlockRevisionError('Chat content cannot be empty')

    entry = read_block_entry(message_doc, kind, index, fingerprint)
    if entry is None:
        raise BlockRevisionError('This diagram has no stored revisions')

    entry = _mutable_entry(entry, '')
    entry['chat'] = (entry['chat'] + [{
        'role': role,
        'content': text,
        'timestamp': utc_now_iso(),
    }])[-MAX_CHAT_TURNS:]

    _write_entry(message_doc, kind, index, entry)
    return entry


def read_block_chat(entry):
    """Return a block's stored sub-conversation as plain role/content turns."""
    if not isinstance(entry, dict):
        return []
    return [
        {'role': turn.get('role'), 'content': turn.get('content') or ''}
        for turn in (entry.get('chat') or [])
        if isinstance(turn, dict) and turn.get('role') in BLOCK_CHAT_ROLES
    ]


def current_block_source(entry, fallback=''):
    """Return the source a block currently renders as, falling back to the original."""
    resolved = resolve_block_source(entry)
    if resolved:
        return resolved
    if isinstance(entry, dict):
        revisions = entry.get('revisions')
        if isinstance(revisions, list) and revisions and isinstance(revisions[0], dict):
            original = revisions[0].get('source')
            if isinstance(original, str) and original:
                return original
    return fallback


def remove_block_entry(message_doc, block_kind, block_index):
    """Drop every stored revision for one block, returning the resulting map."""
    kind = validate_block_kind(block_kind)
    index = validate_block_index(block_index)
    return _write_entry(message_doc, kind, index, None)
