#!/usr/bin/env python3
"""
Functional test for V2 reasoning effort persistence.

Version: 0.261.036
Implemented in: 0.261.036

The V2 reasoning level used to live only in the composer's local state. It was never read
from or written to /api/user/settings, so it was lost on every remount -- navigating away
and back, or reloading -- and it was never cleared when the model changed, which meant a
level chosen for gpt-5 was still sent after switching to gpt-4o, a model that has no
reasoning at all.

The fix reuses the contract the classic interface already has rather than inventing a second
one: the level is stored per model in the `reasoningEffortSettings` user setting, and the
chosen model is stored in `preferredModelId` / `preferredModelDeployment`, which is what
`_build_initial_chat_model_selection` restores the picker from.

Three things are pinned here.

**The keys have to be whitelisted.** /api/user/settings validates against `allowed_keys` in
route_backend_users.py and drops anything outside it **without complaining** -- the POST
still returns success and the value never arrives, so the preference appears to save and is
gone on the next load.

**The key a level is stored under has to match the classic interface.** Both write the same
map, so `getCurrentModelName()` and `reasoningModelKey()` must agree on model id before
deployment name. If they disagree, a level set in one interface is invisible in the other.

**The level has to be derived, not remembered.** The composer must clear the effort for a
model that offers no choice, or the stale value is sent to a model that rejects it.

The resolution itself is exercised by the companion Node test, which is run from here.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"
LEGACY_CHAT_JS = APP_DIR / "static" / "js" / "chat"
LOGIC_TEST = REPO_ROOT / "functional_tests" / "test_v2_reasoning_effort_logic.mjs"

IMPLEMENTED_IN = "0.261.036"

# The settings this fix depends on, all of which are shared with the classic interface.
SHARED_SETTING_KEYS = (
    "reasoningEffortSettings",
    "preferredModelId",
    "preferredModelDeployment",
)

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


def _read(path):
    return path.read_text(encoding="utf-8")


def _allowed_keys():
    """The whitelist the settings route validates against."""
    users = _read(APP_DIR / "route_backend_users.py")
    block = re.search(r"allowed_keys = \{(.*?)\}", users, re.DOTALL)
    assert block, "Could not find allowed_keys in route_backend_users.py"
    return set(re.findall(r"['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]", block.group(1)))


def _writable_keys():
    """The keys the V2 client declares it may write."""
    settings = _read(V2_SRC / "lib" / "userSettings.ts")
    block = re.search(
        r"export const WRITABLE_USER_SETTING_KEYS = \[(.*?)\] as const;", settings, re.DOTALL
    )
    assert block, "Could not find WRITABLE_USER_SETTING_KEYS in userSettings.ts"
    return set(re.findall(r"'([^']+)'", block.group(1)))


def test_the_shared_keys_are_declared_and_accepted():
    """A key outside the route's whitelist is discarded silently, so both sides must list it."""
    print("Testing the shared settings keys...")

    writable = _writable_keys()
    allowed = _allowed_keys()

    for key in SHARED_SETTING_KEYS:
        assert key in writable, (
            f"{key!r} is written by the V2 composer but is not declared in "
            "WRITABLE_USER_SETTING_KEYS, so the whitelist test cannot cover it"
        )
        assert key in allowed, (
            f"{key!r} is not in allowed_keys, so /api/user/settings will return success and "
            "then discard it"
        )

    print(f"All {len(SHARED_SETTING_KEYS)} shared keys are declared and accepted!")
    return True


def test_the_storage_key_matches_the_classic_client():
    """Both interfaces write the same map, so they must key a model the same way."""
    print("Testing the per-model storage key...")

    legacy = _read(LEGACY_CHAT_JS / "chat-reasoning.js")
    # The classic client keys on dataset.modelId first, falling back to the deployment name.
    assert "selectedOption?.dataset?.modelId || selectedOption?.dataset?.deploymentName" in legacy, (
        "chat-reasoning.js no longer resolves the model name id-first; the V2 key must "
        "follow whatever it does now or the shared map splits in two"
    )
    assert "reasoningEffortSettings[modelName]" in legacy, (
        "chat-reasoning.js no longer stores the level per model"
    )

    reasoning = _read(V2_SRC / "lib" / "reasoning.ts")
    assert "export function reasoningModelKey" in reasoning, (
        "V2 needs a single place that decides how a model is keyed in the shared map"
    )
    assert "return modelId || deployment ||" in reasoning, (
        "reasoningModelKey must prefer the model id, matching getCurrentModelName()"
    )

    print("Storage key test passed!")
    return True


