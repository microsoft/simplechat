# test_codeql_workflow_configuration.py
"""Functional tests for coverage-preserving Advanced CodeQL configuration.

Version: 0.261.401
Implemented in: 0.261.399

These tests validate checked-in workflow coverage, not live repository setup or
successful processing of uploaded analyses.
"""

from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def workflow():
    source = (ROOT / ".github" / "workflows" / "codeql.yml").read_text(encoding="utf-8")
    return yaml.load(source, Loader=yaml.BaseLoader)


def test_advanced_codeql_preserves_branch_and_periodic_coverage(workflow):
    events = workflow["on"]
    expected = {"main", "Staging", "Development", "paullizer-react-v2-ui"}
    assert set(events["push"]["branches"]) == expected
    assert set(events["pull_request"]["branches"]) == expected
    assert "workflow_dispatch" in events
    assert "pull_request_target" not in events
    assert events["schedule"] == [{"cron": "17 4 * * 1"}]


def test_advanced_codeql_keeps_all_languages_and_quality_queries(workflow):
    job = workflow["jobs"]["analyze"]
    matrix = job["strategy"]["matrix"]["include"]
    assert len(matrix) == 3
    assert {entry["language"] for entry in matrix} == {
        "actions", "javascript-typescript", "python",
    }
    assert all(entry["build-mode"] == "none" for entry in matrix)
    assert job["strategy"]["fail-fast"] == "false"
    initialize = next(
        step for step in job["steps"]
        if step.get("uses", "").startswith("github/codeql-action/init@")
    )
    assert initialize["with"]["languages"] == "${{ matrix.language }}"
    assert initialize["with"]["queries"] == "+security-and-quality"


def test_advanced_codeql_uploads_each_language_with_required_permissions(workflow):
    job = workflow["jobs"]["analyze"]
    assert job["permissions"]["security-events"] == "write"
    assert job["permissions"]["contents"] == "read"
    analyze = next(
        step for step in job["steps"]
        if step.get("uses", "").startswith("github/codeql-action/analyze@")
    )
    assert analyze["with"]["category"] == "/language:${{matrix.language}}"
    assert "upload" not in analyze["with"]
    assert "continue-on-error" not in job
    assert "continue-on-error" not in analyze
