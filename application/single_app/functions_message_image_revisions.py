# functions_message_image_revisions.py

"""Revision history for a generated image message.

Inline diagram editing made a generated Mermaid diagram something a reader can live with:
refine it in place, keep every version, and never fill the thread with near-duplicates. A
generated image had no equivalent. Asking again cost another paid generation, produced another
``role: 'image'`` message, and left the previous image in the conversation with no relationship
to the new one.

This is the storage behind editing one in place. It deliberately mirrors the *interface* of
``functions_message_block_revisions`` -- a revisions list with a ``current`` pointer, the
original pinned at index zero, a scoped sub-conversation, attribution, pruning and
``expected_revision_count`` conflict detection -- while sharing none of its addressing.

That difference is the point, and it is a simplification rather than a port. A diagram is a
fenced block *inside* an assistant message and has no identity, so the block module needs
``(kind, index, source_hash)`` addressing, a markdown fence scanner, a fingerprint that has to
agree across three languages, and careful ordering against ``masked_ranges`` character offsets.
**A generated image is its own message document.** It is addressed by its message id, so none of
that machinery exists here, and none of its failure modes do either.

Two storage rules are load-bearing:

1. **Revision zero stores no bytes.** It *means* "the message's own stored content", whatever
   form that takes -- a chunked data URL, a blob-backed pointer, or an external URL. Copying a
   multi-megabyte original into metadata would be wasteful, and for a chunked image it is not
   possible at all.
2. **Every later revision is blob-backed and never inlined.** Image messages already split
   across several documents at 1.5 MB because a data URL exceeds the Cosmos item limit, so
   putting even one data URL into metadata would grow the document past what can be written.
   This is a correctness constraint rather than an optimisation.

Blob paths are storage detail and never reach the browser. ``serialize_image_revisions`` is the
only thing a route should hand to a client.
"""

import uuid
from datetime import datetime, timezone

# The message metadata key the whole entry lives under.
IMAGE_REVISIONS_METADATA_KEY = 'image_revisions'

# How a revision came about, which is what the history list shows.
ORIGIN_ORIGINAL = 'original'
ORIGIN_AI = 'ai'
ORIGIN_PROMPT = 'prompt'
ORIGIN_CONTROL = 'control'
IMAGE_REVISION_ORIGINS = (ORIGIN_ORIGINAL, ORIGIN_AI, ORIGIN_PROMPT, ORIGIN_CONTROL)

# Origins a client may ask for. The original is seeded here, never submitted.
IMAGE_REVISION_REQUEST_ORIGINS = (ORIGIN_AI, ORIGIN_PROMPT, ORIGIN_CONTROL)

# Roles in the scoped sub-conversation attached to an image.
CHAT_ROLE_USER = 'user'
CHAT_ROLE_ASSISTANT = 'assistant'
IMAGE_CHAT_ROLES = (CHAT_ROLE_USER, CHAT_ROLE_ASSISTANT)

# Stored revisions per image, including the original. The original is pinned at index 0 and
# never pruned, so this is one original plus nineteen edits. Each edit is a blob, so this also
# bounds what a single message can accumulate in storage.
MAX_REVISIONS = 20

# Turns kept in an image's sub-conversation, oldest dropped first.
MAX_CHAT_TURNS = 20
MAX_CHAT_CONTENT_LENGTH = 4000

# Matches IMAGE_PROPOSAL_PROMPT_MAX_LENGTH in functions_image_generation.py, because a prompt
# stored here is the same kind of thing and is sent to the same endpoint.
MAX_PROMPT_LENGTH = 4000

# Longer than this is a request for a different image, not an edit to this one.
MAX_INSTRUCTION_LENGTH = 2000

MAX_AUTHOR_NAME_LENGTH = 200
MAX_AUTHOR_ID_LENGTH = 200
MAX_MODEL_NAME_LENGTH = 200
MAX_BLOB_PATH_LENGTH = 1024


class ImageRevisionError(ValueError):
    """Raised when a request does not describe a storable image revision."""


class ImageRevisionConflictError(ImageRevisionError):
    """Raised when the stored revisions moved on since the caller last read them."""


def utc_now_iso():
    """Return a timezone-aware UTC timestamp string."""
    return datetime.now(timezone.utc).isoformat()


def _bounded_text(value, max_length):
    """Return a trimmed string no longer than the cap, for anything a caller supplies."""
    return str(value or '').strip()[:max_length]


def normalize_prompt(value):
    """Return a storable image prompt, or raise when there is not one."""
    prompt = _bounded_text(value, MAX_PROMPT_LENGTH)
    if not prompt:
        raise ImageRevisionError('An image prompt is required')
    return prompt


