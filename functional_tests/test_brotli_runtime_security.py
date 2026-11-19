# test_brotli_runtime_security.py
"""Regression coverage for SimpleChat's patched Node and Playwright runtimes.

Version: 0.261.455
Implemented in: 0.261.453

Check actual Playwright executables as well as shipped build/deployment settings.
The security floor includes the October Brotli fix and November Node fixes.
No malformed compressed input, Azure calls, or application bootstrap is needed.
"""

import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
PATCHED_NODE_FLOORS = {
    22: (22, 23, 5),
    24: (24, 22, 3),
    26: (26, 13, 1),
}


def assert_patched_node(version):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", version.strip())
    assert match, f"Unrecognized Node version: {version!r}"
    parsed = tuple(int(part) for part in match.groups())
    floor = PATCHED_NODE_FLOORS.get(parsed[0])
    assert floor is not None, f"Node {version} is not a reviewed, supported release line."
    assert parsed >= floor, f"Node {version} predates the required security release {floor}."


def playwright_pin(path):
    matches = re.findall(r"^playwright==(\S+)\s*$", path.read_text(encoding="utf-8"), re.MULTILINE)
    assert len(matches) == 1, f"Expected one exact Playwright pin in {path}."
    return matches[0]


@pytest.mark.parametrize("version", ["22.23.5", "v24.22.3", "26.13.1", "24.22.4"])
def test_fixed_node_versions_are_accepted(version):
    assert_patched_node(version)


@pytest.mark.parametrize("version", [
    "20.20.1", "24.13.0", "24.22.1", "26.12.0", "26.13.0", "27.0.0", "",
])
def test_old_or_unreviewed_node_versions_are_rejected(version):
    with pytest.raises(AssertionError):
        assert_patched_node(version)


def test_installed_playwright_and_ui_requirements_match_application_pin():
    app_pin = playwright_pin(ROOT / "application" / "single_app" / "requirements.txt")
    ui_pin = playwright_pin(ROOT / "ui_tests" / "requirements.txt")
    installed = importlib.metadata.version("playwright")
    assert ui_pin == app_pin
    assert installed == app_pin, f"Install the application's Playwright pin before checking its runtime: {app_pin}."


def test_playwright_bundled_and_effective_node_are_patched():
    spec = importlib.util.find_spec("playwright")
    assert spec is not None and spec.origin, "Install the application's Playwright dependency."
    bundled = Path(spec.origin).parent / "driver" / ("node.exe" if sys.platform == "win32" else "node")
    assert bundled.is_file(), "Validate a platform wheel containing the production Node driver, not a source-only install."
    effective = os.environ.get("PLAYWRIGHT_NODEJS_PATH") or str(bundled)
    for executable in dict.fromkeys((str(bundled), effective)):
        result = subprocess.run(
            [executable, "--version"], capture_output=True, text=True, timeout=30, check=True,
        )
        assert_patched_node(result.stdout)


def test_frontend_builder_and_ci_use_patched_node():
    dockerfile = (ROOT / "application" / "single_app" / "Dockerfile").read_text(encoding="utf-8")
    builder = re.search(
        r"^FROM mcr\.microsoft\.com/azurelinux/base/nodejs:(\d+\.\d+\.\d+)-\S+ AS v2uibuilder$",
        dockerfile, re.MULTILINE,
    )
    assert builder, "Pin the MCR frontend builder to a reviewed Node patch release."
    assert_patched_node(builder.group(1))
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "staging-ui-smoke.yml").read_text(encoding="utf-8"))
    setup_node = [
        step for step in workflow["jobs"]["ui-smoke"]["steps"]
        if step.get("uses", "").startswith("actions/setup-node@")
    ]
    assert len(setup_node) == 1
    assert_patched_node(setup_node[0]["with"]["node-version"])


def test_optional_host_source_and_generated_arm_use_supported_node_lts():
    source = (ROOT / "deployers" / "bicep" / "modules" / "v2FrontendAppService.bicep").read_text(encoding="utf-8")
    runtime = re.search(r"linuxFxVersion:\s*'(NODE\|24-lts)'", source)
    assert runtime, "The optional frontend must use the reviewed Node 24 LTS platform runtime."
    template = json.loads((ROOT / "deployers" / "bicep" / "main.json").read_text(encoding="utf-8"))

    def node_runtimes(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "linuxFxVersion" and isinstance(child, str) and child.startswith("NODE|"):
                    yield child
                else:
                    yield from node_runtimes(child)
        elif isinstance(value, list):
            for child in value:
                yield from node_runtimes(child)

    assert list(node_runtimes(template)) == [runtime.group(1)], "Regenerate ARM after changing the Bicep runtime."
