#!/usr/bin/env python3
# test_orchestration_workflow_deliverable.py
"""
Functional test for the orchestration ``workflow`` deliverable kind.
Version: 0.261.204
Implemented in: 0.261.204

This test ensures that a plan can declare a proposed workflow as a deliverable only while
``enable_chat_orchestration_workflows`` is on, and that the server owns its truth:

- strict planning accepts the ``workflow`` kind only when the server describes it, with the
  unchanged planner-facing kind error otherwise; saved plans revalidate without it;
- only a ``workflow_propose`` step delivers a workflow, it delivers exactly one, it is linked
  when unambiguous, and a proposal no deliverable declares is refused; a second workflow in
  the same request is declared unavailable with ``workflow_one_per_request``;
- a workflow is proposed only when the user asked for it (``requested: explicit``);
- availability and its closed, application-owned reasons, including the allowlist;
- the answer step is told a separate card proposes the workflow, and delivery notes cover a
  workflow that is unavailable, turned off, or could not be prepared.

Real modules are imported offline; the plan steps are compiled step dictionaries.
"""

import importlib
from copy import deepcopy

import pytest

from test_orchestration_harness_routes import modules  # noqa: F401
from test_support.versioning import assert_app_version_at_least


SETTING = "enable_chat_orchestration_workflows"
FINAL = {
    "version": "orchestration-input-binding-v1", "step_id": "answer",
    "output_name": "answer", "existing_result": None,
}
WORKFLOW_REASONS = (
    "workflow_proposals_disabled", "workflow_role_required", "workflow_shared_conversation",
    "workflow_quota_reached", "workflow_context_unavailable", "workflow_draft_invalid",
    "workflow_one_per_request",
)


def test_version_includes_the_workflow_deliverable():
    assert_app_version_at_least("0.261.204")


# ------------------------------------------------------------------------------------------
# Builders
# ------------------------------------------------------------------------------------------

def _deliverables():
    return importlib.import_module("functions_orchestration_deliverables")


def _answer_step(**extra):
    return {
        "step_id": "answer", "capability_id": "compose",
        "arguments": {"instruction": "List what to focus on this week.", "knowledge_basis": "general_knowledge"},
        "inputs": {}, "outputs": [{"name": "answer", "kind": "markdown-v1"}], **extra,
    }


def _proposal_step(step_id="propose", **extra):
    return {
        "step_id": step_id, "capability_id": "workflow_propose",
        "arguments": {"blueprint": {"name": "Weekly review"}},
        "inputs": {}, "outputs": [{"name": "proposal", "kind": "structured-v1"}], **extra,
    }


def _deliverable(identifier, kind, description, *, requested="explicit", status="planned", **extra):
    return {
        "id": identifier, "kind": kind, "requested": requested, "description": description,
        "status": status, **extra,
    }


def _answer():
    return _deliverable("answer", "answer", "This week's priorities.")


def _workflow(**extra):
    return _deliverable("weekly_review", "workflow", "A workflow that reviews email every Monday", **extra)


def _settings(enabled=True):
    settings = {"enable_chat_orchestration": True, "allow_user_workflows": True}
    if enabled is not None:
        settings[SETTING] = enabled
    return settings


def _availability(*, enabled=True, available=True, reason=None):
    capabilities = [{"id": "compose"}] + ([{"id": "workflow_propose"}] if available else [])
    unavailable = {} if available or reason is None else {"workflow_propose": reason}
    return _deliverables().build_deliverable_availability(
        _settings(enabled), capabilities=capabilities, unavailable=unavailable, export_catalog=[],
    )


def _compile(raw, steps, *, availability=None, final=FINAL):
    return _deliverables().compile_deliverables(
        deepcopy(raw), steps, final_response=deepcopy(final) if final else None, availability=availability,
    )


def _error(raw, steps, **kwargs):
    with pytest.raises(_deliverables().DeliverableError) as caught:
        _compile(raw, steps, **kwargs)
    return caught.value


# ------------------------------------------------------------------------------------------
# The kind exists for the planner only while the setting is on
# ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("enabled", [None, False])
def test_strict_planning_refuses_the_kind_with_the_unchanged_error_when_off(modules, enabled):
    availability = _availability(enabled=enabled)
    assert "workflow" not in availability
    assert not [reason for reason in availability["unavailable_reasons"] if reason.startswith("workflow_")]

    error = _error([_answer(), _workflow()], [_answer_step(), _proposal_step()], availability=availability)
    assert error.rule == "invalid_deliverable_kind"
    assert str(error) == 'Deliverable "weekly_review" needs kind answer, file, image, chart, or diagram.'

    reason_error = _error(
        [_answer(), _deliverable("art", "image", "A picture", status="unavailable",
                                 unavailable_reason="workflow_proposals_disabled")],
        [_answer_step()], availability=availability,
    )
    assert reason_error.rule == "invalid_unavailable_reason"


