#!/usr/bin/env python3
# test_request_intent_side_effect_gate.py
"""
Functional test for the shared request-intent decision that gates side-effect actions.
Version: 0.261.480
Implemented in: 0.261.480

This test ensures that keyword detectors only nominate file exports and background runs,
that an explicit opt-out or a model verdict decides whether they start, that each
permission is tracked separately, that uncertainty withholds the action and says so, and
that the action entry points enforce the decision independently of the detectors.
"""

import os
import sys
import threading
import traceback
import types

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, "application", "single_app")
CHAT_ROUTE = os.path.join(APP_ROOT, "route_backend_chats.py")
EXPORTS_MODULE = os.path.join(APP_ROOT, "functions_tabular_generated_exports.py")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

import functions_request_intent as request_intent  # noqa: E402
from functions_generated_file_exports import (  # noqa: E402
    get_requested_artifact_formats,
    get_requested_generated_file_format,
)
from functions_tabular_orchestration import (  # noqa: E402
    get_tabular_generated_output_formats,
    nominate_side_effect_actions,
    question_requests_tabular_generated_output,
    question_requests_tabular_hierarchical_analysis,
)

FILE = request_intent.ACTION_FILE_EXPORT
BACKGROUND = request_intent.ACTION_BACKGROUND_RUN
ALLOWED = request_intent.PERMISSION_ALLOWED
WITHHELD = request_intent.PERMISSION_WITHHELD

STEP_5C_PROMPT = (
    "STEP 5C - LOSS-EVENT SCENARIO CONSTRUCTION AND AUTHORIZATION. Establish the causal "
    "beginning of each candidate loss-event scenario and analyze every row. This phase "
    "produces the scenario analysis in the chat. Do not generate JSON, create files, or "
    "initiate background processing."
)
MISFIRING_PROMPTS = (
    "You must not generate JSON for these. Analyze every row in chat.",
    "Respond in chat rather than as a JSON file for all rows.",
    "JSON output is not permitted. Analyze all rows.",
    "Step 5D will generate the JSON. For now, analyze all rows in chat.",
)
GENUINE_PROMPTS = (
    "Convert all rows to a JSON file",
    "Export every row as XML and give me the complete file",
)


def make_model(reply=None, error=None, calls=None):
    """Return a stand-in for chat.completions.create."""
    def create_completion(**kwargs):
        if calls is not None:
            calls.append(kwargs)
        if error is not None:
            raise error
        message = types.SimpleNamespace(content=reply)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])
    return create_completion


def resolve(prompt, reply=None, error=None, mode="active", calls=None, **kwargs):
    return request_intent.resolve_request_intent(
        prompt,
        nominate_actions=nominate_side_effect_actions,
        mode=mode,
        create_completion=make_model(reply=reply, error=error, calls=calls),
        model="test-model",
        **kwargs,
    )


def reset():
    request_intent.bind_request_intent(None)
    request_intent._turn_decisions.clear()


def test_opt_out_is_deterministic_and_per_action():
    print("Testing explicit opt-outs are deterministic and scoped per action...")
    assert request_intent.explicit_side_effect_opt_out(STEP_5C_PROMPT) == {FILE, BACKGROUND}
    assert request_intent.explicit_side_effect_opt_out("No files please. Analyze every row.") == {FILE}
    assert request_intent.explicit_side_effect_opt_out(
        "Do not use background processing. Export all rows to CSV."
    ) == {BACKGROUND}
    assert request_intent.explicit_side_effect_opt_out("Answer in chat only.") == {FILE, BACKGROUND}
    # Mentioning the topic is not an opt-out, and unrelated instructions are not affected.
    assert request_intent.explicit_side_effect_opt_out("How does background processing work?") == set()
    assert request_intent.explicit_side_effect_opt_out("Answer here, and remember my preferred units.") == set()
    assert request_intent.explicit_side_effect_opt_out("Which files did I upload?") == set()

    # The opt-out applies with the model check off and without any model call.
    calls = []
    decision = resolve(STEP_5C_PROMPT, mode="off", calls=calls)
    assert decision["permissions"] == {FILE: WITHHELD, BACKGROUND: WITHHELD}, decision
    assert decision["sources"][FILE] == request_intent.SOURCE_OPT_OUT
    assert not calls, "An explicit opt-out must not need a model call."
    print("  passed")