def normalize_instruction(value):
    """Return the reader's edit instruction, or raise when there is not one."""
    instruction = _bounded_text(value, MAX_INSTRUCTION_LENGTH)
    if not instruction:
        raise ImageRevisionError('Describe the change you want')
    return instruction


def validate_origin(value):
    """Return a recognised revision origin, defaulting to an AI edit."""
    origin = str(value or ORIGIN_AI).strip().lower()
    if origin not in IMAGE_REVISION_ORIGINS:
        raise ImageRevisionError('Unsupported revision origin')
    return origin


def read_image_revisions(message_doc):
    """Return the stored entry for a message, or an empty entry when there is none.

    A copy is returned so a caller can modify it without aliasing the stored document, matching
    ``read_block_revisions``.
    """
    if not isinstance(message_doc, dict):
        return {}

    metadata = message_doc.get('metadata')
    if not isinstance(metadata, dict):
        return {}

    entry = metadata.get(IMAGE_REVISIONS_METADATA_KEY)
    if not isinstance(entry, dict):
        return {}

    return entry


def read_revisions(entry):
    """Return the revision records in an entry, ignoring anything that is not one."""
    if not isinstance(entry, dict):
        return []
    revisions = entry.get('revisions')
    if not isinstance(revisions, list):
        return []
    return [revision for revision in revisions if isinstance(revision, dict) and revision.get('id')]


def read_current_index(entry):
    """Return where ``current`` points, clamped into the revisions that actually exist."""
    revisions = read_revisions(entry)
    if not revisions:
        return 0

    current = (entry or {}).get('current')
    if not isinstance(current, int) or isinstance(current, bool):
        return 0
    return max(0, min(current, len(revisions) - 1))


def resolve_current_revision(entry):
    """Return the revision an image currently renders as, or None when it has no history."""
    revisions = read_revisions(entry)
    if not revisions:
        return None
    return revisions[read_current_index(entry)]


def find_revision(entry, revision_id):
    """Return one stored revision by id, or None."""
    target = str(revision_id or '').strip()
    if not target:
        return None
    for revision in read_revisions(entry):
        if revision.get('id') == target:
            return revision
    return None


def revision_blob_location(revision):
    """Return the container and path holding a revision's bytes, or None for the original.

    The original deliberately stores no bytes: it *is* the message's own content, and a caller
    that gets None here should fall back to reading the message the ordinary way.
    """
    if not isinstance(revision, dict):
        return None
    container = _bounded_text(revision.get('blob_container'), MAX_BLOB_PATH_LENGTH)
    path = _bounded_text(revision.get('blob_path'), MAX_BLOB_PATH_LENGTH)
    if not container or not path:
        return None
    return {'blob_container': container, 'blob_path': path,
            'mime_type': _bounded_text(revision.get('mime_type'), 100) or 'image/png'}


def resolve_image_message_content(message_doc, endpoint_url=''):
    """Return the content an image message should be rendered and served as.

    An image nobody has ever changed keeps its stored content untouched, so nothing about the
    overwhelmingly common case changes.

    Once an image *has* a history, the caller's own endpoint is returned instead, carrying the
    id of whichever version is current -- including the original. Returning the stored content
    for the original looks reasonable and is wrong in two cases that matter:

    - A collaboration mirror does not store a URL at all. Its content is a placeholder, because
      a shared image's bytes live on the source message, so handing it back would replace a
      working image with that placeholder for every participant, permanently.
    - A legacy image is split across several documents, and the stored content is only its first
      chunk -- a truncated data URL.

    The endpoint resolves the original perfectly well: ``resolve_served_revision`` reports no
    blob for it and the serve routes fall through to the message's own bytes, reassembling
    chunks or redirecting to an external URL as they always did.

    The revision id is also what stops a change being invisible. ``/api/image/<message_id>``
    never varies on its own, and is served with ``Cache-Control: private, max-age=300``
    personally and ``public, max-age=3600`` collaboratively -- so without a changing URL a reader
    would keep seeing the version they had just replaced for up to an hour. Because the URL is
    addressed by revision, those long cache lifetimes become correct rather than merely
    tolerated.
    """
    stored_content = str((message_doc or {}).get('content') or '')

    entry = read_image_revisions(message_doc)
    revision = resolve_current_revision(entry)
    if not revision:
        return stored_content

    base = str(endpoint_url or '').strip()
    if not base:
        return stored_content

    separator = '&' if '?' in base else '?'
    return f"{base}{separator}rev={revision['id']}"


