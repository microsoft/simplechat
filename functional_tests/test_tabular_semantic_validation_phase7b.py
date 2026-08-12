# test_tabular_semantic_validation_phase7b.py
#!/usr/bin/env python3
"""
Functional test for Phase 7B semantic field verification and targeted repair.
Version: 0.250.179
Implemented in: 0.250.179

This test ensures verifier output is exact and bounded, repairs only failed or
uncertain row fields, and persists only safe aggregate counts.
"""

import asyncio
import ast
import hashlib
import json
import logging
import sys
import time
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from functions_tabular_semantic_validation import (  # noqa: E402
    TABULAR_SEMANTIC_VALIDATION_CONTRACT_VERSION,
    TabularSemanticValidationError,
    apply_semantic_repair_response,
    build_safe_semantic_validation_counts,
    build_semantic_verification_request,
    collect_semantic_repair_targets,
    normalize_semantic_verification_response,
    verify_and_repair_semantic_rows,
)
from functions_analysis_deliverables import is_analysis_internal_lineage_field  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


IMPLEMENTED_VERSION = "0.250.179"
EXPORT_MODULE = APP_ROOT / "functions_tabular_generated_exports.py"


def _load_runner_semantic_helpers():
    source = EXPORT_MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(EXPORT_MODULE))
    helper_names = {
        "_safe_int",
        "_safe_float",
        "_dump_generated_output_json",
        "_get_tabular_generation_plan_public_fields",
        "_build_tabular_semantic_field_guidance",
        "_build_tabular_semantic_verification_prompt",
        "_build_tabular_semantic_repair_prompt",
        "_invoke_tabular_semantic_model",
        "_verify_and_repair_tabular_batch_entries",
        "_generate_batch_entries_for_window",
        "_semantic_candidate_blob_path",
        "_get_tabular_semantic_checkpoint_contract_hash",
        "_build_tabular_semantic_checkpoint_context",
        "_persist_tabular_semantic_candidate_checkpoint",
        "_load_tabular_semantic_candidate_checkpoint",
    }
    selected_nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in helper_names
    ]
    if len(selected_nodes) != len(helper_names):
        raise AssertionError("Missing runner semantic validation helpers")

    class ChatHistory:
        def __init__(self):
            self.messages = []

        def add_system_message(self, message):
            self.messages.append(("system", message))

        def add_user_message(self, message):
            self.messages.append(("user", message))

    class ExecutionSettings:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    blobs = {}

    def upload_json_blob(path, payload, metadata=None, overwrite=True):
        del metadata, overwrite
        blobs[path] = payload

    namespace = {
        "asyncio": asyncio,
        "hashlib": hashlib,
        "json": json,
        "logging": logging,
        "time": time,
        "SKChatHistory": ChatHistory,
        "AzureChatPromptExecutionSettings": ExecutionSettings,
        "TABULAR_EXPORT_DEFAULT_BATCH_TIMEOUT_SECONDS": 120,
        "TABULAR_EXPORT_OUTPUT_ROW_NUMBER_FIELD": "source_row_number",
        "TABULAR_EXPORT_OUTPUT_ROW_IDENTITY_FIELD": "source_row_identity",
        "TABULAR_GENERATION_PLAN_MAX_QUESTION_CHARS": 24000,
        "TABULAR_SEMANTIC_MAX_PROMPT_CHARS": 180000,
        "TABULAR_SEMANTIC_CANDIDATE_CHECKPOINT_VERSION": 1,
        "TABULAR_SEMANTIC_VALIDATION_CONTRACT_VERSION": TABULAR_SEMANTIC_VALIDATION_CONTRACT_VERSION,
        "is_analysis_internal_lineage_field": is_analysis_internal_lineage_field,
        "verify_and_repair_semantic_rows": verify_and_repair_semantic_rows,
        "_parse_generated_json_object": lambda content: json.loads(content),
        "_build_generated_batch_summary": lambda entries: {"row_count": len(entries)},
        "_blob_exists": lambda path: path in blobs,
        "_download_json_blob": lambda path: blobs[path],
        "_upload_json_blob": upload_json_blob,
        "log_event": lambda *args, **kwargs: None,
    }
    module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(EXPORT_MODULE), "exec"), namespace)
    return namespace


