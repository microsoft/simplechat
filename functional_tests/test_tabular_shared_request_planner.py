# test_tabular_shared_request_planner.py
"""
Functional test for the shared tabular request planner.
Version: 0.250.177
Implemented in: 0.250.158; Phase 6 execution units added in 0.250.162; rollout and fingerprint hardening in 0.250.167; Phase 7 harness compatibility in 0.250.177

This test ensures Phase 2 tabular request planning classifies Search and
Analyze caller metadata through one route-neutral planner before row retrieval.
"""

import ast
import logging
import os
import sys
import traceback
import types
import importlib

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, "application", "single_app")
SETTINGS_FILE = os.path.join(APP_ROOT, "functions_settings.py")
CHAT_ROUTE = os.path.join(APP_ROOT, "route_backend_chats.py")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)


def install_lightweight_planner_dependency_stubs():
    assistant_exports_module = types.ModuleType("functions_assistant_table_exports")
    assistant_exports_module.assistant_table_export_requested = (
        lambda prompt: "csv" in str(prompt or "").lower()
    )
    generated_exports_module = types.ModuleType("functions_generated_file_exports")

    def get_requested_artifact_formats(prompt):
        normalized_prompt = str(prompt or "").lower()
        return [output_format for output_format in ("json", "xml", "csv") if output_format in normalized_prompt]

    generated_exports_module.get_requested_artifact_formats = get_requested_artifact_formats
    generated_exports_module.get_requested_structured_artifact_format = (
        lambda prompt: next(iter(get_requested_artifact_formats(prompt)), None)
    )
    generated_exports_module.get_requested_structured_artifact_formats = get_requested_artifact_formats
    sys.modules.setdefault("functions_assistant_table_exports", assistant_exports_module)
    sys.modules.setdefault("functions_generated_file_exports", generated_exports_module)


install_lightweight_planner_dependency_stubs()

from functions_tabular_orchestration import (  # noqa: E402
    TABULAR_EXECUTION_CONTRACT_COMBINED,
    TABULAR_EXECUTION_CONTRACT_FOREGROUND_AGGREGATE,
    TABULAR_EXECUTION_CONTRACT_HIERARCHICAL_ANALYSIS,
    TABULAR_EXECUTION_CONTRACT_STRUCTURED_EXPORT,
    TABULAR_EXECUTION_STATE_DECLINED,
    TABULAR_EXECUTION_STATE_FOREGROUND,
    TABULAR_EXECUTION_STATE_QUEUED,
    TABULAR_ORCHESTRATION_PLANNER_CONTRACT_VERSION,
    get_tabular_generated_output_task_type,
    normalize_tabular_request_planner_mode,
    orchestrate_tabular_request,
    plan_tabular_request,
    question_requests_tabular_generated_output,
    question_requests_tabular_hierarchical_analysis,
)


def build_context(file_name="survey.csv", source_hint="workspace", source_version=None):
    return {
        "document_id": f"doc-{file_name}",
        "file_name": file_name,
        "source_hint": source_hint,
        "source_version": source_version or f"etag-{file_name}",
        "storage_locator": {
            "container": "documents",
            "blob_path": f"user/{file_name}",
        },
    }


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label):
    if not value:
        raise AssertionError(f"Expected truthy value for {label}")