def publicize_message_image_revisions(message_doc):
    """Return a copy of a message whose stored revisions are reduced to their public shape.

    For the readers that return a message document more or less verbatim. The stored entry
    records where each version's bytes live, and a blob path spells out the owner's user id and
    the source conversation id as well as the container, none of which a browser needs.
    """
    if not isinstance(message_doc, dict):
        return message_doc

    metadata = message_doc.get('metadata')
    if not isinstance(metadata, dict) or not metadata.get(IMAGE_REVISIONS_METADATA_KEY):
        return message_doc

    publicized = dict(message_doc)
    publicized['metadata'] = dict(metadata)
    publicized['metadata'][IMAGE_REVISIONS_METADATA_KEY] = serialize_image_revisions(
        metadata[IMAGE_REVISIONS_METADATA_KEY]
    )
    return publicized


def resolve_served_revision(message_doc, revision_id=''):
    """Return the blob a request for this image should be served from, or None for the original.

    None means "this message's own stored content", which is what an unedited image and a
    reader who has restored the original both resolve to, and is the path every image took
    before revisions existed.

    An unrecognised ``rev`` falls back to whatever is current rather than erroring. That
    parameter exists to make an edited image's URL change so caches release the previous one, so
    a stale link is best answered with the image as it now stands rather than with a failure.

    The returned mapping uses the same ``blob_container`` / ``blob_path`` / ``mime_type`` keys a
    blob-backed image message carries, so it can be handed straight to the existing blob
    streaming helpers.
    """
    entry = read_image_revisions(message_doc)
    if not read_revisions(entry):
        return None

    revision = find_revision(entry, revision_id) if revision_id else None
    if revision is None:
        revision = resolve_current_revision(entry)

    return revision_blob_location(revision)


def serialize_image_revisions(entry):
    """Return the entry in the shape a browser may see.

    Blob containers and paths are storage detail. They are never sent: a reader needs to know
    that a version exists, who made it and why, not where its bytes are kept.
    """
    revisions = read_revisions(entry)
    if not revisions:
        return {}

    serialized = []
    for revision in revisions:
        mask = revision.get('mask') if isinstance(revision.get('mask'), dict) else None
        serialized.append({
            'id': revision.get('id'),
            'origin': revision.get('origin') or ORIGIN_AI,
            'prompt': revision.get('prompt') or '',
            'instruction': revision.get('instruction') or '',
            'author_id': revision.get('author_id') or '',
            'author_name': revision.get('author_name') or '',
            'timestamp': revision.get('timestamp') or '',
            'model': revision.get('model') or '',
            'method': revision.get('method') or '',
            'size': revision.get('size') or '',
            'quality': revision.get('quality') or '',
            'background': revision.get('background') or '',
            'width': revision.get('width') or 0,
            'height': revision.get('height') or 0,
            # Whether a region was selected, and how much of the image it covered. The mask
            # itself is not sent back; it was the reader's own input and is kept only so the
            # history can say what the edit applied to.
            'has_mask': bool(mask),
            'mask_coverage': (mask or {}).get('coverage') or 0,
            'mask_regions': (mask or {}).get('regions') or 0,
        })

    return {
        'current': read_current_index(entry),
        'revisions': serialized,
        'chat': [
            {
                'role': turn.get('role'),
                'content': turn.get('content') or '',
                'timestamp': turn.get('timestamp') or '',
            }
            for turn in (entry.get('chat') or [])
            if isinstance(turn, dict) and turn.get('role') in IMAGE_CHAT_ROLES
        ],
    }


def _build_revision(
    origin,
    prompt='',
    instruction='',
    author_id='',
    author_name='',
    image=None,
    mask=None,
    model='',
    method='',
    size='',
    quality='',
    background='',
):
    """Return one stored revision record."""
    revision = {
        'id': str(uuid.uuid4()),
        'origin': origin,
        'prompt': _bounded_text(prompt, MAX_PROMPT_LENGTH),
        'instruction': _bounded_text(instruction, MAX_INSTRUCTION_LENGTH),
        'author_id': _bounded_text(author_id, MAX_AUTHOR_ID_LENGTH),
        'author_name': _bounded_text(author_name, MAX_AUTHOR_NAME_LENGTH),
        'model': _bounded_text(model, MAX_MODEL_NAME_LENGTH),
        'method': _bounded_text(method, 40),
        'size': _bounded_text(size, 40),
        'quality': _bounded_text(quality, 40),
        'background': _bounded_text(background, 40),
        'timestamp': utc_now_iso(),
    }

    if isinstance(image, dict):
        container = _bounded_text(image.get('blob_container'), MAX_BLOB_PATH_LENGTH)
        path = _bounded_text(image.get('blob_path'), MAX_BLOB_PATH_LENGTH)
        if not container or not path:
            raise ImageRevisionError('An edited image must be stored in blob storage')
        revision['blob_container'] = container
        revision['blob_path'] = path
        revision['mime_type'] = _bounded_text(image.get('mime_type'), 100) or 'image/png'
        for dimension in ('width', 'height'):
            value = image.get(dimension)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                revision[dimension] = value

    if isinstance(mask, dict):
        stored_mask = {}
        mask_path = _bounded_text(mask.get('blob_path'), MAX_BLOB_PATH_LENGTH)
        mask_container = _bounded_text(mask.get('blob_container'), MAX_BLOB_PATH_LENGTH)
        if mask_path and mask_container:
            stored_mask['blob_container'] = mask_container
            stored_mask['blob_path'] = mask_path
        coverage = mask.get('coverage')
        if isinstance(coverage, (int, float)) and not isinstance(coverage, bool):
            stored_mask['coverage'] = round(float(coverage), 4)
        regions = mask.get('regions')
        if isinstance(regions, int) and not isinstance(regions, bool) and regions > 0:
            stored_mask['regions'] = regions
        if stored_mask:
            revision['mask'] = stored_mask

    return revision