def _transformation_spec():
    return {
        "version": "tabular-transform-v1",
        "fields": [
            {
                "name": "Item_ID",
                "mode": "deterministic",
                "type": "string",
                "nullable": False,
                "expression": {"op": "copy", "source": "Item_ID"},
            },
            {
                "name": "Risk",
                "mode": "semantic",
                "type": "string",
                "nullable": False,
                "allowed_values": ["High", "Medium", "Low"],
            },
        ],
    }


def test_semantic_verifier_and_targeted_repair_contract():
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    source_rows = [
        {"Item_ID": "A", "Narrative": "Urgent unresolved issue"},
        {"Item_ID": "B", "Narrative": "Routine review"},
    ]
    output_rows = [
        {"Item_ID": "A", "Risk": "Low"},
        {"Item_ID": "B", "Risk": "Low"},
    ]
    request = build_semantic_verification_request(source_rows, output_rows, _transformation_spec())
    report = normalize_semantic_verification_response(
        {
            "version": TABULAR_SEMANTIC_VALIDATION_CONTRACT_VERSION,
            "rows": [
                {
                    "row_key": "r1",
                    "fields": [{
                        "name": "Risk",
                        "status": "fail",
                        "reason_code": "source_conflict",
                        "evidence_fields": ["Narrative"],
                    }],
                },
                {
                    "row_key": "r2",
                    "fields": [{
                        "name": "Risk",
                        "status": "pass",
                        "reason_code": "source_supported",
                        "evidence_fields": ["Narrative"],
                    }],
                },
            ],
        },
        request,
    )
    targets = collect_semantic_repair_targets(report)
    assert targets == [{"row_key": "r1", "field_name": "Risk", "reason_code": "source_conflict"}]

    repaired_rows = apply_semantic_repair_response(
        output_rows,
        {
            "version": TABULAR_SEMANTIC_VALIDATION_CONTRACT_VERSION,
            "rows": [{"row_key": "r1", "values": {"Risk": "High"}}],
        },
        targets,
        _transformation_spec(),
    )
    assert repaired_rows == [
        {"Item_ID": "A", "Risk": "High"},
        {"Item_ID": "B", "Risk": "Low"},
    ]
    assert build_safe_semantic_validation_counts(report, targets, 1) == {
        "pass_count": 1,
        "fail_count": 1,
        "uncertain_count": 0,
        "unsupported_count": 0,
        "repair_target_count": 1,
        "repair_attempt_count": 1,
    }


def test_semantic_repair_rejects_extra_or_invalid_fields():
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    rows = [{"Item_ID": "A", "Risk": "Low"}]
    targets = [{"row_key": "r1", "field_name": "Risk", "reason_code": "source_conflict"}]
    invalid_payloads = [
        {
            "version": TABULAR_SEMANTIC_VALIDATION_CONTRACT_VERSION,
            "rows": [{"row_key": "r1", "values": {"Risk": "Critical"}}],
        },
        {
            "version": TABULAR_SEMANTIC_VALIDATION_CONTRACT_VERSION,
            "rows": [{"row_key": "r1", "values": {"Risk": "High", "Item_ID": "B"}}],
        },
    ]
    for payload in invalid_payloads:
        try:
            apply_semantic_repair_response(rows, payload, targets, _transformation_spec())
        except TabularSemanticValidationError:
            continue
        raise AssertionError("Invalid semantic repair payload was accepted")

    number_spec = {
        "version": "tabular-transform-v1",
        "fields": [{"name": "Score", "mode": "semantic", "type": "number", "nullable": False}],
    }
    try:
        apply_semantic_repair_response(
            [{"Score": 0}],
            {
                "version": TABULAR_SEMANTIC_VALIDATION_CONTRACT_VERSION,
                "rows": [{"row_key": "r1", "values": {"Score": float("nan")}}],
            },
            [{"row_key": "r1", "field_name": "Score", "reason_code": "invalid_number"}],
            number_spec,
        )
    except TabularSemanticValidationError:
        pass
    else:
        raise AssertionError("Non-finite semantic repair values must be rejected")