def read_text(file_path):
    with open(file_path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def plan_for(prompt, caller="search", settings=None, contexts=None):
    return plan_tabular_request(
        prompt,
        contexts if contexts is not None else [build_context()],
        action_mode=caller,
        caller=caller,
        settings=settings or {"enable_tabular_hierarchical_analysis": True},
    )


def test_classification_contracts():
    print("Testing shared tabular planner classification contracts...")
    assert_app_version_at_least("0.250.158")

    cases = [
        (
            "Export every row as JSON with one object per row.",
            TABULAR_EXECUTION_CONTRACT_STRUCTURED_EXPORT,
            TABULAR_EXECUTION_CONTRACT_COMBINED,
            "json",
            "durable_intent",
        ),
        (
            "Analyze all rows and summarize the risk patterns.",
            TABULAR_EXECUTION_CONTRACT_HIERARCHICAL_ANALYSIS,
            TABULAR_EXECUTION_CONTRACT_HIERARCHICAL_ANALYSIS,
            None,
            "durable_intent",
        ),
        (
            "Analyze every row and create a CSV file with one output row per source row.",
            TABULAR_EXECUTION_CONTRACT_COMBINED,
            TABULAR_EXECUTION_CONTRACT_COMBINED,
            "csv",
            "durable_intent",
        ),
        (
            "What is the average score by department?",
            TABULAR_EXECUTION_CONTRACT_FOREGROUND_AGGREGATE,
            TABULAR_EXECUTION_CONTRACT_FOREGROUND_AGGREGATE,
            None,
            "bounded_foreground",
        ),
    ]
    for prompt, expected_search_contract, expected_analyze_contract, expected_format, expected_reason in cases:
        search_plan = plan_for(prompt, caller="search")
        analyze_plan = plan_for(prompt, caller="analyze")
        assert_equal(
            search_plan["planner_contract_version"],
            TABULAR_ORCHESTRATION_PLANNER_CONTRACT_VERSION,
            "planner contract version",
        )
        assert_equal(
            search_plan["execution_contract"],
            expected_search_contract,
            f"Search execution contract for {prompt}",
        )
        assert_equal(
            analyze_plan["execution_contract"],
            expected_analyze_contract,
            f"Analyze execution contract for {prompt}",
        )
        if expected_search_contract == expected_analyze_contract:
            assert_equal(
                search_plan["durable_task_type"],
                analyze_plan["durable_task_type"],
                f"caller parity durable task type for {prompt}",
            )
        assert_equal(search_plan["output_format"], expected_format, "output format")
        assert_equal(search_plan["reason_code"], expected_reason, "reason code")

    foreground_plan = plan_for("What is the average score by department?")
    assert_equal(
        foreground_plan["execution_state"],
        TABULAR_EXECUTION_STATE_FOREGROUND,
        "bounded foreground execution state",
    )
    print("Shared classification contract checks passed")


def test_replayable_context_boundaries():
    print("Testing shared tabular planner source-context boundaries...")
    exhaustive_prompt = "Analyze all rows and summarize the risk patterns."
    no_context_plan = plan_for(exhaustive_prompt, contexts=[])
    assert_equal(
        no_context_plan["execution_state"],
        TABULAR_EXECUTION_STATE_DECLINED,
        "missing context execution state",
    )
    assert_equal(
        no_context_plan["reason_code"],
        "no_replayable_tabular_context",
        "missing context reason code",
    )

    multi_context_plan = plan_for(
        exhaustive_prompt,
        contexts=[build_context("one.csv"), build_context("two.xlsx")],
    )
    assert_equal(
        multi_context_plan["execution_contract"],
        TABULAR_EXECUTION_CONTRACT_HIERARCHICAL_ANALYSIS,
        "multi-context durable contract remains explicit",
    )
    assert_equal(
        multi_context_plan["reason_code"],
        "multi_context_durable_not_enabled",
        "multi-context reason code",
    )

    disabled_plan = plan_for(
        exhaustive_prompt,
        settings={"enable_tabular_hierarchical_analysis": False},
    )
    assert_equal(
        disabled_plan["execution_contract"],
        TABULAR_EXECUTION_CONTRACT_FOREGROUND_AGGREGATE,
        "disabled hierarchical contract",
    )
    assert_equal(
        disabled_plan["reason_code"],
        "hierarchical_analysis_disabled",
        "disabled hierarchical reason code",
    )
    print("Source-context boundary checks passed")


def test_phase6_multifile_execution_units_are_explicit():
    print("Testing Phase 6 multi-file execution-unit planning...")
    exhaustive_prompt = "Analyze all rows and summarize the risk patterns."
    contexts = [
        build_context("one.csv", source_version="etag-one"),
        build_context("two.xlsx", source_version="etag-two"),
    ]

    gate_off_plan = plan_for(exhaustive_prompt, contexts=contexts)
    assert_equal(
        len(gate_off_plan["execution_units"]),
        1,
        "gate-off collective unit count",
    )
    assert_equal(
        gate_off_plan["execution_units"][0]["operation_relationship"],
        "collective",
        "gate-off operation relationship",
    )
    assert_equal(
        gate_off_plan["execution_units"][0]["source_count"],
        2,
        "gate-off collective source count",
    )

    gate_on_plan = plan_for(
        exhaustive_prompt,
        settings={
            "enable_tabular_hierarchical_analysis": True,
            "enable_tabular_multifile_execution_unit_planning": True,
        },
        contexts=contexts,
    )
    assert_equal(
        gate_on_plan["execution_state"],
        TABULAR_EXECUTION_STATE_DECLINED,
        "gate-on multi-file top-level state",
    )
    assert_equal(
        gate_on_plan["reason_code"],
        "multi_context_execution_units_unavailable",
        "gate-on multi-file reason code",
    )
    assert_true(gate_on_plan["safe_failure_details"], "gate-on unavailable detail")
    assert_equal(
        gate_on_plan["execution_group_id"],
        gate_on_plan["request_fingerprint"],
        "execution group fingerprint",
    )
    assert_equal(len(gate_on_plan["execution_units"]), 2, "gate-on unit count")
    assert_equal(
        [unit["request_order"] for unit in gate_on_plan["execution_units"]],
        [1, 2],
        "unit request order",
    )
    assert_equal(
        [unit["operation_relationship"] for unit in gate_on_plan["execution_units"]],
        ["independent", "independent"],
        "unit relationships",
    )
    assert_equal(
        [unit["source_ids"] for unit in gate_on_plan["execution_units"]],
        [["doc-one.csv"], ["doc-two.xlsx"]],
        "unit source ids",
    )
    assert_equal(
        [unit["source_versions"] for unit in gate_on_plan["execution_units"]],
        [["etag-one"], ["etag-two"]],
        "unit source versions",
    )
    assert_equal(
        {unit["required_completion_policy"] for unit in gate_on_plan["execution_units"]},
        {"all_units_required"},
        "unit completion policy",
    )
    assert_true(
        gate_on_plan["execution_units"][0]["idempotency_fingerprint"]
        != gate_on_plan["execution_units"][1]["idempotency_fingerprint"],
        "per-source idempotency fingerprints",
    )

    updated_source_plan = plan_for(
        exhaustive_prompt,
        settings={
            "enable_tabular_hierarchical_analysis": True,
            "enable_tabular_multifile_execution_unit_planning": True,
        },
        contexts=[
            build_context("one.csv", source_version="etag-one-updated"),
            build_context("two.xlsx", source_version="etag-two"),
        ],
    )
    assert_true(
        updated_source_plan["request_fingerprint"] != gate_on_plan["request_fingerprint"],
        "source-version request fingerprint",
    )
    assert_true(
        updated_source_plan["execution_units"][0]["idempotency_fingerprint"]
        != gate_on_plan["execution_units"][0]["idempotency_fingerprint"],
        "source-version unit fingerprint",
    )

    active_gate_on_result = orchestrate_tabular_request(
        exhaustive_prompt,
        contexts,
        action_mode="analyze",
        caller="analyze",
        settings={
            "enable_tabular_hierarchical_analysis": True,
            "enable_tabular_multifile_execution_unit_planning": True,
            "tabular_analyze_parity_rollout_percent": 0,
        },
        planner_mode="active",
        durable_execution_callback=lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("Multi-file planning must not invoke durable execution")
        ),
    )
    assert_equal(
        active_gate_on_result["reason_code"],
        "multi_context_execution_units_unavailable",
        "active multi-file unavailable reason",
    )
    assert_true(active_gate_on_result["safe_failure_details"], "active unavailable detail")
    print("Phase 6 multi-file execution-unit planning checks passed")


