#!/usr/bin/env python3
# test_v2_workflow_ask_ai_parity.py
"""
Functional test for the round trip between the V2 editor's Ask AI tab and the AI workflow assistant.
Version: 0.261.210
Implemented in: 0.261.210

This test ensures that the requests the Ask AI tab builds are the requests the assistant accepts,
and that the answers the assistant gives are the answers the tab applies. It runs the tab's real
TypeScript under node on both sides of real assistant requests that use a scripted model:

* node builds each request with ``buildWorkflowAssistRequest`` from the draft the editor holds (a
  saved workflow, a v3 flow, New workflow's draft and a chat proposal's draft), with ``#`` documents
  as the picker makes them and a thread history, and prints the exact JSON text the browser POSTs;
* the assistant reads that text with its own checks (``parse_assist_body``, ``parse_assist_request``)
  and answers it. A new or proposal draft must arrive with ``base: null`` and no ``id``, a saved one
  with its ``id`` and ``definition_revision``, and the focus, time zone, documents and completed
  turns as the contract says;
* node replays each answer as the tab does: ``parseWorkflowAssistResponse``, ``rebaseAssistCandidate``
  over the live draft, the editor's own diff (``verifyAssistChanges``) and ``applyAssist``. The
  editor's diff must find exactly the change keys, Jump to targets and wording the server reported.

Every scenario in test_workflow_assist_candidate_parity.py runs this way, plus cases for the request
shapes. The TypeScript side is test_v2_workflow_ask_ai_parity_logic.ts. The node checks are skipped
when application/v2_ui/node_modules is missing; run npm ci there first.
"""

import ast
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

import functions_workflow_assist as core  # noqa: E402
from functions_workflow_schedules import build_workflow_schedule_editor_options  # noqa: E402
from test_support import workflow_assist as wa  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_workflow_assist_candidate_parity import (  # noqa: E402
    PARITY_OPTIONS,
    SCENARIOS,
    URGENT_ONLY,
    WEEKDAYS_AT_SEVEN,
)

V2_DIR = REPO_ROOT / "application" / "v2_ui"
LOGIC_CHECK = Path(__file__).with_name("test_v2_workflow_ask_ai_parity_logic.ts")
FIXTURE_ENV = "WORKFLOW_ASK_AI_PARITY_FIXTURE"
REQUEST_FIELDS = {"submission_id", "base", "instruction", "conversation", "focus", "time_zone", "draft", "references"}

# The editor options the V2 editor receives: 3b's parity options with the real schedule choices,
# so the time zone list the tab checks is the server's own.
ASK_AI_OPTIONS = {
    **copy.deepcopy(PARITY_OPTIONS),
    "schedule": build_workflow_schedule_editor_options(min_interval_seconds=300),
}

# A thread history: eleven completed turns, so the oldest falls out of the ten the tab replays, with
# a failed and a cancelled turn among them that must never reach the server.
REPLAY = {
    "done": [f"Turn {number}: tighten the review \U0001F512\tthen\nsummarize it." for number in range(1, 12)],
    "replies": [f"Reply {number} \u2705\twith a tab\nand a new line." for number in range(1, 12)],
    "failed": "This failed turn is never replayed.",
    "cancelled": "This cancelled turn is never replayed.",
}

# Ask AI about this task, for some of 3b's scenarios.
SCENARIO_FOCUS = {
    "one task's document target": wa.REVIEW_ID,
    "flow task renamed and rewritten": "spare-task",
}


def _draft_server_fields():
    """The fields a chat proposal's draft is served without, read from the proposal module's source.

    Importing that module would bring in Cosmos DB, so its constant is read as a literal instead.
    """
    source = (APP_DIR / "functions_orchestration_workflow_proposals.py").read_text(encoding="utf-8")
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(getattr(target, "id", None) == "DRAFT_SERVER_FIELDS" for target in node.targets):
            return frozenset(ast.literal_eval(node.value.args[0]))
    raise AssertionError("DRAFT_SERVER_FIELDS is missing from functions_orchestration_workflow_proposals.py")


PROPOSAL_FIELDS = _draft_server_fields()


def _proposal_source(stored):
    """A workflow as a chat proposal serves it to the editor: without the server's own fields."""
    return {key: copy.deepcopy(value) for key, value in stored.items() if key not in PROPOSAL_FIELDS}


def _case(name, reply, *, live, stored=None, source=None, instruction="Change the workflow.", references=(),
          focus_task=None, replay=False):
    return {
        "name": name, "live": live, "stored": stored, "source": source, "instruction": instruction,
        "references": list(references), "focus_task": focus_task, "replay": replay, "reply": reply,
    }