def test_active_semantic_validation_repairs_then_reverifies():
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    source_rows = [{"Item_ID": "A", "Narrative": "Urgent unresolved issue"}]
    output_rows = [{"Item_ID": "A", "Risk": "Low"}]
    verifier_calls = []
    repair_calls = []

    async def invoke_verifier(request):
        verifier_calls.append(request)
        status = "fail" if request["rows"][0]["candidate"]["Risk"] == "Low" else "pass"
        return {
            "version": TABULAR_SEMANTIC_VALIDATION_CONTRACT_VERSION,
            "rows": [{
                "row_key": "r1",
                "fields": [{
                    "name": "Risk",
                    "status": status,
                    "reason_code": "source_conflict" if status == "fail" else "source_supported",
                    "evidence_fields": ["Narrative"],
                }],
            }],
        }

    async def invoke_repair(request, targets, attempt_number):
        repair_calls.append((request, targets, attempt_number))
        return {
            "version": TABULAR_SEMANTIC_VALIDATION_CONTRACT_VERSION,
            "rows": [{"row_key": "r1", "values": {"Risk": "High"}}],
        }

    repaired_rows, counts, attempts = asyncio.run(verify_and_repair_semantic_rows(
        source_rows,
        output_rows,
        _transformation_spec(),
        "active",
        invoke_verifier,
        invoke_repair,
        max_repair_attempts=2,
        max_repair_rows=10,
    ))
    assert repaired_rows[0]["Risk"] == "High"
    assert len(verifier_calls) == 2
    assert len(repair_calls) == 1
    assert counts["pass_count"] == 1
    assert counts["repair_attempt_count"] == 1
    assert attempts[-1]["fail_count"] == 0


def test_runner_invokes_verifier_and_repair_before_checkpoint_boundary():
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    helpers = _load_runner_semantic_helpers()

    class SemanticModel:
        def __init__(self):
            self.service_ids = []

        async def get_chat_message_contents(self, chat_history, execution_settings):
            del chat_history
            service_id = execution_settings.kwargs["service_id"]
            self.service_ids.append(service_id)
            if self.service_ids == ["tabular-generated-output-semantic-verifier"]:
                payload = {
                    "version": TABULAR_SEMANTIC_VALIDATION_CONTRACT_VERSION,
                    "rows": [{
                        "row_key": "r1",
                        "fields": [{
                            "name": "Risk",
                            "status": "fail",
                            "reason_code": "source_conflict",
                            "evidence_fields": ["Narrative"],
                        }],
                    }],
                }
            elif service_id == "tabular-generated-output-semantic-repair":
                payload = {
                    "version": TABULAR_SEMANTIC_VALIDATION_CONTRACT_VERSION,
                    "rows": [{"row_key": "r1", "values": {"Risk": "High"}}],
                }
            else:
                payload = {
                    "version": TABULAR_SEMANTIC_VALIDATION_CONTRACT_VERSION,
                    "rows": [{
                        "row_key": "r1",
                        "fields": [{
                            "name": "Risk",
                            "status": "pass",
                            "reason_code": "source_supported",
                            "evidence_fields": ["Narrative"],
                        }],
                    }],
                }
            return [SimpleNamespace(content=json.dumps(payload))]

    model = SemanticModel()
    generation_plan = {
        "output_fields": [
            {
                "name": "source_row_number",
                "description": "Server row number.",
                "type": "integer",
                "nullable": False,
                "source": "server",
            },
            {
                "name": "source_row_identity",
                "description": "Server row identity.",
                "type": "string",
                "nullable": False,
                "source": "server",
            },
            {
                "name": "Risk",
                "description": "Risk supported by the narrative evidence.",
                "type": "string",
                "nullable": False,
                "source": "llm",
            },
        ],
    }
    repaired_rows, counts, _attempts = asyncio.run(
        helpers["_verify_and_repair_tabular_batch_entries"](
            model,
            "Classify risk from the narrative.",
            [{
                "Narrative": "Urgent unresolved issue",
                "__simplechat_source_row_number": 1,
                "__simplechat_source_row_identity": "A",
            }],
            [{"source_row_number": 1, "source_row_identity": "A", "Risk": "Low"}],
            _transformation_spec(),
            generation_plan,
            {"mode": "active", "max_repair_attempts": 2, "max_repair_rows": 10},
            30,
        )
    )
    assert repaired_rows[0]["Risk"] == "High"
    assert counts["pass_count"] == 1
    assert model.service_ids == [
        "tabular-generated-output-semantic-verifier",
        "tabular-generated-output-semantic-repair",
        "tabular-generated-output-semantic-verifier",
    ]

    tree = ast.parse(EXPORT_MODULE.read_text(encoding="utf-8"), filename=str(EXPORT_MODULE))
    generate_function = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_generate_batch_entries"
    )
    called_functions = {
        call.func.id
        for call in ast.walk(generate_function)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
    }
    assert "_verify_and_repair_tabular_batch_entries" in called_functions
    assert "_checkpoint_generated_batch_results" not in called_functions


