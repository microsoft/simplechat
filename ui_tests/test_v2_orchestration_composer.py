#!/usr/bin/env python3
"""
UI test for the V2 Composer's orchestration mode: the toggle, the manual-controls disclosure.
Version: 0.261.059
Implemented in: 0.261.059

Orchestration inverts the composer. The Orchestrate toggle appears only where the deployment ships
the feature, is held off by default, and -- once on -- folds the model, agent, reasoning and
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


def test_toggle_is_off_by_default_with_classic_controls():
    """When available the toggle opens off, and the classic manual controls are on the bar."""
    print("Testing orchestration is off by default with the classic controls shown...")
    page = _PAGE
    try:
        page.evaluate(_SEED_COMPOSER, {"features": _features(), "orchestration": _orchestration()})

        pressed = page.eval_on_selector('#mount-a [title="Orchestrate"]', "el => el.getAttribute('aria-pressed')")
        assert pressed == "false", "orchestration must be held off by default"
        # The classic composer shows its manual controls inline: the Documents capability toggle,
        # and the ever-present attach and voice controls.
        assert _has(page, '[title="Documents"]') is True, "the classic composer shows the capability toggles"
        assert _has(page, '[aria-label="Attach a file"]') is True
        assert _has(page, '[aria-label="Voice input"]') is True
        # No disclosure yet -- it belongs to orchestration mode.
        assert _has(page, '[title="Manual controls"]') is False
        print("  ok  the toggle is off by default and the classic controls are shown")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def test_turning_on_collapses_controls_but_keeps_upload_and_voice():
    """Orchestrating folds the pickers behind the disclosure; attach and voice stay put."""
    print("Testing orchestration collapses the manual controls but keeps upload and voice...")
    page = _PAGE
    try:
        page.evaluate(_SEED_COMPOSER, {"features": _features(), "orchestration": _orchestration()})

        classic_pressed = _count_pressed(page)
        assert classic_pressed >= 2, (
            f"classic mode should show the Orchestrate and capability toggles, saw {classic_pressed}"
        )

        # Turn orchestration on.
        page.click('#mount-a [title="Orchestrate"]')
        page.wait_for_function(
            "() => document.querySelector('#mount-a [title=\"Orchestrate\"]')"
            ".getAttribute('aria-pressed') === 'true'",
            timeout=5000,
        )

        # The capability toggles and pickers collapse: the only pressable toggle left is Orchestrate
        # itself, and the Documents capability toggle is gone.
        assert _has(page, '[title="Documents"]') is False, "the capability toggles must collapse"
        assert _count_pressed(page) == 1, "only the Orchestrate toggle should remain once collapsed"
        assert _has(page, '[title="Manual controls"]') is True, "orchestrating offers the disclosure"

        # Upload and voice are deliberately kept on the bar.
        assert _has(page, '[aria-label="Attach a file"]') is True, "file upload must stay visible"
        assert _has(page, '[aria-label="Voice input"]') is True, "voice input must stay visible"

        # Opening the disclosure brings the manual controls back.
        page.click('#mount-a [title="Manual controls"]')
        page.wait_for_function(
            "() => Boolean(document.querySelector('#mount-a [title=\"Documents\"]'))",
            timeout=5000,
        )
        assert _count_pressed(page) >= 2, "opening the disclosure restores the capability toggles"
        print("  ok  orchestration collapsed the pickers, kept upload/voice, and the disclosure restored them")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


PAGE_TESTS = [
    test_toggle_hidden_unless_feature_and_switch_are_on,
    test_toggle_is_off_by_default_with_classic_controls,
    test_turning_on_collapses_controls_but_keeps_upload_and_voice,
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
