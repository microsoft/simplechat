#!/usr/bin/env python3
"""
Functional test for V2 agent / model / reasoning exclusivity.

Version: 0.261.034
Implemented in: 0.261.034

In the V2 chat composer the Model, Agent and Reasoning pickers were all independently live.
Selecting an agent left a model showing as selected and left a reasoning level selectable,
but neither applies: an agent answers with its own ``azure_openai_gpt_deployment``, and
``reasoning_effort`` only ever reaches the direct-model path.

The visible part was the smaller half. ``chatStore.sendMessage`` assigned the model identity
unconditionally and then appended ``agent_info`` and ``reasoning_effort``, so V2 posted all
three together -- and the server reads a model identity sent alongside ``agent_info`` as a
deliberate override, which meant V2 never reached any of the agent default-model handling the
route already has.

This test first establishes the server's contract rather than assuming it, then asserts the
client honours it: an agent selection sends ``agent_info`` and nothing else, the model picker
is shown as overridden rather than removed or disabled, and the reasoning picker is hidden.
"""

import os
import subprocess
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
APP = REPO_ROOT / "application" / "single_app"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"
V2_UI = REPO_ROOT / "application" / "v2_ui"

IMPLEMENTED_IN = "0.261.034"


def read(*parts) -> str:
    return Path(*parts).read_text(encoding="utf-8")


def slice_between(text: str, start: str, end: str) -> str:
    """Take the body of a store action, so an assertion is scoped to it."""
    begin = text.index(start)
    return text[begin : text.index(end, begin)]