def test_ordinary_messages_are_untouched():
    print("Testing ordinary messages produce no decision and no model call...")
    calls = []
    assert resolve("What is the average order value by region?", calls=calls) is None
    assert resolve("", calls=calls) is None
    assert not calls
    print("  passed")


def test_model_verdict_blocks_known_misfires():
    print("Testing the model verdict withholds keyword misfires...")
    reply = '{"file_export": "not_wanted", "formats": [], "background_run": "not_wanted", "reason": "forbidden"}'
    for prompt in MISFIRING_PROMPTS:
        reset()
        nominated = nominate_side_effect_actions(prompt)
        assert FILE in nominated, f"Expected keywords to nominate a file export for: {prompt}"
        decision = resolve(prompt, reply=reply)
        request_intent.bind_request_intent(decision, conversation_id="conv-1")
        assert get_requested_artifact_formats(prompt) == [], prompt
        assert get_tabular_generated_output_formats(prompt) == [], prompt
        assert question_requests_tabular_generated_output(prompt) is False, prompt
        assert question_requests_tabular_hierarchical_analysis(prompt) is False, prompt
    reset()
    print("  passed")


def test_genuine_requests_still_fire():
    print("Testing genuine export requests still start...")
    for prompt in GENUINE_PROMPTS:
        reset()
        requested_format = get_tabular_generated_output_formats(prompt)[0]
        reply = (
            '{"file_export": "wanted", "formats": ["%s"], "background_run": "wanted", "reason": "asked"}'
            % requested_format
        )
        decision = resolve(prompt, reply=reply)
        request_intent.bind_request_intent(decision, conversation_id="conv-1")
        assert decision["permissions"] == {FILE: ALLOWED, BACKGROUND: ALLOWED}, decision
        assert get_tabular_generated_output_formats(prompt) == [requested_format], prompt
        assert question_requests_tabular_generated_output(prompt) is True, prompt
        assert request_intent.build_request_intent_withheld_notice(decision) == ""
    reset()
    print("  passed")


def test_uncertainty_withholds_and_is_visible():
    print("Testing failures and unclear verdicts withhold the action and say so...")
    prompt = GENUINE_PROMPTS[0]
    cases = {
        "unclear": dict(reply='{"file_export": "unclear", "background_run": "unclear"}'),
        "not json": dict(reply="I think they want a file."),
        "empty": dict(reply=""),
        "timeout": dict(error=TimeoutError("timed out")),
        "error": dict(error=RuntimeError("endpoint unavailable")),
    }
    for label, case in cases.items():
        reset()
        decision = resolve(prompt, **case)
        assert decision["permissions"] == {FILE: WITHHELD, BACKGROUND: WITHHELD}, (label, decision)
        assert decision["sources"][FILE] == request_intent.SOURCE_FALLBACK, (label, decision)
        notice = request_intent.build_request_intent_withheld_notice(decision)
        assert "did not create a file" in notice, (label, notice)
        assert "did not start background processing" in notice, (label, notice)
        assert "single chat response" in notice, (label, notice)

    # The user's own opt-out needs no notice: they already know.
    reset()
    assert request_intent.build_request_intent_withheld_notice(resolve(STEP_5C_PROMPT)) == ""

    # The answering model is told not to promise a file or claim full coverage.
    system_message = request_intent.build_request_intent_system_message(resolve(STEP_5C_PROMPT))
    assert system_message["role"] == "system"
    assert "No file will be created" in system_message["content"]
    assert "Never present partial coverage as complete" in system_message["content"]
    print("  passed")


