# admin_settings_int_utils.py


def safe_int_with_source(raw_value, fallback_value, hard_default=0):
    """
    Safely parse an integer value using raw input, fallback, then hard default.

    Args:
        raw_value (object): Primary value to parse.
        fallback_value (object): Secondary value to parse when raw parsing fails.
        hard_default (int): Final integer default when both values are invalid.

    Returns:
        tuple[int, str]: Parsed integer and parse source (`raw`, `fallback`, `hard_default`).
    """
    try:
        return int(raw_value), "raw"
    except (TypeError, ValueError):
        try:
            return int(fallback_value), "fallback"
        except (TypeError, ValueError):
            return int(hard_default), "hard_default"


def safe_int(raw_value, fallback_value, hard_default=0):
    """
    Safely parse an integer using raw input, fallback, then hard default.

    Args:
        raw_value (object): Primary value to parse.
        fallback_value (object): Secondary value to parse when raw parsing fails.
        hard_default (int): Final integer default when both values are invalid.

    Returns:
        int: Parsed integer value.
    """
    parsed_value, _ = safe_int_with_source(raw_value, fallback_value, hard_default)
    return parsed_value
