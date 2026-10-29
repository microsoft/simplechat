#!/usr/bin/env python3
# test_image_generation_api_version_default.py
"""
Functional test for the Azure OpenAI image generation API version default and its migration.
Version: 0.261.047
Implemented in: 0.261.047

azure_openai_image_gen_api_version defaulted to 2024-12-01-preview, which predates gpt-image
model support. The default is now 2025-04-01-preview, the newest dated Azure OpenAI API version and
the one Microsoft documents for gpt-image-1, gpt-image-1.5, and gpt-image-2. deep_merge_dicts()
never overwrites a key that a persisted settings document already has, so existing deployments
keep the old default unless it is migrated when settings load.

This test ensures that:
  - the shipped default is 2025-04-01-preview,
  - normalize_image_generation_api_version_settings() upgrades the previous default and blank
    values, leaves any other value untouched, and never changes the APIM API version,
  - the migration runs on every settings load and is persisted to the settings document,
  - the admin documentation and example settings artifacts show the new default.

The migration helper is loaded from source without importing functions_settings, which builds
Azure clients at import time. The end-to-end load check imports the real module in fresh normal
and optimized processes with external I/O blocked.
"""

import ast
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
TEST_ROOT = ROOT / "functional_tests"
SETTINGS_FILE = APP_ROOT / "functions_settings.py"
IMPLEMENTED_IN_VERSION = "0.261.047"
NEW_DEFAULT = "2025-04-01-preview"
PREVIOUS_DEFAULT = "2024-12-01-preview"
MIGRATION_FUNCTION = "normalize_image_generation_api_version_settings"
DEFAULT_CONSTANT = "AZURE_OPENAI_IMAGE_GEN_API_VERSION_DEFAULT"
PREVIOUS_DEFAULT_CONSTANT = "AZURE_OPENAI_IMAGE_GEN_API_VERSION_PREVIOUS_DEFAULT"

if str(TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_ROOT))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


def _require(condition, message):
    """Raise explicitly so checks survive python -O."""
    if not condition:
        raise AssertionError(message)


def load_migration():
    """Load the migration helper and its constants from source, without importing Azure config."""
    tree = ast.parse(SETTINGS_FILE.read_text(encoding="utf-8"), filename=str(SETTINGS_FILE))
    wanted_constants = {DEFAULT_CONSTANT, PREVIOUS_DEFAULT_CONSTANT}

    selected_nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == MIGRATION_FUNCTION:
            selected_nodes.append(node)
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in wanted_constants
        ):
            selected_nodes.append(node)

    assert len(selected_nodes) == 3, (
        f"Expected {DEFAULT_CONSTANT}, {PREVIOUS_DEFAULT_CONSTANT}, and {MIGRATION_FUNCTION}() "
        "at module level in functions_settings.py"
    )

    namespace = {}
    exec(compile(ast.Module(body=selected_nodes, type_ignores=[]), str(SETTINGS_FILE), "exec"), namespace)
    return namespace


def _function_node(tree, name):
    return next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)


def test_default_is_the_newest_gpt_image_api_version():
    """The code-level default must be 2025-04-01-preview."""
    assert_app_version_at_least(IMPLEMENTED_IN_VERSION)
    namespace = load_migration()
    assert namespace[DEFAULT_CONSTANT] == NEW_DEFAULT
    assert namespace[PREVIOUS_DEFAULT_CONSTANT] == PREVIOUS_DEFAULT

    source = SETTINGS_FILE.read_text(encoding="utf-8")
    assert f"'azure_openai_image_gen_api_version': {DEFAULT_CONSTANT}," in source, (
        "get_settings() defaults must use the named image generation API version constant"
    )
    assert f"'azure_openai_image_gen_api_version': '{PREVIOUS_DEFAULT}'" not in source
    assert "'azure_apim_image_gen_api_version': ''," in source, (
        "The APIM image generation API version must keep having no default"
    )