def test_missing_model_keeps_keyword_behavior():
    print("Testing a path with no model keeps today's keyword behavior...")
    reset()
    prompt = GENUINE_PROMPTS[0]
    decision = request_intent.resolve_request_intent(
        prompt, nominate_actions=nominate_side_effect_actions, mode="active", create_completion=None, model=None,
    )
    assert decision["permissions"] == {FILE: ALLOWED, BACKGROUND: ALLOWED}, decision
    assert decision["sources"][FILE] == request_intent.SOURCE_UNCHECKED
    print("  passed")


def test_parameter_rejection_retries_with_defaults():
    print("Testing the check retries when an endpoint rejects the request options...")
    reset()
    calls = []
    reply = '{"file_export": "wanted", "formats": ["json"], "background_run": "wanted"}'

    def create_completion(**kwargs):
        calls.append(kwargs)
        if "max_tokens" in kwargs:
            raise ValueError("Unsupported parameter: 'max_tokens' is not supported with this model.")
        message = types.SimpleNamespace(content=reply)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

    decision = request_intent.resolve_request_intent(
        GENUINE_PROMPTS[0], nominate_actions=nominate_side_effect_actions, mode="active",
        create_completion=create_completion, model="reasoning-model",
    )
    assert len(calls) == 2 and "max_tokens" not in calls[1], calls
    assert decision["permissions"][FILE] == ALLOWED, decision
    print("  passed")


def test_shadow_mode_logs_without_changing_behavior():
    print("Testing shadow mode records the verdict but changes nothing...")
    reset()
    prompt = MISFIRING_PROMPTS[1]
    reply = '{"file_export": "not_wanted", "background_run": "not_wanted"}'
    decision = resolve(prompt, reply=reply, mode="shadow")
    assert decision["permissions"] == {FILE: ALLOWED, BACKGROUND: ALLOWED}, decision
    assert decision["shadow_verdict"] == {FILE: "not_wanted", BACKGROUND: "not_wanted"}, decision
    request_intent.bind_request_intent(decision, conversation_id="conv-1")
    assert get_tabular_generated_output_formats(prompt) == ["json"]
    reset()
    print("  passed")


def test_user_override_and_prior_message():
    print("Testing the per-turn override and lazy prior-message context...")
    reset()
    calls = []
    decision = resolve(GENUINE_PROMPTS[0], calls=calls, suppressed_actions={FILE, BACKGROUND})
    assert decision["permissions"] == {FILE: WITHHELD, BACKGROUND: WITHHELD}, decision
    assert decision["sources"][FILE] == request_intent.SOURCE_USER_OVERRIDE
    assert not calls, "An explicit override must not need a model call."
    assert request_intent.build_request_intent_withheld_notice(decision) == ""

    read_count = []

    def read_prior():
        read_count.append(1)
        return "Which columns should the JSON file include?"

    calls = []
    resolve(
        GENUINE_PROMPTS[0],
        reply='{"file_export": "wanted", "formats": ["json"], "background_run": "wanted"}',
        calls=calls,
        prior_assistant_text=read_prior,
    )
    assert read_count == [1]
    assert "Which columns should the JSON file include?" in calls[0]["messages"][1]["content"]
    print("  passed")


def test_decision_is_bound_to_one_message():
    print("Testing a decision never leaks to a different message...")
    reset()
    blocked_prompt = MISFIRING_PROMPTS[1]
    decision = resolve(blocked_prompt, reply='{"file_export": "not_wanted", "background_run": "not_wanted"}')
    request_intent.bind_request_intent(decision, conversation_id="conv-1")
    other_prompt = GENUINE_PROMPTS[0]
    assert get_tabular_generated_output_formats(other_prompt) == ["json"]
    assert question_requests_tabular_generated_output(other_prompt) is True
    assert get_requested_generated_file_format("Summarize this as a PDF") == "pdf"
    assert request_intent.action_withheld(other_prompt, BACKGROUND, conversation_id="conv-1") is False
    reset()
    print("  passed")


