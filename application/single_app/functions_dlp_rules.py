# functions_dlp_rules.py

import copy
import hashlib
from collections import OrderedDict

import regex


CONFIDENCE_ORDER = {"low": 1, "medium": 2, "high": 3}
ALLOWED_FLAGS = {"IGNORECASE": regex.IGNORECASE, "MULTILINE": regex.MULTILINE}
ALLOWED_VALIDATORS = {"none", "luhn"}
ALLOWED_SURFACES = {"web_search", "upload"}
MAX_RULES = 50
MAX_PATTERN_LENGTH = 512
MAX_REPLACEMENT_LENGTH = 80
MAX_KEYWORDS = 25
MAX_KEYWORD_LENGTH = 80
MAX_WINDOW_CHARS = 256
REGEX_TIMEOUT_SECONDS = 0.05


DEFAULT_DLP_REGEX_RULES = [
    {
        "id": "us_ssn",
        "label": "U.S. Social Security Number",
        "entity_type": "US_SSN",
        "enabled": True,
        "pattern": r"(?<!\d)(?!000|666|9\d{2})(\d{3})[- ](?!00)(\d{2})[- ](?!0000)(\d{4})(?!\d)",
        "replacement": "[REDACTED_US_SSN]",
        "surfaces": ["web_search", "upload"],
        "flags": [],
        "validator": "none",
        "confidence": {
            "regex_only": "medium",
            "with_keywords": "high",
            "keywords": ["ssn", "social security", "social"],
            "window_chars": 48,
            "minimum": "medium",
        },
    },
    {
        "id": "credit_card",
        "label": "Credit Card Number",
        "entity_type": "CREDIT_CARD",
        "enabled": True,
        "pattern": r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)",
        "replacement": "[REDACTED_CREDIT_CARD]",
        "surfaces": ["web_search", "upload"],
        "flags": [],
        "validator": "luhn",
        "confidence": {
            "regex_only": "medium",
            "with_keywords": "high",
            "keywords": ["card", "credit card", "visa", "mastercard", "amex", "pan"],
            "window_chars": 48,
            "minimum": "medium",
        },
    },
]


def get_default_dlp_regex_rules():
    return copy.deepcopy(DEFAULT_DLP_REGEX_RULES)


def _as_string(value, fallback=""):
    return str(value if value is not None else fallback).strip()


def _normalize_confidence(value, fallback):
    text = _as_string(value, fallback).lower()
    return text if text in CONFIDENCE_ORDER else fallback


def _normalize_flags(flags):
    normalized = []
    for flag in flags if isinstance(flags, list) else []:
        text = _as_string(flag).upper()
        if text in ALLOWED_FLAGS and text not in normalized:
            normalized.append(text)
    return normalized


def _compile_flags(flags):
    compiled_flags = 0
    for flag in flags:
        compiled_flags |= ALLOWED_FLAGS.get(flag, 0)
    return compiled_flags


def _luhn_valid(candidate):
    digits = [int(char) for char in regex.sub(r"\D", "", candidate or "")]
    if len(digits) < 13 or len(digits) > 19:
        return False

    checksum = 0
    reverse_digits = list(reversed(digits))
    for index, digit in enumerate(reverse_digits):
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def _validator_allows(value, validator):
    if validator == "luhn":
        return _luhn_valid(value)
    return True


def _safe_rule_id(value, index):
    candidate = _as_string(value, f"rule_{index + 1}").lower()
    candidate = regex.sub(r"[^a-z0-9_\-]+", "_", candidate).strip("_-")
    return candidate or f"rule_{index + 1}"


