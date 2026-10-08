# functions_access_restriction.py
"""Describe a user's access restriction for the access gate and the Access restricted screen.

Control Center and safety remediation restrict a user by writing
``settings.access = {'status': 'deny', 'datetime_to_allow': <ISO 8601 or None>}``. A
suspension or block applied for a safety violation also stores a ``notice`` beside them:
the title and message the user was sent, so the screen a restricted user lands on can say
why. Control Center writes replace the whole ``access`` value, so restoring access there
clears the notice too.

This module only reads and builds those values. It imports nothing from ``config`` or
``functions_settings``: reading the signed-in user's settings, and restoring an expired
suspension, happen in ``functions_authentication.get_user_access_restriction``.
"""

from datetime import datetime, timezone


ACCESS_RESTRICTION_KIND_SUSPENDED = 'suspended'
ACCESS_RESTRICTION_KIND_BLOCKED = 'blocked'
ACCESS_RESTRICTION_KINDS = (
    ACCESS_RESTRICTION_KIND_SUSPENDED,
    ACCESS_RESTRICTION_KIND_BLOCKED,
)
ACCESS_RESTRICTION_SOURCE_SAFETY_VIOLATION = 'safety_violation'

# What the gate answers an API call from a restricted user with, and where it sends a page.
ACCESS_RESTRICTED_ERROR = 'access_restricted'
V2_ACCESS_RESTRICTED_PATH = '/v2/access-restricted'
CLASSIC_ACCESS_RESTRICTED_PATH = '/access-restricted'
V2_ACCESS_RESTRICTION_API_PATH = '/api/v2/access-restriction'
ACCESS_RESTRICTION_PATHS = frozenset({
    V2_ACCESS_RESTRICTED_PATH,
    CLASSIC_ACCESS_RESTRICTED_PATH,
    V2_ACCESS_RESTRICTION_API_PATH,
})

ACCESS_STATE_ALLOW = 'allow'
ACCESS_STATE_EXPIRED = 'expired'
ACCESS_STATE_RESTRICTED = 'restricted'

NOTICE_TITLE_MAX_LENGTH = 200
NOTICE_MESSAGE_MAX_LENGTH = 4000
NOTICE_REFERENCE_MAX_LENGTH = 200

LEGACY_PERMANENT_DENY_REASON = 'Access denied by administrator'
LEGACY_TIMED_DENY_PREFIX = 'Access denied until '

# Shown when a restriction carries no notice, such as one applied from Control Center.
_DEFAULT_COPY = {
    ACCESS_RESTRICTION_KIND_SUSPENDED: (
        'Your access is temporarily suspended',
        'An administrator has temporarily suspended your access to this application. '
        'Your access is restored automatically at the time shown.',
    ),
    ACCESS_RESTRICTION_KIND_BLOCKED: (
        'Your access has been blocked',
        'An administrator has blocked your access to this application. '
        'Contact your administrator if you have questions about this decision.',
    ),
}

_API_SENTENCES = {
    ACCESS_RESTRICTION_KIND_SUSPENDED: 'Your access to this application is temporarily suspended.',
    ACCESS_RESTRICTION_KIND_BLOCKED: 'Your access to this application has been blocked by an administrator.',
}

PUBLIC_RESTRICTION_FIELDS = ('kind', 'until', 'title', 'message', 'reference_id')


def _clean_text(value, max_length):
    """Return trimmed text no longer than ``max_length``, or '' for anything that isn't text."""
    if not isinstance(value, str):
        return ''
    return value.strip()[:max_length]