def test_entry_points_enforce_across_threads():
    print("Testing action entry points enforce the decision on another thread...")
    reset()
    prompt = MISFIRING_PROMPTS[1]
    decision = resolve(prompt, reply='{"file_export": "not_wanted", "background_run": "not_wanted"}')
    request_intent.bind_request_intent(decision, conversation_id="conv-1")

    results = {}

    def worker():
        # A new thread starts with an empty context, so only the turn registry can answer.
        results["context_only"] = request_intent.action_withheld(prompt, BACKGROUND)
        results["with_conversation"] = request_intent.action_withheld(prompt, BACKGROUND, conversation_id="conv-1")
        results["other_conversation"] = request_intent.action_withheld(prompt, BACKGROUND, conversation_id="conv-2")
        try:
            request_intent.enforce_action_permitted(prompt, BACKGROUND, conversation_id="conv-1")
            results["raised"] = False
        except request_intent.RequestIntentWithheldError as exc:
            results["raised"] = exc.action == BACKGROUND

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    assert results == {
        "context_only": False,
        "with_conversation": True,
        "other_conversation": False,
        "raised": True,
    }, results

    # No recorded decision means no enforcement, so workflows and other callers are unaffected.
    request_intent.enforce_action_permitted("Export all rows to CSV", BACKGROUND, conversation_id="conv-9")
    reset()
    print("  passed")


def test_action_entry_points_are_wired():
    print("Testing the chat route and run queue call the enforcement...")
    with open(CHAT_ROUTE, "r", encoding="utf-8") as route_file:
        route_source = route_file.read()
    with open(EXPORTS_MODULE, "r", encoding="utf-8") as exports_file:
        exports_source = exports_file.read()

    assert route_source.count("resolve_chat_turn_request_intent(") == 3, "Expected one definition and two route calls."
    assert route_source.count("action_withheld(user_question, ACTION_FILE_EXPORT, conversation_id=conversation_id)") >= 3
    assert route_source.count("action_withheld(user_question, ACTION_BACKGROUND_RUN, conversation_id=conversation_id)") >= 2
    assert route_source.count("except RequestIntentWithheldError:") == 3
    assert route_source.count("append_request_intent_withheld_notice(") == 3
    assert route_source.count("maybe_append_request_intent_system_message(") == 4
    assert "Understood. I am generating" not in route_source
    assert "The app started a background job to generate the complete" in route_source
    assert "enforce_action_permitted(user_question, ACTION_BACKGROUND_RUN" in exports_source
    assert "enforce_action_permitted(user_question, ACTION_FILE_EXPORT" in exports_source
    print("  passed")


if __name__ == "__main__":
    assert_app_version_at_least("0.261.480")
    tests = [
        test_opt_out_is_deterministic_and_per_action,
        test_ordinary_messages_are_untouched,
        test_model_verdict_blocks_known_misfires,
        test_genuine_requests_still_fire,
        test_uncertainty_withholds_and_is_visible,
        test_missing_model_keeps_keyword_behavior,
        test_parameter_rejection_retries_with_defaults,
        test_shadow_mode_logs_without_changing_behavior,
        test_user_override_and_prior_message,
        test_decision_is_bound_to_one_message,
        test_entry_points_enforce_across_threads,
        test_action_entry_points_are_wired,
    ]
    failures = 0
    for test in tests:
        try:
            test()
        except Exception as exc:
            failures += 1
            print(f"  FAILED {test.__name__}: {exc}")
            traceback.print_exc()
    print(f"{len(tests) - failures}/{len(tests)} tests passed")
    sys.exit(0 if failures == 0 else 1)
