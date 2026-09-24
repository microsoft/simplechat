# orchestration_research.py
"""
Offline source loading and synthetic inputs for research-planner evaluation.

Version: 0.261.139
Implemented in: 0.261.099
Single orchestration contract updated in: 0.261.139

Only production definitions are executed, never their application imports. In particular,
config.py, the source-review browser stack, and Azure clients must not be imported here.
This is an evaluation seam, not a second implementation of planning or authorization.
"""

import ast
import copy
import hashlib
import json
import logging
import math
import re
import sys
import types
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar, Dict, Iterable, List, Optional
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPO_ROOT / "application" / "single_app"
CASE_FILE = Path(__file__).with_name("orchestration_research_cases.json")
PLANNER_FILE = "functions_orchestration_planner.py"
REGISTRY_FILE = "functions_orchestration_registry.py"
RESULT_CONTRACTS_FILE = "functions_orchestration_result_contracts.py"
OFFLINE_CAPABILITY_IDS = {
    "document_search", "document_analyze", "document_compare", "web_search",
    "url_fetch", "deep_research", "action_invoke", "agent_invoke", "compose",
}


class _OfflineDraftValidator:
    """Small schema validator for the synthetic planner cases."""

    def __init__(self, schema):
        self.schema = schema if isinstance(schema, dict) else {}

    def is_valid(self, value):
        if self.schema.get("type") == "object" and not isinstance(value, dict):
            return False
        required = self.schema.get("required") or []
        if any(name not in value for name in required):
            return False
        properties = self.schema.get("properties") or {}
        for name, rules in properties.items():
            if name not in value or not isinstance(rules, dict):
                continue
            current = value[name]
            expected = rules.get("type")
            if expected == "string" and not isinstance(current, str):
                return False
            if expected == "array" and not isinstance(current, list):
                return False
            if expected == "object" and not isinstance(current, dict):
                return False
            if rules.get("minLength") and isinstance(current, str) and len(current) < rules["minLength"]:
                return False
            if "enum" in rules and current not in rules["enum"]:
                return False
        return True


def _deliverable_availability(settings, *, capabilities, unavailable=None, export_catalog=None):
    available = {capability["id"] for capability in capabilities or ()}
    return {
        "answer": {"status": "available"} if "compose" in available else {
            "status": "unavailable", "reason": "capability_not_enabled_for_orchestration",
        },
        "files": {},
        "images": {},
        "charts": {},
        "diagrams": {},
        "facts": [],
        "recipes": [],
    }


def _compile_deliverables(
    deliverables, steps, *, final_response=None, availability=None, image_selected=False,
):
    values = [copy.deepcopy(item) for item in deliverables or [] if isinstance(item, dict)]
    if not values and final_response:
        values = [{
            "id": "answer", "kind": "answer", "requested": "explicit",
            "description": "The answer", "status": "planned", "implicit": True,
        }]
    return values


def _offline_registry_capabilities(registry, candidate_ids=None):
    selected = set(candidate_ids) if candidate_ids is not None else OFFLINE_CAPABILITY_IDS
    return [
        registry["_resolve_descriptor"](descriptor)
        for descriptor in registry["CAPABILITY_REGISTRY"]
        if selected is None or descriptor["id"] in selected
    ]


class OfflineAPIError(RuntimeError):
    """SDK-shaped error seam; importing the real SDK is unnecessary offline."""


class OfflineBadRequestError(OfflineAPIError):
    def __init__(self, message, *, body=None):
        super().__init__(message)
        self.body = body or {}
        self.status_code = 400


class OfflineAzureError(RuntimeError):
    pass


def _assignment(tree, name):
    return next(
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
    )


