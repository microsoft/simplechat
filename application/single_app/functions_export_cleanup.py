# functions_export_cleanup.py
"""Small, import-independent cleanup guards for owned export resources."""

from typing import Generic, Optional, TypeVar


_Resource = TypeVar('_Resource')


def close_export_resource(resource, *, primary_error: Optional[BaseException] = None) -> None:
    """Attempt close once, without replacing an active failure with cleanup errors.

    GeneratorExit represents normal generator closing, not a failed operation.
    Its cleanup failures must reach the enclosing owner, which can then preserve
    the actual render error if there is one.

    primary_error must belong to this operation. Prefer ClosingExportResource:
    ambient sys.exc_info() can describe an unrelated, already-handled caller error.
    """
    try:
        close = getattr(resource, 'close', None)
        if callable(close):
            close()
    except Exception:
        if primary_error is None or isinstance(primary_error, GeneratorExit):
            raise
        BaseException.add_note(
            primary_error,
            'Export resource cleanup also failed; the original failure is preserved.',
        )


class ClosingExportResource(Generic[_Resource]):
    """Like closing(), but keep the body's failure and cause when close also fails."""

    def __init__(self, resource: _Resource):
        self.resource = resource

    def __enter__(self) -> _Resource:
        return self.resource

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        close_export_resource(self.resource, primary_error=exc_value)
        return False
