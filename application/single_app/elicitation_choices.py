# elicitation_choices.py
"""Bootstrap-free presentation hints for open questions, never authorization choices."""

MAX_CUSTOM_ANSWER_LENGTH = 4000


def normalize_choice_hint(rules, hint):
    """Keep suggestions outside JSON Schema enums so custom answers remain honest."""
    value_rules = rules.get("items", {}) if rules["type"] == "array" else rules
    choices = hint.get("choices")
    allow_custom = hint.get("allow_custom", "enum" not in value_rules)
    if (
        value_rules.get("type") != "string"
        or type(allow_custom) is not bool
        or (allow_custom and "enum" in value_rules)
        or (not allow_custom and "enum" not in value_rules)
        or ("enum" in value_rules and any(not isinstance(value, str) for value in value_rules["enum"]))
        or type(choices) is not list or not 1 <= len(choices) <= 40
    ):
        raise ValueError("Invalid choice question.")
    normalized, seen = [], set()
    for choice in choices:
        choice = {"value": choice} if isinstance(choice, str) else choice
        if type(choice) is not dict or set(choice) - {"value", "label", "description"}:
            raise ValueError("Invalid question choice.")
        value = choice.get("value")
        value = value.strip() if isinstance(value, str) else value
        label = choice.get("label", value)
        description = choice.get("description", "")
        if (
            not isinstance(value, str) or not value.strip() or len(value) > 500
            or not isinstance(label, str) or not label.strip() or len(label) > 200
            or not isinstance(description, str) or len(description) > 500
            or value in seen
            or ("enum" in value_rules and value not in value_rules["enum"])
        ):
            raise ValueError("Invalid question choice.")
        seen.add(value)
        normalized.append({"value": value, "label": label, "description": description})
    if "enum" in value_rules and set(value_rules["enum"]) != seen:
        raise ValueError("Closed question hints must preserve every offered value.")
    return {"input": "choices", "choices": normalized, "allow_custom": allow_custom}


def choice_answer_errors(elicitation, content):
    errors = []
    for name, hint in ((elicitation.get("ui_hints") or {}).get("fields") or {}).items():
        if hint.get("input") != "choices" or name not in content:
            continue
        allowed = {choice["value"] for choice in hint["choices"]}
        values = content[name] if isinstance(content[name], list) else [content[name]]
        if any(not isinstance(value, str) or len(value) > MAX_CUSTOM_ANSWER_LENGTH for value in values):
            errors.append(f"'{name}' has an invalid or overly long answer.")
        elif not hint["allow_custom"] and any(value not in allowed for value in values):
            errors.append(f"'{name}' is not one of the offered choices.")
    return errors