def test_compatibility_intent_helpers_delegate_to_shared_contract():
    print("Testing shared helper compatibility surface...")
    assert_true(
        question_requests_tabular_generated_output("Export every row as JSON."),
        "generated output intent",
    )
    assert_true(
        question_requests_tabular_hierarchical_analysis("Analyze all rows for themes."),
        "hierarchical analysis intent",
    )
    assert_equal(
        get_tabular_generated_output_task_type(True, False, {}),
        TABULAR_EXECUTION_CONTRACT_STRUCTURED_EXPORT,
        "structured export task type",
    )
    print("Compatibility helper checks passed")


def test_shadow_and_active_facade_side_effect_boundaries():
    print("Testing shadow and active facade side-effect boundaries...")
    calls = []

    def fake_durable_executor(plan, **execution_context):
        calls.append({"plan": plan, "execution_context": execution_context})
        return {
            "export_run_id": "run-123",
            "status": "queued",
            "task_type": plan["durable_task_type"],
        }

    prompt = "Analyze every row and create a CSV file with one output row per source row."
    assert_equal(normalize_tabular_request_planner_mode({}, mode="invalid"), "off", "invalid mode")
    shadow_result = orchestrate_tabular_request(
        prompt,
        [build_context()],
        action_mode="analyze",
        caller="analyze",
        settings={"enable_tabular_hierarchical_analysis": True},
        planner_mode="shadow",
        durable_execution_callback=fake_durable_executor,
    )
    assert_equal(len(calls), 0, "shadow executor calls")
    assert_equal(shadow_result["planner_mode"], "shadow", "shadow planner mode")
    assert_equal(shadow_result["execution_contract"], TABULAR_EXECUTION_CONTRACT_COMBINED, "shadow contract")
    assert_equal(shadow_result["shadow_side_effects"], False, "shadow side effects")

    idempotency_cache = {}
    first_active_result = orchestrate_tabular_request(
        prompt,
        [build_context()],
        action_mode="analyze",
        caller="analyze",
        settings={"enable_tabular_hierarchical_analysis": True},
        planner_mode="active",
        durable_execution_callback=fake_durable_executor,
        idempotency_cache=idempotency_cache,
        workflow_id="workflow-123",
    )
    second_active_result = orchestrate_tabular_request(
        prompt,
        [build_context()],
        action_mode="analyze",
        caller="analyze",
        settings={"enable_tabular_hierarchical_analysis": True},
        planner_mode="active",
        durable_execution_callback=fake_durable_executor,
        idempotency_cache=idempotency_cache,
        workflow_id="workflow-123",
    )
    assert_equal(len(calls), 1, "active executor calls with idempotency cache")
    assert_equal(first_active_result["execution_state"], TABULAR_EXECUTION_STATE_QUEUED, "first active state")
    assert_equal(second_active_result["reason_code"], "active_execution_reused", "reused active reason")
    assert_equal(
        calls[0]["execution_context"].get("workflow_id"),
        "workflow-123",
        "execution context propagation",
    )

    rollout_call_count = len(calls)
    excluded_result = orchestrate_tabular_request(
        prompt,
        [build_context()],
        action_mode="analyze",
        caller="analyze",
        settings={
            "enable_tabular_hierarchical_analysis": True,
            "tabular_analyze_parity_rollout_percent": 0,
        },
        planner_mode="active",
        durable_execution_callback=fake_durable_executor,
    )
    assert_equal(len(calls), rollout_call_count, "rollout-excluded executor calls")
    assert_equal(excluded_result["execution_state"], TABULAR_EXECUTION_STATE_DECLINED, "rollout state")
    assert_equal(excluded_result["reason_code"], "rollout_not_assigned", "rollout reason")
    print("Facade side-effect boundary checks passed")


