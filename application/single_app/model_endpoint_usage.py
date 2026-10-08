# model_endpoint_usage.py
"""Preserve the distinction between missing usage and measured zero consumption."""

from collections.abc import Mapping


def project_completion_token_usage(usage, captured_at):
    if usage is None:
        return None
    result = {}
    for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(field) if isinstance(usage, Mapping) else getattr(usage, field, None)
        if type(value) is not int or value < 0:
            raise ValueError("The provider supplied invalid token usage.")
        result[field] = value
    result["captured_at"] = captured_at
    return result