def _definitions(filename, seed=None, names=None):
    """Load real functions/constants with only explicitly supplied, offline dependencies."""
    if filename == REGISTRY_FILE:
        # The registry's table reads two constants from the pure result-contract module.
        contracts = _definitions(
            RESULT_CONTRACTS_FILE, names={"IMAGE_ASSET_KIND", "RESULT_KINDS"},
        )
        seed = {
            "IMAGE_ASSET_KIND": contracts["IMAGE_ASSET_KIND"], "RESULT_KINDS": contracts["RESULT_KINDS"],
            "deepcopy": copy.deepcopy, **(seed or {}),
        }
    elif filename == "functions_orchestration_schema.py":
        contracts = _definitions(RESULT_CONTRACTS_FILE)
        seed = {
            **contracts,
            "Draft202012Validator": _OfflineDraftValidator,
            "SchemaError": ValueError,
            "ServiceRequestError": RuntimeError,
            "APIConnectionError": RuntimeError,
            "APITimeoutError": RuntimeError,
            "AgentDelegationTimeout": RuntimeError,
            "ModelCatalogError": RuntimeError,
            "DeliverableError": type("DeliverableError", (ValueError,), {"code": "deliverables_invalid"}),
            "compile_deliverables": _compile_deliverables,
            **(seed or {}),
        }
    elif filename == PLANNER_FILE:
        seed = {
            "build_deliverable_availability": _deliverable_availability,
            "TASKS": {},
            "ROUTING_INSTRUCTIONS": "",
            "assign_step_models": lambda *_args, **_kwargs: None,
            "authorized_routing_candidates": lambda *_args, **_kwargs: [],
            "ModelCatalogError": RuntimeError,
            **(seed or {}),
        }
    path = APP_ROOT / filename
    tree = ast.parse(path.read_text(encoding="utf-8"))
    body = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            if names is None or node.name in names:
                body.append(node)
        elif isinstance(node, ast.Assign):
            targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if any(name.isupper() and (names is None or name in names) for name in targets):
                body.append(node)
    namespace = {
        "json": json, "logging": logging, "math": math, "re": re, "uuid": uuid,
        "hashlib": hashlib, "copy": copy, "deepcopy": copy.deepcopy,
        "dataclass": dataclass, "fields": fields,
        "Any": Any, "Dict": Dict, "Iterable": Iterable, "List": List, "Optional": Optional,
        "ClassVar": ClassVar,
        # Production telemetry is intentionally disabled for this isolated evaluation.
        "log_event": lambda *args, **kwargs: None,
        **(seed or {}),
        "__name__": f"_research_evaluation_{path.stem}",
    }
    exec(compile(ast.Module(body=body, type_ignores=[]), str(path), "exec"), namespace)
    if names is not None and set(names) - set(namespace):
        raise ValueError(f"Missing evaluation definitions in {filename}.")
    return namespace


def document_action_policy_module():
    """Load the actual pure settings policy without importing its execution engines."""
    limits = _definitions("functions_document_analysis.py", names={
        "CHAT_DOCUMENT_ANALYSIS_MAX_DOCUMENTS", "WORKFLOW_DOCUMENT_ANALYSIS_MAX_DOCUMENTS",
    })
    module = types.ModuleType("functions_document_actions")
    module.__dict__.update(_definitions(
        "functions_document_actions.py", seed={**limits, "copy": copy},
    ))
    return module


@contextmanager
def stubbed_orchestration_imports():
    """Use real document capability defaults, not an import failure as a disabled gate."""
    # Keep this opt-in so tests of the document action engine can import their real subject.
    from .app_stubs import stubbed_app_imports

    with stubbed_app_imports(), patch.dict(sys.modules, {
        "functions_document_actions": document_action_policy_module(),
    }):
        yield


def _visual_output_seed():
    """The planner's pure visual-output helpers, loaded like every other definition here."""
    proposals = _definitions("functions_image_proposals.py", names={"image_generation_is_enabled"})
    return _definitions("functions_orchestration_visuals.py", seed=proposals, names={
        "image_proposals_available", "image_requested_by_user", "planner_visual_outputs",
    })


