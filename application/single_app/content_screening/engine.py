# engine.py
"""Fail-closed orchestration of independent required content-screening checks.

This module makes no storage or authorization decisions. In particular, a clean
result is not permission to erase a previously persisted human-review hold.
Injected evaluators implement the same trusted DetectorResult adapter contract
as the production model evaluator; raw provider responses are not accepted here.
"""

import math
import time
from copy import deepcopy

from .contracts import (
    ContentUnit,
    DetectorResult,
    Finding,
    InspectionResult,
    SCHEMA_VERSION,
    Subject,
    content_fingerprint,
    hash_payload,
    normalize_units,
)
from .deterministic import deterministic_window_ids, evaluate_deterministic_units
from .policies import compose_policy, normalize_effective_policy


_USAGE_FIELDS = frozenset({
    "input_tokens", "output_tokens", "total_tokens", "requests", "reported_requests",
    "budgeted_tokens", "input_characters", "output_characters",
    "checkpoint_windows",
})
_SAFE_ERROR_CODES = frozenset({
    "screening_unit_limit", "screening_character_limit", "screening_window_limit",
    "screening_runtime_limit", "screening_findings_limit", "screening_regex_timeout",
    "screening_regex_invalid", "screening_regex_empty_match", "screening_deterministic_failed",
    "screening_detector_failed", "screening_detector_invalid", "screening_coverage_incomplete",
    "screening_model_failed", "screening_model_timeout", "screening_model_unavailable",
    "screening_model_invalid_response", "screening_model_refused", "screening_model_configuration",
    "screening_cancelled",
    "model_check_disabled", "model_invalid_input", "model_configuration_unavailable",
    "model_protocol_unsupported", "model_input_limit", "model_time_limit",
    "model_token_limit", "model_response_limit", "model_finding_limit",
    "model_timeout", "model_capacity_exhausted", "model_provider_error",
    "model_refused", "model_invalid_response", "model_invalid_evidence",
    "model_invalid_usage", "model_incomplete_response", "model_incomplete_coverage",
    "model_cancelled", "model_progress_error", "model_evaluation_error",
})
_CANCELLATION_CODES = frozenset({"screening_cancelled", "model_cancelled"})
_COVERAGE_FIELDS = frozenset({
    "schema_version", "content_fingerprint", "rule_ids", "unit_ids", "window_ids",
})


def _safe_failure(status, code, required_units, required_windows=0):
    return DetectorResult(
        status, required_units=required_units, required_windows=required_windows, error_code=code,
    )


def _grounded_finding(finding, unit_map, rule_map, source):
    if not isinstance(finding, Finding) or finding.source != source:
        return False
    if not isinstance(finding.unit_id, str) or not isinstance(finding.rule_id, str):
        return False
    unit, rule = unit_map.get(finding.unit_id), rule_map.get(finding.rule_id)
    if unit is None or rule is None:
        return False
    if finding.category != rule["category"] or finding.severity != rule["severity"]:
        return False
    if not isinstance(finding.reason, str) or not finding.reason.strip() or len(finding.reason) > 2000:
        return False
    if not isinstance(finding.evidence, str) or not finding.evidence or len(finding.evidence) > 64000:
        return False
    if finding.confidence is not None:
        if type(finding.confidence) not in (int, float) or not math.isfinite(finding.confidence) or not 0 <= finding.confidence <= 1:
            return False
    if finding.start is None and finding.end is None:
        return source == "model" and finding.evidence in unit.text
    if (
        type(finding.start) is not int or type(finding.end) is not int
        or not 0 <= finding.start < finding.end <= len(unit.text)
    ):
        return False
    if source == "model":
        return unit.text[finding.start:finding.end] == finding.evidence
    return (
        len(finding.evidence) <= finding.end - finding.start
        and unit.text[finding.start:finding.start + len(finding.evidence)] == finding.evidence
    )