def test_the_composer_reads_and_writes_the_shared_map():
    """The level has to survive a remount, which means reading and writing the setting."""
    print("Testing composer persistence...")

    composer = _read(V2_SRC / "components" / "chat" / "Composer.tsx")

    assert "state.settings.reasoningEffortSettings" in composer, (
        "The composer must read the stored level, or it starts empty on every mount"
    )
    assert "reasoningEffortSettings: { ...saved, ...levels }" in composer, (
        "A chosen level must be written back into the shared map under the model's key"
    )
    assert "resolveReasoningEffort(reasoningKey, reasoningEffortSettings)" in composer, (
        "The level in effect must be resolved from the model and the stored map"
    )

    # Derived, not remembered: a model that offers no choice must carry no level at all, and
    # a deployment with no model catalog must not have one guessed for it.
    derived = re.search(
        r"reasoningKey && reasoningLevels\.length > 0\s*\?\s*resolveReasoningEffort\(", composer
    )
    assert derived, (
        "The effort must be cleared for a model with no reasoning and left alone when there "
        "is no model identity, or a stale or invented level is sent"
    )
    assert re.search(r"if \(!reasoningKey\) \{\s*return;", composer), (
        "The sync effect must leave the session's own choice alone when there is no model "
        "to derive a level from"
    )

    # The route stores this setting whole, and the app renders before the settings load
    # necessarily finishes, so an early write would replace the map with a single entry.
    assert "pendingLevels.current = { ...pendingLevels.current, [reasoningKey]: level }" in composer, (
        "A level chosen before the stored map arrives must be held, not written into an "
        "empty map, which would discard every other model's level"
    )
    assert "if (!settingsLoaded || Object.keys(pendingLevels.current).length === 0)" in composer, (
        "The held levels must be written once the map has been read, or the choice is lost"
    )
    assert "useUserSettingsStore.getState().settings" in composer, (
        "The write must merge into the map as it stands at write time, not as it was when "
        "the choice was made"
    )
    assert "settingsFailed" in composer, (
        "A settings load that failed leaves no map to merge into; the user has to be told "
        "the level is not being saved rather than left to discover it"
    )

    # Derived, not remembered: a model that offers no choice must carry no level at all.
    derived = re.search(
        r"reasoningLevels\.length > 0\s*\?\s*resolveReasoningEffort\(", composer
    )
    assert derived, (
        "The effort must be cleared for a model with no reasoning, or a stale level is sent "
        "to a model that rejects it"
    )

    # There is always an effective level once a model is known, so the control is clearable
    # only where none is derived -- a deployment with no model catalog.
    reasoning_control = composer.split(
        "{gating.showReasoning && reasoningLevels.length > 0 && ("
    )[1].split(")}")[0]
    assert "clearable={!reasoningKey}" in reasoning_control, (
        "The reasoning picker should be clearable only where no level is in effect; a model "
        "with a level already has `None` as an explicit option where it is supported"
    )

    print("Composer persistence test passed!")
    return True


def test_the_model_selection_is_remembered():
    """Per-model memory is meaningless if the model itself is not restored."""
    print("Testing model selection persistence...")

    composer = _read(V2_SRC / "components" / "chat" / "Composer.tsx")
    assert "preferredModelId: modelSelectionKey(model)" in composer, (
        "The chosen model must be saved as its selection key, which is what "
        "_build_initial_chat_model_selection matches on"
    )
    assert "preferredModelDeployment: deployment" in composer, (
        "The deployment name is the server's fallback when the selection key no longer "
        "resolves, so it is saved too"
    )
    assert "rememberModelSelection(value)" in composer, (
        "The save must be wired to the model picker's change handler"
    )

    # The server side of the contract, which is what makes the saved keys matter.
    bootstrap = _read(APP_DIR / "route_backend_v2.py")
    assert 'user_settings_dict.get("preferredModelId")' in bootstrap, (
        "The bootstrap must still resolve the initial model from preferredModelId"
    )

    print("Model selection test passed!")
    return True