def _prune_revisions(entry):
    """Drop the oldest edits until the entry is within the cap, keeping the original.

    Index zero is the original and is never dropped, because "show me the image I was actually
    given" has to keep working however many times it has been edited. ``current`` follows
    whatever it was pointing at.
    """
    revisions = entry['revisions']
    current = entry.get('current', 0)

    while len(revisions) > MAX_REVISIONS:
        del revisions[1]
        if current >= 1:
            current -= 1

    entry['current'] = max(0, min(current, len(revisions) - 1))


def _write_entry(message_doc, entry):
    """Store an entry back onto the message, removing the key when nothing is left."""
    metadata = message_doc.setdefault('metadata', {})
    if not isinstance(metadata, dict):
        metadata = {}
        message_doc['metadata'] = metadata

    if entry and entry.get('revisions'):
        metadata[IMAGE_REVISIONS_METADATA_KEY] = entry
    else:
        metadata.pop(IMAGE_REVISIONS_METADATA_KEY, None)

    return entry or {}


def _mutable_entry(entry):
    """Return a copy of a stored entry that can be modified without aliasing the document."""
    copied = dict(entry or {})
    copied['revisions'] = [dict(revision) for revision in read_revisions(entry)]
    copied['chat'] = [
        dict(turn) for turn in (entry or {}).get('chat') or [] if isinstance(turn, dict)
    ]
    return copied


def _seed_entry(message_doc, original_prompt):
    """Return a fresh entry whose revision zero stands for the image as it was generated.

    The original's prompt is taken from the message itself rather than from the request, so
    "restore the image I was given" cannot be pointed at a prompt the caller made up. Image
    messages persist the prompt that produced them in a top-level ``prompt`` field.
    """
    stored_prompt = _bounded_text((message_doc or {}).get('prompt'), MAX_PROMPT_LENGTH)
    return {
        'current': 0,
        'revisions': [
            _build_revision(
                ORIGIN_ORIGINAL,
                prompt=stored_prompt or _bounded_text(original_prompt, MAX_PROMPT_LENGTH),
                model=_bounded_text((message_doc or {}).get('model_deployment_name'),
                                    MAX_MODEL_NAME_LENGTH),
            )
        ],
        'chat': [],
    }


def assert_revision_expectations(
    message_doc,
    expected_revision_count=None,
    expected_current_revision_id='',
):
    """Raise when the stored versions have moved on since the caller last read them.

    Two guards, because the obvious one has a blind spot. Comparing the number of versions works
    until pruning starts: once the cap is reached, every append drops an entry, so the count is
    pinned at the cap and can never disagree again. From that point a count-only check would
    silently stop protecting anybody.

    Comparing which version is *current* has no such limit, and is the stronger statement
    anyway -- the editor was opened against a particular version, and that is what an edit is
    built on.
    """
    entry = read_image_revisions(message_doc)
    revisions = read_revisions(entry)

    if expected_revision_count is not None and len(revisions) != expected_revision_count:
        raise ImageRevisionConflictError('This image was changed by someone else')

    expected_id = str(expected_current_revision_id or '').strip()
    if expected_id:
        current = resolve_current_revision(entry)
        if not current or current.get('id') != expected_id:
            raise ImageRevisionConflictError('This image was changed by someone else')


