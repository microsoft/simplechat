# functions_schema_diagnostics.py
"""Content-free locations for JSON Schema failures.

Argument names and values written by a planner, or taken from a document, can hold private
text. These diagnostics therefore name only what the schema itself defines: its keywords, its
property names, the position of an array item, enumerated values and counts. A property name
the schema does not define is only ever counted.

Version: 0.261.443
Implemented in: 0.261.443
"""

import re

from jsonschema.exceptions import best_match


MAX_REPORTED_NAMES = 12
MAX_PATH_LENGTH = 80
_TOKEN = re.compile(r"[a-z][a-z0-9_]{0,79}")


def _token(value):
    return value if isinstance(value, str) and _TOKEN.fullmatch(value) else None


def _tokens(values, limit=MAX_REPORTED_NAMES):
    return [item for item in (_token(value) for value in list(values or ())[:limit]) if item]


def _constants(alternative):
    """The string constants a oneOf/anyOf alternative owns, by property: how an alternative names itself."""
    properties = alternative.get("properties") if isinstance(alternative, dict) else None
    return {
        name: definition["const"] for name, definition in (properties or {}).items()
        if isinstance(definition, dict) and isinstance(definition.get("const"), str)
    }


def _matching_constants(alternative, instance):
    """How many of an alternative's own constants the instance already carries."""
    if not isinstance(instance, dict):
        return 0
    return sum(1 for name, value in _constants(alternative).items() if instance.get(name) == value)


def innermost_schema_error(error):
    """Descend into oneOf/anyOf to the branch the instance was written for.

    A branch whose schema-owned constant, such as a step operation, equals the instance's own value
    is the branch the instance names. It is chosen before closeness, because another branch can fail
    in fewer places only when the named one has more faults. When no constant matches, the branch with
    the fewest failures is chosen, and the lowest index among equals.

    Returns the error, the schema of the chosen branch, every alternative's schema and the instance
    that choice was made for; the last three are None when the error was not a branch failure.
    """
    branch = alternatives = instance = None
    while error.validator in ("oneOf", "anyOf") and error.context:
        grouped = {}
        for item in error.context:
            grouped.setdefault(item.relative_schema_path[0], []).append(item)
        alternatives = error.schema.get(error.validator)
        alternatives = alternatives if isinstance(alternatives, list) else None
        instance = error.instance
        offered = alternatives or ()
        index = min(grouped, key=lambda key: (
            -_matching_constants(offered[key] if key < len(offered) else None, instance), len(grouped[key]), key,
        ))
        branch = offered[index] if index < len(offered) else None
        error = best_match(grouped[index])
    return error, branch, alternatives, instance


def _discriminator(branch, instance):
    """The schema-owned constant a branch is selected by, such as a step operation."""
    if not isinstance(instance, dict):
        return None
    for name, value in _constants(branch).items():
        if instance.get(name) == value and _token(value):
            return value
    return None


def schema_error_location(error):
    """A content-free description of where, and why, an instance failed its schema.

    Always ``argument_keyword`` and ``argument_path`` (empty at the root). ``argument_branch`` is
    present when a oneOf/anyOf alternative was chosen by a schema-owned constant. The failed
    keyword adds ``missing_properties``, ``allowed_properties``, ``extra_property_count``,
    ``allowed_values``, ``expected_type`` or ``schema_limit`` when it defines them.

    A diagnostic must never replace the failure it describes, so an unexpected schema shape
    yields only the failed keyword.
    """
    try:
        return _locate(error)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return {"argument_keyword": str(getattr(error, "validator", "unknown")).lower(), "argument_path": ""}


def _locate(error):
    error, branch, alternatives, instance = innermost_schema_error(error)
    schema_path = list(error.absolute_schema_path)
    names = {
        step for position, step in enumerate(schema_path[1:], 1)
        if schema_path[position - 1] == "properties" and isinstance(step, str)
    }
    # Instance-path text is kept only when the schema defines it; anything else is a model-supplied key.
    path = "_".join(
        str(part) if isinstance(part, int) else part if part in names else "x"
        for part in error.absolute_path
    )
    location = {"argument_keyword": error.validator.lower(), "argument_path": path[:MAX_PATH_LENGTH]}
    branch_value = _discriminator(branch, instance)
    if branch_value:
        location["argument_branch"] = branch_value
    keyword = error.validator
    value = error.validator_value
    if keyword == "required" and isinstance(value, list) and isinstance(error.instance, dict):
        location["missing_properties"] = _tokens(name for name in value if name not in error.instance)
    elif keyword == "additionalProperties" and isinstance(error.instance, dict):
        properties = error.schema.get("properties") or {}
        location["allowed_properties"] = _tokens(sorted(properties))
        location["extra_property_count"] = len(set(error.instance) - set(properties))
    elif keyword == "enum" and isinstance(value, list):
        location["allowed_values"] = _tokens(value)
    elif keyword == "const":
        # A discriminator that matched no alternative is corrected against every alternative.
        name = schema_path[-2] if len(schema_path) > 1 else None
        siblings = [
            (alternative.get("properties") or {}).get(name, {}).get("const")
            for alternative in alternatives or () if isinstance(alternative, dict)
        ]
        location["allowed_values"] = _tokens([item for item in siblings if isinstance(item, str)] or [value])
    elif keyword == "type":
        expected = value if isinstance(value, str) else None
        if _token(expected):
            location["expected_type"] = expected
    elif keyword in ("minItems", "maxItems", "minLength", "maxLength", "minimum", "maximum"):
        if isinstance(value, int) and not isinstance(value, bool):
            location["schema_limit"] = value
    return location