def test_none_is_not_sent_to_the_endpoint():
    """`none` is a choice in the picker but not a value the endpoint takes."""
    print("Testing the none level...")

    legacy = _read(LEGACY_CHAT_JS / "chat-reasoning.js")
    assert "return effort === 'none' ? null : effort;" in legacy, (
        "chat-reasoning.js no longer suppresses none; V2 should follow whatever it does now"
    )

    reasoning = _read(V2_SRC / "lib" / "reasoning.ts")
    assert "export function requestReasoningEffort" in reasoning, (
        "V2 needs one place that decides what is safe to send"
    )

    # Every request's routing fields are built here, for both the send and the retry path,
    # so this is the one place the level has to be filtered.
    selection = _read(V2_SRC / "lib" / "chatRequestSelection.ts")
    assert "requestReasoningEffort(input.reasoningEffort)" in selection, (
        "The reasoning level must be filtered where a request's routing fields are built, "
        "or `none` reaches the endpoint"
    )
    assert "if (input.reasoningEffort)" not in selection, (
        "The raw level must not be assigned directly; `none` would pass straight through"
    )

    store = _read(V2_SRC / "stores" / "chatStore.ts")
    assert "requestBody.reasoning_effort =" not in store, (
        "The level must not be attached outside buildSelectionFields, which is also what "
        "keeps it off the agent path"
    )
    assert "reasoning_effort: options?.reasoningEffort," not in store, (
        "The retry path must not send the raw level, or `none` reaches the endpoint"
    )

    print("None-level test passed!")
    return True


def test_reasoning_logic_behaves():
    """Run the companion runtime test, which executes the resolution itself.

    The assertions above prove the composer is wired to the setting. They cannot prove that
    the right level comes out of it, because that is behaviour rather than shape. The Node
    test does that, and is run from here so it cannot quietly rot next to a suite that never
    invokes it.

    Node is not otherwise required to work on this repository, so its absence is reported
    rather than failed. A Node that is present and reports a failure is a failure.
    """
    print("Testing reasoning resolution behaviour...")
    if not LOGIC_TEST.exists():
        raise AssertionError(f"The runtime logic test is missing: {LOGIC_TEST}")

    node = shutil.which("node")
    if not node:
        print("  Node is not installed; skipping the runtime logic test.")
        print(f"  Run it with: node {LOGIC_TEST.relative_to(REPO_ROOT)}")
        return True

    completed = subprocess.run(
        [node, str(LOGIC_TEST)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    output = (completed.stdout or "") + (completed.stderr or "")

    # Node below 22.6 cannot import TypeScript directly. That is a limitation of the
    # environment, not a defect in the code under test.
    if completed.returncode != 0 and "Unknown file extension" in output:
        print("  This Node cannot import TypeScript directly (needs 22.6 or newer); skipping.")
        return True

    for line in output.splitlines():
        if line.strip():
            print(f"  {line}")

    if completed.returncode != 0:
        raise AssertionError("The runtime logic test failed; see the output above.")

    print("Reasoning resolution test passed!")
    return True


def test_version_was_incremented():
    """The application version records when this shipped."""
    print("Testing version...")
    version = assert_app_version_at_least(
        IMPLEMENTED_IN,
        reason="V2 per-model reasoning effort persistence.",
    )
    print(f"  config.py VERSION is {version}.")
    print("Version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_the_shared_keys_are_declared_and_accepted,
        test_the_storage_key_matches_the_classic_client,
        test_the_composer_reads_and_writes_the_shared_map,
        test_the_model_selection_is_remembered,
        test_none_is_not_sent_to_the_endpoint,
        test_reasoning_logic_behaves,
        test_version_was_incremented,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
        except Exception as exc:  # noqa: BLE001 - surface any failure with a traceback
            print(f"Test failed: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