def _model_window_requirements(units, check, limits):
    # Planning is pure; keep the model module unloaded for deterministic-only work.
    from .model import build_model_windows

    plan = build_model_windows(units, {**deepcopy(check), "limits": dict(limits)})
    if not isinstance(plan, list) or not 1 <= len(plan) <= limits["max_windows"]:
        return None
    unit_map = {unit.unit_id: unit for unit in units}
    ranges = {unit.unit_id: [] for unit in units}
    last_windows = {}
    window_ids = []
    for index, window in enumerate(plan):
        if not isinstance(window, dict) or set(window) != {"window_id", "unit_ranges"}:
            return None
        window_id = window["window_id"]
        if not isinstance(window_id, str) or not window_id:
            return None
        window_ids.append(window_id)
        if not isinstance(window["unit_ranges"], list) or not window["unit_ranges"]:
            return None
        seen_units = set()
        window_characters = 0
        for part in window["unit_ranges"]:
            if not isinstance(part, dict) or set(part) != {"unit_id", "start", "end"}:
                return None
            unit_id, start, end = part["unit_id"], part["start"], part["end"]
            if not isinstance(unit_id, str) or unit_id not in unit_map or unit_id in seen_units:
                return None
            unit = unit_map[unit_id]
            if (
                type(start) is not int or type(end) is not int
                or not 0 <= start <= end <= len(unit.text)
                or (start == end and unit.text)
            ):
                return None
            seen_units.add(unit_id)
            window_characters += end - start
            ranges[unit_id].append((start, end))
            last_windows[unit_id] = index
        if window_characters > check["max_characters"]:
            return None
    if len(set(window_ids)) != len(window_ids):
        return None
    for unit in units:
        if not ranges[unit.unit_id]:
            return None
        covered_end = 0
        for start, end in sorted(ranges[unit.unit_id]):
            if start > covered_end:
                return None
            covered_end = max(covered_end, end)
        if covered_end != len(unit.text):
            return None
    return window_ids, last_windows


def _valid_explicit_coverage(result, units, rules, source, limits):
    """Prove ordered source/window coverage, including every empty unit and tail."""
    try:
        coverage = result.usage.get("coverage")
        if not isinstance(coverage, dict) or set(coverage) != _COVERAGE_FIELDS:
            return False
        if type(coverage["schema_version"]) is not int or coverage["schema_version"] != SCHEMA_VERSION:
            return False
        if (
            coverage["content_fingerprint"] != content_fingerprint(units)
            or coverage["rule_ids"] != [rule["id"] for rule in rules]
            or result.required_units != len(units)
        ):
            return False
        unit_ids, window_ids = coverage["unit_ids"], coverage["window_ids"]
        if (
            not isinstance(unit_ids, list) or any(not isinstance(item, str) for item in unit_ids)
            or len(unit_ids) != result.completed_units or len(set(unit_ids)) != len(unit_ids)
            or not isinstance(window_ids, list) or any(not isinstance(item, str) or not item for item in window_ids)
            or len(window_ids) != result.completed_windows or len(set(window_ids)) != len(window_ids)
        ):
            return False
        if source == "deterministic":
            expected_windows = deterministic_window_ids(units, rules)
            last_windows = {
                unit.unit_id: (index + 1) * len(rules) - 1 for index, unit in enumerate(units)
            }
        else:
            expected = _model_window_requirements(units, rules[0], limits)
            if expected is None:
                return False
            expected_windows, last_windows = expected
        expected_units = [
            unit.unit_id for unit in units if last_windows[unit.unit_id] < result.completed_windows
        ]
        if (
            result.required_windows != len(expected_windows)
            or window_ids != expected_windows[:result.completed_windows]
            or unit_ids != expected_units
        ):
            return False
        if result.status in {"pass", "findings"}:
            return window_ids == expected_windows and unit_ids == [unit.unit_id for unit in units]
        return True
    except Exception:
        return False