def test_strict_planning_accepts_the_kind_when_the_server_describes_it(modules):
    steps = [_answer_step(), _proposal_step()]
    compiled = _compile([_answer(), _workflow()], steps, availability=_availability())

    assert [item["kind"] for item in compiled] == ["answer", "workflow"]
    by_id = {step["step_id"]: step for step in steps}
    assert by_id["propose"]["delivers"] == ["weekly_review"]
    assert by_id["answer"]["delivers"] == ["answer"]

    unknown = _error(
        [_answer(), _deliverable("clip", "video", "A video")], [_answer_step()], availability=_availability(),
    )
    assert unknown.rule == "invalid_deliverable_kind"
    assert str(unknown) == 'Deliverable "clip" needs kind answer, file, image, chart, diagram, or workflow.'


def test_saved_plans_revalidate_the_kind_without_availability(modules):
    steps = [_answer_step(), _proposal_step(delivers=["weekly_review"])]
    compiled = _compile([_answer(), _workflow()], steps, availability=None)
    assert compiled[1]["kind"] == "workflow"

    unavailable = _compile(
        [_answer(), _workflow(status="unavailable", unavailable_reason="workflow_shared_conversation")],
        [_answer_step()], availability=None,
    )
    assert unavailable[1]["unavailable_message"] == (
        "Workflows can be proposed only in your own conversations, not in shared ones."
    )


# ------------------------------------------------------------------------------------------
# Producers
# ------------------------------------------------------------------------------------------

def test_only_a_workflow_propose_step_delivers_a_workflow(modules):
    error = _error(
        [_answer(), _workflow()], [_answer_step(delivers=["answer", "weekly_review"])],
        availability=_availability(),
    )
    assert error.rule == "workflow_producer_mismatch"
    assert "only a workflow_propose step proposes a workflow" in str(error)

    wrong_kind = _error(
        [_answer(), _workflow()], [_answer_step(), _proposal_step(delivers=["answer", "weekly_review"])],
        availability=_availability(),
    )
    assert wrong_kind.rule == "answer_producer_mismatch"


def test_a_proposal_no_deliverable_declares_is_refused(modules):
    declared = _error([_answer()], [_answer_step(), _proposal_step()], availability=_availability())
    assert declared.rule == "undeclared_workflow_output"

    nothing_declared = _error([], [_answer_step(), _proposal_step()], availability=_availability())
    assert nothing_declared.rule == "undeclared_workflow_output"

    saved = _error([], [_answer_step(), _proposal_step()], availability=None)
    assert saved.rule == "undeclared_workflow_output"


def test_a_proposal_step_proposes_exactly_one_workflow(modules):
    second = _deliverable("daily_review", "workflow", "A daily review.")
    ambiguous = _error([_answer(), _workflow(), second], [_answer_step(), _proposal_step()], availability=None)
    assert ambiguous.rule == "undeclared_workflow_output"

    both = _error(
        [_answer(), _workflow(), second],
        [_answer_step(), _proposal_step(delivers=["weekly_review", "daily_review"])], availability=None,
    )
    assert both.rule == "workflow_delivers_one"


def test_a_workflow_is_proposed_only_when_the_user_asked_for_one(modules):
    error = _error(
        [_answer(), _workflow(requested="suggested")], [_answer_step(), _proposal_step()],
        availability=_availability(),
    )
    assert error.rule == "suggested_workflow"
    assert "only when the user asks" in str(error)


def test_a_second_workflow_is_declared_with_the_one_per_request_reason(modules):
    second = _deliverable(
        "daily_review", "workflow", "A daily review", status="unavailable",
        unavailable_reason="workflow_one_per_request",
    )
    steps = [_answer_step(), _proposal_step()]
    compiled = _compile([_answer(), _workflow(), second], steps, availability=_availability())

    assert compiled[2]["unavailable_message"] == (
        "One request can propose one workflow. Ask for the next one in a new message."
    )
    assert next(step for step in steps if step["step_id"] == "propose")["delivers"] == ["weekly_review"]

    # Without a planned proposal the budget is not spent, so the server can propose this one.
    declined = _error(
        [_answer(), _workflow(status="unavailable", unavailable_reason="workflow_one_per_request")],
        [_answer_step()], availability=_availability(),
    )
    assert declined.rule == "available_deliverable_declined"


