# evaluate_orchestration_research_planning.py
"""
Small, opt-in paired evaluation of research-selection guidance.

Version: 0.261.099
Implemented in: 0.261.099

Default invocation lists synthetic cases without network access. Capture BEFORE changing
planner guidance; capture never imports the application or constructs Azure/Cosmos clients:

    python scripts\\evaluate_orchestration_research_planning.py
    python scripts\\evaluate_orchestration_research_planning.py --mode capture --output .\\research-baseline.json

Live example (only against an explicitly approved evaluation deployment):

    python scripts\\evaluate_orchestration_research_planning.py --mode live --baseline .\\research-baseline.json --output .\\research-comparison.json --endpoint https://YOUR-EVAL.openai.azure.com --deployment YOUR-PLANNER --api-version 2024-10-21 --api-key-env SIMPLECHAT_EVAL_KEY --call-cap 30 --repeat 1

Use --case original-playlist to select a case (repeat --case for several). All 11 cases
need 22 primary requests per repetition; retries also consume the explicit call cap.
Alternatively use --entra-token-env with an explicitly obtained evaluation bearer token.
No default credential chain, application settings, real conversations, web searches,
answer generation, or automatic model grading are used.

Python callers can inject a configured client into run_comparison(), with explicit
deployment and call_cap. The client must expose max_retries=0; SDK automatic retries
would otherwise defeat request accounting. The production planner's response-format
fallback is retained and counted. Do not inject a client with hidden transport retries.

Both variants use the current production planner/context/normalizer and identical
synthetic availability, deployment and parameters. Only the captured system prompt and
capability guidance differ. Triage is recorded, but every case exercises the planner,
including cases the production route might answer without a planning call. This measures
planner selection, not end-to-end answer quality. Review the rubric for overuse AND
underuse, not an arbitrary research rate. Mock tests establish contracts only.

Outputs never overwrite an existing file. Provider failures and exhausted budgets are
explicit unsuccessful outcomes with nonzero CLI exit status, not successful direct-answer
choices. Usage is observed per request (unknown on failed requests); durations are measured,
not cost estimates. Raw provider errors, authentication values and endpoint URLs are omitted.
"""

import argparse
import copy
import hashlib
import json
import os
import sys
import time
import types
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Direct script execution needs the repository path before this offline support import.
from functional_tests.test_support.orchestration_research import (  # noqa: E402
    capture_baseline,
    case_inputs,
    load_case_suite,
    planner_runtime,
)


SUCCESS_STATUSES = {"completed", "completed_with_repairs", "completed_with_recoveries"}


class EvaluationConfigurationError(ValueError):
    """A safe, actionable configuration failure before model work."""


class EvaluationBudgetExceeded(RuntimeError):
    """No more provider requests may be made."""


class EvaluationProviderFailure(RuntimeError):
    """A provider request failed; its raw exception is deliberately withheld."""


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _text(value, limit=600):
    return value.strip()[:limit] if isinstance(value, str) else ""


def _usage(response):
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    return {
        name: value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
        for name in ("prompt_tokens", "completion_tokens", "total_tokens")
        for value in [getattr(usage, name, None)]
    }


def _provider_error_types():
    """Include the SDK's error base only when live mode already loaded that SDK."""
    error_types = (OSError, RuntimeError, ValueError, TypeError)
    sdk_error = getattr(sys.modules.get("openai"), "OpenAIError", None)
    if isinstance(sdk_error, type) and issubclass(sdk_error, Exception):
        error_types += (sdk_error,)
    return error_types