def apply_image_revision(
    message_doc,
    image,
    origin=ORIGIN_AI,
    prompt='',
    instruction='',
    mask=None,
    model='',
    method='',
    size='',
    quality='',
    background='',
    author_id='',
    author_name='',
    expected_revision_count=None,
    expected_current_revision_id='',
):
    """Append a new version of an image and make it current, returning the stored entry.

    ``image`` describes where the new bytes were written. It is required: a revision that stores
    no location would resolve to the original and silently discard the edit that was just paid
    for.

    ``expected_revision_count`` and ``expected_current_revision_id`` guard against two people in
    a shared conversation changing the same image at once. See ``assert_revision_expectations``
    for why both exist rather than just the count.
    """
    revision_origin = validate_origin(origin)
    if revision_origin == ORIGIN_ORIGINAL:
        raise ImageRevisionError('Cannot store a revision as the original')
    if not isinstance(image, dict):
        raise ImageRevisionError('An edited image must be stored in blob storage')

    assert_revision_expectations(
        message_doc, expected_revision_count, expected_current_revision_id
    )

    entry = read_image_revisions(message_doc)
    entry = _mutable_entry(entry) if read_revisions(entry) else _seed_entry(message_doc, prompt)

    entry['revisions'].append(
        _build_revision(
            revision_origin,
            prompt=prompt,
            instruction=instruction,
            author_id=author_id,
            author_name=author_name,
            image=image,
            mask=mask,
            model=model,
            method=method,
            size=size,
            quality=quality,
            background=background,
        )
    )
    entry['current'] = len(entry['revisions']) - 1
    _prune_revisions(entry)

    return _write_entry(message_doc, entry)


def set_current_image_revision(message_doc, revision_id):
    """Point an image at one of its stored versions, returning the stored entry.

    Addressed by revision id rather than position, because positions shift when the oldest edits
    are pruned and an undo that moved by index would eventually undo to the wrong version.
    Nothing is discarded: editing after restoring an older version appends rather than
    truncating, so the list stays a record of everything that happened.
    """
    entry = read_image_revisions(message_doc)
    if not read_revisions(entry):
        raise ImageRevisionError('This image has no stored versions')

    entry = _mutable_entry(entry)
    target = next(
        (
            position
            for position, revision in enumerate(entry['revisions'])
            if revision.get('id') == str(revision_id or '').strip()
        ),
        None,
    )
    if target is None:
        raise ImageRevisionError('That version no longer exists')

    entry['current'] = target
    return _write_entry(message_doc, entry)


def append_image_chat_turn(message_doc, role, content):
    """Add one turn to an image's scoped sub-conversation, returning the stored entry.

    The transcript is kept with the image rather than in the message list, which is the whole
    point of the feature: refining an image should not fill the thread with near-duplicates, and
    none of these turns is ever sent as conversation history. Image messages are excluded from
    the model's history entirely, so this is the only record of how an image was arrived at.
    """
    if role not in IMAGE_CHAT_ROLES:
        raise ImageRevisionError('Unsupported chat role')
    if not isinstance(content, str):
        raise ImageRevisionError('Chat content must be a string')

    text = content.strip()[:MAX_CHAT_CONTENT_LENGTH]
    if not text:
        raise ImageRevisionError('Chat content cannot be empty')

    entry = read_image_revisions(message_doc)
    if not read_revisions(entry):
        raise ImageRevisionError('This image has no stored versions')

    entry = _mutable_entry(entry)
    entry['chat'] = (entry['chat'] + [{
        'role': role,
        'content': text,
        'timestamp': utc_now_iso(),
    }])[-MAX_CHAT_TURNS:]

    return _write_entry(message_doc, entry)


def read_image_chat(entry):
    """Return an image's stored sub-conversation as plain role/content turns."""
    if not isinstance(entry, dict):
        return []
    return [
        {'role': turn.get('role'), 'content': turn.get('content') or ''}
        for turn in (entry.get('chat') or [])
        if isinstance(turn, dict) and turn.get('role') in IMAGE_CHAT_ROLES
    ]


def current_image_prompt(message_doc, fallback=''):
    """Return the prompt describing the image as it currently stands.

    An edit is composed against the prompt of the version in front of the reader, not against
    the prompt that produced the very first image, so that successive edits accumulate rather
    than each one being applied to the original.
    """
    entry = read_image_revisions(message_doc)
    revision = resolve_current_revision(entry)
    if revision and revision.get('prompt'):
        return revision['prompt']

    stored = _bounded_text((message_doc or {}).get('prompt'), MAX_PROMPT_LENGTH)
    return stored or _bounded_text(fallback, MAX_PROMPT_LENGTH)


def remove_image_revisions(message_doc):
    """Drop every stored version for an image, returning the resulting entry."""
    return _write_entry(message_doc, None)