# ------------------------------------------------------------------------------------------
# Availability and reasons
# ------------------------------------------------------------------------------------------

def test_availability_describes_the_workflow_kind_only_when_enabled(modules):
    off = _availability(enabled=False)
    on = _availability()

    assert on["workflow"] == {"status": "available", "produced_by": ["workflow_propose"], "max_per_plan": 1}
    assert [reason for reason in on["unavailable_reasons"] if reason.startswith("workflow_")] == list(WORKFLOW_REASONS)
    base = {key: value for key, value in on["unavailable_reasons"].items() if not key.startswith("workflow_")}
    assert list(base) == list(off["unavailable_reasons"]) and base == off["unavailable_reasons"]
    assert on["facts"][:len(off["facts"])] == off["facts"]
    assert any("proposal card" in fact for fact in on["facts"][len(off["facts"]):])
    assert on["recipes"][:len(off["recipes"])] == off["recipes"]
    assert [recipe["for"] for recipe in on["recipes"][len(off["recipes"]):]] == [
        "Recurring or automated work the user asks for",
    ]


@pytest.mark.parametrize("capability_reason, expected", [
    ("not_enabled_for_orchestration", "capability_not_enabled_for_orchestration"),
    ("feature_disabled", "workflow_proposals_disabled"),
    ("workflow_role_required", "workflow_role_required"),
    ("workflow_shared_conversation", "workflow_shared_conversation"),
    ("workflow_quota_reached", "workflow_quota_reached"),
    ("workflow_context_unavailable", "workflow_context_unavailable"),
    ("something_else", "workflow_proposals_disabled"),
    (None, "workflow_proposals_disabled"),
])
def test_an_unavailable_workflow_carries_a_closed_reason(modules, capability_reason, expected):
    availability = _availability(available=False, reason=capability_reason)
    off = _availability(enabled=False)

    assert availability["workflow"] == {"status": "unavailable", "reason": expected}
    # Facts and recipes are unchanged: nothing tells the planner how to propose one.
    assert availability["facts"] == off["facts"]
    assert availability["recipes"] == off["recipes"]


def test_unavailable_workflow_claims_must_match_the_server(modules):
    shared = _availability(available=False, reason="workflow_shared_conversation")

    planned = _error([_answer(), _workflow()], [_answer_step(), _proposal_step()], availability=shared)
    assert planned.rule == "planned_deliverable_unavailable"
    assert "workflow_shared_conversation" in str(planned)

    mismatch = _error(
        [_answer(), _workflow(status="unavailable", unavailable_reason="workflow_quota_reached")],
        [_answer_step()], availability=shared,
    )
    assert mismatch.rule == "unavailable_reason_mismatch"

    declined = _error(
        [_answer(), _workflow(status="unavailable", unavailable_reason="workflow_shared_conversation")],
        [_answer_step()], availability=_availability(),
    )
    assert declined.rule == "available_deliverable_declined"

    accepted = _compile(
        [_answer(), _workflow(status="unavailable", unavailable_reason="workflow_shared_conversation")],
        [_answer_step()], availability=shared,
    )
    assert accepted[1]["unavailable_message"] == (
        "Workflows can be proposed only in your own conversations, not in shared ones."
    )
    allowlisted = _compile(
        [_answer(), _workflow(status="unavailable", unavailable_reason="capability_not_enabled_for_orchestration")],
        [_answer_step()], availability=_availability(available=False, reason="not_enabled_for_orchestration"),
    )
    assert allowlisted[1]["unavailable_reason"] == "capability_not_enabled_for_orchestration"


def test_every_workflow_reason_has_application_owned_text(modules):
    reasons = _deliverables().WORKFLOW_UNAVAILABLE_REASONS
    assert tuple(reasons) == WORKFLOW_REASONS
    for reason, message in reasons.items():
        assert message and message.endswith("."), reason
        assert "{" not in message and "<" not in message, reason
    assert "Create it in Workflows" in reasons["workflow_draft_invalid"]
    assert not set(reasons) & set(_deliverables().UNAVAILABLE_REASONS)


