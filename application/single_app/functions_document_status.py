# functions_document_status.py
"""Document terminal-state predicates, independent of application bootstrap.

Status details can contain filenames, sheet names, or retry diagnostics. Only
lifecycle phrases at the start of a status can declare a terminal outcome.
Keep the browser predicates aligned through document_processing_status_cases.json.
"""

import re


_FAILURE = re.compile(
    r"^(?:(?:error|failed)(?:$|[\s:!]|\.(?:$|\s))"
    r"|(?:processing|document processing|approval|content screening) failed(?:$|[\s:;!]|\.(?:$|\s))"
    r"|video:\s*(?:blob upload|auth|upload|indexing) failed(?:$|[\s:!]|\.(?:$|\s)))",
    re.IGNORECASE,
)
_COMPLETE = re.compile(
    r"^(?:(?:ready|complete|completed|processed|finished)[.!]?$"
    r"|processing complete(?:$|[.!]$|\s+[-(]))",
    re.IGNORECASE,
)


def is_document_processing_failure(status):
    """Recognize terminal failures, not error words in processing details."""
    return isinstance(status, str) and _FAILURE.match(status.strip()) is not None


def is_document_processing_complete(status):
    """Recognize final completion, not completion of an intermediate stage."""
    return isinstance(status, str) and _COMPLETE.match(status.strip()) is not None
