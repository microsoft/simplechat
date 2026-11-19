# support_export_privacy.py
"""Complete structured support-data redaction without settings or Azure bootstrap."""

import copy
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
from collections import Counter
from urllib.parse import unquote

import regex

from content_screening.contracts import ContentUnit
from content_screening.deterministic import evaluate_deterministic_units
from content_screening.policies import STARTER_RULE_TEMPLATES
from functions_appinsights import AUTHORIZATION_VALUE_RE, SECRET_ASSIGNMENT_RE, _is_sensitive_log_key
from support_export_contracts import AI_TOKEN_BUDGET, check_size, fail


SECRET_TEXT = regex.compile(
    r"""(?ix)
    (?P<assignment>["']?(?:api[-_]?key|accountkey|access[-_]?token|client[-_]?secret|
    connection[-_]?string|password|passwd|pwd|secret|subscription[-_]?key|token|
    authorization|cookie|sig|signature)["']?\s*[:=]\s*)
    (?:"[^"]*"|'[^']*'|[^\s&,;]+)
    """
)
PRIVATE_KEY = regex.compile(
    r"-----BEGIN (?:[A-Z ]{0,30})PRIVATE KEY-----.*?-----END (?:[A-Z ]{0,30})PRIVATE KEY-----",
    regex.DOTALL,
)
TOKEN = regex.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{30,255}|github_pat_[A-Za-z0-9_]{30,255}|"
    r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b"
)
IP_CANDIDATE = regex.compile(r"(?<![\w:])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![\w.])|(?<!\w)[0-9A-Fa-f:]*:[0-9A-Fa-f:]+(?!\w)")
GUID = re.compile(r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b")
HASH = re.compile(r"\b[0-9a-f]{64}\b")
RULES = [copy.deepcopy(STARTER_RULE_TEMPLATES[key]) for key in ("email", "phone", "us_ssn", "credit_card")]
REDACTED = "[REDACTED_CREDENTIAL]"


def scrub_credentials(text):
    """Preserve complete multiline diagnostic text, unlike the bounded log formatter."""
    for _ in range(2):
        decoded = unquote(text)
        if decoded == text or not (
            SECRET_TEXT.search(decoded, timeout=0.1) or AUTHORIZATION_VALUE_RE.search(decoded)
            or TOKEN.search(decoded, timeout=0.1)
        ):
            break
        text = decoded
    text = PRIVATE_KEY.sub(REDACTED, text, timeout=0.1)
    text = TOKEN.sub(REDACTED, text, timeout=0.1)
    text = SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}={REDACTED}", text)
    text = AUTHORIZATION_VALUE_RE.sub(lambda match: f"{match.group(1)} {REDACTED}", text)
    return SECRET_TEXT.sub(lambda match: match.group("assignment") + REDACTED, text, timeout=0.1)


def _credential_field(key, value):
    normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
    numeric = value is None or type(value) in (bool, int, float)
    if numeric and (
        normalized.endswith(("present", "count", "length", "configured"))
        or normalized.removeprefix("sc") in (
            "prompttokens", "completiontokens", "totaltokens", "inputtokens", "outputtokens", "budgetedtokens",
            "credentialfields",
        )
    ):
        return False
    return _is_sensitive_log_key(key)


IDENTIFIER_KEYS = frozenset({
    "id", "userid", "adminuserid", "requesterid", "ownerid", "participantid", "memberid",
    "conversationid", "documentid", "groupid", "publicworkspaceid", "scopeid", "sourceid",
    "addedbyuserid", "changedbyuserid", "runid", "turnid", "stepid", "jobid", "messageid",
    "requestid", "operationid", "parentid", "instanceid",
})
PII_KEYS = {
    "email": "email", "emailaddress": "email", "useremail": "email",
    "phone": "phone", "phonenumber": "phone", "mobilephone": "phone",
    "ssn": "us-ssn", "socialsecuritynumber": "us-ssn",
    "creditcard": "credit-card", "cardnumber": "credit-card",
    "bankaccountnumber": "financial", "passportnumber": "national-id",
    "displayname": "name", "fullname": "name", "firstname": "name", "lastname": "name",
    "username": "name", "membername": "name", "streetaddress": "address", "postaladdress": "address",
    "dateofbirth": "birth-date",
}


def _identifier_key(key):
    normalized = re.sub(r"[^a-z0-9]", "", str(key).lower().removeprefix("sc_"))
    if normalized in PII_KEYS:
        return "pii:" + PII_KEYS[normalized]
    return normalized if normalized.removesuffix("hash") in IDENTIFIER_KEYS else None