def _validate_detector(result, units, rules, source, limits):
    """Keep valid findings even when an adapter's other output is contradictory."""
    expected_windows = len(units) * len(rules) if source == "deterministic" else 0
    if not isinstance(result, DetectorResult):
        return _safe_failure("error", "screening_detector_invalid", len(units), expected_windows)
    invalid = not isinstance(result.status, str) or result.status not in {"pass", "findings", "incomplete", "error"}
    counters = (result.required_units, result.completed_units, result.required_windows, result.completed_windows)
    valid_counters = all(type(value) is int and value >= 0 for value in counters)
    invalid = invalid or not valid_counters
    if valid_counters:
        invalid = invalid or result.completed_units > result.required_units or result.completed_windows > result.required_windows
    findings = []
    seen = set()
    if not isinstance(result.findings, list) or len(result.findings) > limits["max_findings"]:
        invalid = True
    else:
        unit_map = {unit.unit_id: unit for unit in units}
        rule_map = {rule["id"]: rule for rule in rules}
        for finding in result.findings:
            if not _grounded_finding(finding, unit_map, rule_map, source):
                invalid = True
                continue
            if finding.finding_id not in seen:
                findings.append(finding)
                seen.add(finding.finding_id)
    usage = result.usage if isinstance(result.usage, dict) else {}
    invalid = invalid or not isinstance(result.usage, dict)
    for key in _USAGE_FIELDS:
        if key in usage and (type(usage[key]) is not int or usage[key] < 0):
            invalid = True
    status = result.status if isinstance(result.status, str) else "error"
    error_code = result.error_code if isinstance(result.error_code, str) and result.error_code in _SAFE_ERROR_CODES else None
    coverage_valid = False
    if status in {"pass", "findings"}:
        invalid = (
            invalid or (status == "pass" and bool(result.findings))
            or (status == "findings" and not findings)
            or result.error_code is not None
        )
        if not invalid and (
            result.required_units != len(units)
            or result.completed_units != len(units)
            or result.required_windows < 1
            or result.completed_windows != result.required_windows
            or (source == "deterministic" and result.required_windows != expected_windows)
        ):
            status, error_code = "incomplete", "screening_coverage_incomplete"
    if not invalid and "coverage" in usage and result.required_windows <= limits["max_windows"]:
        coverage_valid = _valid_explicit_coverage(result, units, rules, source, limits)
    if not invalid and status in {"pass", "findings"} and not coverage_valid:
        status, error_code = "incomplete", "screening_coverage_incomplete"
    if valid_counters and result.required_windows > limits["max_windows"]:
        status, error_code = "incomplete", "screening_window_limit"
    if invalid:
        status, error_code = "error", "screening_detector_invalid"
    elif status == "error":
        error_code = error_code or "screening_detector_failed"
    elif status == "incomplete":
        error_code = error_code or "screening_coverage_incomplete"
    return DetectorResult(
        status, findings=findings,
        required_units=result.required_units if valid_counters else len(units),
        completed_units=result.completed_units if valid_counters else 0,
        required_windows=result.required_windows if valid_counters else expected_windows,
        completed_windows=result.completed_windows if valid_counters else 0,
        error_code=error_code,
        usage={
            **{key: value for key, value in usage.items() if key in _USAGE_FIELDS and type(value) is int and value >= 0},
            **({"coverage": deepcopy(usage["coverage"])} if coverage_valid else {}),
        },
    )


def _progress_callback(callback, detector_id):
    if callback is None:
        return None

    def report(progress):
        if not isinstance(progress, dict):
            raise ValueError("Invalid screening progress.")
        safe = {"detector": detector_id}
        for key in ("required_units", "completed_units", "required_windows", "completed_windows"):
            if key in progress and type(progress[key]) is int and progress[key] >= 0:
                safe[key] = progress[key]
        if progress.get("status") in ("pass", "findings", "incomplete", "error", "scanning"):
            safe["status"] = progress["status"]
        return callback(safe)

    return report


def _remaining_limits(limits, deadline):
    remaining = deadline - time.monotonic()
    # A smaller budget cannot satisfy the shared schema's one-millisecond minimum.
    if remaining < 0.001:
        return None
    return {**limits, "max_runtime_seconds": min(limits["max_runtime_seconds"], remaining)}