def _scenario_case(scenario):
    stored = scenario["stored"]
    draft = scenario["draft"]
    if stored is not None and draft is None:
        live, source = "stored", None
    else:
        live, source = "draft", draft if draft is not None else wa.new_draft()
    return _case(
        scenario["name"], wa.reply("changed", "Done.", scenario["operations"]), live=live, stored=stored,
        source=source, references=scenario["references"], focus_task=SCENARIO_FOCUS.get(scenario["name"]),
    )


def _request_cases():
    return [
        _case(
            "saved workflow with a focus, documents and a replayed conversation",
            wa.reply("explained", "The review already checks each document \u2705."),
            live="stored", stored=wa.stored_workflow(),
            instruction="Make the review \U0001F512 stricter\tfor every document\nand tell the team \U0001F469\u200d\U0001F4BB.",
            references=[wa.INCIDENT, wa.TEAM_GUIDE, wa.CHECKLIST], focus_task=wa.REVIEW_ID, replay=True,
        ),
        _case(
            "saved flow focused on a nested task's block",
            wa.reply("explained", "That step accepts the decision."),
            live="stored", stored=wa.flow_stored(), instruction="What does this step do?", focus_task="yes-task",
        ),
        _case(
            "New workflow's draft",
            wa.reply("changed", "Done.", [
                {"op": "set_name", "name": "Morning digest"},
                {"op": "set_task_instructions", "task": "task_1", "instructions": "Summarize the new documents."},
            ]),
            live="new", instruction="Call it Morning digest and have the task summarize new documents.",
        ),
        _case(
            "chat proposal's draft opened with Edit",
            wa.reply("changed", "Done.", [WEEKDAYS_AT_SEVEN, *URGENT_ONLY]),
            live="proposal", source=_proposal_source(wa.stored_workflow()),
            instruction="Run this at 7 AM on weekdays and only alert me when something is urgent",
        ),
        _case(
            "instruction of exactly 2,000 code points",
            wa.reply("explained", "Tell me what to change."),
            live="stored", stored=wa.stored_workflow(),
            instruction="\U0001F600" * core.ASSIST_INSTRUCTION_MAX_LENGTH,
        ),
        _case(
            "question about where a document goes",
            wa.reply("question", "Should every task read Security checklist.pdf, or only Review?"),
            live="stored", stored=wa.stored_workflow(), instruction="Use #Security checklist.pdf.",
            references=[wa.CHECKLIST],
        ),
        _case(
            "document read as context",
            wa.reply("changed", "I read Security checklist.pdf and rewrote the description.", [
                {"op": "set_description", "description": "Check new documents against the security checklist."},
            ]),
            live="stored", stored=wa.stored_workflow(),
            instruction="Use #Security checklist.pdf to rewrite the description.", references=[wa.CHECKLIST],
        ),
    ]


def _cases():
    cases = [_scenario_case(scenario) for scenario in SCENARIOS] + _request_cases()
    for index, case in enumerate(cases, start=1):
        case["submission_id"] = f"ask-ai-parity:{index:03d}"
    return cases


def _for_node(case, **extra):
    fields = {key: value for key, value in case.items() if key != "reply"}
    fields.update(extra)
    return fields


def _flow_node_for_task(region, task_id):
    for node in (region or {}).get("nodes") or []:
        if node.get("kind") == "task" and node.get("task_id") == task_id:
            return node["id"]
        for child in ("then", "else", "body"):
            if isinstance(node.get(child), dict):
                found = _flow_node_for_task(node[child], task_id)
                if found:
                    return found
    return None


def _expected_focus(case):
    task_id = case["focus_task"]
    if task_id is None:
        return None
    stored = case["stored"] or case["source"] or {}
    if stored.get("definition_version") == 3:
        return _flow_node_for_task(stored.get("flow"), task_id)
    return task_id


def _reference_order(reference):
    scope = reference["scope"]
    return (reference["kind"], scope["kind"], scope.get("id") or "", reference["id"])


def _node(bundle_path, fixture_path, fixture):
    fixture_path.write_text(json.dumps(fixture, allow_nan=False), encoding="utf-8")
    try:
        return subprocess.run(
            ["node", str(bundle_path)],
            cwd=str(V2_DIR), capture_output=True, text=True, encoding="utf-8", shell=(sys.platform == "win32"),
            timeout=300, env={**os.environ, FIXTURE_ENV: str(fixture_path)},
        )
    finally:
        if fixture_path.exists():
            fixture_path.unlink()


def _emitted(run, label):
    """One line the logic check printed, read with Python's JSON parser."""
    # Split on newlines only: splitlines() also splits on U+001C, U+0085 and U+2028.
    lines = [line for line in run.stdout.split("\n") if line.startswith(f"{label} ")]
    assert len(lines) == 1, f"the tab printed {len(lines)} {label} lines\n{(run.stdout + run.stderr)[-3000:]}"
    return json.loads(lines[0][len(label) + 1:])


