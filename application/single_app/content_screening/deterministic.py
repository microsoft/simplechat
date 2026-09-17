# deterministic.py
"""Complete, deadline-bound deterministic inspection of canonical content units.

Matching is unit-local: it never joins unrelated pages, sheets, or transcripts.
Every admitted unit is searched in full, so anchors, lookarounds, long matches,
Unicode offsets, and the final tail retain their original semantics. Overlapping
matches within a unit are supported. Aggregate input limits reject, not truncate,
oversized requests. Evidence is a bounded prefix of the exact matched span.
"""

import time

import regex

from .contracts import (
    DetectorResult,
    Finding,
    SCHEMA_VERSION,
    ScreeningError,
    content_fingerprint,
    hash_payload,
    normalize_units,
)
from .policies import compile_regex, normalize_limits, normalize_rules


MAX_EVIDENCE_CHARACTERS = 512
_PII_PATTERNS = {
    "email": (
        r"(?<![\w.!#$%&'*+/=?^`{|}~-])"
        r"[\p{L}\p{N}!#$%&'*+/=?^_`{|}~-]+"
        r"(?:\.[\p{L}\p{N}!#$%&'*+/=?^_`{|}~-]+)*"
        r"@(?:[\p{L}\p{N}](?:[\p{L}\p{N}-]{0,61}[\p{L}\p{N}])?\.)+"
        r"[\p{L}]{2,63}(?![\w-])"
    ),
    "phone": (
        r"(?<![\w+])(?:"
        r"\+[1-9](?:[ .()-]{0,3}[0-9]){7,14}"
        r"|(?:1[ .-]?)?(?:\([2-9][0-9]{2}\)|[2-9][0-9]{2})"
        r"[ .-]?[2-9][0-9]{2}[ .-]?[0-9]{4}"
        r")(?:[ \t]*(?:x|ext\.?)[ \t]*[0-9]{1,6})?(?![0-9])"
    ),
    "us_ssn": (
        r"(?<![0-9])(?!000|666|9[0-9]{2})[0-9]{3}"
        r"(?P<separator>[- ]?)(?!00)[0-9]{2}(?P=separator)(?!0000)[0-9]{4}(?![0-9])"
    ),
    "credit_card": r"(?<![0-9])[0-9](?:[ -]?[0-9]){12,18}(?![ -]?[0-9])",
}
_REASONS = {
    "email": "An email-address pattern was found; review its context.",
    "phone": "A phone-number pattern was found; locale and context require review.",
    "us_ssn": "A US Social Security number pattern was found; review its context.",
    "credit_card": "A payment-card pattern with a valid Luhn checksum was found.",
    "regex": "This span matches a configured regular-expression rule.",
    "literal": "This span matches a configured literal value.",
}


class _InspectionLimit(Exception):
    def __init__(self, code):
        self.code = code


def _luhn_valid(value):
    digits = [int(char) for char in value if "0" <= char <= "9"]
    if not 13 <= len(digits) <= 19 or len(set(digits)) == 1 or digits[0] == 0:
        return False
    total = 0
    for index, digit in enumerate(reversed(digits)):
        if index % 2:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _patterns_for_rule(rule):
    if rule["type"] == "pii":
        return [regex.compile(_PII_PATTERNS[rule["pii_type"]], regex.VERSION1 | regex.IGNORECASE)]
    if rule["type"] == "regex":
        return [compile_regex(
            rule["pattern"], case_sensitive=rule["case_sensitive"], whole_word=rule["whole_word"],
        )]
    flags = regex.VERSION1
    if not rule["case_sensitive"]:
        flags |= regex.IGNORECASE | regex.FULLCASE
    patterns = []
    for value in rule["values"]:
        pattern = regex.escape(value)
        if rule["whole_word"]:
            pattern = f"(?<!\\w)(?:{pattern})(?!\\w)"
        patterns.append(regex.compile(pattern, flags))
    return patterns


def deterministic_window_ids(units, rules):
    """Return the exact required rule/unit work identifiers for coverage checks."""
    return [
        hash_payload({"unit_id": unit.unit_id, "rule_id": rule["id"]})
        for unit in units for rule in rules if rule["enabled"]
    ]


def _remaining_timeout(deadline, regex_timeout):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _InspectionLimit("screening_runtime_limit")
    return min(remaining, regex_timeout)


