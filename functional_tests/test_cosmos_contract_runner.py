# test_cosmos_contract_runner.py
"""Functional tests for portable, isolated Cosmos contract subprocess execution.

Version: 0.261.402
Implemented in: 0.261.399

The full selection must survive Windows command limits without changing node
IDs, child exit codes, or network blocking before collection.
"""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "cosmos_contract_runner_checker", ROOT / "scripts" / "check_cosmos_response_boundaries.py",
)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


@pytest.fixture
def contract_runner_root(tmp_path, monkeypatch):
    root = tmp_path / "workspace with spaces"
    root.mkdir()
    inventory = root / "inventory.json"
    inventory.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(checker, "ROOT", root)
    monkeypatch.setattr(checker, "INVENTORY", inventory)
    monkeypatch.setattr(checker, "scan_boundaries", lambda: {})
    monkeypatch.setattr(checker, "scan_doubles", lambda: {})
    monkeypatch.setattr(checker, "validate_inventory", lambda *args, **kwargs: [])
    monkeypatch.setattr(sys, "argv", ["check_cosmos_response_boundaries.py", "--run-contracts"])
    return root


@pytest.mark.parametrize("launch_failure", [False, True])
def test_contract_runner_preserves_large_selections_and_cleans_argument_file(
    contract_runner_root, monkeypatch, launch_failure,
):
    root = contract_runner_root
    targets = [
        f"functional_tests/test_owner_{index:04d}.py::test_contract[case with spaces]"
        for index in range(512)
    ]
    expected = [
        f"{root / 'functional_tests' / f'test_owner_{index:04d}.py'}::test_contract[case with spaces]"
        for index in range(512)
    ]
    old_length = len(subprocess.list2cmdline([sys.executable, "-m", "pytest", *expected]))
    assert old_length > 32767
    monkeypatch.setattr(checker, "runtime_test_targets", lambda inventory: targets)
    monkeypatch.setenv("PYTHONPATH", "retained-python-path")
    monkeypatch.setenv("COSMOS_RUNNER_SENTINEL", "retained")
    captured = {}

    def run_child(command, *, cwd, env, check):
        argument_files = [argument[1:] for argument in command if argument.startswith("@")]
        assert len(argument_files) == 1
        argument_file = Path(argument_files[0])
        captured["argument_file"] = argument_file
        actual = argument_file.read_text(encoding="utf-8").splitlines()
        command_length = len(subprocess.list2cmdline(command))
        assert actual == expected
        assert command_length < 32767
        assert command[:5] == [
            sys.executable, "-m", "pytest", "-p", "test_support.cosmos_network_guard",
        ]
        assert command[-3:] == ["-q", "--disable-warnings", "--tb=short"]
        assert cwd == root and check is False
        assert env["COSMOS_RUNNER_SENTINEL"] == "retained"
        assert env["PYTHONPATH"].split(os.pathsep) == [
            str(root / "application" / "single_app"), str(root / "functional_tests"),
            "retained-python-path",
        ]
        if launch_failure:
            raise OSError("Contract child could not start.")
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(checker.subprocess, "run", run_child)
    if launch_failure:
        with pytest.raises(OSError, match="could not start"):
            checker.main()
    else:
        result = checker.main()
        assert result == 7
    argument_directory_exists = captured["argument_file"].parent.exists()
    assert argument_directory_exists is False


def test_contract_runner_uses_real_child_selection_and_guard_before_collection(
    contract_runner_root, monkeypatch,
):
    tests = contract_runner_root / "functional_tests"
    tests.mkdir()
    test_file = tests / "test_selected.py"
    test_file.write_text(
        "import socket\n"
        "import pytest\n"
        "if socket.getaddrinfo.__module__ != 'test_support.cosmos_network_guard':\n"
        "    raise AssertionError('Network guard was not active before collection.')\n"
        "with pytest.raises(AssertionError, match='cannot access the network'):\n"
        "    socket.getaddrinfo('contract.invalid', 443)\n"
        "@pytest.mark.parametrize('choice', ['case with spaces', 'second'])\n"
        "def test_selected(choice):\n"
        "    if choice not in {'case with spaces', 'second'}:\n"
        "        raise AssertionError('Unexpected parameter.')\n"
        "def test_unselected():\n"
        "    raise AssertionError('An unselected test ran.')\n",
        encoding="utf-8",
    )
    targets = [
        "functional_tests/test_selected.py::test_selected[case with spaces]",
        "functional_tests/test_selected.py::test_selected[second]",
    ]
    monkeypatch.setattr(checker, "runtime_test_targets", lambda inventory: targets)
    monkeypatch.setenv("PYTHONPATH", str(ROOT / "functional_tests"))
    run_child = subprocess.run
    results = []

    def capture_child(command, **kwargs):
        result = run_child(command, capture_output=True, text=True, timeout=60, **kwargs)
        results.append(result)
        return result

    monkeypatch.setattr(checker.subprocess, "run", capture_child)
    result = checker.main()
    assert result == 0, results[0].stdout + results[0].stderr
    assert len(results) == 1 and "2 passed" in results[0].stdout