def _answer(case, text):
    """What the assistant does with the exact text the tab sent."""
    body = core.parse_assist_body(text.encode("utf-8"))
    request = core.parse_assist_request(copy.deepcopy(body), wa.USER_ID)
    model = wa.ScriptedModel(case["reply"])
    bundle = wa.services(model, stored=case["stored"] if body["base"] is not None else None, options=ASK_AI_OPTIONS)
    result = wa.run(body, bundle)
    return {"body": body, "request": request, "bundle": bundle, "result": result}


@pytest.fixture(scope="module")
def round_trip():
    """Both node runs around the assistant: the tab's requests, the answers, and the tab's replay."""
    assert LOGIC_CHECK.exists(), "the TypeScript logic check is missing"
    if not (V2_DIR / "node_modules").exists():
        pytest.skip("run npm ci in application/v2_ui to build the requests with the tab's code")

    cases = _cases()
    bundle_path = V2_DIR / "node_modules" / ".cache-workflow-ask-ai-parity-check.mjs"
    fixture_path = V2_DIR / "node_modules" / ".cache-workflow-ask-ai-parity-fixture.json"
    shared = {"options": ASK_AI_OPTIONS, "time_zone": wa.TIME_ZONE, "replay": REPLAY}
    try:
        subprocess.run(
            [
                "npx", "esbuild", str(LOGIC_CHECK), "--bundle", "--platform=node", "--format=esm",
                "--packages=external", f"--outfile={bundle_path}", "--log-level=error",
            ],
            cwd=str(V2_DIR), check=True, shell=(sys.platform == "win32"), timeout=300,
        )
        built = _node(bundle_path, fixture_path, {**shared, "phase": "requests", "cases": [_for_node(case) for case in cases]})
        assert built.returncode == 0, (built.stdout + built.stderr)[-4000:]
        requests = _emitted(built, "REQUESTS")
        assert [item["name"] for item in requests] == [case["name"] for case in cases]
        refused = [f"{item['name']}: {item['refused']}" for item in requests if "refused" in item]
        assert not refused, "the tab refused to build: " + "; ".join(refused)

        answers = [_answer(case, item["text"]) for case, item in zip(cases, requests)]
        replayed = _node(bundle_path, fixture_path, {**shared, "phase": "responses", "cases": [
            _for_node(case, request_text=item["text"], response=answer["result"])
            for case, item, answer in zip(cases, requests, answers)
        ]})
    finally:
        if bundle_path.exists():
            bundle_path.unlink()
    return {"cases": cases, "requests": requests, "answers": answers, "replayed": replayed}


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least("0.261.210")


def test_the_proposal_draft_is_served_without_an_id():
    assert {"id", "user_id", "definition_revision"} <= PROPOSAL_FIELDS
    assert "id" not in _proposal_source(wa.stored_workflow())


def test_every_request_the_tab_builds_is_one_the_assistant_accepts(round_trip):
    for case, answer in zip(round_trip["cases"], round_trip["answers"]):
        body = answer["body"]
        name = case["name"]
        assert set(body) == REQUEST_FIELDS, name
        assert answer["result"]["submission_id"] == case["submission_id"], name
        assert body["time_zone"] == wa.TIME_ZONE, name
        assert body["focus"] == _expected_focus(case), name
        assert answer["request"].instruction == case["instruction"].strip(), name
        if case["replay"]:
            assert len(body["conversation"]) == 20, name
        else:
            assert body["conversation"] == [], name


def test_a_new_or_proposal_draft_is_sent_without_a_base_or_an_id(round_trip):
    unsaved = [
        (case, answer) for case, answer in zip(round_trip["cases"], round_trip["answers"])
        if case["live"] in ("new", "proposal") or case["stored"] is None
    ]
    assert {case["live"] for case, _answer in unsaved} == {"new", "proposal", "draft"}
    for case, answer in unsaved:
        body = answer["body"]
        assert body["base"] is None, case["name"]
        assert "id" not in body["draft"], case["name"]
        assert not answer["bundle"].recorder.named("read_base"), case["name"]


def test_a_saved_workflow_is_sent_with_its_id_and_revision(round_trip):
    saved = [
        (case, answer) for case, answer in zip(round_trip["cases"], round_trip["answers"]) if case["stored"] is not None
    ]
    assert any(case["stored"].get("definition_version") == 3 for case, _answer in saved)
    for case, answer in saved:
        body = answer["body"]
        stored = case["stored"]
        assert body["base"] == {"workflow_id": stored["id"], "definition_revision": stored["definition_revision"]}, case["name"]
        assert body["draft"]["id"] == stored["id"], case["name"]
        assert body["draft"].get("definition_revision", stored["definition_revision"]) == stored["definition_revision"], case["name"]
        assert answer["bundle"].recorder.named("read_base") == [(wa.USER_ID, stored["id"])], case["name"]