@contextmanager
def planner_runtime():
    """Expose actual planner, context, registry and schema functions without Azure imports."""
    review = types.ModuleType("functions_source_review")
    review.__dict__.update(_definitions("functions_source_review.py", names={
        "SOURCE_REVIEW_DEFAULTS", "SOURCE_REVIEW_HARD_LIMITS", "DEEP_RESEARCH_APP_ROLE",
        "_coerce_bool", "parse_source_review_list", "get_source_review_config",
        "normalize_user_roles", "has_deep_research_app_role", "is_source_review_enabled_for_user",
    }))
    registry = _definitions(REGISTRY_FILE)
    registry["_build_capabilities"] = lambda candidate_ids=None: _offline_registry_capabilities(
        registry, candidate_ids,
    )
    schema = _definitions("functions_orchestration_schema.py", seed=registry)
    events = _definitions("functions_orchestration_events.py")
    delegation = _definitions("functions_agent_delegation.py", names={"AGENT_PLUGIN_TYPE"})
    catalog = _definitions("functions_action_catalog.py", seed=delegation)
    context = _definitions("functions_orchestration_context.py", seed={
        **registry, "build_action_planner_projection": catalog["build_action_planner_projection"],
        "deepcopy": copy.deepcopy, "datetime": datetime, "timezone": timezone,
    }, names={
        "SELECTED_PROMPT_LENGTH", "_text", "_string_list", "_history_text",
        "_extract_urls", "_selected_prompt", "build_conversation_signals", "resolve_seeds",
        "build_planner_context", "conversation_reference_messages",
        "_elicitation_answer_text", "build_elicitation_user_request",
    })
    planner = _definitions(PLANNER_FILE, seed={
        **registry, **schema,
        **_visual_output_seed(),
        "build_model_reasoning_metadata": events["build_model_reasoning_metadata"],
        "conversation_reference_messages": context["conversation_reference_messages"],
        "APIError": getattr(sys.modules.get("openai"), "APIError", OfflineAPIError),
        "BadRequestError": getattr(sys.modules.get("openai"), "BadRequestError", OfflineBadRequestError),
        "AzureError": OfflineAzureError,
    })

    def no_configured_client(settings):
        raise planner["PlannerError"]("No explicit evaluation client was supplied.")

    planner["resolve_planner_client"] = no_configured_client
    with patch.dict(sys.modules, {
        "functions_source_review": review,
        "functions_document_actions": document_action_policy_module(),
    }):
        yield types.SimpleNamespace(
            planner=planner, registry=registry, schema=schema, context=context,
        )


