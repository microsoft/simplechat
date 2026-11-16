# test_group_agent_assertion_execution.py
"""
Functional tests for group-agent API request execution outside assertions.
Version: 0.261.422
Implemented in: 0.261.422

The real group-agent contract module and its existing isolated backend harness
run in fresh normal and optimized Python processes. Required API requests and
their response checks must survive assertion removal without any live network.
"""

import ast
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_FILE = REPO_ROOT / "functional_tests" / "test_group_agent_apis.py"


def test_api_requests_are_not_embedded_in_assertions():
    """Prevent HTTP requests from disappearing when Python removes assertions."""
    assert_app_version_at_least("0.261.422")
    source = CONTRACT_FILE.read_text(encoding="utf-8")
    request_lines = []
    for assertion in ast.walk(ast.parse(source)):
        if not isinstance(assertion, ast.Assert):
            continue
        for call in ast.walk(assertion.test):
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Attribute)
                and call.func.value.attr == "client"
            ):
                request_lines.append(call.lineno)
    assert request_lines == [], f"API calls remain inside assertions at lines {request_lines}"


@pytest.mark.parametrize("optimized", [False, True], ids=["normal", "optimized"])
def test_real_api_request_contracts_survive_optimization(optimized):
    """Check the actual request/status sequence in a cold process in both modes."""
    command = [sys.executable]
    if optimized:
        command.append("-O")
    command.extend([str(Path(__file__).resolve()), "--probe"])
    environment = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONOPTIMIZE": "0",
    }
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report == {"optimized": optimized, "scenarios": 12, "requests": 49}


def run_request_probe():
    """Load the real contracts only inside the isolated subprocess."""
    # These imports intentionally stay in the probe so parent collection does
    # not import or initialize the backend harness.
    from flask import request
    import test_group_agent_apis as contracts

    cases = []
    for group_id in ("locked-grp", "upload-disabled-grp", "inactive-grp"):
        cases.append((
            contracts.test_writes_are_refused_outside_active_status,
            {"group_id": group_id},
            [("POST", 403), ("PATCH", 403), ("DELETE", 403)],
        ))
    cases.append((
        contracts.test_writes_on_a_global_id_are_refused,
        {},
        [("PATCH", 404), ("DELETE", 404)],
    ))
    denied_routes = [
        ("GET", 403), ("GET", 403), ("GET", 403), ("GET", 403),
        ("POST", 403), ("PATCH", 403), ("DELETE", 403),
    ]
    for flag in contracts.AVAILABILITY_FLAGS:
        cases.append((
            contracts.test_every_route_refuses_when_an_availability_flag_is_off,
            {"flag": flag},
            denied_routes,
        ))
    cases.extend([
        (contracts.test_every_route_refuses_when_governance_denies, {}, denied_routes),
        (contracts.test_delete_logs_agent_deletion_with_group_scope, {}, [("DELETE", 200)]),
        (
            contracts.test_a_refused_write_logs_nothing,
            {"role": "User"},
            [("POST", 403), ("DELETE", 403), ("PATCH", 200), ("PATCH", 409), ("POST", 400)],
        ),
        (contracts.test_unknown_group_is_404_and_unknown_agent_is_404, {}, [("GET", 404), ("GET", 404)]),
        (contracts.test_agent_options_rejects_query_and_body, {}, [("GET", 400), ("GET", 400)]),
    ])

    request_count = 0
    for contract, arguments, expected in cases:
        observed = []
        with pytest.MonkeyPatch.context() as monkeypatch:
            setup = contracts.environment.__wrapped__(monkeypatch)
            backend = next(setup)
            try:
                @backend.app.after_request
                def record_response(response):
                    observed.append((request.method, response.status_code))
                    return response

                contract(backend, **arguments)
                if observed != expected:
                    raise AssertionError(
                        f"{contract.__name__}: expected {expected}, observed {observed}"
                    )
                request_count += len(observed)
            finally:
                try:
                    next(setup)
                except StopIteration:
                    pass

    print(json.dumps({
        "optimized": not __debug__,
        "scenarios": len(cases),
        "requests": request_count,
    }))


if __name__ == "__main__":
    if sys.argv[1:] == ["--probe"]:
        run_request_probe()
    else:
        raise SystemExit(pytest.main([__file__, "-q"]))
