# test_v2_static_security_fix.py
"""
Functional tests for the React V2 static-security check fix.
Version: 0.261.421
Implemented in: 0.261.421

Validate the actual frontend manifest against its lockfile and the unchanged
security checker. Screening fixtures retain visible source escapes rather than
literal hidden controls; their runtime Unicode behavior is tested in Node.
"""

import json
import runpy
from pathlib import Path

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = REPO_ROOT / "application" / "v2_ui"
CHECKER_FILE = REPO_ROOT / "scripts" / "check_malicious_pr_security_review.py"
SCREENING_FIXTURE = REPO_ROOT / "functional_tests" / "test_v2_content_screening_logic.mjs"


def test_frontend_dependencies_are_exact_pins_matching_the_lockfile():
    """Exercise the real checker and require matching root and resolved pins."""
    assert_app_version_at_least("0.261.421")
    checker = runpy.run_path(str(CHECKER_FILE))
    manifest_file = FRONTEND_ROOT / "package.json"
    source = manifest_file.read_text(encoding="utf-8")
    manifest = json.loads(source)
    lockfile = json.loads((FRONTEND_ROOT / "package-lock.json").read_text(encoding="utf-8"))
    findings = []
    releases = []
    checker["inspect_package_json"](manifest_file, source, findings, releases)

    blockers = [finding for finding in findings if finding.verdict == "Blocker"]
    assert blockers == []
    expected_releases = []
    for section in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        dependencies = manifest.get(section, {})
        assert isinstance(dependencies, dict)
        assert lockfile["packages"][""].get(section, {}) == dependencies
        for name, version in sorted(dependencies.items()):
            locked_version = lockfile["packages"][f"node_modules/{name}"]["version"]
            assert version == locked_version, f"{section}.{name} differs from its resolved version"
            expected_releases.append((name, version))
    actual_releases = [(release.package_name, release.version) for release in releases]
    assert actual_releases == expected_releases
    assert actual_releases


def test_screening_fixture_uses_visible_unicode_source_escapes():
    """Keep joined-emoji coverage without literal hidden source controls."""
    checker = runpy.run_path(str(CHECKER_FILE))
    source = SCREENING_FIXTURE.read_text(encoding="utf-8")
    findings = []
    checker["scan_text_patterns"](SCREENING_FIXTURE, source, None, True, findings)

    hidden_controls = checker["HIDDEN_UNICODE_RE"].findall(source)
    blockers = [finding for finding in findings if finding.verdict == "Blocker"]
    assert hidden_controls == []
    assert blockers == []
    assert source.count(r"\u200d") >= 3


if __name__ == "__main__":
    test_frontend_dependencies_are_exact_pins_matching_the_lockfile()
    test_screening_fixture_uses_visible_unicode_source_escapes()