def parse_access_restore_time(value):
    """Return a stored restore time as an aware UTC datetime, or None when it can't be read.

    A value without a UTC offset is read as UTC, as Control Center reads it.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _restriction(kind, until=None, title='', message='', reference_id=None):
    default_title, default_message = _DEFAULT_COPY[kind]
    return {
        'kind': kind,
        'until': until if kind == ACCESS_RESTRICTION_KIND_SUSPENDED else None,
        'title': title or default_title,
        'message': message or default_message,
        'reference_id': reference_id or None,
    }


def _notice_copy(notice, kind):
    """Return ``(title, message, reference_id)`` from a stored notice that matches ``kind``.

    A notice written for a different kind of restriction describes something that no longer
    applies, so it is ignored and the generic copy is used instead.
    """
    if not isinstance(notice, dict) or notice.get('kind') != kind:
        return '', '', None
    return (
        _clean_text(notice.get('title'), NOTICE_TITLE_MAX_LENGTH),
        _clean_text(notice.get('message'), NOTICE_MESSAGE_MAX_LENGTH),
        _clean_text(notice.get('reference_id'), NOTICE_REFERENCE_MAX_LENGTH) or None,
    )


def describe_access_restriction(access_settings, now=None):
    """Return ``(state, restriction)`` for a stored ``settings.access`` value.

    ``state`` is ``'allow'``, ``'expired'`` -- a suspension whose restore time has passed,
    which the caller restores -- or ``'restricted'``, the only state that comes with a
    restriction. A deny whose restore time can't be read stays in force with no end date,
    as it always has, and is described as a block.

    The restriction holds ``kind``, ``until`` (ISO 8601 UTC, suspensions only), ``title``,
    ``message`` and ``reference_id``.
    """
    if not isinstance(access_settings, dict) or access_settings.get('status') != 'deny':
        return ACCESS_STATE_ALLOW, None

    kind = ACCESS_RESTRICTION_KIND_BLOCKED
    until = None
    if access_settings.get('datetime_to_allow'):
        restore_at = parse_access_restore_time(access_settings.get('datetime_to_allow'))
        if restore_at is not None:
            if (now or datetime.now(timezone.utc)) >= restore_at:
                return ACCESS_STATE_EXPIRED, None
            kind = ACCESS_RESTRICTION_KIND_SUSPENDED
            until = restore_at.isoformat()

    title, message, reference_id = _notice_copy(access_settings.get('notice'), kind)
    return ACCESS_STATE_RESTRICTED, _restriction(kind, until, title, message, reference_id)


def legacy_access_denied_reason(access_settings, restriction):
    """Return the reason ``check_user_access_status`` has always given for a restriction."""
    if restriction.get('kind') == ACCESS_RESTRICTION_KIND_SUSPENDED:
        return f"{LEGACY_TIMED_DENY_PREFIX}{access_settings.get('datetime_to_allow')}"
    return LEGACY_PERMANENT_DENY_REASON


def fallback_access_restriction(reason=None):
    """Describe a restriction from its legacy reason alone, with the generic copy.

    Used when the access check refused a user but the stored details could not be read
    again, so the response still says whether access returns on its own.
    """
    text = reason if isinstance(reason, str) else ''
    if text.startswith(LEGACY_TIMED_DENY_PREFIX):
        restore_at = parse_access_restore_time(text[len(LEGACY_TIMED_DENY_PREFIX):])
        if restore_at is not None:
            return _restriction(ACCESS_RESTRICTION_KIND_SUSPENDED, restore_at.isoformat())
    return _restriction(ACCESS_RESTRICTION_KIND_BLOCKED)


def public_access_restriction(restriction):
    """Return only the fields of a restriction that are shown to the restricted user."""
    restriction = restriction if isinstance(restriction, dict) else {}
    return {field: restriction.get(field) for field in PUBLIC_RESTRICTION_FIELDS}


def access_restricted_sentence(restriction):
    """Return the plain sentence an API response gives a restricted user."""
    kind = (restriction or {}).get('kind')
    return _API_SENTENCES.get(kind, _API_SENTENCES[ACCESS_RESTRICTION_KIND_BLOCKED])


def build_access_restriction_notice(
    kind,
    title,
    message,
    until=None,
    reference_id=None,
    source=ACCESS_RESTRICTION_SOURCE_SAFETY_VIOLATION,
    applied_at=None,
):
    """Return the ``notice`` stored beside a restriction so the restricted user can see why."""
    if kind not in ACCESS_RESTRICTION_KINDS:
        raise ValueError(f'Unsupported access restriction kind: {kind}')
    return {
        'kind': kind,
        'title': _clean_text(title, NOTICE_TITLE_MAX_LENGTH),
        'message': _clean_text(message, NOTICE_MESSAGE_MAX_LENGTH),
        'until': until if kind == ACCESS_RESTRICTION_KIND_SUSPENDED and until else None,
        'source': source,
        'reference_id': _clean_text(reference_id, NOTICE_REFERENCE_MAX_LENGTH) or None,
        'applied_at': applied_at or datetime.now(timezone.utc).isoformat(),
    }


def is_v2_request_path(path):
    """True for V2 pages and V2 API calls. Mirrors ``_is_v2_request_path`` in app.py."""
    return path in ('/v2', '/api/v2') or path.startswith('/v2/') or path.startswith('/api/v2/')


def access_restricted_page_path(request_path):
    """Return the Access restricted page for the interface ``request_path`` belongs to."""
    if is_v2_request_path(str(request_path or '')):
        return V2_ACCESS_RESTRICTED_PATH
    return CLASSIC_ACCESS_RESTRICTED_PATH
