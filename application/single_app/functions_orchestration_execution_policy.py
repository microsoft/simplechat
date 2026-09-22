# functions_orchestration_execution_policy.py
"""Task-local, server-owned restrictions on managed file creation.

The absent policy preserves standalone and workflow behavior. An inner scope
cannot grant file publication when its owning orchestration task forbids it.
This module deliberately has no application/bootstrap dependencies.
"""

from contextlib import contextmanager
from contextvars import ContextVar


class OrchestrationFilePolicyError(PermissionError):
    """A Gather/Reason task attempted managed file creation or publication."""

    def __init__(self):
        super().__init__("File creation and publication require an explicit Render task.")


_file_policy = ContextVar("orchestration_file_policy", default=None)

MANAGED_FILE_FUNCTIONS = frozenset({
    "upload_markdown_document",
    "upload_word_document",
    "upload_powerpoint_document",
})


def current_orchestration_file_policy():
    """Return the immutable policy for capture in a server-owned execution frame."""
    return _file_policy.get()


def generated_file_publication_allowed():
    return current_orchestration_file_policy() is not False


@contextmanager
def orchestration_file_policy(*, allow_generated_files: bool):
    if type(allow_generated_files) is not bool:
        raise TypeError("The orchestration file policy requires an explicit boolean.")
    token = _file_policy.set(allow_generated_files and generated_file_publication_allowed())
    try:
        yield
    finally:
        _file_policy.reset(token)


def require_generated_file_publication_allowed():
    if not generated_file_publication_allowed():
        raise OrchestrationFilePolicyError()