def test_focus_names_the_task_or_its_flow_block(round_trip):
    focused = {case["name"]: answer["body"]["focus"] for case, answer in zip(round_trip["cases"], round_trip["answers"])
               if case["focus_task"]}
    assert focused == {
        "one task's document target": wa.REVIEW_ID,
        "flow task renamed and rewritten": "constructor",
        "saved workflow with a focus, documents and a replayed conversation": wa.REVIEW_ID,
        "saved flow focused on a nested task's block": "yes-node",
    }


def test_documents_are_sent_in_the_servers_canonical_form(round_trip):
    for case, answer in zip(round_trip["cases"], round_trip["answers"]):
        references = answer["body"]["references"]
        assert [reference["id"] for reference in sorted(case["references"], key=_reference_order)] == [
            reference["id"] for reference in references
        ], case["name"]
        assert references == sorted(references, key=_reference_order), case["name"]
        for reference in references:
            assert reference["kind"] == "document" and set(reference) <= {"kind", "id", "label", "scope"}, case["name"]
            assert set(reference["scope"]) == {"kind", "id"}, case["name"]
            assert (reference["scope"]["id"] is None) == (reference["scope"]["kind"] == "personal"), case["name"]
        resolved = answer["bundle"].recorder.named("resolve_references")
        assert resolved == ([(wa.USER_ID, answer["request"].references)] if references else []), case["name"]


def test_only_completed_turns_are_replayed(round_trip):
    [answer] = [answer for case, answer in zip(round_trip["cases"], round_trip["answers"]) if case["replay"]]
    conversation = answer["body"]["conversation"]
    assert [item["role"] for item in conversation] == ["user", "assistant"] * 10
    texts = [item["text"] for item in conversation]
    assert not any(REPLAY["failed"] in text or REPLAY["cancelled"] in text for text in texts)
    # Eleven turns completed; the oldest falls out of the ten replayed.
    assert texts[0] == REPLAY["done"][1] and not any(text.startswith("Turn 1:") for text in texts)
    assert [texts[index] for index in range(0, 20, 2)] == REPLAY["done"][1:]
    for index, reply in enumerate(REPLAY["replies"][1:]):
        assert texts[2 * index + 1].startswith(reply), texts[2 * index + 1]
    assert any("Changes applied: Workflow: Name." in text for text in texts)
    assert any("later undone" in text for text in texts)
    assert any("earlier editing session" in text for text in texts)
    # A turn that changed nothing is replayed as its reply alone.
    assert REPLAY["replies"][2] in texts
    assert all("\t" in text and "\n" in text for text in texts)
    assert answer["request"].conversation == [
        {"role": item["role"], "text": item["text"].strip()} for item in conversation
    ]


def test_the_boundary_instruction_reaches_the_assistant_whole(round_trip):
    [answer] = [answer for case, answer in zip(round_trip["cases"], round_trip["answers"])
                if case["name"] == "instruction of exactly 2,000 code points"]
    instruction = answer["body"]["instruction"]
    assert len(instruction) == core.ASSIST_INSTRUCTION_MAX_LENGTH
    assert len(instruction.encode("utf-16-le")) // 2 == 2 * core.ASSIST_INSTRUCTION_MAX_LENGTH


def test_the_assistant_answers_every_case_as_scripted(round_trip):
    outcomes = {case["name"]: answer["result"]["outcome"] for case, answer in zip(round_trip["cases"], round_trip["answers"])}
    assert all(outcomes[scenario["name"]] == "changed" for scenario in SCENARIOS)
    assert outcomes["question about where a document goes"] == "question"
    assert outcomes["saved flow focused on a nested task's block"] == "explained"
    [context] = [answer["result"] for case, answer in zip(round_trip["cases"], round_trip["answers"])
                 if case["name"] == "document read as context"]
    assert context["outcome"] == "changed" and context["context_documents"] == [wa.CHECKLIST["label"]]
    run_as = {case["name"] for case, answer in zip(round_trip["cases"], round_trip["answers"])
              if any(warning["code"] == "run_as_reapproval" for warning in answer["result"]["warnings"])}
    assert "weekdays at seven with urgent alerts and Run as" in run_as


def test_the_tab_applies_every_answer_as_the_server_reported_it(round_trip):
    replayed = round_trip["replayed"]
    output = replayed.stdout + replayed.stderr
    failures = [line for line in output.split("\n") if line.startswith("FAIL")]
    assert replayed.returncode == 0 and not failures, "\n".join(failures or [output[-4000:]])
    expected = sum(10 if answer["result"]["outcome"] == "changed" else 4 for answer in round_trip["answers"])
    passed = sum(1 for line in replayed.stdout.split("\n") if line.startswith("  ok  "))
    assert passed == expected, f"expected {expected} tab checks, saw {passed}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