def test_backend_rollout_settings_are_not_frontend_visible():
    print("Testing backend rollout setting sanitization coverage...")
    settings_source = read_text(SETTINGS_FILE)
    for setting_key in (
        "tabular_request_planner_mode",
        "enable_tabular_search_shared_preflight",
        "enable_tabular_analyze_durable_preflight",
        "enable_tabular_multifile_execution_unit_planning",
    ):
        assert_true(
            f"'{setting_key}'" in settings_source,
            f"default setting {setting_key}",
        )
        backend_key_start = settings_source.index("TABULAR_GENERATION_BACKEND_SETTING_KEYS = {")
        sanitizer_start = settings_source.index("def sanitize_settings_for_user")
        backend_key_source = settings_source[backend_key_start:sanitizer_start]
        assert_true(
            f"'{setting_key}'" in backend_key_source,
            f"backend-only setting denylist {setting_key}",
        )
    print("Backend rollout setting sanitization checks passed")


def test_active_facade_can_use_existing_direct_preflight_adapter():
    print("Testing active facade direct preflight adapter...")
    tabular_analysis = importlib.import_module("functions_tabular_analysis")
    original_loader = tabular_analysis._load_chat_helper
    calls = []

    def fake_direct_preflight(**kwargs):
        calls.append(kwargs)
        return {
            "background_export": True,
            "export_run_id": "direct-run-123",
            "task_type": "combined",
        }

    try:
        tabular_analysis._load_chat_helper = lambda helper_name: fake_direct_preflight
        result = tabular_analysis.orchestrate_tabular_request(
            "Analyze every row and create a CSV file with one output row per source row.",
            [build_context()],
            action_mode="search",
            caller="search",
            settings={"enable_tabular_hierarchical_analysis": True},
            planner_mode="active",
            durable_execution_callback=tabular_analysis.queue_direct_tabular_generated_output_from_plan,
            user_id="user-1",
            conversation_id="conversation-1",
            gpt_model="gpt-4o",
        )
    finally:
        tabular_analysis._load_chat_helper = original_loader

    assert_equal(len(calls), 1, "direct preflight adapter call count")
    assert_equal(calls[0]["user_id"], "user-1", "adapter user id")
    assert_equal(calls[0]["conversation_id"], "conversation-1", "adapter conversation id")
    assert_equal(result["execution_state"], TABULAR_EXECUTION_STATE_QUEUED, "adapter active state")
    assert_equal(result["generated_output_metadata"]["export_run_id"], "direct-run-123", "adapter metadata")
    print("Direct preflight adapter checks passed")