def test_previous_default_is_upgraded():
    """A stored value equal to the previous default was never customized, so it is upgraded."""
    migrate = load_migration()[MIGRATION_FUNCTION]
    settings = {
        "azure_openai_image_gen_api_version": PREVIOUS_DEFAULT,
        "azure_apim_image_gen_api_version": "",
        "unrelated_key": "left alone",
    }

    changed = migrate(settings)

    assert changed is True
    assert settings["azure_openai_image_gen_api_version"] == NEW_DEFAULT
    assert settings["azure_apim_image_gen_api_version"] == ""
    assert settings["unrelated_key"] == "left alone"

    padded = {"azure_openai_image_gen_api_version": f"  {PREVIOUS_DEFAULT} "}
    assert migrate(padded) is True and padded["azure_openai_image_gen_api_version"] == NEW_DEFAULT


@pytest.mark.parametrize("stored_version", ["", "   ", None])
def test_blank_values_are_upgraded(stored_version):
    """A blank stored value would send no API version, so it becomes the new default."""
    migrate = load_migration()[MIGRATION_FUNCTION]
    settings = {"azure_openai_image_gen_api_version": stored_version}

    changed = migrate(settings)

    assert changed is True
    assert settings["azure_openai_image_gen_api_version"] == NEW_DEFAULT


def test_missing_value_is_filled():
    """A document without the key gets the new default rather than nothing."""
    migrate = load_migration()[MIGRATION_FUNCTION]
    settings = {}

    changed = migrate(settings)

    assert changed is True
    assert settings == {"azure_openai_image_gen_api_version": NEW_DEFAULT}


@pytest.mark.parametrize("custom_version", ["2025-03-01-preview", "2024-10-21", "2024-05-01-preview", NEW_DEFAULT])
def test_custom_values_are_left_untouched(custom_version):
    """Any other value is an admin's deliberate choice, and an up-to-date value needs no write."""
    migrate = load_migration()[MIGRATION_FUNCTION]
    settings = {"azure_openai_image_gen_api_version": custom_version}

    changed = migrate(settings)

    assert changed is False
    assert settings["azure_openai_image_gen_api_version"] == custom_version


def test_apim_version_is_never_changed():
    """APIM gateways define their own API version, so it is never migrated."""
    migrate = load_migration()[MIGRATION_FUNCTION]
    for apim_version in (PREVIOUS_DEFAULT, "", "   ", "2024-02-01"):
        settings = {
            "azure_openai_image_gen_api_version": PREVIOUS_DEFAULT,
            "azure_apim_image_gen_api_version": apim_version,
        }
        migrate(settings)
        assert settings["azure_apim_image_gen_api_version"] == apim_version, (
            f"The APIM API version {apim_version!r} must not be migrated"
        )

    apim_only = {"azure_openai_image_gen_api_version": "2025-03-01-preview", "azure_apim_image_gen_api_version": PREVIOUS_DEFAULT}
    assert migrate(apim_only) is False
    assert apim_only["azure_apim_image_gen_api_version"] == PREVIOUS_DEFAULT


def test_unexpected_input_is_handled_safely():
    """Non-dict settings and non-string values must not raise or be rewritten."""
    migrate = load_migration()[MIGRATION_FUNCTION]
    assert migrate(None) is False
    assert migrate("not-a-dict") is False

    settings = {"azure_openai_image_gen_api_version": 20250401}
    assert migrate(settings) is False
    assert settings["azure_openai_image_gen_api_version"] == 20250401


def test_migration_is_wired_into_every_settings_load():
    """get_settings() must run the migration inside normalize_loaded_settings()."""
    tree = ast.parse(SETTINGS_FILE.read_text(encoding="utf-8"), filename=str(SETTINGS_FILE))
    loader = _function_node(_function_node(tree, "get_settings"), "normalize_loaded_settings")
    calls = [
        node for node in ast.walk(loader)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == MIGRATION_FUNCTION
    ]
    assert len(calls) == 1, f"normalize_loaded_settings() must call {MIGRATION_FUNCTION}() once"
    assert [ast.unparse(arg) for arg in calls[0].args] == ["merged"], "The migration must run on the merged settings"