def map_text(value, transform, on_sensitive=None, on_identifier=None):
    if isinstance(value, str):
        return transform(value)
    if isinstance(value, list):
        return [map_text(item, transform, on_sensitive, on_identifier) for item in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            safe_key = transform(str(key))
            if safe_key in result:
                fail("privacy_key_collision", "Privacy processing would lose a diagnostic field. Narrow the export.", 422)
            if _credential_field(key, item):
                if on_sensitive is not None and item != REDACTED:
                    on_sensitive()
                result[safe_key] = REDACTED
            elif on_identifier is not None and _identifier_key(key) and type(item) in (str, int):
                result[safe_key] = on_identifier(_identifier_key(key), str(item)) if str(item) else item
            else:
                result[safe_key] = map_text(item, transform, on_sensitive, on_identifier)
        return result
    if value is None or type(value) in (bool, int, float):
        return value
    fail("invalid_log_value", "A source returned an unsupported diagnostic value.", 422)


def text_counts(value):
    fields = Counter()

    def remember(text):
        if text.strip():
            fields[text] += 1
        return text

    map_text(value, remember)
    return fields


class BundleRedactor:
    """Keep aliases stable across logs and approved snapshots in one bundle only."""

    def __init__(self, salt=None):
        self.salt = bytes.fromhex(salt) if salt else secrets.token_bytes(32)
        self.counts = Counter()
        self.fields_checked = 0

    def alias(self, category, value):
        opaque = hmac.new(self.salt, value.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
        opaque = "_".join(opaque[index:index + 4] for index in range(0, len(opaque), 4))
        return f"[{category.upper()}_{opaque}]"

    def credentials(self, text):
        cleaned = scrub_credentials(text)
        if cleaned != text:
            self.counts["credential_fields"] += 1
        return cleaned

    def deterministic(self, value, *, identifiers=(), progress=None):
        known = {
            item: self.alias("identifier", item)
            for item in sorted(set(identifiers), key=len, reverse=True) if item
        }
        known_hashes = {
            hashlib.sha256(item.encode("utf-8")).hexdigest(): replacement
            for item, replacement in known.items()
        }
        def seed_hashes(item):
            if isinstance(item, dict):
                for key, child in item.items():
                    normalized = _identifier_key(key)
                    if normalized and not normalized.startswith("pii:") and not normalized.endswith("hash") and type(child) in (str, int):
                        original = str(child)
                        known_hashes[hashlib.sha256(original.encode("utf-8")).hexdigest()] = self.alias("identifier", original)
                    elif isinstance(child, (dict, list)):
                        seed_hashes(child)
            elif isinstance(item, list):
                for child in item:
                    seed_hashes(child)
        seed_hashes(value)
        known_pattern = re.compile(
            r"(?<![\w.:@-])(?:" + "|".join(re.escape(item) for item in known) + r")(?![\w.:@-])"
        ) if known else None

        def replacement(category, original, references=1):
            self.counts[category] += references
            return self.alias(category, original)

        def identifier_value(key, original, references=1):
            category = key[4:] if key.startswith("pii:") else ("correlation" if key.endswith("hash") else "identifier")
            self.counts[category] += references
            return (known_hashes.get(original) if not key.startswith("pii:") else None) or self.alias(category, original)

        def clean_identifiers(text, references):
            if known_pattern:
                def replace_known(match):
                    self.counts["identifier"] += references
                    return known[match.group()]
                text = known_pattern.sub(replace_known, text)
            text = GUID.sub(lambda match: replacement("identifier", match.group(), references), text)
            text = HASH.sub(lambda match: identifier_value("hash", match.group(), references), text)

            def replace_ip(match):
                try:
                    ipaddress.ip_address(match.group())
                except ValueError:
                    return match.group()
                return replacement("ip", match.group(), references)

            return IP_CANDIDATE.sub(replace_ip, text, timeout=0.1)

        try:
            def sensitive_field():
                self.counts["credential_fields"] += 1
            prepared = map_text(value, self.credentials, sensitive_field, identifier_value)
            fields = text_counts(prepared)
            replacements = {}
            items = list(fields)
            for offset in range(0, len(items), 100):
                if progress:
                    progress()
                batch = items[offset:offset + 100]
                units = [ContentUnit(str(index), text) for index, text in enumerate(batch)]
                result = evaluate_deterministic_units(units, RULES, limits={
                    "max_units": 100, "max_windows": 400, "max_total_characters": 20000000,
                    "max_findings": 1000, "max_runtime_seconds": 30,
                })
                if result.status not in ("pass", "findings"):
                    fail("privacy_incomplete", "Deterministic privacy inspection did not complete. Narrow the export.", 422)
                by_unit = {}
                for finding in result.findings:
                    by_unit.setdefault(int(finding.unit_id), []).append(finding)
                for index, original in enumerate(batch):
                    spans = sorted(by_unit.get(index, []), key=lambda finding: (finding.start, -finding.end))
                    merged = []
                    for finding in spans:
                        if merged and finding.start <= merged[-1][1]:
                            merged[-1][1] = max(merged[-1][1], finding.end)
                        else:
                            merged.append([finding.start, finding.end, finding.rule_id])
                    text = original
                    for start, end, category in reversed(merged):
                        self.counts[category] += fields[original]
                        text = text[:start] + self.alias(category, original[start:end]) + text[end:]
                    replacements[original] = clean_identifiers(text, fields[original])
                self.fields_checked += sum(fields[text] for text in batch)
            return map_text(prepared, lambda text: replacements.get(text, text))
        except TimeoutError:
            fail("privacy_timeout", "Credential or PII inspection timed out. Narrow the export.", 422)

    def inspect_ai(self, value, *, selection, inspect, progress=None):
        """The supplied adapter uses the existing grounded, isolated model detector."""
        fields = text_counts(value)
        texts = list(fields)
        if not texts:
            return value, {"status": "complete", "input_tokens": 0}
        units, locations = [], []
        packed, ranges = "", []
        for index, text in enumerate(texts):
            header = f"\nFIELD_{index}\n"
            if packed and len(packed) + len(header) + len(text) > 12000:
                units.append(ContentUnit(str(len(units)), packed))
                locations.append(ranges)
                packed, ranges = "", []
            start = len(packed) + len(header)
            packed += header + text
            ranges.append((start, len(packed), index))
        if packed:
            units.append(ContentUnit(str(len(units)), packed))
            locations.append(ranges)
        result = inspect(units, selection, progress, AI_TOKEN_BUDGET)
        if result.status not in ("pass", "findings"):
            fail("ai_incomplete", "AI privacy inspection did not complete. Narrow the export or create a deterministic-only export.", 422)
        if result.completed_units != len(units) or result.completed_windows != result.required_windows:
            fail("ai_incomplete", "AI privacy inspection did not cover the complete bundle.", 422)
        by_unit = {}
        for finding in result.findings:
            try:
                unit_index = int(finding.unit_id)
                if not 0 <= unit_index < len(units):
                    raise IndexError()
                text = units[unit_index].text
            except (ValueError, IndexError):
                fail("ai_invalid_span", "AI privacy inspection returned invalid references.", 422)
            if (
                type(finding.start) is not int or type(finding.end) is not int
                or not 0 <= finding.start < finding.end <= len(text)
                or text[finding.start:finding.end] != finding.evidence
            ):
                fail("ai_invalid_span", "AI privacy inspection needs manual span review. The export was not released.", 422)
            containing = [
                (start, end, index) for start, end, index in locations[unit_index]
                if start <= finding.start < finding.end <= end
            ]
            if len(containing) != 1:
                fail("ai_invalid_span", "AI privacy inspection crossed field boundaries. The export was not released.", 422)
            start, _, index = containing[0]
            by_unit.setdefault(index, []).append((finding.start - start, finding.end - start))
        replacements = {}
        for index, spans in by_unit.items():
            merged = []
            for start, end in sorted(spans):
                if merged and start <= merged[-1][1]:
                    merged[-1][1] = max(end, merged[-1][1])
                else:
                    merged.append([start, end])
            text = texts[index]
            for start, end in reversed(merged):
                self.counts["ai_sensitive"] += fields[texts[index]]
                text = text[:start] + self.alias("ai_sensitive", texts[index][start:end]) + text[end:]
            replacements[texts[index]] = text
        redacted = map_text(value, lambda text: self.credentials(replacements.get(text, text)))
        return redacted, {
            "status": "complete", "fields_checked": sum(fields.values()),
            "input_tokens": result.usage.get("input_tokens", 0),
            "budgeted_tokens": result.usage.get("budgeted_tokens", 0),
            "model_selection": dict(selection),
        }

    def report(self, ai=None):
        return {
            "deterministic": "complete", "fields_checked": self.fields_checked,
            "redaction_counts": dict(self.counts), "ai": ai or {"status": "not_requested"},
            "limitations": "Best-effort privacy checks are not a guarantee of anonymity. Review before sharing.",
        }


def encoded_json(value):
    data = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    check_size(0, len(data))
    return data
