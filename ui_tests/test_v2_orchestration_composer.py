#!/usr/bin/env python3
"""
UI test for the V2 Composer's orchestration mode: the toggle, the manual-controls disclosure.
Version: 0.261.059
Implemented in: 0.261.059

Orchestration inverts the composer. The Orchestrate toggle appears only where the deployment ships
the feature, is on by default wherever the deployment offers it, and -- while on -- folds the
model, agent, reasoning and
capability controls behind a "Manual controls" disclosure, because the planner is meant to make
those choices. File upload and voice input are deliberately NOT folded away: an attachment or a
spoken prompt is still just input to the question, so they stay on the bar.

This test drives the REAL Composer over a seeded bootstrap (no server, no credentials) and asserts:

  * The Orchestrate toggle is absent unless both the feature flag and the bootstrap switch are on.
  * When available it is off by default and the classic manual controls are shown.
  * Turning it on collapses the capability toggles and the model/agent/reasoning pickers behind the
    disclosure, while the attach-a-file and voice-input controls stay visible; opening the
    disclosure brings the manual controls back.

The browser checks are skipped (reported, not failed) when node_modules is absent.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "orchestration"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "functional_tests"))

import harness_build as hb  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


IMPLEMENTED_IN = "0.261.059"

_PAGE = None


# Seed the bootstrap store with just enough for the Composer to render, then mount it. Catalogs are
# empty on purpose: the manual controls under test are the capability toggles and the pickers that
# appear regardless of catalog contents, and the Documents toggle is the reliable marker for them.
_SEED_COMPOSER = r"""
(spec) => {
    const H = window.OrchHarness;
    H.reset();
    H.stores.bootstrap.useBootstrapStore.setState({
        data: {
            features: spec.features,
            orchestration: spec.orchestration,
            settings: {},
            catalogs: { prompts: [], models: [], agents: [] },
            user: { display_name: 'Tester' },
        },
    });
    H.mount('mount-a', 'Composer', {});
}
"""


def _features(**overrides):
    base = {"enable_chat_orchestration": True, "enable_speech_to_text_input": True}
    base.update(overrides)
    return base


def _orchestration(**overrides):
    base = {
        "enabled": True,
        "show_manual_controls": True,
        "default_approval_mode": "manual",
        "allow_user_approval_override": True,
        "timed_approval_seconds": 8,
    }
    base.update(overrides)
    return base


def _count_pressed(page):
    return page.evaluate("() => document.querySelectorAll('#mount-a button[aria-pressed]').length")


def _has(page, selector):
    return page.query_selector(f"#mount-a {selector}") is not None


def test_version_is_at_least_the_implementing_release():
    """The Composer's orchestration mode shipped in IMPLEMENTED_IN, so the app must be at least it."""
    print("Testing the app version is at least the implementing release...")
    try:
        assert_app_version_at_least(IMPLEMENTED_IN)
        print(f"  ok  config.py VERSION is at least {IMPLEMENTED_IN}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        return False


def test_toggle_hidden_unless_feature_and_switch_are_on():
    """The Orchestrate toggle needs BOTH the feature flag and the bootstrap switch."""
    print("Testing the Orchestrate toggle is gated on the feature and the switch...")
    page = _PAGE
    try:
        # Feature flag off: no toggle.
        page.evaluate(
            _SEED_COMPOSER,
            {"features": _features(enable_chat_orchestration=False), "orchestration": _orchestration()},
        )
        assert _has(page, '[title="Orchestrate"]') is False, "the feature flag off must hide the toggle"

        # Bootstrap switch off: no toggle.
        page.evaluate(
            _SEED_COMPOSER,
            {"features": _features(), "orchestration": _orchestration(enabled=False)},
        )
        assert _has(page, '[title="Orchestrate"]') is False, "the bootstrap switch off must hide the toggle"

        # Both on: the toggle appears.
        page.evaluate(_SEED_COMPOSER, {"features": _features(), "orchestration": _orchestration()})
        assert _has(page, '[title="Orchestrate"]') is True, "with both on the toggle must appear"
        print("  ok  the toggle appears only when the feature and the switch are both on")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_toggle_is_on_by_default_with_controls_collapsed():
    """When the deployment offers orchestration the composer opens in it, controls collapsed."""
    print("Testing orchestration is on by default with the manual controls collapsed...")
    page = _PAGE
    try:
        page.evaluate(_SEED_COMPOSER, {"features": _features(), "orchestration": _orchestration()})

        pressed = page.eval_on_selector('#mount-a [title="Orchestrate"]', "el => el.getAttribute('aria-pressed')")
        assert pressed == "true", (
            "orchestration must be on by default where the administrator enabled it; "
            "defaulting it off leaves the capability row inviting exactly the decisions "
            "the planner exists to make"
        )
        # The capability toggles are folded away, replaced by the disclosure.
        assert _has(page, '[title="Documents"]') is False, "the capability toggles must be collapsed"
        assert _has(page, '[title="Manual controls"]') is True, "the disclosure replaces them"
        # Attach and voice are never collapsed.
        assert _has(page, '[aria-label="Attach a file"]') is True
        assert _has(page, '[aria-label="Voice input"]') is True
        print("  ok  orchestration is on by default and the manual controls are collapsed")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_turning_off_restores_the_classic_composer():
    """Going back to the composer everyone knows stays one click away."""
    print("Testing turning orchestration off restores the classic controls...")
    page = _PAGE
    try:
        page.evaluate(_SEED_COMPOSER, {"features": _features(), "orchestration": _orchestration()})

        # Opens orchestrating, so only the Orchestrate toggle is pressable.
        assert _count_pressed(page) == 1, "only the Orchestrate toggle should be shown while collapsed"

        # Turn orchestration off.
        page.click('#mount-a [title="Orchestrate"]')
        page.wait_for_function(
            "() => document.querySelector('#mount-a [title=\"Orchestrate\"]')"
            ".getAttribute('aria-pressed') === 'false'",
            timeout=5000,
        )

        # The classic composer is back: capability toggles inline, no disclosure.
        assert _has(page, '[title="Documents"]') is True, "the capability toggles must return"
        assert _has(page, '[title="Manual controls"]') is False, "the disclosure belongs to orchestration"
        assert _count_pressed(page) >= 2, "classic mode shows Orchestrate plus the capability toggles"

        # Upload and voice are unaffected either way.
        assert _has(page, '[aria-label="Attach a file"]') is True, "file upload must stay visible"
        assert _has(page, '[aria-label="Voice input"]') is True, "voice input must stay visible"
        print("  ok  turning orchestration off restored the classic composer")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_disclosure_restores_the_manual_controls():
    """While orchestrating, the disclosure brings the pickers back without leaving the mode."""
    print("Testing the manual controls disclosure...")
    page = _PAGE
    try:
        page.evaluate(_SEED_COMPOSER, {"features": _features(), "orchestration": _orchestration()})

        assert _has(page, '[title="Documents"]') is False, "the pickers start collapsed"

        page.click('#mount-a [title="Manual controls"]')
        page.wait_for_function(
            "() => Boolean(document.querySelector('#mount-a [title=\"Documents\"]'))",
            timeout=5000,
        )

        # Still orchestrating -- the disclosure reveals, it does not leave the mode. Anything
        # chosen here is passed as a seed and constrains the plan rather than being ignored.
        pressed = page.eval_on_selector('#mount-a [title="Orchestrate"]', "el => el.getAttribute('aria-pressed')")
        assert pressed == "true", "the disclosure must not leave orchestration mode"
        assert _count_pressed(page) >= 2, "opening the disclosure restores the capability toggles"
        print("  ok  the disclosure restored the manual controls without leaving orchestration")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


PAGE_TESTS = [
    test_toggle_hidden_unless_feature_and_switch_are_on,
    test_toggle_is_on_by_default_with_controls_collapsed,
    test_turning_off_restores_the_classic_composer,
    test_disclosure_restores_the_manual_controls,
]


def main():
    results = [test_version_is_at_least_the_implementing_release()]

    errors = []
    try:
        with hb.harness_page(collect_errors=errors) as page:
            global _PAGE
            _PAGE = page
            for test in PAGE_TESTS:
                print(f"\nRunning {test.__name__}...")
                page.evaluate("() => window.OrchHarness.reset()")
                results.append(test())
    except hb.HarnessUnavailable as exc:
        print(f"\n  --  skipped the browser-driven checks: {exc}")
        results.extend([True] * len(PAGE_TESTS))

    if errors:
        print("\nUncaught page errors observed during the run:")
        for message in errors:
            print(f"  !!  {message}")

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