def _notify(on_progress, result):
    if on_progress is not None:
        if on_progress({
            "detector": "deterministic",
            "status": "scanning" if result.status == "incomplete" and result.error_code is None else result.status,
            "required_units": result.required_units, "completed_units": result.completed_units,
            "required_windows": result.required_windows, "completed_windows": result.completed_windows,
        }) is False:
            raise _InspectionLimit("screening_cancelled")


def evaluate_deterministic_units(units, rules, *, limits=None, on_progress=None):
    """Inspect all required pairs; False progress responses cancel, retaining findings."""
    started = time.monotonic()
    result = DetectorResult("incomplete")
    try:
        limits = normalize_limits({} if limits is None else limits)
        if isinstance(units, (list, tuple)):
            result.required_units = len(units)
            if len(units) > limits["max_units"]:
                raise _InspectionLimit("screening_unit_limit")
        units = normalize_units(units)
        result.required_units = len(units)
        effective_rules = isinstance(rules, list) and any(
            isinstance(rule, dict) and ("origin" in rule or "required" in rule) for rule in rules
        )
        rules = [rule for rule in normalize_rules(rules, effective=effective_rules) if rule["enabled"]]
        result.required_windows = len(units) * len(rules)
        if not rules:
            result.status = "error"
            result.error_code = "screening_no_deterministic_checks"
            return result
        total_characters = sum(len(unit.text) for unit in units)
        result.usage = {
            "characters_total": total_characters,
            "coverage": {
                "schema_version": SCHEMA_VERSION,
                "content_fingerprint": content_fingerprint(units),
                "unit_ids": [], "window_ids": [], "rule_ids": [rule["id"] for rule in rules],
            },
        }
        if total_characters > limits["max_total_characters"]:
            raise _InspectionLimit("screening_character_limit")
        if result.required_windows > limits["max_windows"]:
            raise _InspectionLimit("screening_window_limit")
        deadline = started + limits["max_runtime_seconds"]
        patterns = {rule["id"]: _patterns_for_rule(rule) for rule in rules}
        seen = set()
        _notify(on_progress, result)
        for unit in units:
            for rule in rules:
                enclosing_pii_end = -1
                for pattern in patterns[rule["id"]]:
                    timeout = _remaining_timeout(deadline, limits["regex_timeout_seconds"])
                    for match in pattern.finditer(unit.text, overlapped=True, timeout=timeout, concurrent=True):
                        _remaining_timeout(deadline, limits["regex_timeout_seconds"])
                        start, end = match.span()
                        if start == end:
                            result.status = "error"
                            result.error_code = "screening_regex_empty_match"
                            return result
                        if rule["type"] == "pii":
                            if end <= enclosing_pii_end:
                                continue
                            if rule["pii_type"] == "credit_card" and not _luhn_valid(unit.text[start:end]):
                                continue
                            enclosing_pii_end = end
                        key = (rule["id"], unit.unit_id, start, end)
                        if key in seen:
                            continue
                        if len(result.findings) >= limits["max_findings"]:
                            raise _InspectionLimit("screening_findings_limit")
                        seen.add(key)
                        result.findings.append(Finding(
                            rule_id=rule["id"], unit_id=unit.unit_id,
                            category=rule["category"], severity=rule["severity"],
                            reason=_REASONS[rule.get("pii_type", rule["type"])],
                            start=start, end=end,
                            evidence=unit.text[start:min(end, start + MAX_EVIDENCE_CHARACTERS)],
                        ))
                    _remaining_timeout(deadline, limits["regex_timeout_seconds"])
                result.completed_windows += 1
                result.usage["coverage"]["window_ids"].append(
                    hash_payload({"unit_id": unit.unit_id, "rule_id": rule["id"]})
                )
            result.completed_units += 1
            result.usage["coverage"]["unit_ids"].append(unit.unit_id)
            _notify(on_progress, result)
            _remaining_timeout(deadline, limits["regex_timeout_seconds"])
        result.status = "findings" if result.findings else "pass"
        _notify(on_progress, result)
        _remaining_timeout(deadline, limits["regex_timeout_seconds"])
    except _InspectionLimit as exc:
        result.status = "incomplete"
        result.error_code = exc.code
    except TimeoutError:
        result.status = "incomplete"
        result.error_code = "screening_regex_timeout"
    except ScreeningError as exc:
        result.status = "error"
        result.error_code = exc.code
    except (regex.error, OverflowError, RecursionError):
        result.status = "error"
        result.error_code = "screening_regex_invalid"
    except Exception:
        result.status = "error"
        result.error_code = "screening_deterministic_failed"
    return result
