#!/usr/bin/env python3
# test_analysis_unavailable_message_families.py
"""
Functional test for the wording of AnalysisResultUnavailable by message family.
Version: 0.261.233
Implemented in: 0.261.233

This test ensures every AnalysisResultUnavailable raised in application/single_app has a
determined message family (a source document, the conversation, workflow or run that holds a
result, or the saved result itself), that each family has its own plain wording, that the
workflow runner, chat routes and progress route show the family's message, and that the
codes and HTTP statuses callers depend on are unchanged.
"""

import ast
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))

# Application and fixture imports follow the module-path setup.
from functions_analysis_access import (  # noqa: E402
    ANALYSIS_CONTAINER_UNAVAILABLE_CODES,
    ANALYSIS_SAVED_RESULT_UNAVAILABLE_CODES,
    ANALYSIS_SOURCE_UNAVAILABLE_CODES,
    ANALYSIS_UNAVAILABLE_CONTAINER,
    ANALYSIS_UNAVAILABLE_MESSAGES,
    ANALYSIS_UNAVAILABLE_SAVED_RESULT,
    ANALYSIS_UNAVAILABLE_SOURCE,
    AnalysisResultUnavailable,
    analysis_unavailable_family,
    authorize_analysis_sources,
    resolve_analysis_source_manifest,
)
from functions_document_analysis_results import index_analysis_source_manifest  # noqa: E402
from test_analyze_backend_saved_integration import analyze_body, chat, followup_body, saved, saved_chat  # noqa: E402,F401
from test_support.app_stubs import stubbed_config  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_workflow_task_result_handoff import build_inventory_run  # noqa: E402


IMPLEMENTED_VERSION = "0.261.233"
SOURCE_MESSAGE = "A source document for this analysis is no longer available or has changed."
CONTAINER_MESSAGE = (
    "The conversation, workflow or run that holds this result no longer exists or isn't available to you."
)
SAVED_RESULT_MESSAGE = "This saved result can't be used because something it depends on is missing or has changed."
FAMILY_CODES = {
    ANALYSIS_UNAVAILABLE_SOURCE: ANALYSIS_SOURCE_UNAVAILABLE_CODES,
    ANALYSIS_UNAVAILABLE_CONTAINER: ANALYSIS_CONTAINER_UNAVAILABLE_CODES,
    ANALYSIS_UNAVAILABLE_SAVED_RESULT: ANALYSIS_SAVED_RESULT_UNAVAILABLE_CODES,
}
FAMILY_CONSTANTS = {
    "ANALYSIS_UNAVAILABLE_SOURCE": ANALYSIS_UNAVAILABLE_SOURCE,
    "ANALYSIS_UNAVAILABLE_CONTAINER": ANALYSIS_UNAVAILABLE_CONTAINER,
    "ANALYSIS_UNAVAILABLE_SAVED_RESULT": ANALYSIS_UNAVAILABLE_SAVED_RESULT,
}
CODE_FAMILIES = {code: family for family, codes in FAMILY_CODES.items() for code in codes}
# The one raise whose code is computed: loop document re-authorization passes its own code through.
# Its possible codes are resolved from functions_workflow_loop_inputs below.
RESOLVED_DYNAMIC_RAISES = {("functions_workflow_iterations.py", "_authorize_frozen_document")}
# One representative code per family, raised for real by the runner and route checks below.
FAMILY_SAMPLES = {
    ANALYSIS_UNAVAILABLE_SOURCE: "analysis_source_snapshot_changed",
    ANALYSIS_UNAVAILABLE_CONTAINER: "analysis_conversation_deleted",
    ANALYSIS_UNAVAILABLE_SAVED_RESULT: "analysis_lineage_invalid",
}