def inspect_content(subject, units, policy, *, model_evaluator=None, on_progress=None):
    """Union mandatory findings; a False progress response cancels without passing."""
    started = time.monotonic()
    result = InspectionResult("error", "", "", error_code="screening_invalid_request")
    try:
        if not isinstance(subject, Subject):
            Subject.from_dict(subject)
        units = [
            ContentUnit.from_dict(deepcopy(unit.to_dict()))
            for unit in normalize_units(units)
        ]
        result.units_total = len(units)
        result.content_fingerprint = content_fingerprint(units)
        policy_fingerprint = hash_payload(policy)
        if isinstance(policy, dict) and "ai_checks" in policy:
            policy = normalize_effective_policy(policy)
        else:
            policy = compose_policy(policy)
        result.policy_fingerprint = policy_fingerprint
    except Exception:
        return result
    if not policy["enabled"]:
        result.status, result.error_code = "incomplete", "screening_policy_inactive"
        return result
    limits = policy["limits"]
    deadline = started + limits["max_runtime_seconds"]
    if len(units) > limits["max_units"] or sum(len(unit.text) for unit in units) > limits["max_total_characters"]:
        result.status, result.error_code = "incomplete", "screening_input_limit"
        result.detectors = [{
            "id": "input", **_safe_failure("incomplete", "screening_input_limit", len(units)).to_dict(),
        }]
        return result
    detectors = []
    if policy["rules"]:
        try:
            remaining_limits = _remaining_limits(limits, deadline)
            if remaining_limits is None:
                deterministic = _safe_failure(
                    "incomplete", "screening_runtime_limit", len(units), len(units) * len(policy["rules"]),
                )
            else:
                deterministic = evaluate_deterministic_units(
                    units, policy["rules"], limits=remaining_limits,
                    on_progress=_progress_callback(on_progress, "deterministic"),
                )
        except Exception:
            deterministic = _safe_failure("error", "screening_detector_failed", len(units))
        detectors.append((
            "deterministic",
            _validate_detector(deterministic, units, policy["rules"], "deterministic", limits),
        ))
    for check in policy["ai_checks"]:
        if any(detector.error_code in _CANCELLATION_CODES for _, detector in detectors):
            detectors.append((
                check["id"], _safe_failure("incomplete", "screening_cancelled", len(units)),
            ))
            continue
        if _remaining_limits(limits, deadline) is None:
            detectors.append((
                check["id"], _safe_failure("incomplete", "screening_runtime_limit", len(units)),
            ))
            continue
        try:
            if model_evaluator is None:
                # Model routing imports application configuration only when AI is required.
                from .model import evaluate_model_units
                evaluator = evaluate_model_units
            else:
                evaluator = model_evaluator
            evaluator_units = [ContentUnit.from_dict(deepcopy(unit.to_dict())) for unit in units]
            evaluator_check = deepcopy(check)
            callback = _progress_callback(on_progress, check["id"])
            kwargs = {"on_progress": callback} if callback is not None else {}
            remaining_limits = _remaining_limits(limits, deadline)
            if remaining_limits is None:
                model = _safe_failure("incomplete", "screening_runtime_limit", len(units))
            else:
                evaluator_check["limits"] = remaining_limits
                model = evaluator(evaluator_units, evaluator_check, **kwargs)
        except TimeoutError:
            model = _safe_failure("incomplete", "screening_model_timeout", len(units))
        except Exception:
            model = _safe_failure("error", "screening_model_failed", len(units))
        detectors.append((
            check["id"], _validate_detector(model, units, [check], "model", limits),
        ))
    if not detectors:
        result.error_code = "screening_policy_empty"
        return result
    findings = {}
    usage = {}
    for detector_id, detector in detectors:
        result.detectors.append({"id": detector_id, **detector.to_dict()})
        for finding in detector.findings:
            findings.setdefault(finding.finding_id, finding)
        for key in _USAGE_FIELDS:
            if key in detector.usage:
                usage[key] = usage.get(key, 0) + detector.usage[key]
    result.findings = list(findings.values())
    result.usage = usage
    if any(detector.status == "error" for _, detector in detectors):
        result.status, result.error_code = "error", "screening_detector_failed"
    elif any(detector.error_code in _CANCELLATION_CODES for _, detector in detectors):
        result.status, result.error_code = "incomplete", "screening_cancelled"
    elif any(detector.status == "incomplete" for _, detector in detectors):
        result.status, result.error_code = "incomplete", "screening_coverage_incomplete"
    elif len(result.findings) > limits["max_findings"]:
        result.status, result.error_code = "incomplete", "screening_findings_limit"
    elif time.monotonic() - started > limits["max_runtime_seconds"]:
        result.status, result.error_code = "incomplete", "screening_runtime_limit"
    else:
        result.status, result.error_code = ("findings" if result.findings else "pass"), None
    return result