def test_version_is_at_least_the_implementing_release():
    """The fix must be present in the running application."""
    print("Testing the application version...")
    try:
        assert_app_version_at_least(IMPLEMENTED_IN)
        print("  ok  version is at least the implementing release")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_the_server_treats_a_model_alongside_an_agent_as_an_override():
    """Establish the server's contract rather than assuming it.

    This is the assertion the whole change rests on. If the route ever stops keying its
    agent default-model handling on the absence of a model identity, suppressing those
    fields becomes the wrong thing to do and this test should be the first to say so.
    """
    print("Testing the server's agent-versus-model contract...")
    try:
        route = read(APP, "route_backend_chats.py")

        assert "should_use_default_model = (" in route, (
            "the route must still decide whether an agent request picks its own model"
        )
        for condition in (
            "_has_chat_agent_selection(request_agent_info)",
            "and not data.get('model_id')",
            "and not data.get('model_endpoint_id')",
        ):
            assert condition in route, (
                f"expected {condition!r} in the should_use_default_model condition -- "
                "an agent request only falls back to the default model when no model "
                "identity was sent"
            )

        # The condition is what gates the multi-endpoint default.
        assert "allow_default_selection=should_use_default_model" in route, (
            "the multi-endpoint resolver must be told when it may choose a default"
        )

        # And the two non-multi-endpoint configurations have their own agent handling, so
        # omitting the model is a supported request shape in every deployment.
        assert (
            "[GPT_CLIENT] Agent request without model_deployment; defaulting to first APIM deployment."
            in route
        ), "the APIM path must have its own agent-without-a-model fallback"
        assert 'raise ValueError("No GPT model selected or configured.")' in route, (
            "the legacy single-endpoint path falls back to the configured default model"
        )

        print("  ok  a model identity sent with an agent suppresses the agent default")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_an_agent_supplies_its_own_model_and_takes_no_reasoning_level():
    """Why the two controls are inert under an agent, established from the source."""
    print("Testing that an agent brings its own deployment...")
    try:
        loader = read(APP, "semantic_kernel_loader.py")
        assert 'deployment = agent.get("azure_openai_gpt_deployment")' in loader, (
            "an agent answers with its own deployment, which is why the model picker "
            "cannot apply to it"
        )

        route = read(APP, "route_backend_chats.py")
        assert "def _resolve_reasoning_effort_for_model(" in route, (
            "reasoning effort is resolved per model"
        )
        # It only ever lands on the direct-model call parameters.
        assert "api_params['reasoning_effort'] = request_reasoning_effort" in route
        assert "stream_params['reasoning_effort'] = request_reasoning_effort" in route

        print("  ok  the agent path takes neither the picked model nor a reasoning level")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_the_divergence_from_the_classic_client_is_deliberate():
    """V1 posts a model alongside an agent. That is the bug, not the behaviour to match."""
    print("Testing the classic client's behaviour...")
    try:
        classic = read(APP, "static", "js", "chat", "chat-messages.js")

        # The classic payload always carries a model, whatever mode the UI is in...
        assert "model_deployment: modelDeployment," in classic
        assert "agent_info: agentInfo," in classic
        # ...because the model selection is read without checking that agent mode hid it.
        model_selection = slice_between(
            classic, "function getCurrentModelSelection()", "function getCurrentAgentSelection()"
        )
        assert "agent-select-container" not in model_selection, (
            "if the classic client ever starts checking agent mode before reading the "
            "model select, revisit whether V2 should still diverge"
        )
        # Whereas its agent selection *is* mode-aware, which is the asymmetry behind the bug.
        agent_selection = slice_between(
            classic, "function getCurrentAgentSelection()", "\n}\n"
        )
        assert "areAgentsEnabled()" in agent_selection

        print("  ok  the classic client's asymmetry is confirmed, so the divergence is known")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_the_request_builder_owns_the_exclusivity():
    """The rule lives in one place, not in JSX and the store separately."""
    print("Testing the shared request-selection helper...")
    try:
        selection = read(V2_SRC, "lib", "chatRequestSelection.ts")

        assert "export function buildSelectionFields(" in selection
        assert "export function hasResolvableAgent(" in selection
        # The identity contracts established by the earlier fix are reused, not re-derived.
        assert "agentInfoForSelection" in selection, (
            "agent_info must keep its dict shape, which the server requires"
        )
        assert "modelIdentityForSelection" in selection, (
            "the four-field model identity must still be resolved from the catalog"
        )

        print("  ok  buildSelectionFields is the single source of the rule")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_the_store_no_longer_sends_both_halves():
    """Neither send nor retry may reintroduce the combination."""
    print("Testing the chat store...")
    try:
        store = read(V2_SRC, "stores", "chatStore.ts")

        send = slice_between(store, "sendMessage: async", "\n    },")
        assert "buildSelectionFields({" in send, (
            "sendMessage must build its routing fields through the shared rule"
        )
        assert "modelIdentityForSelection(" not in send, (
            "the model identity must no longer be assigned unconditionally"
        )
        assert "requestBody.agent_info =" not in send, (
            "agent_info must no longer be appended after a model identity"
        )
        assert "requestBody.reasoning_effort =" not in send, (
            "reasoning_effort must no longer be appended independently"
        )

        retry = slice_between(store, "retryMessage: async", "\n    },")
        assert "buildSelectionFields({" in retry, (
            "retry must go through the same rule, or it can reintroduce the conflict"
        )
        assert "model: options?.modelDeployment" not in retry, (
            "sending the selection key as the model name would not resolve"
        )
        assert "model: selection.model_deployment" in retry, (
            "the retry endpoint takes a flat deployment name, resolved from the catalog"
        )

        print("  ok  both request paths route through the exclusive rule")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_the_model_picker_is_overridden_rather_than_disabled():
    """It has to stay usable: choosing a model is the way back out of agent mode."""
    print("Testing the Dropdown inactive state...")
    try:
        dropdown = read(V2_SRC, "components", "ui", "Dropdown.tsx")

        assert "inactive?: boolean;" in dropdown
        assert "inactive = false," in dropdown
        # The trigger falls back to the placeholder while the value is retained.
        assert "const triggerLabel = inactive ? placeholder :" in dropdown, (
            "an overridden picker shows its placeholder rather than the retained label"
        )
        # But the menu still marks the retained value, so what returns is visible.
        assert "const isSelected = option.value === value;" in dropdown

        # Crucially, inactive must not feed the disabled attribute.
        assert "disabled={disabled}" in dropdown, "disabled stays its own, separate prop"
        assert "disabled={disabled || inactive}" not in dropdown, (
            "an overridden picker must stay clickable, since using it clears the agent"
        )

        print("  ok  the overridden picker is muted but still usable")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_the_composer_wires_the_rule_into_the_toolbar():
    """The visible half: what the user sees must match what is sent."""
    print("Testing the composer toolbar...")
    try:
        gating = read(V2_SRC, "lib", "composerGating.ts")
        assert "agentActive: boolean;" in gating
        assert "modelPickerInactive: boolean;" in gating
        assert "showReasoning: boolean;" in gating
        assert "modelPickerInactive: agentActive," in gating
        assert "showReasoning: !agentActive && !imageGenerationActive," in gating

        composer = read(V2_SRC, "components", "chat", "Composer.tsx")

        # The agent must be resolved against the catalog, not taken from the raw key.
        assert "hasResolvableAgent(" in composer
        assert "agentActive," in composer, "the gating rule must be told about the agent"

        assert "inactive={gating.modelPickerInactive}" in composer
        # Picking a model is what takes the override off.
        assert "agentSelection: undefined," in composer, (
            "choosing a model must clear the agent, since the two cannot both apply"
        )
        # Picking an agent must not clear the model: it is retained, just not in force.
        assert "modelDeployment: undefined" not in composer, (
            "the model selection is retained under an agent and comes back when it is cleared"
        )

        assert "{gating.showReasoning && reasoningLevels.length > 0 && (" in composer, (
            "the reasoning picker must be gated on the rule as well as on model support"
        )

        print("  ok  the toolbar reflects the same rule as the request")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_the_typescript_logic_checks_pass():
    """Run the bundled behaviour checks, when the front-end toolchain is installed."""
    print("Testing the behaviour of the rule itself...")
    try:
        check = Path(__file__).with_name("test_v2_agent_model_exclusivity_logic.ts")
        assert check.exists(), "the logic check file is missing"

        if not (V2_UI / "node_modules").exists():
            print("  --  skipped the TypeScript checks: run npm install in application/v2_ui")
            return True

        # The check file lives in functional_tests/, which has no node_modules of its own, so
        # bare imports are left for node to resolve from where the bundle is written.
        bundle = V2_UI / "node_modules" / ".cache-agent-model-exclusivity-check.mjs"
        try:
            subprocess.run(
                [
                    "npx",
                    "esbuild",
                    str(check),
                    "--bundle",
                    "--platform=node",
                    "--format=esm",
                    "--packages=external",
                    f"--outfile={bundle}",
                    "--log-level=error",
                ],
                cwd=str(V2_UI),
                check=True,
                shell=(sys.platform == "win32"),
            )
            result = subprocess.run(
                ["node", str(bundle)],
                cwd=str(V2_UI),
                capture_output=True,
                text=True,
                shell=(sys.platform == "win32"),
            )
        finally:
            if bundle.exists():
                bundle.unlink()

        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr)
            raise AssertionError("the TypeScript logic checks failed")

        passed = result.stdout.count("  ok  ")
        assert passed >= 25, f"expected the full check suite, saw {passed} checks"
        print(f"  ok  {passed} TypeScript logic checks passed")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


TESTS = [
    test_version_is_at_least_the_implementing_release,
    test_the_server_treats_a_model_alongside_an_agent_as_an_override,
    test_an_agent_supplies_its_own_model_and_takes_no_reasoning_level,
    test_the_divergence_from_the_classic_client_is_deliberate,
    test_the_request_builder_owns_the_exclusivity,
    test_the_store_no_longer_sends_both_halves,
    test_the_model_picker_is_overridden_rather_than_disabled,
    test_the_composer_wires_the_rule_into_the_toolbar,
    test_the_typescript_logic_checks_pass,
]


if __name__ == "__main__":
    results = []
    for test in TESTS:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
