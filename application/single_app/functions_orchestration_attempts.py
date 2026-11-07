# functions_orchestration_attempts.py
"""Which saved orchestration attempts a later retry replaced.

Retrying a failed plan saves the retry's answer as a new assistant message and keeps the
earlier attempt's message, so the conversation still records what happened. Once the
retry's message exists, the earlier attempt no longer describes the request: its "could
not be completed" text is history, not an answer. Readers that send stored messages to a
model, or export them for the user, drop it with these helpers. The V2 thread hides it the
same way (``lib/orchestration.ts`` ``supersededOrchestrationRunIds``).

Only the standard library is imported, so any reader can use this module without pulling
orchestration storage into its import graph.

Version: 0.261.304
Implemented in: 0.261.304
"""

from collections.abc import Mapping


def _attempt_lineage(message):
    """The run id and the retried run id a saved message records, either of which may be None."""
    metadata = message.get('metadata') if isinstance(message, Mapping) else None
    orchestration = metadata.get('orchestration') if isinstance(metadata, Mapping) else None
    if not isinstance(orchestration, Mapping):
        return None, None
    run_id = orchestration.get('run_id')
    retry_of = orchestration.get('retry_of_run_id')
    return (
        run_id if isinstance(run_id, str) and run_id else None,
        retry_of if isinstance(retry_of, str) and retry_of else None,
    )


def superseded_orchestration_run_ids(messages):
    """The run ids of attempts that a later attempt among ``messages`` retried."""
    superseded = set()
    for message in messages or ():
        run_id, retry_of = _attempt_lineage(message)
        if retry_of and retry_of != run_id:
            superseded.add(retry_of)
    return superseded


def is_superseded_orchestration_attempt(message, superseded):
    """Whether ``message`` is the assistant answer of an attempt in ``superseded``."""
    if not superseded or not isinstance(message, Mapping) or message.get('role') != 'assistant':
        return False
    run_id, _retry_of = _attempt_lineage(message)
    return bool(run_id and run_id in superseded)


def exclude_superseded_orchestration_attempts(messages):
    """Return the messages without replaced attempts' answers, preserving their order."""
    messages = list(messages or ())
    superseded = superseded_orchestration_run_ids(messages)
    if not superseded:
        return messages
    return [
        message for message in messages
        if not is_superseded_orchestration_attempt(message, superseded)
    ]