def test_shadow_semantic_validation_observes_without_repairing():
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    repair_calls = []

    async def invoke_verifier(request):
        del request
        return {
            "version": TABULAR_SEMANTIC_VALIDATION_CONTRACT_VERSION,
            "rows": [{
                "row_key": "r1",
                "fields": [{
                    "name": "Risk",
                    "status": "uncertain",
                    "reason_code": "insufficient_evidence",
                    "evidence_fields": ["Narrative"],
                }],
            }],
        }

    async def invoke_repair(*args):
        repair_calls.append(args)
        raise AssertionError("Shadow validation must not repair rows")

    rows = [{"Item_ID": "A", "Risk": "Low"}]
    observed_rows, counts, attempts = asyncio.run(verify_and_repair_semantic_rows(
        [{"Item_ID": "A", "Narrative": "Ambiguous evidence"}],
        rows,
        _transformation_spec(),
        "shadow",
        invoke_verifier,
        invoke_repair,
    ))
    assert observed_rows == rows
    assert repair_calls == []
    assert attempts == []
    assert counts["uncertain_count"] == 1
    assert counts["repair_target_count"] == 1


def test_active_semantic_repair_exhaustion_fails_closed():
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    repair_values = iter(["High", "Medium"])

    async def invoke_verifier(request):
        del request
        return {
            "version": TABULAR_SEMANTIC_VALIDATION_CONTRACT_VERSION,
            "rows": [{
                "row_key": "r1",
                "fields": [{
                    "name": "Risk",
                    "status": "fail",
                    "reason_code": "source_conflict",
                    "evidence_fields": ["Narrative"],
                }],
            }],
        }

    async def invoke_repair(request, targets, attempt_number):
        del request, targets, attempt_number
        return {
            "version": TABULAR_SEMANTIC_VALIDATION_CONTRACT_VERSION,
            "rows": [{"row_key": "r1", "values": {"Risk": next(repair_values)}}],
        }

    try:
        asyncio.run(verify_and_repair_semantic_rows(
            [{"Item_ID": "A", "Narrative": "Conflicting evidence"}],
            [{"Item_ID": "A", "Risk": "Low"}],
            _transformation_spec(),
            "active",
            invoke_verifier,
            invoke_repair,
            max_repair_attempts=2,
            max_repair_rows=10,
        ))
    except TabularSemanticValidationError as exc:
        assert "exhausted" in str(exc).lower()
    else:
        raise AssertionError("Unresolved semantic failures must not reach checkpointing")


