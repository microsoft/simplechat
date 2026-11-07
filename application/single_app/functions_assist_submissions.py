# functions_assist_submissions.py

"""Client submission ids for the scoped AI assist threads.

The diagram, chart, image and plan editors each keep a small conversation of their own. The
browser shows a message the moment it is sent, before the server has answered, and has to
recognise that same message when the stored transcript comes back -- otherwise it would show it
twice, or lose it. It does that with an id it mints for each message, which the server stores on
both turns of the exchange.

The id is optional. A client that sends none gets exactly the behaviour it had before. When one is
sent it also makes a retry safe: a request whose id is already stored answers from what was
stored instead of calling the model and writing a second revision. The same id arriving with a
different instruction is refused rather than replayed, because it cannot be the same request.

Submission ids are bookkeeping. They are never part of what a model is shown.
"""

import re

# Matches MAX_SUBMISSION_ID_LENGTH in functions_message_block_revisions.py and
# functions_message_image_revisions.py, which store the id and stay free of application imports.
MAX_SUBMISSION_ID_LENGTH = 128

# Letters, digits and a few separators. Enough for a UUID or a prefixed token, and nothing that
# needs escaping anywhere it is stored or echoed.
SUBMISSION_ID_PATTERN = re.compile(rf'^[A-Za-z0-9._:-]{{1,{MAX_SUBMISSION_ID_LENGTH}}}$')

SUBMISSION_NEW = 'new'
SUBMISSION_REPLAY = 'replay'
SUBMISSION_CONFLICT = 'conflict'

SUBMISSION_CONFLICT_CODE = 'submission_conflict'
SUBMISSION_CONFLICT_MESSAGE = (
    'This request id was already used for a different message. Send the message again.'
)


class SubmissionIdError(ValueError):
    """Raised when a supplied submission id is not one the server will store."""


def normalize_submission_id(value):
    """Return a storable submission id, None when none was sent, or raise when it is malformed."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise SubmissionIdError('submission_id must be a string')
    text = value.strip()
    if not text:
        return None
    if not SUBMISSION_ID_PATTERN.fullmatch(text):
        raise SubmissionIdError('submission_id is not valid')
    return text


def find_submission_turn(chat_turns, submission_id, role='user'):
    """Return the stored turn carrying this submission id and role, or None."""
    if not submission_id or not isinstance(chat_turns, list):
        return None
    for turn in chat_turns:
        if (
            isinstance(turn, dict)
            and turn.get('role') == role
            and turn.get('submission_id') == submission_id
        ):
            return turn
    return None


def classify_submission(chat_turns, submission_id, content, max_length):
    """Say whether a request is new, repeats a stored exchange, or reuses an id for something else.

    ``content`` is the instruction as the route is about to store it; it is trimmed and bounded the
    same way the chat helpers bound a stored turn, so a replay compares like with like. A turn
    stored before submission ids existed has none, so it can never match.
    """
    turn = find_submission_turn(chat_turns, submission_id)
    if turn is None:
        return SUBMISSION_NEW
    candidate = str(content or '').strip()[:max_length]
    stored = str(turn.get('content') or '')
    return SUBMISSION_REPLAY if stored == candidate else SUBMISSION_CONFLICT