def test_docs_and_example_artifacts_show_the_new_default():
    """Admin docs and example settings must match the shipped image generation default."""
    ai_models_doc = (ROOT / "docs" / "admin" / "ai-models.md").read_text(encoding="utf-8")
    image_row = next(line for line in ai_models_doc.splitlines() if "`azure_openai_image_gen_api_version`" in line)
    assert f"| {NEW_DEFAULT} |" in image_row, f"The Image Gen API Version row must show {NEW_DEFAULT}: {image_row}"
    apim_row = next(line for line in ai_models_doc.splitlines() if "`azure_apim_image_gen_api_version`" in line)
    assert "| Empty |" in apim_row, "The APIM image generation API version must still have no default"

    cosmos_example = json.loads((ROOT / "artifacts" / "cosmos_examples" / "cosmos-settings-example.json").read_text(encoding="utf-8"))
    assert cosmos_example["azure_openai_image_gen_api_version"] == NEW_DEFAULT
    assert cosmos_example["azure_openai_gpt_api_version"] == PREVIOUS_DEFAULT, "Only the image generation entry changes"
    assert cosmos_example["azure_openai_embedding_api_version"] == PREVIOUS_DEFAULT, "Only the image generation entry changes"

    seeder_settings = json.loads(
        (ROOT / "application" / "external_apps" / "databaseseeder" / "artifacts" / "admin_settings.json").read_text(encoding="utf-8")
    )
    assert seeder_settings["azure_openai_image_gen_api_version"] == NEW_DEFAULT
    assert seeder_settings["azure_apim_image_gen_api_version"] == ""


def _run_offline_probe():
    # Real application imports must occur inside the external-I/O bootstrap seam.
    from test_support.offline_bootstrap import offline_app_imports  # noqa: PLC0415

    with offline_app_imports() as offline:
        import functions_settings as settings_module  # noqa: PLC0415
        _require(not offline.network_attempts, "Settings imports attempted network access.")
        container = settings_module.cosmos_settings_container

        for stored_version, apim_version, expected_version in (
            (PREVIOUS_DEFAULT, PREVIOUS_DEFAULT, NEW_DEFAULT),
            ("", "", NEW_DEFAULT),
            ("   ", "2024-02-01", NEW_DEFAULT),
            ("2025-03-01-preview", "", "2025-03-01-preview"),
        ):
            container.upsert_item({
                "id": "app_settings",
                "azure_openai_image_gen_api_version": stored_version,
                "azure_apim_image_gen_api_version": apim_version,
            })

            loaded = settings_module.get_settings()
            _require(isinstance(loaded, dict), "Settings must load.")
            _require(loaded["azure_openai_image_gen_api_version"] == expected_version,
                     f"Loaded {loaded['azure_openai_image_gen_api_version']!r} for stored {stored_version!r}.")
            _require(loaded["azure_apim_image_gen_api_version"] == apim_version,
                     f"The APIM version {apim_version!r} must not be migrated.")

            persisted = container.read_item(item="app_settings", partition_key="app_settings")
            _require(persisted["azure_openai_image_gen_api_version"] == expected_version,
                     f"The migrated value must be persisted for stored {stored_version!r}.")
            _require(persisted["azure_apim_image_gen_api_version"] == apim_version,
                     "The persisted APIM version must be unchanged.")

        _require(settings_module.get_settings()["azure_openai_image_gen_api_version"] == "2025-03-01-preview",
                 "A custom value must survive repeated loads.")
        _require(not offline.network_attempts, "Settings loads attempted network access.")

    print("Image generation API version load migration checks passed.")


@pytest.mark.parametrize("optimized", (False, True))
def test_settings_load_migrates_and_persists_the_api_version(optimized):
    """Run the real get_settings() load path in a fresh process with external I/O blocked."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT), str(APP_ROOT), str(TEST_ROOT)))
    env["PYTHONIOENCODING"] = "utf-8"
    command = [sys.executable]
    if optimized:
        command.append("-O")
    command.extend((str(Path(__file__).resolve()), "--offline-probe"))
    result = subprocess.run(
        command, cwd=ROOT, env=env, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_version_is_at_least_implementation_version():
    """The app version must be at or beyond the version this fix shipped in."""
    assert_app_version_at_least(IMPLEMENTED_IN_VERSION)


if __name__ == "__main__":
    if "--offline-probe" in sys.argv:
        _run_offline_probe()
    else:
        raise SystemExit(pytest.main([__file__, "-q"]))