def test_direct_preflight_uses_planner_action_mode_for_parity_events():
    print("Testing route-neutral direct preflight telemetry mode...")
    route_source = read_text(CHAT_ROUTE)
    module_tree = ast.parse(route_source, filename=CHAT_ROUTE)
    function_node = next(
        node for node in module_tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "maybe_queue_direct_tabular_generated_output"
    )
    parity_modes = []
    namespace = {
        "classify_tabular_parity_request": lambda prompt: {"execution_contract": "combined"},
        "emit_tabular_parity_event": lambda settings, event_name, mode, **kwargs: parity_modes.append(mode),
        "_build_direct_tabular_generated_output_source": lambda *args, **kwargs: None,
        "logging": logging,
    }
    exec(compile(ast.Module(body=[function_node], type_ignores=[]), CHAT_ROUTE, "exec"), namespace)

    result = namespace["maybe_queue_direct_tabular_generated_output"](
        user_question="Analyze every row.",
        file_contexts=[build_context()],
        user_id="user-1",
        conversation_id="conversation-1",
        gpt_model="gpt-4o",
        settings={},
        planner_metadata={"action_mode": "analyze"},
    )

    assert_equal(result, None, "declined direct preflight result")
    assert_true(parity_modes, "direct preflight parity events")
    assert_equal(set(parity_modes), {"analyze"}, "direct preflight parity modes")
    print("Route-neutral direct preflight telemetry checks passed")


def run_tests():
    tests = [
        test_classification_contracts,
        test_replayable_context_boundaries,
        test_phase6_multifile_execution_units_are_explicit,
        test_compatibility_intent_helpers_delegate_to_shared_contract,
        test_shadow_and_active_facade_side_effect_boundaries,
        test_backend_rollout_settings_are_not_frontend_visible,
        test_active_facade_can_use_existing_direct_preflight_adapter,
        test_direct_preflight_uses_planner_action_mode_for_parity_events,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"Test failed: {exc}")
            traceback.print_exc()
            results.append(False)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)