def _name_of(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _family_of(node):
    if isinstance(node, ast.Constant) and node.value in ANALYSIS_UNAVAILABLE_MESSAGES:
        return node.value
    return FAMILY_CONSTANTS.get(_name_of(node))


def _raise_sites():
    for path in sorted(APP_ROOT.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "AnalysisResultUnavailable" not in source:
            continue
        tree = ast.parse(source, filename=str(path))
        enclosing = {}
        # Breadth-first, so a nested function's name replaces its parent's for its own body.
        for function in ast.walk(tree):
            if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for child in ast.walk(function):
                    enclosing[child] = function.name
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _name_of(node.func) == "AnalysisResultUnavailable":
                yield path.relative_to(APP_ROOT).as_posix(), node, enclosing.get(node)


def _site_problem(path, node, function):
    location = f"{path}:{node.lineno} in {function or 'module scope'}"
    keywords = {keyword.arg: keyword.value for keyword in node.keywords}
    if None in keywords or any(isinstance(argument, ast.Starred) for argument in node.args):
        return f"{location}: pass the code and family explicitly, not through * or ** arguments"
    if len(node.args) > 1:
        return f"{location}: family is keyword-only"
    code = node.args[0] if node.args else keywords.get("code")
    family = keywords.get("family")
    if family is not None and _family_of(family) is None:
        return f"{location}: family= must be one of the ANALYSIS_UNAVAILABLE_* constants"
    if code is None:
        return f"{location}: a bare raise relies on the default code; pass the code that describes this check"
    if isinstance(code, ast.Constant) and isinstance(code.value, str):
        if code.value not in CODE_FAMILIES:
            return f"{location}: {code.value!r} is not classified in functions_analysis_access"
        return None
    if (path, function) in RESOLVED_DYNAMIC_RAISES or family is not None:
        return None
    return f"{location}: a computed code needs family= or a reviewed resolution in this test"


def _loop_reauthorization_codes():
    """Every WorkflowLoopInputError code reauthorize_workflow_loop_document can raise."""
    limits = ast.parse((APP_ROOT / "functions_workflow_limits.py").read_text(encoding="utf-8"))
    defaults = {}
    for node in limits.body:
        if isinstance(node, ast.ClassDef) and node.name in {"WorkflowLoopInputError", "WorkflowLoopLimitError"}:
            init = next(item for item in node.body if isinstance(item, ast.FunctionDef) and item.name == "__init__")
            for argument, default in zip(init.args.kwonlyargs, init.args.kw_defaults):
                if argument.arg == "code":
                    defaults[node.name] = default.value
    tree = ast.parse((APP_ROOT / "functions_workflow_loop_inputs.py").read_text(encoding="utf-8"))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    pending, visited, codes = ["reauthorize_workflow_loop_document"], set(), set()
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        for node in ast.walk(functions[name]):
            if isinstance(node, ast.Name) and node.id in functions:
                pending.append(node.id)
            if isinstance(node, ast.Call) and _name_of(node.func) in defaults:
                code = next((keyword.value for keyword in node.keywords if keyword.arg == "code"), None)
                if code is None:
                    codes.add(defaults[_name_of(node.func)])
                else:
                    codes.add(code.value if isinstance(code, ast.Constant) else None)
    return codes


def test_every_application_raise_has_a_determined_family():
    """A new raise must name a classified code, so it can't silently get another family's text."""
    print("Testing every AnalysisResultUnavailable raise for a determined message family...")
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    sites = list(_raise_sites())
    problems = [problem for problem in (_site_problem(*site) for site in sites) if problem]
    assert not problems, "Unclassified AnalysisResultUnavailable raises:\n" + "\n".join(problems)
    literal_codes = {
        site[1].args[0].value for site in sites
        if site[1].args and isinstance(site[1].args[0], ast.Constant)
    }
    # The scan is meaningful only if it still finds the raises it was written against.
    assert len(sites) >= 150
    assert {CODE_FAMILIES[code] for code in literal_codes} == set(FAMILY_CODES)
    print("Test passed!")


def test_family_overrides_are_explicit_at_shared_code_sites():
    """Shared codes whose raise site checks something else carry family= at that site only."""
    overrides = {
        (path, node.args[0].value, _family_of(keyword.value))
        for path, node, _function in _raise_sites()
        for keyword in node.keywords if keyword.arg == "family"
    }
    assert overrides == {
        ("functions_analysis_access.py", "analysis_source_manifest_invalid", ANALYSIS_UNAVAILABLE_SOURCE),
        ("functions_document_analysis_results.py", "analysis_source_manifest_invalid", ANALYSIS_UNAVAILABLE_SOURCE),
        ("functions_workflow_artifacts.py", "generated_artifact_source_unavailable", ANALYSIS_UNAVAILABLE_SAVED_RESULT),
    }


def test_loop_document_codes_passed_through_are_source_codes():
    """The computed code in _authorize_frozen_document comes from a loop input read."""
    source = (APP_ROOT / "functions_workflow_iterations.py").read_text(encoding="utf-8")
    function = next(
        node for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == "_authorize_frozen_document"
    )
    body = ast.unparse(function)
    assert "reauthorize_workflow_loop_document(" in body
    assert "except WorkflowLoopInputError as exc" in body
    assert "AnalysisResultUnavailable(exc.code)" in body
    codes = _loop_reauthorization_codes()
    assert None not in codes, "A loop input code could not be resolved statically."
    assert "workflow_loop_input_unavailable" in codes and "workflow_loop_source_changed" in codes
    assert codes <= ANALYSIS_SOURCE_UNAVAILABLE_CODES


def test_family_code_sets_are_disjoint_and_every_family_has_a_message():
    families = list(FAMILY_CODES.values())
    for index, codes in enumerate(families):
        for other in families[index + 1:]:
            assert not codes & other
    assert set(ANALYSIS_UNAVAILABLE_MESSAGES) == set(FAMILY_CODES)
    assert ANALYSIS_UNAVAILABLE_MESSAGES == {
        ANALYSIS_UNAVAILABLE_SOURCE: SOURCE_MESSAGE,
        ANALYSIS_UNAVAILABLE_CONTAINER: CONTAINER_MESSAGE,
        ANALYSIS_UNAVAILABLE_SAVED_RESULT: SAVED_RESULT_MESSAGE,
    }
    for message in ANALYSIS_UNAVAILABLE_MESSAGES.values():
        assert "source access" not in message and "could not be confirmed" not in message
        assert "retry" not in message.lower() and "try again" not in message.lower()


@pytest.mark.parametrize("code,family,message", [
    ("analysis_source_unavailable", ANALYSIS_UNAVAILABLE_SOURCE, SOURCE_MESSAGE),
    ("analysis_source_snapshot_changed", ANALYSIS_UNAVAILABLE_SOURCE, SOURCE_MESSAGE),
    ("workflow_loop_source_changed", ANALYSIS_UNAVAILABLE_SOURCE, SOURCE_MESSAGE),
    ("analysis_conversation_deleted", ANALYSIS_UNAVAILABLE_CONTAINER, CONTAINER_MESSAGE),
    ("generated_artifact_source_unavailable", ANALYSIS_UNAVAILABLE_CONTAINER, CONTAINER_MESSAGE),
    ("analysis_message_masked", ANALYSIS_UNAVAILABLE_CONTAINER, CONTAINER_MESSAGE),
    ("analysis_lineage_invalid", ANALYSIS_UNAVAILABLE_SAVED_RESULT, SAVED_RESULT_MESSAGE),
    ("analysis_native_source_mismatch", ANALYSIS_UNAVAILABLE_SAVED_RESULT, SAVED_RESULT_MESSAGE),
    ("workflow_repeat_state_changed", ANALYSIS_UNAVAILABLE_SAVED_RESULT, SAVED_RESULT_MESSAGE),
])
def test_each_family_has_its_own_message_and_keeps_its_code(code, family, message):
    error = AnalysisResultUnavailable(code)
    assert isinstance(error, PermissionError)
    assert error.code == code
    assert error.family == family == analysis_unavailable_family(code)
    assert error.public_message == str(error) == message
    assert error.args == (message,)


def test_default_override_and_unclassified_codes():
    default = AnalysisResultUnavailable()
    assert (default.code, default.family, str(default)) == (
        "analysis_source_unavailable", ANALYSIS_UNAVAILABLE_SOURCE, SOURCE_MESSAGE,
    )
    shared = AnalysisResultUnavailable("analysis_source_manifest_invalid", family=ANALYSIS_UNAVAILABLE_SOURCE)
    assert (shared.code, shared.family, str(shared)) == (
        "analysis_source_manifest_invalid", ANALYSIS_UNAVAILABLE_SOURCE, SOURCE_MESSAGE,
    )
    # Unknown codes and families never blame a source document or the caller's access.
    assert AnalysisResultUnavailable("a_future_code").family == ANALYSIS_UNAVAILABLE_SAVED_RESULT
    assert AnalysisResultUnavailable("analysis_lineage_invalid", family="unknown").family == (
        ANALYSIS_UNAVAILABLE_SAVED_RESULT
    )


def test_input_reads_keep_their_codes_and_say_a_source_is_unavailable():
    with pytest.raises(AnalysisResultUnavailable) as lookup:
        resolve_analysis_source_manifest(["document-1"], "owner", resolver=lambda ids, **kwargs: [])
    assert (lookup.value.code, lookup.value.family) == ("analysis_source_manifest_invalid", ANALYSIS_UNAVAILABLE_SOURCE)
    with pytest.raises(AnalysisResultUnavailable) as reader:
        authorize_analysis_sources("", [{"document_id": "document-1", "scope": "personal", "scope_id": "owner"}])
    assert (reader.value.code, reader.value.family) == ("analysis_source_unavailable", ANALYSIS_UNAVAILABLE_SOURCE)
    unauthorized = [{
        "document_id": "document-1", "scope": "personal", "scope_id": "owner",
        "source_version": 1, "authorization_status": "unresolved",
    }]
    with pytest.raises(AnalysisResultUnavailable) as assigned:
        index_analysis_source_manifest(unauthorized, ["document-1"])
    assert (assigned.value.code, assigned.value.family) == ("analysis_source_manifest_invalid", ANALYSIS_UNAVAILABLE_SOURCE)
    with pytest.raises(AnalysisResultUnavailable) as incomplete:
        index_analysis_source_manifest([{**unauthorized[0], "authorization_status": "authorized"}], ["document-1", "document-2"])
    assert (incomplete.value.code, incomplete.value.family) == (
        "analysis_source_manifest_missing", ANALYSIS_UNAVAILABLE_SAVED_RESULT,
    )


def test_saved_output_records_that_cannot_load_are_a_saved_result_failure(monkeypatch):
    import functions_workflow_artifacts as artifacts

    def unreadable(*args, **kwargs):
        raise ValueError("The saved output's run records are invalid.")

    monkeypatch.setattr(artifacts, "_load_workflow_artifact_binding", unreadable)
    with pytest.raises(AnalysisResultUnavailable) as refused:
        artifacts.load_workflow_artifact_binding("owner", {})
    assert (refused.value.code, refused.value.family) == (
        "generated_artifact_source_unavailable", ANALYSIS_UNAVAILABLE_SAVED_RESULT,
    )


def _module(name, **attributes):
    module = ModuleType(name)
    module.__dict__.update(attributes)
    return module


def test_former_bare_raises_name_the_container_that_failed(monkeypatch):
    conversations = SimpleNamespace(read_item=lambda item, partition_key: {"id": item, "user_id": "owner"})
    messages = SimpleNamespace(read_item=lambda item, partition_key: {"id": item, "conversation_id": "elsewhere"})
    monkeypatch.setitem(sys.modules, "functions_collaboration", _module(
        "functions_collaboration", build_conversation_participation_context=lambda user_id, conversation: None,
        assert_user_can_view_collaboration_conversation=lambda *args, **kwargs: None,
        get_collaboration_conversation=lambda *args: pytest.fail("A personal message is read from its conversation."),
        get_collaboration_message=lambda *args: pytest.fail("A personal message is read from its conversation."),
    ))
    monkeypatch.setitem(sys.modules, "functions_group", _module("functions_group", assert_group_role=lambda *args, **kwargs: None))
    monkeypatch.setitem(sys.modules, "functions_group_workflows", _module(
        "functions_group_workflows", get_group_workflow=lambda *args: None, get_group_workflow_run=lambda *args: None,
        get_group_workflow_run_item=lambda *args: None,
    ))
    monkeypatch.setitem(sys.modules, "functions_personal_workflows", _module(
        "functions_personal_workflows", get_personal_workflow=lambda *args: None,
        get_personal_workflow_run=lambda *args: None, get_personal_workflow_run_item=lambda *args: None,
    ))
    monkeypatch.setitem(sys.modules, "functions_workflow_runner", _module(
        "functions_workflow_runner", _workflow_task_run_item_id=lambda run_id, task_id, *args: f"{run_id}:{task_id}",
    ))
    with stubbed_config(cosmos_conversations_container=conversations, cosmos_messages_container=messages):
        with pytest.raises(AnalysisResultUnavailable) as message:
            saved._load_authorized_message("owner", "conversation-1", "message-1")
        with pytest.raises(AnalysisResultUnavailable) as workflow:
            saved._load_authorized_workflow("owner", {"workflow_id": "workflow-1", "run_id": "run-1", "task_id": "task-1"})
    assert (message.value.code, message.value.family) == ("analysis_message_unavailable", ANALYSIS_UNAVAILABLE_CONTAINER)
    assert (workflow.value.code, workflow.value.family) == ("analysis_workflow_unavailable", ANALYSIS_UNAVAILABLE_CONTAINER)


@pytest.mark.parametrize("code", ["analysis_source_unavailable", "analysis_message_unavailable", "analysis_workflow_unavailable"])
def test_renamed_container_codes_keep_every_response_code(code):
    from functions_orchestration_rendering import _source_visibility_code
    from functions_workflow_result_followup import _analysis_refusal_code
    from functions_workflow_result_reader import _authorization_code

    error = AnalysisResultUnavailable(code)
    assert _analysis_refusal_code(error) == "workflow_result_access_denied"
    assert _source_visibility_code(error) == "output_access_denied"
    assert _authorization_code(error) == "workflow_result_invalid"


RUNNER_TASK_ERRORS = {
    ANALYSIS_UNAVAILABLE_SOURCE: "A required source is no longer available for this workflow run.",
    ANALYSIS_UNAVAILABLE_CONTAINER: "A conversation, workflow or run that this task needs is no longer available.",
    ANALYSIS_UNAVAILABLE_SAVED_RESULT: (
        "A saved result this task needs can't be used because something it depends on is missing or has changed."
    ),
}
RUNNER_NOT_SAVED_ERRORS = {
    ANALYSIS_UNAVAILABLE_SOURCE: (
        "The analysis result was not saved because a document it read changed or became unavailable while it ran. "
        "Dependent tasks were not run."
    ),
    ANALYSIS_UNAVAILABLE_CONTAINER: (
        "The analysis result was not saved because the conversation, workflow or run that holds it is no longer "
        "available. Dependent tasks were not run."
    ),
    ANALYSIS_UNAVAILABLE_SAVED_RESULT: (
        "The analysis result was not saved because something it depends on is missing or has changed. "
        "Dependent tasks were not run."
    ),
}


@pytest.mark.parametrize("family", list(FAMILY_SAMPLES))
def test_runner_reports_the_family_message_for_a_task_that_cannot_read_its_input(family):
    runner, workflow, records, requests, artifacts, items = build_inventory_run()
    workflow["error_handling"] = {"strategy": "halt", "retry_count": 2}

    def refuse(*args, **kwargs):
        raise AnalysisResultUnavailable(FAMILY_SAMPLES[family])

    runner["_execute_workflow_dispatch"] = refuse
    with pytest.raises(RuntimeError) as caught:
        runner["_execute_workflow_task_sequence"](workflow, {}, "conversation-inventory", "run-inventory", None, {})
    expected = RUNNER_TASK_ERRORS[family]
    assert str(caught.value) == f"Workflow task 'Extract inventory' failed after 1 attempt(s): {expected}"
    failed = items[("run-inventory", runner["_workflow_task_run_item_id"]("run-inventory", "extract"))]
    assert (failed["status"], failed["attempt_count"], failed["error"]) == ("failed", 1, expected)
    assert requests == []


@pytest.mark.parametrize("family", list(FAMILY_SAMPLES))
def test_runner_reports_the_family_message_when_a_result_is_not_saved(family):
    runner, workflow, records, requests, artifacts, items = build_inventory_run()

    def refuse(*args, **kwargs):
        raise AnalysisResultUnavailable(FAMILY_SAMPLES[family])

    runner["persist_workflow_task_result"] = refuse
    expected = RUNNER_NOT_SAVED_ERRORS[family]
    with pytest.raises(RuntimeError) as caught:
        runner["_execute_workflow_task_sequence"](workflow, {}, "conversation-inventory", "run-inventory", None, {})
    assert str(caught.value) == expected
    failed = items[("run-inventory", runner["_workflow_task_run_item_id"]("run-inventory", "extract"))]
    assert (failed["status"], failed["error"]) == ("failed", expected)
    assert not any(item.get("task_id") == "consume" for item in items.values())


def test_loop_item_pause_reasons_cover_every_family():
    from functions_workflow_flow_runner import LOOP_ITEM_UNAVAILABLE_REASONS

    assert set(LOOP_ITEM_UNAVAILABLE_REASONS) == set(FAMILY_CODES)
    assert LOOP_ITEM_UNAVAILABLE_REASONS[ANALYSIS_UNAVAILABLE_SOURCE] == (
        "The current loop item's original source is no longer available."
    )
    for family in (ANALYSIS_UNAVAILABLE_CONTAINER, ANALYSIS_UNAVAILABLE_SAVED_RESULT):
        assert "source" not in LOOP_ITEM_UNAVAILABLE_REASONS[family]


@pytest.mark.parametrize("family", list(FAMILY_SAMPLES))
def test_saved_analysis_explanation_shows_the_family_message(chat, family):
    def refuse(*args, **kwargs):
        raise AnalysisResultUnavailable(FAMILY_SAMPLES[family])

    chat.namespace["load_saved_analysis_input"] = refuse
    response = chat.client.post("/api/chat", json=followup_body(chat))
    assert response.status_code == 403
    payload = response.get_json()
    assert payload["error"] == ANALYSIS_UNAVAILABLE_MESSAGES[family]
    assert payload["warning_type"] == "saved_analysis_unavailable"
    assert chat.state["model_calls"] == []


def test_saved_analysis_explanation_keeps_its_access_message_for_other_refusals(chat):
    def refuse(*args, **kwargs):
        raise PermissionError("Not a participant.")

    chat.namespace["load_saved_analysis_input"] = refuse
    response = chat.client.post("/api/chat", json=followup_body(chat))
    assert response.status_code == 403
    assert response.get_json()["error"] == (
        "This analysis is unavailable because access to its conversation or saved result could not be confirmed."
    )


@pytest.mark.parametrize("family,message", [
    (ANALYSIS_UNAVAILABLE_SOURCE,
     "The analysis could not be saved because this conversation or a selected document is no longer available."),
    (ANALYSIS_UNAVAILABLE_CONTAINER,
     "The analysis could not be saved because this conversation or a selected document is no longer available."),
    (ANALYSIS_UNAVAILABLE_SAVED_RESULT,
     "The analysis could not be saved because something it depends on is missing or has changed."),
])
def test_analyze_save_failure_shows_the_family_message(chat, family, message):
    def refuse(*args, **kwargs):
        raise AnalysisResultUnavailable(FAMILY_SAMPLES[family])

    chat.namespace["save_chat_analysis"] = refuse
    response = chat.client.post("/api/chat/document-action", json=analyze_body())
    assert response.status_code == 403
    assert response.get_json()["error"] == message
    assert response.get_json()["warning_type"] == "analysis_save_failed"
    assert chat.state["rollbacks"] == 1


@pytest.mark.parametrize("family,message", [
    (ANALYSIS_UNAVAILABLE_SOURCE,
     "The analysis could not be saved because a selected document is no longer available or has changed."),
    (ANALYSIS_UNAVAILABLE_CONTAINER, "This analysis conversation is unavailable."),
    (ANALYSIS_UNAVAILABLE_SAVED_RESULT,
     "The analysis could not be saved because something it depends on is missing or has changed."),
])
def test_analyze_publication_check_shows_the_family_message(chat, family, message):
    assistants_before = {key for key, item in chat.messages.documents.items() if item["role"] == "assistant"}

    def refuse(*args, **kwargs):
        raise AnalysisResultUnavailable(FAMILY_SAMPLES[family])

    chat.namespace["assert_analysis_attempt_current"] = refuse
    response = chat.client.post("/api/chat/document-action", json=analyze_body())
    assert response.status_code == 403
    assert response.get_json() == {"error": message, "conversation_id": "conversation-1"}
    assert chat.state["rollbacks"] == 1
    assert {key for key, item in chat.messages.documents.items() if item["role"] == "assistant"} == assistants_before


def test_history_placeholders_no_longer_blame_access_confirmation():
    from functions_generated_artifact_sources import _UNAVAILABLE_HISTORY

    for placeholder in (saved.UNAVAILABLE_ANALYSIS_MESSAGE, _UNAVAILABLE_HISTORY):
        assert "could not be confirmed" not in placeholder
        assert "missing, has changed or can't be read right now" in placeholder


def test_no_application_text_says_source_access_could_not_be_confirmed():
    candidates = [
        *(APP_ROOT.rglob("*.py")),
        *(APP_ROOT / "templates").rglob("*.html"),
        *(path for path in (APP_ROOT / "static" / "js").rglob("*.js") if "vendor" not in path.parts),
        *(ROOT / "application" / "v2_ui" / "src").rglob("*.ts"),
        *(ROOT / "application" / "v2_ui" / "src").rglob("*.tsx"),
    ]
    offenders = [
        path.relative_to(ROOT).as_posix() for path in candidates
        if "source access could not be confirmed" in path.read_text(encoding="utf-8", errors="replace").lower()
    ]
    assert offenders == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
