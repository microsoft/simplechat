# test_deep_research_chromium_build_opt_out.py
#!/usr/bin/env python3
"""
Functional test for Deep Research Chromium build opt-out.
Version: 0.241.069
Implemented in: 0.241.068

This test ensures azd container builds can skip Playwright Chromium browser
packaging by setting SIMPLECHAT_INSTALL_CHROMIUM=false before deployment.
"""

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = REPO_ROOT / "application" / "single_app" / "Dockerfile"
AZURE_YAML = REPO_ROOT / "deployers" / "azure.yaml"
DEPLOYER_VERSION = REPO_ROOT / "deployers" / "version.txt"


def read_text(path):
    """Read a workspace file as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def assert_contains(source_text, expected_text, description):
    """Assert expected deployment wiring is present."""
    if expected_text not in source_text:
        raise AssertionError(f"Missing {description}: {expected_text}")


def test_dockerfile_supports_chromium_build_arg():
    """Validate Dockerfile can skip Chromium browser/runtime packaging."""
    dockerfile = read_text(DOCKERFILE)

    assert_contains(dockerfile, "ARG INSTALL_PLAYWRIGHT_CHROMIUM=true", "Chromium install build arg")
    assert_contains(dockerfile, "Skipping Chromium runtime package installation", "native dependency skip path")
    assert_contains(dockerfile, "Skipping Playwright Chromium browser installation", "browser download skip path")
    assert_contains(dockerfile, "COPY --from=builder /playwright-runtime/ /", "distroless runtime copy path")


def test_azd_predeploy_passes_chromium_build_arg():
    """Validate azd predeploy maps SIMPLECHAT_INSTALL_CHROMIUM into ACR build args."""
    azure_yaml = read_text(AZURE_YAML)

    assert_contains(azure_yaml, "SIMPLECHAT_INSTALL_CHROMIUM", "azd Chromium install environment setting")
    assert_contains(azure_yaml, "--build-arg INSTALL_PLAYWRIGHT_CHROMIUM=${install_chromium}", "POSIX ACR build arg")
    assert_contains(azure_yaml, "--build-arg \"INSTALL_PLAYWRIGHT_CHROMIUM=$installChromium\"", "Windows ACR build arg")
    assert_contains(azure_yaml, "Chromium rendering runtime install:", "deployment output for Chromium install setting")


def test_deployer_version_updated_for_build_contract():
    """Validate deployer version was bumped for the ACR build contract change."""
    deployer_version = read_text(DEPLOYER_VERSION).strip()
    if deployer_version != "1.0.4":
        raise AssertionError(f"Expected deployer version 1.0.4, found {deployer_version}")


def main():
    """Run all Chromium build opt-out checks."""
    tests = [
        test_dockerfile_supports_chromium_build_arg,
        test_azd_predeploy_passes_chromium_build_arg,
        test_deployer_version_updated_for_build_contract,
    ]
    results = []

    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            print(f"PASS {test.__name__}")
            results.append(True)
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
            results.append(False)

    passed = sum(1 for result in results if result)
    print(f"Results: {passed}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
