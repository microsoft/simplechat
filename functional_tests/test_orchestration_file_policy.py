# test_orchestration_file_policy.py
"""
Scoped managed-file denial, delegation/thread propagation, and standalone defaults.
Version: 0.261.127
Implemented in: 0.261.127

Real application hooks run in fresh processes with only external I/O doubled.
The optimized probes use explicit checks; required operations never live in assert.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"
sys.path.insert(0, str(APP))

# Application imports follow the standalone test path setup.
from agent_execution_context import (
    AgentExecutionFrame, DelegationBudget, ExecutionIdentity, agent_execution, current_agent_execution,
)
from functions_orchestration_execution_policy import (
    OrchestrationFilePolicyError,
    current_orchestration_file_policy,
    orchestration_file_policy,
    require_generated_file_publication_allowed,
)


def publication_blocked():
    try:
        require_generated_file_publication_allowed()
    except OrchestrationFilePolicyError:
        return True
    return False


def test_absent_policy_and_explicit_render_preserve_legacy_permission():
    before = current_orchestration_file_policy()
    require_generated_file_publication_allowed()
    with orchestration_file_policy(allow_generated_files=True):
        require_generated_file_publication_allowed()
        rendering = current_orchestration_file_policy()
    after = current_orchestration_file_policy()
    assert before is after is None
    assert rendering is True


def test_nested_scope_cannot_escalate_and_exception_restores_outer_policy():
    with pytest.raises(RuntimeError, match="fixture"):
        with orchestration_file_policy(allow_generated_files=False):
            with orchestration_file_policy(allow_generated_files=True):
                blocked = publication_blocked()
            raise RuntimeError("fixture")
    restored = current_orchestration_file_policy()
    require_generated_file_publication_allowed()
    assert blocked is True
    assert restored is None


def test_legacy_empty_agent_frame_does_not_clear_the_owning_policy():
    with agent_execution(None):
        require_generated_file_publication_allowed()
    with orchestration_file_policy(allow_generated_files=False):
        with agent_execution(None):
            blocked = publication_blocked()
    require_generated_file_publication_allowed()
    assert blocked is True


@pytest.mark.parametrize("value", [None, 0, 1, "false", {}, []])
def test_policy_rejects_coercible_non_boolean_values(value):
    with pytest.raises(TypeError):
        with orchestration_file_policy(allow_generated_files=value):
            pytest.fail("Invalid policy was admitted.")


def test_async_tasks_and_asyncio_threads_keep_isolated_policies():
    async def check(allowed):
        with orchestration_file_policy(allow_generated_files=allowed):
            await asyncio.sleep(0)
            threaded = await asyncio.to_thread(publication_blocked)
            return publication_blocked(), threaded

    async def run():
        return await asyncio.gather(check(False), check(True))

    observed = asyncio.run(run())
    restored = current_orchestration_file_policy()
    assert observed == [(True, True), (False, False)]
    assert restored is None


def test_captured_agent_frame_and_delegated_child_rebind_policy_in_worker_threads():
    with orchestration_file_policy(allow_generated_files=False):
        root = AgentExecutionFrame(ExecutionIdentity("owner", "conversation"), {}, DelegationBudget())
        child = replace(root, depth=1, invocation_id="child")

    def invoke(frame):
        with agent_execution(frame):
            with orchestration_file_policy(allow_generated_files=True):
                return publication_blocked()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(invoke, frame) for frame in (root, child)]
        observed = [future.result() for future in futures]
    require_generated_file_publication_allowed()
    assert observed == [True, True]
    assert root.orchestration_allow_generated_files is False
    assert child.orchestration_allow_generated_files is False


@pytest.mark.parametrize("previous_permission", [None, True])
def test_reused_frame_carries_effective_denial_into_delegated_worker(previous_permission):
    root = AgentExecutionFrame(
        ExecutionIdentity("owner", "conversation"), {}, DelegationBudget(),
        orchestration_allow_generated_files=previous_permission,
    )
    with orchestration_file_policy(allow_generated_files=False):
        with agent_execution(root):
            active = current_agent_execution()
            child = replace(active, depth=1, invocation_id="child")

    def invoke():
        with agent_execution(child):
            return publication_blocked()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(invoke)
        blocked = future.result()
    require_generated_file_publication_allowed()
    assert root.orchestration_allow_generated_files is previous_permission
    assert active.budget is root.budget
    assert child.orchestration_allow_generated_files is False
    assert blocked is True


HOOK_PROBE = r'''
import importlib
from io import BytesIO
import sys
from unittest.mock import patch

sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports
from functions_orchestration_execution_policy import (
    MANAGED_FILE_FUNCTIONS, OrchestrationFilePolicyError,
    orchestration_file_policy, require_generated_file_publication_allowed,
)

def check(value, message):
    if not value:
        raise AssertionError(message)

with offline_app_imports() as environment:
    operations = importlib.import_module("functions_simplechat_operations")
    standalone = operations.get_simplechat_enabled_function_names()
    check(MANAGED_FILE_FUNCTIONS.issubset(standalone), "Standalone file operations changed")
    calls = [
        ("upload_markdown_document_for_current_user", ("data.md", "complete text"), {}),
        ("upload_generated_document_for_current_user", ("data.csv", "a\n1"), {}),
        ("upload_word_document_for_current_user", ("data.docx", "Title", "Complete text"), {}),
        ("upload_powerpoint_document_for_current_user", ("data.pptx", "Title", "Complete text"), {}),
        ("upload_generated_chat_artifact_for_current_user", ("conversation", "data.csv", "a\n1"), {}),
        ("upload_generated_analysis_artifact_for_current_user", ("conversation", "data.md", "text"), {}),
        ("upload_generated_analysis_artifact_for_user", ("owner", "conversation", "data.md", "text"), {}),
        ("upload_generated_analysis_artifact_stream_for_user",
         ("owner", "conversation", "data.csv", BytesIO(b"a\n1"), 3), {}),
        ("upload_generated_file_artifact_stream_for_user",
         ("owner", "conversation", "data.xlsx", BytesIO(b"file"), 4), {}),
        ("_upload_generated_document_for_current_user", ("owner", "data.csv", b"a\n1", "personal"), {}),
        ("_upload_generated_chat_artifact_for_current_user", ("owner", "conversation", "data.xlsx", b"file"), {}),
        ("_write_temp_generated_file", (b"file", ".xlsx"), {}),
        ("queue_generated_document_processing", ("document", "owner", "data.xlsx", b"file"), {}),
        ("_queue_document_upload_background_task", ("document", "owner", "not-created.xlsx", "data.xlsx"), {}),
        ("commit_generated_chat_artifact_publication_for_user",
         ("owner", "conversation", "artifact", "set", "member", 1), {}),
        ("upload_chat_image_bytes_for_user", ("owner", "conversation", "message", "image.png", b"image"), {}),
    ]
    io_calls = []
    with patch.object(operations, "create_document", side_effect=lambda **kwargs: io_calls.append(kwargs)):
        with orchestration_file_policy(allow_generated_files=False):
            offered = operations.get_simplechat_enabled_function_names()
            check(not MANAGED_FILE_FUNCTIONS.intersection(offered), "Managed generation was offered as a bypass")
            for name, args, kwargs in calls:
                try:
                    getattr(operations, name)(*args, **kwargs)
                except OrchestrationFilePolicyError:
                    continue
                raise AssertionError("Managed operation escaped its policy: " + name)
    check(not io_calls, "A denied file operation created a workspace document")
    require_generated_file_publication_allowed()
    restored = operations.get_simplechat_enabled_function_names()
    check(restored == standalone, "A scoped policy leaked into standalone/workflow callers")
    check(not environment.network_attempts, "Managed policy probe attempted external I/O")
print("PASS: all managed hooks denied before I/O and legacy defaults restored")
'''

PURE_PROBE = r'''
import importlib
import socket
import sys
from unittest.mock import patch

sys.path.insert(0, sys.argv[1])
with patch.object(socket.socket, "connect", side_effect=AssertionError("Unexpected network I/O")):
    for module in sys.argv[2:]:
        importlib.import_module(module)
    from functions_orchestration_execution_policy import (
        OrchestrationFilePolicyError, orchestration_file_policy,
        require_generated_file_publication_allowed,
    )
    with orchestration_file_policy(allow_generated_files=False):
        try:
            require_generated_file_publication_allowed()
        except OrchestrationFilePolicyError:
            pass
        else:
            raise AssertionError("A cold-imported policy admitted a file")
    require_generated_file_publication_allowed()
    forbidden = {"config", "functions_settings", "functions_appinsights", "functions_saved_analysis"}
    if forbidden.intersection(sys.modules):
        raise AssertionError("The pure policy imported an application owner")
print("PASS: policy/frame cold imports remain owner-free")
'''


def run_probe(source, arguments, optimized):
    command = [sys.executable, "-B"]
    if optimized:
        command.append("-O")
    process = subprocess.run(
        [*command, "-c", source, *arguments], capture_output=True, text=True, timeout=180, check=False,
    )
    assert process.returncode == 0, process.stdout[-8000:] + process.stderr[-8000:]
    assert "PASS:" in process.stdout


@pytest.mark.parametrize("optimized", [False, True])
def test_real_managed_hooks_and_standalone_defaults(optimized):
    run_probe(HOOK_PROBE, [str(APP), str(TESTS)], optimized)


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("order", [
    ("functions_orchestration_execution_policy", "agent_execution_context"),
    ("agent_execution_context", "functions_orchestration_execution_policy"),
])
def test_policy_is_safe_before_bootstrap_in_both_import_orders(order, optimized):
    run_probe(PURE_PROBE, [str(APP), *order], optimized)