def capture_baseline():
    """Capture current guidance and real synthetic context, without resource access."""
    planner_source = (APP_ROOT / PLANNER_FILE).read_text(encoding="utf-8")
    registry_source = (APP_ROOT / REGISTRY_FILE).read_text(encoding="utf-8")
    context_source = (APP_ROOT / "functions_orchestration_context.py").read_text(encoding="utf-8")
    planner_tree = ast.parse(planner_source)
    registry_tree = ast.parse(registry_source)
    context_tree = ast.parse(context_source)
    config_tree = ast.parse((APP_ROOT / "config.py").read_text(encoding="utf-8"))
    registry = _definitions(REGISTRY_FILE)
    definitions = {}
    for name, tree, source in (
        ("PLANNER_SYSTEM_PROMPT", planner_tree, planner_source),
        ("build_planner_messages", planner_tree, planner_source),
        ("capabilities_for_contract", registry_tree, registry_source),
        ("build_planner_capability_projection", registry_tree, registry_source),
        ("build_planner_context", context_tree, context_source),
        ("resolve_seeds", context_tree, context_source),
    ):
        node = next(
            (item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name),
            None,
        )
        definitions[name] = ast.get_source_segment(source, node or _assignment(tree, name))
    suite = load_case_suite()
    with planner_runtime() as runtime:
        contexts = {}
        for case in suite["cases"]:
            settings, caller, context = case_inputs(runtime, suite, case)

            def capture_call(_client, _deployment, messages, **_kwargs):
                contexts[case["id"]] = json.loads(messages[1]["content"])
                # A renderable question ends planning without invoking any execution path.
                return json.dumps({
                    "kind": "elicitation", "message": "Synthetic capture only.",
                    "requested_schema": {
                        "type": "object", "properties": {"detail": {"type": "string"}},
                    },
                }), None

            with patch.dict(runtime.planner, {
                "resolve_planner_client": lambda _settings: (None, "synthetic-capture"),
                "_call_planner": capture_call,
            }):
                runtime.planner["plan_request"](
                    case["message"], context, "synthetic-capture", caller["user_id"],
                    settings=settings, request_context=caller,
                    seeds=runtime.context["resolve_seeds"](case.get("request") or {}),
                )
    return {
        "schema_version": 2,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "app_version": ast.literal_eval(_assignment(config_tree, "VERSION").value),
        "capture_method": (
            "Offline production context/planner/registry definitions with synthetic inputs "
            "and controlled completions; no application bootstrap or service access"
        ),
        "planner_system_prompt": ast.literal_eval(
            _assignment(planner_tree, "PLANNER_SYSTEM_PROMPT").value
        ),
        "contexts": contexts,
        "case_inputs_sha256": {
            case["id"]: hashlib.sha256(
                json.dumps(
                    {"settings": suite["settings"], "roles": suite["user_roles"], "case": case},
                    sort_keys=True, separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            for case in suite["cases"]
        },
        "capabilities": registry["build_planner_capability_projection"](
            _offline_registry_capabilities(registry)
        ),
        "parameters": {
            "max_tokens": ast.literal_eval(_assignment(planner_tree, "PLANNER_MAX_TOKENS").value),
            "temperature": ast.literal_eval(
                _assignment(planner_tree, "PLANNER_TEMPERATURE").value
            ),
        },
        "source_sha256": {
            PLANNER_FILE: hashlib.sha256(planner_source.encode("utf-8")).hexdigest(),
            REGISTRY_FILE: hashlib.sha256(registry_source.encode("utf-8")).hexdigest(),
            "functions_orchestration_context.py": hashlib.sha256(context_source.encode("utf-8")).hexdigest(),
        },
        "source_definitions": definitions,
    }


def load_case_suite():
    """Return fresh copies of the committed public scenarios and their manual rubric."""
    return json.loads(CASE_FILE.read_text(encoding="utf-8"))


def case_inputs(runtime, suite, case):
    """Adapt synthetic data through the production context builder; no resources are read."""
    settings = copy.deepcopy(suite["settings"])
    settings.update(case.get("settings", {}))
    request_context = {
        "user_id": "synthetic-evaluation-user",
        "user_roles": copy.deepcopy(case.get("user_roles", suite["user_roles"])),
        "message_urls": [],
        "agent_catalog": copy.deepcopy(case.get("agents", [])),
        "external_source_admission": lambda **_kwargs: None,
        "external_source_preflight": lambda **_kwargs: None,
        "capture_external_source_configuration": lambda *_args, **_kwargs: None,
        "external_source_authorizer": lambda **_kwargs: None,
    }
    signals = runtime.context["build_conversation_signals"](
        case.get("prior_messages", []), case["message"],
    )
    context = runtime.context["build_planner_context"](
        case["message"], ledger=copy.deepcopy(case.get("earlier_runs")), signals=signals,
        seeds=runtime.context["resolve_seeds"](case.get("request") or {}),
        candidates=copy.deepcopy(case.get("candidate_documents", [])),
        agents=request_context["agent_catalog"],
        memory_context=copy.deepcopy(case.get("memory_context")),
    )
    if "request_time_utc" in context:
        context["request_time_utc"] = "2026-09-07T12:00:00+00:00"
    return settings, request_context, context
