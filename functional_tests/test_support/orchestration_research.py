# orchestration_research.py
"""
Offline source loading and synthetic inputs for research-planner evaluation.

Version: 0.261.096
Implemented in: 0.261.096

Only production definitions are executed, never their application imports. In particular,
config.py, the source-review browser stack, and Azure clients must not be imported here.
This is an evaluation seam, not a second implementation of planning or authorization.
"""

import ast
import copy
import hashlib
import json
import logging
import re
import sys
import types
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPO_ROOT / "application" / "single_app"
CASE_FILE = Path(__file__).with_name("orchestration_research_cases.json")
PLANNER_FILE = "functions_orchestration_planner.py"
REGISTRY_FILE = "functions_orchestration_registry.py"


def _assignment(tree, name):
    return next(
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
    )


def _definitions(filename, seed=None, names=None):
    """Load real functions/constants with only explicitly supplied, offline dependencies."""
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
        "json": json, "logging": logging, "re": re, "uuid": uuid, "hashlib": hashlib,
        "Any": Any, "Dict": Dict, "List": List, "Optional": Optional,
        # Production telemetry is intentionally disabled for this isolated evaluation.
        "log_event": lambda *args, **kwargs: None,
        **(seed or {}),
        "__name__": f"_research_evaluation_{path.stem}",
    }
    exec(compile(ast.Module(body=body, type_ignores=[]), str(path), "exec"), namespace)
    if names is not None and set(names) - set(namespace):
        raise ValueError(f"Missing evaluation definitions in {filename}.")
    return namespace


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
    schema = _definitions("functions_orchestration_schema.py", seed=registry)
    planner = _definitions(PLANNER_FILE, seed={**registry, **schema})
    context = _definitions("functions_orchestration_context.py", seed=registry, names={
        "HISTORY_MAX_TURNS", "HISTORY_TURN_LENGTH", "SELECTED_PROMPT_LENGTH",
        "_text", "_string_list", "_extract_urls", "_selected_prompt",
        "build_conversation_signals", "build_planner_context",
    })

    def no_configured_client(settings):
        raise planner["PlannerError"]("No explicit evaluation client was supplied.")

    planner["resolve_planner_client"] = no_configured_client
    with patch.dict(sys.modules, {"functions_source_review": review}):
        yield types.SimpleNamespace(
            planner=planner, registry=registry, schema=schema, context=context,
        )


def capture_baseline():
    """Capture the actual current prompt/projection, without invoking capability gates."""
    planner_source = (APP_ROOT / PLANNER_FILE).read_text(encoding="utf-8")
    registry_source = (APP_ROOT / REGISTRY_FILE).read_text(encoding="utf-8")
    planner_tree = ast.parse(planner_source)
    registry_tree = ast.parse(registry_source)
    config_tree = ast.parse((APP_ROOT / "config.py").read_text(encoding="utf-8"))
    registry = _definitions(REGISTRY_FILE)
    definitions = {}
    for name, tree, source in (
        ("PLANNER_SYSTEM_PROMPT", planner_tree, planner_source),
        ("build_planner_messages", planner_tree, planner_source),
        ("CAPABILITY_REGISTRY", registry_tree, registry_source),
        ("build_planner_capability_projection", registry_tree, registry_source),
    ):
        node = next(
            (item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name),
            None,
        )
        definitions[name] = ast.get_source_segment(source, node or _assignment(tree, name))
    return {
        "schema_version": 1,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "app_version": ast.literal_eval(_assignment(config_tree, "VERSION").value),
        "capture_method": (
            "AST literal extraction and execution of registry definitions only; "
            "no app imports or gates invoked"
        ),
        "planner_system_prompt": ast.literal_eval(
            _assignment(planner_tree, "PLANNER_SYSTEM_PROMPT").value
        ),
        "capabilities": registry["build_planner_capability_projection"](
            registry["CAPABILITY_REGISTRY"]
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
        "agent_catalog": [],
    }
    signals = runtime.context["build_conversation_signals"](
        case.get("prior_messages", []), case["message"],
    )
    context = runtime.context["build_planner_context"](
        case["message"], ledger=copy.deepcopy(case.get("earlier_runs")), signals=signals,
    )
    return settings, request_context, context