def test_batch_wrapper_persists_only_safe_semantic_counts():
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    helpers = _load_runner_semantic_helpers()

    async def generate_batch_entries(*args, **kwargs):
        del args, kwargs
        return (
            [{"source_row_number": 1, "source_row_identity": "A", "Risk": "High"}],
            0,
            ["source_row_number", "source_row_identity", "Risk"],
            {
                "semantic_validation_counts": {
                    "pass_count": 1,
                    "fail_count": 0,
                    "uncertain_count": 0,
                    "unsupported_count": 0,
                    "repair_target_count": 0,
                    "repair_attempt_count": 1,
                },
                "semantic_validation_attempts": [{
                    "pass_count": 1,
                    "fail_count": 0,
                    "uncertain_count": 0,
                    "unsupported_count": 0,
                    "repair_target_count": 0,
                    "repair_attempt_count": 1,
                }],
            },
        )

    helpers["_generate_batch_entries"] = generate_batch_entries
    result = asyncio.run(helpers["_generate_batch_entries_for_window"](
        asyncio.Semaphore(1),
        object(),
        "Classify risk.",
        {"batch_number": 1, "rows": [{"Narrative": "Urgent"}]},
        1,
        "source.csv",
        None,
        1,
        "run-1",
        ["source_row_number", "source_row_identity", "Risk"],
        30,
        "object-v1",
        None,
        _transformation_spec(),
        {"mode": "active"},
        None,
    ))
    assert result["semantic_validation_counts"]["pass_count"] == 1
    assert result["batch_summary"]["semantic_validation"]["final"]["repair_attempt_count"] == 1
    assert "Narrative" not in json.dumps(result["batch_summary"], sort_keys=True)


def test_semantic_candidate_checkpoint_is_restart_safe_and_plan_fenced():
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    helpers = _load_runner_semantic_helpers()
    run = {
        "id": "run-1",
        "user_id": "user-1",
        "conversation_id": "conversation-1",
        "plan_hash": "a" * 64,
    }
    context = helpers["_build_tabular_semantic_checkpoint_context"](run, 1)
    rows = [{"source_row_number": 1, "source_row_identity": "A", "Risk": "High"}]
    schema = ["source_row_number", "source_row_identity", "Risk"]
    helpers["_persist_tabular_semantic_candidate_checkpoint"](
        context,
        schema,
        rows,
        {"pass_count": 1, "repair_attempt_count": 1},
        1,
    )
    checkpoint = helpers["_load_tabular_semantic_candidate_checkpoint"](
        context,
        schema,
        1,
    )
    assert checkpoint["rows"] == rows
    assert checkpoint["repair_attempt_count"] == 1
    assert checkpoint["validation_counts"] == {"pass_count": 1, "repair_attempt_count": 1}

    wrong_plan_context = {**context, "plan_hash": "b" * 64}
    try:
        helpers["_load_tabular_semantic_candidate_checkpoint"](
            wrong_plan_context,
            schema,
            1,
        )
    except ValueError as exc:
        assert "plan hash" in str(exc).lower()
    else:
        raise AssertionError("A stale semantic candidate must not cross plan generations")

    supplied_contract_run = {
        "id": "run-2",
        "user_id": "user-1",
        "conversation_id": "conversation-1",
        "plan_hash": None,
        "public_output_schema": ["Risk"],
        "transformation_spec": _transformation_spec(),
    }
    supplied_context = helpers["_build_tabular_semantic_checkpoint_context"](
        supplied_contract_run,
        1,
    )
    assert len(supplied_context["plan_hash"]) == 64

    tree = ast.parse(EXPORT_MODULE.read_text(encoding="utf-8"), filename=str(EXPORT_MODULE))
    generate_function = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_generate_batch_entries"
    )
    generate_source = ast.unparse(generate_function)
    assert generate_source.index("_load_tabular_semantic_candidate_checkpoint") < generate_source.index(
        "_build_batch_prompt"
    )


if __name__ == "__main__":
    tests = [
        test_semantic_verifier_and_targeted_repair_contract,
        test_semantic_repair_rejects_extra_or_invalid_fields,
        test_active_semantic_validation_repairs_then_reverifies,
        test_runner_invokes_verifier_and_repair_before_checkpoint_boundary,
        test_shadow_semantic_validation_observes_without_repairing,
        test_active_semantic_repair_exhaustion_fails_closed,
        test_batch_wrapper_persists_only_safe_semantic_counts,
        test_semantic_candidate_checkpoint_is_restart_safe_and_plan_fenced,
    ]
    results = []
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
            results.append(True)
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
            results.append(False)
    print(f"Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
