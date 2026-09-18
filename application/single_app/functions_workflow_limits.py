# functions_workflow_limits.py
"""Validated item ceilings shared by workflow administration and loop admission."""

from collections.abc import Mapping


WORKFLOW_LOOP_ITEMS_DEFAULT = 500
WORKFLOW_LOOP_ITEMS_MIN = 1
WORKFLOW_LOOP_ITEMS_MAX = 5000
WORKFLOW_LOOP_LIMIT_SETTING = "workflow_max_loop_items"


class WorkflowLoopInputError(ValueError):
    """A safe workflow-input failure shared by source and cardinality checks."""

    def __init__(self, public_message, *, code="workflow_loop_input_unavailable",
                 count=None, count_exact=False, limit=None):
        self.public_message = public_message
        self.code = code
        self.count = count
        self.count_exact = bool(count_exact)
        self.limit = limit
        super().__init__(public_message)


class WorkflowLoopLimitError(WorkflowLoopInputError):
    """A safe validation or admission failure, with explicit count precision."""

    def __init__(self, public_message, *, code="workflow_loop_limit_invalid",
                 count=None, count_exact=False, limit=None):
        super().__init__(
            public_message, code=code, count=count, count_exact=count_exact, limit=limit,
        )


def validate_workflow_max_loop_items(value):
    """Accept an integer in the supported admin range; never clamp a supplied value."""
    candidate = value
    if isinstance(value, str):
        text = value.strip()
        candidate = (
            int(text)
            if text.isascii() and text.isdecimal() and len(text) <= 10
            else None
        )
    if (
        type(candidate) is not int
        or not WORKFLOW_LOOP_ITEMS_MIN <= candidate <= WORKFLOW_LOOP_ITEMS_MAX
    ):
        raise WorkflowLoopLimitError(
            "Workflow Loop Item Limit must be a whole number from 1 to 5,000."
        )
    return candidate


def get_workflow_max_loop_items(settings=None):
    """Read the current policy, without normalizing or writing the settings document."""
    if settings is None:
        # Settings initialize application clients; load them only at a request boundary.
        from functions_settings import get_settings

        settings = get_settings()
    if not isinstance(settings, Mapping):
        raise WorkflowLoopLimitError("The workflow item limit is temporarily unavailable.")
    return validate_workflow_max_loop_items(
        settings.get(WORKFLOW_LOOP_LIMIT_SETTING, WORKFLOW_LOOP_ITEMS_DEFAULT)
    )


def get_workflow_loop_item_limit(settings=None):
    """Return the validated administrator ceiling to snapshot at new-run admission."""
    return get_workflow_max_loop_items(settings)


def effective_workflow_loop_limit(max_items=None, *, settings=None, policy=None):
    """Combine an authored ceiling with a run's admitted policy or current settings."""
    if policy is None:
        admin_limit = get_workflow_max_loop_items(settings)
    else:
        if not isinstance(policy, Mapping) or "max_items" not in policy:
            raise WorkflowLoopLimitError("The admitted workflow item limit is unavailable.")
        admin_limit = validate_workflow_max_loop_items(policy["max_items"])
    author_limit = admin_limit if max_items is None else validate_workflow_max_loop_items(max_items)
    return min(admin_limit, author_limit)


def assert_workflow_loop_item_count(count, *, limit, count_exact=True):
    """Reject oversized inputs before body execution, preserving lower-bound wording."""
    limit = validate_workflow_max_loop_items(limit)
    if type(count) is not int or count < 0:
        raise WorkflowLoopLimitError("The workflow input count could not be confirmed.")
    if count > limit:
        qualifier = "" if count_exact else "at least "
        raise WorkflowLoopLimitError(
            f"This selection contains {qualifier}{count:,} items. This run allows "
            f"{limit:,} items. Narrow the query or select {limit:,} or fewer items "
            "before starting a new run.",
            code="workflow_loop_item_limit_exceeded",
            count=count,
            count_exact=count_exact,
            limit=limit,
        )
    return count