def test_the_reasons_and_names_match_the_planning_context(modules):
    context = importlib.import_module("functions_orchestration_workflow_context")
    registry = importlib.import_module("functions_orchestration_registry")
    drafts = importlib.import_module("functions_workflow_drafts")
    deliverables = _deliverables()

    # Each value has one definition in the registry; a local copy added later would fail here.
    assert (
        registry.WORKFLOW_PROPOSALS_SETTING == deliverables.WORKFLOW_PROPOSALS_SETTING
        == context.WORKFLOW_PROPOSALS_SETTING == SETTING
    )
    assert registry.CAPABILITY_WORKFLOW_PROPOSE == context.WORKFLOW_PROPOSE_CAPABILITY_ID == "workflow_propose"
    assert context.WORKFLOW_ACTION_KINDS == registry.WORKFLOW_TASK_ACTION_KINDS
    task_actions = registry.get_capability("workflow_propose")["inputs"]["properties"]["task_actions"]
    assert task_actions["items"]["items"]["enum"] == list(registry.WORKFLOW_TASK_ACTION_KINDS)
    assert set(context.WORKFLOW_M365_ACTION_KINDS) <= set(registry.WORKFLOW_TASK_ACTION_KINDS)
    # The draft service keeps its own literal, so the registry stays importable without storage.
    assert (
        registry.WORKFLOW_PROPOSAL_MAX_TASKS == context.WORKFLOW_BLUEPRINT_MAX_TASKS
        == drafts.BLUEPRINT_MAX_TASKS == task_actions["maxItems"] == 5
    )
    context_reasons = [
        getattr(context, name) for name in dir(context) if name.startswith("WORKFLOW_REASON_")
    ]
    assert context_reasons and set(context_reasons) <= set(deliverables.WORKFLOW_UNAVAILABLE_REASONS)


# ------------------------------------------------------------------------------------------
# The answer step and delivery notes
# ------------------------------------------------------------------------------------------

def _guidance(steps):
    answer = next(step for step in steps if step["step_id"] == "answer")
    return "\n".join(_deliverables().compose_deliverable_guidance(answer, []))


def test_the_answer_step_is_told_a_separate_card_proposes_the_workflow(modules):
    steps = [_answer_step(), _proposal_step()]
    _compile([_answer(), _workflow()], steps, availability=_availability())

    brief = next(step for step in steps if step["step_id"] == "answer")["deliverable_context"]
    assert [entry["relation"] for entry in brief] == ["delivers", "workflow_proposal"]
    assert brief[1]["enabled"] is True
    guidance = _guidance(steps)
    assert "A card after this answer proposes a workflow" in guidance
    assert "Nothing is created or scheduled until the user approves it" in guidance
    assert "Do not say the workflow was created" in guidance


def test_a_turned_off_proposal_is_not_announced(modules):
    steps = [_answer_step(), _proposal_step(enabled=False)]
    _compile([_answer(), _workflow()], steps, availability=None)
    assert "A card after this answer" not in _guidance(steps)


def test_an_unavailable_workflow_is_explained_by_the_answer_step_brief(modules):
    steps = [_answer_step()]
    _compile(
        [_answer(), _workflow(status="unavailable", unavailable_reason="workflow_role_required")],
        steps, availability=_availability(available=False, reason="workflow_role_required"),
    )
    guidance = _guidance(steps)
    assert "which is not available here: Your account does not have access to personal workflows." in guidance
    assert "A card after this answer" not in guidance


def _plan(steps, deliverables):
    compiled_steps = deepcopy(steps)
    compiled = _compile(deliverables, compiled_steps, availability=None)
    return {"steps": compiled_steps, "deliverables": compiled}


def test_delivery_notes_cover_a_workflow_that_was_not_proposed(modules):
    notes = _deliverables().delivery_notes

    unavailable = _plan(
        [_answer_step()],
        [_answer(), _workflow(status="unavailable", unavailable_reason="workflow_draft_invalid")],
    )
    text = notes(unavailable, {"answer": "completed"})
    assert text.startswith("Delivery notes:\n- Not available: A workflow that reviews email every Monday.")
    assert "Create it in Workflows, where you can edit every setting." in text

    turned_off = _plan([_answer_step(), _proposal_step(enabled=False)], [_answer(), _workflow()])
    assert notes(turned_off, {"answer": "completed"}).endswith("Its step was turned off.")

    failed = _plan([_answer_step(), _proposal_step()], [_answer(), _workflow()])
    assert notes(failed, {"answer": "completed", "propose": "failed"}) == (
        "Delivery notes:\n- Not delivered: A workflow that reviews email every Monday. "
        "The workflow proposal could not be prepared."
    )
    # A prepared proposal speaks for itself on its card.
    assert notes(failed, {"answer": "completed", "propose": "completed"}) == ""
