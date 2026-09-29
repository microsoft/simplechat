# functions_assist_references.py

"""
Request-side rules for `#` document and tag references in an AI-assist input.

A reference arrives from the browser as a claim: a kind, an identity, the workspace it
was picked from, and the label the user saw. None of that is authorization; the acting
user's access is checked when the reference is used, by ``resolve_scope_references`` in
``functions_orchestration_context``. What this module owns is the request identity: one
canonical, bounded form for a selection, whatever order or duplicates the browser sent,
so a submission id can tell a replayed request from a different one.

The browser computes the same canonical form (``application/v2_ui/src/lib/planReferences.ts``)
to decide when a submission id may be reused. The two are pinned to each other by
``functional_tests/fixtures/plan_reference_canonicalization.json``; change them together.

This module has no Azure, Flask or configuration imports, so stores and tests can import
it cheaply and without a cycle.

Version: 0.261.198
Implemented in: 0.261.198
"""

import re

REFERENCE_LABEL_LIMIT = 200
REFERENCE_IDENTIFIER_LIMIT = 512
REQUEST_REFERENCE_LIMIT = 20
# Bounds the work done on a request before duplicates are removed.
REQUEST_REFERENCE_RAW_LIMIT = 100
REQUEST_REFERENCE_KINDS = ('document', 'tag')
REQUEST_REFERENCE_SCOPES = ('personal', 'group', 'public')

_REFERENCE_FIELDS = frozenset(('kind', 'id', 'label', 'scope'))
_SCOPE_FIELDS = frozenset(('kind', 'id', 'name'))
# Character sets are spelled out rather than left to str.strip(), so the browser's
# canonical form matches this one exactly whatever each runtime's Unicode tables say.
# Bidirectional controls are removed with the other controls: a label is shown inside a
# sentence, and must not be able to reorder the text around it.
_LABEL_CONTROL_CHARACTERS = re.compile(
    '[\x00-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]'
)
_LABEL_SPACE = ''.join((
    ' \u00a0\u1680', *(chr(code) for code in range(0x2000, 0x200b)),
    '\u2028\u2029\u202f\u205f\u3000',
))
_IDENTIFIER_SPACE = '\t\n\v\f\r '


class ReferenceRequestError(ValueError):
    """A reference list that cannot be part of a request, with a stable code."""

    def __init__(self, message, code='invalid_request'):
        super().__init__(message)
        self.message = message
        self.code = code


def sanitize_reference_label(value, limit=REFERENCE_LABEL_LIMIT):
    """The label a user picked, as plain display text: no control characters, bounded.

    A label is untrusted text. It is only ever displayed back as text and named in an
    error message; it is never authorization and never reaches a prompt.
    """
    if not isinstance(value, str):
        return ''
    text = _LABEL_CONTROL_CHARACTERS.sub('', value).strip(_LABEL_SPACE)
    if len(text) > limit:
        text = text[:limit].rstrip(_LABEL_SPACE)
    return text


def _strip_identifier(value):
    return value.strip(_IDENTIFIER_SPACE) if isinstance(value, str) else value


def _identifier(value, message):
    if not isinstance(value, str):
        raise ReferenceRequestError(message)
    text = _strip_identifier(value)
    if not text or len(text) > REFERENCE_IDENTIFIER_LIMIT:
        raise ReferenceRequestError(message)
    return text


def canonical_reference(value):
    """One reference in canonical form, or ReferenceRequestError."""
    if not isinstance(value, dict) or set(value) - _REFERENCE_FIELDS:
        raise ReferenceRequestError('Choose documents or tags from the # picker.')
    kind = value.get('kind')
    if kind not in REQUEST_REFERENCE_KINDS:
        raise ReferenceRequestError('Only documents and tags from your workspaces can be attached here.')
    scope = value.get('scope')
    if not isinstance(scope, dict) or set(scope) - _SCOPE_FIELDS:
        raise ReferenceRequestError('Choose documents or tags from the # picker.')
    scope_kind = scope.get('kind')
    if scope_kind not in REQUEST_REFERENCE_SCOPES:
        raise ReferenceRequestError('Only documents and tags from your workspaces can be attached here.')
    scope_id = scope.get('id')
    if scope_id is None or (isinstance(scope_id, str) and not _strip_identifier(scope_id)):
        if scope_kind != 'personal':
            raise ReferenceRequestError('Choose documents or tags from the # picker.')
        scope_id = None
    else:
        scope_id = _identifier(scope_id, 'Choose documents or tags from the # picker.')
    reference = {
        'kind': kind,
        'id': _identifier(value.get('id'), 'Choose documents or tags from the # picker.'),
        'scope': {'kind': scope_kind, 'id': scope_id},
    }
    label = sanitize_reference_label(value.get('label'))
    if label:
        reference['label'] = label
    return reference


def reference_identity(reference):
    """The dedupe identity of a canonical reference. Never the label."""
    return (
        reference['kind'], reference['id'],
        reference['scope']['kind'], reference['scope']['id'] or '',
    )


def canonical_request_references(value, limit=REQUEST_REFERENCE_LIMIT):
    """Canonical references for a request: shape-checked, deduplicated and ordered.

    Duplicates keep the first label sent. The order is by kind, workspace and identity in
    code point order, so the same selection always has the same form. ``None`` and an empty
    list are both no references.
    """
    if value is None:
        return []
    if not isinstance(value, list):
        raise ReferenceRequestError('Choose documents or tags from the # picker.')
    if len(value) > REQUEST_REFERENCE_RAW_LIMIT:
        raise ReferenceRequestError(
            f'Attach at most {limit} documents or tags.', 'reference_limit',
        )
    unique = {}
    for item in value:
        reference = canonical_reference(item)
        unique.setdefault(reference_identity(reference), reference)
    if len(unique) > limit:
        raise ReferenceRequestError(
            f'Attach at most {limit} documents or tags.', 'reference_limit',
        )
    return sorted(
        unique.values(),
        key=lambda item: (
            item['kind'], item['scope']['kind'], item['scope']['id'] or '', item['id'],
        ),
    )