class CountedPlannerClient:
    """One guarded SDK create call is one request; the underlying SDK must not retry."""

    def __init__(self, client, call_cap):
        if getattr(client, "max_retries", None) != 0:
            raise EvaluationConfigurationError("The injected client must have max_retries=0.")
        self.client = client
        self.call_cap = call_cap
        self.requests = []
        self.blocked_requests = 0
        self.labels = {}
        self.chat = types.SimpleNamespace(completions=self)

    def create(self, **kwargs):
        if len(self.requests) >= self.call_cap:
            self.blocked_requests += 1
            raise EvaluationBudgetExceeded("The explicit evaluation request cap is exhausted.")
        event = {
            "request_number": len(self.requests) + 1,
            **self.labels,
            "response_format": "json_object" if kwargs.get("response_format") else "prompt_only",
            "usage": None,
            "status": "provider_error",
        }
        self.requests.append(event)
        started = time.perf_counter()
        try:
            response = self.client.chat.completions.create(**kwargs)
            event.update({
                "status": "completed",
                "usage": _usage(response),
                "observed_model": _text(getattr(response, "model", None), 200),
            })
            return response
        except _provider_error_types() as exc:
            event["status"] = "provider_error"
            status = getattr(exc, "status_code", None)
            if isinstance(status, int) and 100 <= status <= 599:
                event["http_status"] = status
            raise EvaluationProviderFailure("The evaluation planner request failed.") from None
        finally:
            event["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)


def _project_steps(steps):
    if not isinstance(steps, list):
        return []
    return [
        {
            **{name: _text(step.get(name)) for name in (
                "step_id", "capability_id", "title", "rationale",
            )},
            "arguments": {
                name: _text(value, 2000)
                for name, value in (step.get("arguments") or {}).items()
                if name in ("query", "instruction") and isinstance(value, str)
            } if isinstance(step.get("arguments"), dict) else {},
            "depends_on": [
                _text(value, 200) for value in step.get("depends_on", [])[:30]
                if isinstance(value, str)
            ] if isinstance(step.get("depends_on"), list) else [],
        }
        for step in steps[:30] if isinstance(step, dict)
    ]


def _validate_comparison(baseline, candidate, suite, case_ids, call_cap, repetitions):
    if type(call_cap) is not int or call_cap < 1:
        raise EvaluationConfigurationError("Supply an explicit positive integer call cap.")
    if type(repetitions) is not int or repetitions < 1:
        raise EvaluationConfigurationError("Repetitions must be a positive integer.")
    if not isinstance(baseline, dict) or baseline.get("schema_version") != 1:
        raise EvaluationConfigurationError("A captured schema-version-1 baseline is required.")
    if not _text(baseline.get("planner_system_prompt")):
        raise EvaluationConfigurationError("The baseline has no captured planner prompt.")
    if baseline.get("parameters") != candidate["parameters"]:
        raise EvaluationConfigurationError("Baseline and candidate planner parameters must match.")
    original = baseline.get("capabilities")
    if not isinstance(original, list) or any(not isinstance(item, dict) for item in original):
        raise EvaluationConfigurationError("The baseline has no valid capability projection.")
    if any(not _text(item.get(name)) for item in original for name in ("summary", "when_to_use")):
        raise EvaluationConfigurationError("The baseline capability guidance is incomplete.")
    # Only descriptive guidance may differ in this paired selection comparison.
    without_guidance = lambda entries: [
        {key: value for key, value in item.items() if key not in ("summary", "when_to_use")}
        for item in entries
    ]
    if without_guidance(original) != without_guidance(candidate["capabilities"]):
        raise EvaluationConfigurationError("Baseline and candidate capability contracts must match.")
    all_ids = {case["id"] for case in suite["cases"]}
    selected = list(case_ids) if case_ids is not None else [case["id"] for case in suite["cases"]]
    if not selected or len(set(selected)) != len(selected) or not set(selected) <= all_ids:
        raise EvaluationConfigurationError("Select distinct case IDs from the committed synthetic suite.")
    cases = [case for case in suite["cases"] if case["id"] in selected]
    if call_cap < 2 * len(cases) * repetitions:
        raise EvaluationConfigurationError("The call cap cannot cover the requested paired primary calls.")
    return cases


def _run_variant(runtime, suite, case, snapshot, client, deployment, variant, repetition):
    planner = runtime.planner
    settings, request_context, context = case_inputs(runtime, suite, case)
    available = runtime.registry["resolve_available_capabilities"](
        settings, allowed_ids=settings.get("chat_orchestration_enabled_capabilities"),
        request_context=request_context,
    )
    projection_by_id = {item["id"]: item for item in snapshot["capabilities"]}
    before = len(client.requests)
    blocked_before = client.blocked_requests
    raw_proposals = []
    message_digests = []
    original_call = planner["_call_planner"]
    client.labels = {"case_id": case["id"], "variant": variant, "repetition": repetition}

    def observed_call(configured_client, configured_deployment, messages):
        message_digests.append(_digest(messages))
        reply, usage = original_call(configured_client, configured_deployment, messages)
        raw_proposals.append(copy.deepcopy(planner["extract_planner_json"](reply)))
        return reply, usage

    started = time.perf_counter()
    processing_failed = False
    with patch.dict(planner, {
        "PLANNER_SYSTEM_PROMPT": snapshot["planner_system_prompt"],
        "PLANNER_TEMPERATURE": snapshot["parameters"]["temperature"],
        "PLANNER_MAX_TOKENS": snapshot["parameters"]["max_tokens"],
        "build_planner_capability_projection": lambda capabilities: [
            copy.deepcopy(projection_by_id[item["id"]]) for item in capabilities
        ],
        "resolve_planner_client": lambda settings: (client, deployment),
        "_call_planner": observed_call,
    }):
        try:
            kind, document = planner["plan_request"](
                case["message"], context, "synthetic-evaluation-conversation",
                request_context["user_id"], settings=settings, request_context=request_context,
                authorized_document_ids=[],
            )
        except (ValueError, TypeError, AttributeError, KeyError, OverflowError):
            # Malformed model fields can fail beyond the normalizer's repair contract.
            # Keep request accounting and never persist a raw exception or claim success.
            kind, document = "error", {}
            processing_failed = True
    requests = client.requests[before:]
    fallback = None
    if client.blocked_requests > blocked_before:
        fallback = "budget_exhausted"
    elif processing_failed:
        fallback = "planner_processing_error"
    elif "planner_fallback_reason" in document:
        if not raw_proposals:
            fallback = "provider_failure"
        elif not raw_proposals[-1]:
            fallback = "unparseable_reply"
        elif raw_proposals[-1].get("kind") == "elicitation":
            fallback = "elicitation_fallback"
        else:
            fallback = "validation_fallback"
    recoveries = []
    if not fallback and any(item["status"] == "provider_error" for item in requests):
        recoveries.append("retry_without_response_format")
    if len(raw_proposals) > 1:
        recoveries.append("invalid_elicitation_replanned")
    validation = document.get("validation") or {}
    return {
        **client.labels,
        "triage": planner["triage_request"](case["message"], context),
        "available_capabilities": [item["id"] for item in available],
        "kind": kind,
        "outcome": fallback or kind,
        "fallback_classification": fallback,
        "recoveries": recoveries,
        "semantic_review_eligible": fallback is None,
        "proposals": [
            {
                "kind": _text((proposal or {}).get("kind"), 40),
                "steps": _project_steps((proposal or {}).get("steps")),
                "elicitation_message": _text((proposal or {}).get("message")),
            }
            for proposal in raw_proposals
        ],
        "selected_steps": _project_steps(document.get("steps")),
        "validation": {
            "ok": validation.get("ok"),
            "repairs": [_text(value) for value in (validation.get("repairs") or [])[:30]],
            "errors": [_text(value) for value in (validation.get("errors") or [])[:30]],
        },
        "request_numbers": [item["request_number"] for item in requests],
        "message_sha256": message_digests,
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def run_comparison(baseline, *, client, deployment, call_cap, repetitions=1, case_ids=None):
    """Run a bounded comparison with an explicit configured client; return safe observations."""
    if not isinstance(deployment, str) or not deployment.strip():
        raise EvaluationConfigurationError("An explicit evaluation deployment is required.")
    candidate = capture_baseline()
    suite = load_case_suite()
    cases = _validate_comparison(baseline, candidate, suite, case_ids, call_cap, repetitions)
    counted = CountedPlannerClient(client, call_cap)
    report = {
        "schema_version": 1,
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "review_status": "not_reviewed",
        "rubric": suite["rubric"],
        "cases": cases,
        "synthetic_settings": suite["settings"],
        "synthetic_user_roles": suite["user_roles"],
        "suite_sha256": _digest(suite),
        "deployment": deployment,
        "parameters": candidate["parameters"],
        "guidance_changed": (
            baseline["planner_system_prompt"] != candidate["planner_system_prompt"]
            or baseline["capabilities"] != candidate["capabilities"]
        ),
        "sdk_max_retries": 0,
        "request_accounting": "SDK completion-create attempts, including failures; automatic SDK retries disabled.",
        "call_cap": call_cap,
        "repetitions": repetitions,
        "expected_planner_runs": 2 * len(cases) * repetitions,
        "guidance": {
            name: {
                "app_version": snapshot.get("app_version"),
                "source_sha256": snapshot.get("source_sha256"),
                "prompt_sha256": _digest(snapshot["planner_system_prompt"]),
                "projection_sha256": _digest(snapshot["capabilities"]),
            }
            for name, snapshot in (("baseline", baseline), ("candidate", candidate))
        },
        "results": [],
        "requests": counted.requests,
    }
    with planner_runtime() as runtime:
        for repetition in range(1, repetitions + 1):
            variants = [("baseline", baseline), ("candidate", candidate)]
            if repetition % 2 == 0:
                variants.reverse()
            for case in cases:
                for variant, snapshot in variants:
                    result = _run_variant(
                        runtime, suite, case, snapshot, counted, deployment, variant, repetition,
                    )
                    report["results"].append(result)
                    if result["outcome"] in (
                        "budget_exhausted", "provider_failure", "planner_processing_error",
                    ):
                        report["status"] = result["outcome"]
                        break
                if report["status"] != "running":
                    break
            if report["status"] != "running":
                break
    if report["status"] == "running":
        if any(item["fallback_classification"] for item in report["results"]):
            report["status"] = "completed_with_planner_fallbacks"
        elif any(item["recoveries"] for item in report["results"]):
            report["status"] = "completed_with_recoveries"
        elif any(
            item["validation"]["repairs"] or item["validation"]["errors"]
            for item in report["results"]
        ):
            report["status"] = "completed_with_repairs"
        else:
            report["status"] = "completed"
    report.update({
        "requests_made": len(counted.requests),
        "blocked_requests": counted.blocked_requests,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    })
    return report


def _explicit_client(args):
    endpoint = urlsplit(args.endpoint or "")
    if (
        endpoint.scheme != "https" or not endpoint.hostname or endpoint.username is not None
        or endpoint.password is not None or endpoint.query or endpoint.fragment
        or endpoint.path not in ("", "/")
    ):
        raise EvaluationConfigurationError("Supply an explicit HTTPS evaluation endpoint without credentials or a path.")
    if not args.deployment or not args.api_version:
        raise EvaluationConfigurationError("Live mode requires --deployment and --api-version.")
    if not args.api_key_env and not args.entra_token_env:
        raise EvaluationConfigurationError("Select --api-key-env or --entra-token-env explicitly.")
    value = os.environ.get(args.api_key_env or args.entra_token_env)
    if not value:
        raise EvaluationConfigurationError("The explicitly named authentication variable is empty.")
    # SDK import is deliberately live-only; offline capture/tests need no Azure packages.
    from openai import AzureOpenAI

    # AzureOpenAI otherwise reads the other auth type from its default environment
    # variables even when one explicit auth type was supplied. Restore the process
    # environment immediately after construction; the client keeps the explicit value.
    with patch.dict(os.environ):
        os.environ.pop("AZURE_OPENAI_API_KEY", None)
        os.environ.pop("AZURE_OPENAI_AD_TOKEN", None)
        return AzureOpenAI(
            azure_endpoint=args.endpoint,
            api_version=args.api_version,
            api_key=value if args.api_key_env else None,
            azure_ad_token=value if args.entra_token_env else None,
            organization="",
            project="",
            max_retries=0,
            timeout=args.timeout,
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=("cases", "capture", "live"), default="cases")
    parser.add_argument("--baseline", help="Required pre-change JSON capture for live comparison.")
    parser.add_argument("--output", help="New output JSON file; never overwrites an existing file.")
    parser.add_argument("--endpoint", help="Explicit approved evaluation Azure OpenAI HTTPS endpoint.")
    parser.add_argument("--deployment", help="Explicit planner deployment, shared by both variants.")
    parser.add_argument("--api-version", help="Explicit Azure OpenAI API version.")
    auth = parser.add_mutually_exclusive_group()
    auth.add_argument("--api-key-env", help="Name of the environment variable holding the evaluation API key.")
    auth.add_argument("--entra-token-env", help="Name of the variable holding an explicit evaluation bearer token.")
    parser.add_argument("--call-cap", type=int, help="Required live request cap, including planner fallback retries.")
    parser.add_argument("--repeat", type=int, default=1, help="Paired repetitions within the explicit cap.")
    parser.add_argument("--case", dest="case_ids", action="append", help="Synthetic case ID; may be repeated.")
    parser.add_argument("--timeout", type=float, default=45, help="Per-request SDK timeout in seconds (default: 45).")
    args = parser.parse_args(argv)
    if args.mode == "cases":
        suite = load_case_suite()
        sys.stdout.write(json.dumps({
            "status": "offline",
            "case_ids": [case["id"] for case in suite["cases"]],
            "rubric": suite["rubric"],
            "network_calls": 0,
        }, indent=2) + "\n")
        return 0
    if not args.output:
        parser.error("Capture and live modes require --output.")
    if args.mode == "live" and not args.baseline:
        parser.error("Live mode requires an explicit --baseline artifact.")
    if args.timeout <= 0 or not args.timeout < float("inf"):
        parser.error("--timeout must be a positive finite number.")
    try:
        if args.mode == "capture":
            report = capture_baseline()
        else:
            baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
            _validate_comparison(
                baseline, capture_baseline(), load_case_suite(),
                args.case_ids, args.call_cap, args.repeat,
            )
        output = Path(args.output).resolve()
        # Reserve before creating a live client, so a path error cannot waste API calls.
        with output.open("x", encoding="utf-8") as stream:
            if args.mode == "live":
                client = None
                try:
                    client = _explicit_client(args)
                    report = run_comparison(
                        baseline, client=client, deployment=args.deployment, call_cap=args.call_cap,
                        repetitions=args.repeat, case_ids=args.case_ids,
                    )
                    report["environment"] = {
                        "endpoint_sha256": _digest(args.endpoint),
                        "api_version": args.api_version,
                        "auth_type": "api_key" if args.api_key_env else "explicit_bearer_token",
                        "request_timeout_seconds": args.timeout,
                    }
                except (EvaluationConfigurationError, ImportError):
                    report = {"status": "configuration_error", "message": "Check the explicit evaluation client configuration and installed OpenAI SDK."}
                except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError):
                    report = {"status": "evaluation_error", "message": "Evaluation failed before a complete report was available."}
                finally:
                    if client is not None:
                        try:
                            client.close()
                        except _provider_error_types():
                            report["client_cleanup_failed"] = True
                            report["status"] = "evaluation_error"
            json.dump(report, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
    except (OSError, ValueError, TypeError, KeyError):
        sys.stderr.write("Evaluation did not run: check the baseline, selected cases, budget and new output path.\n")
        return 2
    status = report.get("status", "captured")
    sys.stdout.write(json.dumps({
        "status": status,
        "requests_made": report.get("requests_made", 0),
        "review_status": report.get("review_status", "not_applicable"),
    }) + "\n")
    return 0 if args.mode == "capture" or status in SUCCESS_STATUSES else 2


if __name__ == "__main__":
    sys.exit(main())