def validate_dlp_regex_rules(rules):
    normalized_rules = []
    errors = []

    if rules is None:
        return get_default_dlp_regex_rules(), []
    if not isinstance(rules, list):
        return [], ["dlp_regex_rules must be a list."]
    if len(rules) > MAX_RULES:
        return [], [f"dlp_regex_rules cannot contain more than {MAX_RULES} rules."]

    seen_ids = set()
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            errors.append(f"Rule {index + 1} must be an object.")
            continue

        rule_id = _safe_rule_id(rule.get("id"), index)
        if rule_id in seen_ids:
            errors.append(f"Rule {rule_id} has a duplicate id.")
            continue
        seen_ids.add(rule_id)

        pattern = _as_string(rule.get("pattern"))
        if not pattern:
            errors.append(f"Rule {rule_id} requires a regex pattern.")
            continue
        if len(pattern) > MAX_PATTERN_LENGTH:
            errors.append(f"Rule {rule_id} pattern exceeds {MAX_PATTERN_LENGTH} characters.")
            continue

        flags = _normalize_flags(rule.get("flags", []))
        try:
            regex.compile(pattern, _compile_flags(flags))
        except Exception as exc:
            errors.append(f"Rule {rule_id} regex does not compile: {type(exc).__name__}.")
            continue

        surfaces = [
            _as_string(surface).lower()
            for surface in rule.get("surfaces", ["web_search", "upload"])
            if _as_string(surface).lower() in ALLOWED_SURFACES
        ]
        if not surfaces:
            errors.append(f"Rule {rule_id} must target web_search, upload, or both.")
            continue

        validator = _as_string(rule.get("validator", "none")).lower()
        if validator not in ALLOWED_VALIDATORS:
            errors.append(f"Rule {rule_id} uses unsupported validator {validator}.")
            continue

        confidence = rule.get("confidence", {})
        if not isinstance(confidence, dict):
            confidence = {}

        keywords = []
        for keyword in confidence.get("keywords", []):
            keyword_text = _as_string(keyword).lower()
            if keyword_text and len(keyword_text) <= MAX_KEYWORD_LENGTH and keyword_text not in keywords:
                keywords.append(keyword_text)
            if len(keywords) >= MAX_KEYWORDS:
                break

        try:
            window_chars = int(confidence.get("window_chars", 48))
        except (TypeError, ValueError):
            window_chars = 48
        window_chars = max(0, min(window_chars, MAX_WINDOW_CHARS))

        entity_type = _as_string(rule.get("entity_type"), rule_id.upper()).upper()
        replacement = _as_string(rule.get("replacement"), f"[REDACTED_{entity_type}]")
        if len(replacement) > MAX_REPLACEMENT_LENGTH:
            replacement = replacement[:MAX_REPLACEMENT_LENGTH]

        normalized_rules.append(
            {
                "id": rule_id,
                "label": _as_string(rule.get("label"), entity_type),
                "entity_type": entity_type,
                "enabled": bool(rule.get("enabled", True)),
                "pattern": pattern,
                "replacement": replacement,
                "surfaces": surfaces,
                "flags": flags,
                "validator": validator,
                "confidence": {
                    "regex_only": _normalize_confidence(confidence.get("regex_only"), "medium"),
                    "with_keywords": _normalize_confidence(confidence.get("with_keywords"), "high"),
                    "keywords": keywords,
                    "window_chars": window_chars,
                    "minimum": _normalize_confidence(confidence.get("minimum"), "medium"),
                },
            }
        )

    return normalized_rules, errors


def get_effective_dlp_regex_rules(settings):
    normalized_rules, errors = validate_dlp_regex_rules((settings or {}).get("dlp_regex_rules"))
    if errors:
        default_rules, _ = validate_dlp_regex_rules(get_default_dlp_regex_rules())
        return default_rules, errors
    return normalized_rules, []


def _confidence_for_match(source_text, start, end, confidence):
    keywords = confidence.get("keywords", [])
    window_chars = int(confidence.get("window_chars", 0) or 0)
    if not keywords or window_chars <= 0:
        return confidence.get("regex_only", "medium")

    left = max(0, start - window_chars)
    right = min(len(source_text), end + window_chars)
    window = source_text[left:right].lower()
    if any(keyword in window for keyword in keywords):
        return confidence.get("with_keywords", "high")
    return confidence.get("regex_only", "medium")


def _confidence_allows(actual, minimum):
    return CONFIDENCE_ORDER.get(actual, 0) >= CONFIDENCE_ORDER.get(minimum, 2)


def _merge_confidence(existing, candidate):
    return max(existing, candidate, key=lambda item: CONFIDENCE_ORDER.get(item, 0))


def scan_text_with_dlp_regex_rules(text, rules, surface):
    source_text = str(text or "")
    redactions = []
    counts = OrderedDict()
    confidence_by_entity = {}

    for rule in rules:
        if not rule.get("enabled", True):
            continue
        if surface not in rule.get("surfaces", []):
            continue

        compiled = regex.compile(rule["pattern"], _compile_flags(rule.get("flags", [])))
        try:
            rule_matches = list(compiled.finditer(source_text, timeout=REGEX_TIMEOUT_SECONDS))
        except TimeoutError:
            raise RuntimeError(f"DLP regex rule timed out: {rule['id']}")

        for match in rule_matches:
            value = match.group(0)
            if not _validator_allows(value, rule.get("validator", "none")):
                continue

            confidence = _confidence_for_match(source_text, match.start(), match.end(), rule["confidence"])
            if not _confidence_allows(confidence, rule["confidence"].get("minimum", "medium")):
                continue

            entity_type = rule["entity_type"]
            counts[entity_type] = counts.get(entity_type, 0) + 1
            confidence_by_entity[entity_type] = _merge_confidence(
                confidence_by_entity.get(entity_type, "low"),
                confidence,
            )
            redactions.append((match.start(), match.end(), rule["replacement"]))

    redactions.sort(key=lambda item: item[0])
    redacted_parts = []
    cursor = 0
    for start, end, replacement in redactions:
        if start < cursor:
            continue
        redacted_parts.append(source_text[cursor:start])
        redacted_parts.append(replacement)
        cursor = end
    redacted_parts.append(source_text[cursor:])

    matches = [
        {"entity_type": entity_type, "count": count, "confidence": confidence_by_entity.get(entity_type, "medium")}
        for entity_type, count in counts.items()
    ]
    metadata = {
        "rule_count": len(rules),
        "match_hash": hashlib.sha256("|".join(counts.keys()).encode("utf-8")).hexdigest()[:16] if counts else "",
    }
    return "".join(redacted_parts), dict(counts), matches, metadata
