#!/usr/bin/env python3
# test_workflow_chat_delivery_loop.py
"""
Functional test for the workflow chat delivery background loop.
Version: 0.261.226
Implemented in: 0.261.226

This test ensures that the delivery loop binds the worker's services once with the distributed
lock helpers, processes hints on every wake, runs the cross-user sweep at most once per sweep
interval, recovers from failures without a busy loop and logs only the error type, and that
start_background_task_threads registers it with the Flask app. It also drives the real sweep
through the real lock helpers over a fake settings container.
"""

import ast
import logging
import os
import socket
import sys
import threading
import types
import uuid
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
for _path in (APP_ROOT, ROOT / "functional_tests"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest  # noqa: E402
from azure.core import MatchConditions  # noqa: E402

import functions_workflow_chat_delivery as delivery_contract  # noqa: E402
import functions_workflow_chat_delivery_worker as delivery_worker  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_support.workflow_chat_delivery_fakes import FakeContainer, make_world  # noqa: E402


BACKGROUND_TASKS = APP_ROOT / "background_tasks.py"
LOOP_NAME = "run_workflow_chat_delivery_loop"
LOG_MESSAGE = "[WORKFLOW_CHAT_DELIVERY] Delivery slice could not complete."
CANARY = "private-delivery-canary"
INTERVAL = delivery_contract.SWEEP_INTERVAL_SECONDS


class LoopStopped(Exception):
    """Raised by the fakes to end the endless loop after the scripted wakes."""


def _module_functions():
    parsed = ast.parse(BACKGROUND_TASKS.read_text(encoding="utf-8"))
    return {node.name: node for node in parsed.body if isinstance(node, ast.FunctionDef)}


def load_background_functions(names, namespace):
    functions = _module_functions()
    body = [functions[name] for name in names]
    code = compile(ast.Module(body=body, type_ignores=[]), "background_tasks.py", "exec")
    exec(code, namespace)
    return [namespace[name] for name in names]


class LoopHarness:
    """Fakes for one run of the loop: a scripted clock, the worker entry points and the wait."""

    def __init__(self, monkeypatch, *, wake_after=(), max_waits=3, factory_errors=(), hint_errors=(),
                 sweep_seconds=2.0):
        self.now = 100.0
        self.wake_after = list(wake_after)
        self.max_waits = max_waits
        self.factory_errors = list(factory_errors)
        self.hint_errors = list(hint_errors)
        self.sweep_seconds = sweep_seconds
        self.services = object()
        self.events = []
        self.waits = []
        self.sleeps = []
        self.logs = []
        self.factory_calls = []
        self.acquire_lock = lambda name, seconds: {"id": name}
        self.release_lock = lambda lock: None
        monkeypatch.setattr(delivery_worker, "default_workflow_chat_delivery_services", self.factory)
        monkeypatch.setattr(delivery_worker, "process_workflow_chat_delivery_hints", self.hints)
        monkeypatch.setattr(delivery_worker, "run_workflow_chat_delivery_sweep", self.sweep)
        monkeypatch.setattr(delivery_contract, "wait_for_workflow_chat_delivery_hint", self.wait)

    def factory(self, **kwargs):
        self.factory_calls.append(kwargs)
        if self.factory_errors:
            raise self.factory_errors.pop(0)
        return self.services

    def hints(self, services):
        self.events.append(("hints", services))
        if self.hint_errors:
            raise self.hint_errors.pop(0)
        return []

    def sweep(self, services):
        self.events.append(("sweep", services))
        self.now += self.sweep_seconds
        return {"locked": True, "processed": 0, "outcomes": {}}

    def _stop_if_done(self):
        if len(self.waits) + len(self.sleeps) >= self.max_waits:
            raise LoopStopped()

    def wait(self, timeout):
        self.waits.append(timeout)
        self._stop_if_done()
        # A scripted hint wakes the loop early; otherwise the wait runs to its timeout.
        self.now += self.wake_after.pop(0) if self.wake_after else timeout
        return True

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self._stop_if_done()
        self.now += seconds

    def namespace(self):
        return {
            "time": types.SimpleNamespace(monotonic=lambda: self.now, sleep=self.sleep),
            "nullcontext": nullcontext,
            "logging": logging,
            "log_event": lambda message, **kwargs: self.logs.append((message, kwargs)),
            "acquire_distributed_task_lock": self.acquire_lock,
            "release_distributed_task_lock": self.release_lock,
        }

    def run(self, app=None):
        (loop,) = load_background_functions([LOOP_NAME], self.namespace())
        with pytest.raises(LoopStopped):
            loop(app=app)


def test_version_is_at_least_the_delivery_release():
    assert_app_version_at_least("0.261.226")


def test_the_loop_binds_services_once_and_throttles_the_sweep(monkeypatch):
    harness = LoopHarness(monkeypatch, wake_after=[5], max_waits=3)

    harness.run()

    assert harness.factory_calls == [{
        "acquire_lock": harness.acquire_lock,
        "release_lock": harness.release_lock,
    }], "the services must be bound once, with the distributed lock helpers"
    services = harness.services
    assert harness.events == [
        ("hints", services), ("sweep", services),
        ("hints", services),
        ("hints", services), ("sweep", services),
    ], "every wake processes hints, but the sweep runs only once per interval"
    # t=100 sweeps (2 s) and waits for the rest of the interval; a hint wakes it at t=107; t=130
    # is the next sweep.
    assert harness.waits == [INTERVAL - 2.0, INTERVAL - 7.0, INTERVAL - 2.0]
    assert harness.sleeps == []
    assert harness.logs == []


def test_the_wait_never_drops_below_one_second(monkeypatch):
    harness = LoopHarness(monkeypatch, max_waits=2, sweep_seconds=INTERVAL + 5.0)

    harness.run()

    assert harness.waits[0] == 1.0, "a sweep that overruns the interval must not leave a zero-second wait"


def test_a_failure_sleeps_instead_of_spinning_and_logs_only_the_error_type(monkeypatch):
    harness = LoopHarness(
        monkeypatch,
        max_waits=3,
        factory_errors=[RuntimeError(CANARY)],
        hint_errors=[ValueError(CANARY)],
    )

    harness.run()

    services = harness.services
    assert len(harness.factory_calls) == 2, "a failed bind is retried, and a bound service is kept"
    assert harness.events == [("hints", services), ("hints", services), ("sweep", services)]
    assert harness.sleeps == [INTERVAL, INTERVAL], "a failure waits a full interval without the hint event"
    assert harness.logs == [
        (LOG_MESSAGE, {"level": logging.ERROR, "extra": {"error_type": "RuntimeError"}}),
        (LOG_MESSAGE, {"level": logging.ERROR, "extra": {"error_type": "ValueError"}}),
    ]
    assert CANARY not in repr(harness.logs), "exception text must never reach the log"


def test_each_slice_runs_inside_the_app_context(monkeypatch):
    harness = LoopHarness(monkeypatch, max_waits=1)

    class FakeApp:
        @contextmanager
        def app_context(self):
            harness.events.append(("enter", None))
            yield
            harness.events.append(("exit", None))

    harness.run(app=FakeApp())

    services = harness.services
    assert harness.events == [("enter", None), ("hints", services), ("sweep", services), ("exit", None)]


def test_start_background_task_threads_registers_the_delivery_loop_with_the_app():
    functions = _module_functions()
    starter = functions["start_background_task_threads"]
    loop_names = sorted({
        node.id for node in ast.walk(starter)
        if isinstance(node, ast.Name) and node.id.startswith("run_")
    })
    assert LOOP_NAME in loop_names
    loop_calls = []
    printed = []
    started = []

    def recorder(name):
        return lambda **kwargs: loop_calls.append((name, kwargs))

    class FakeThread:
        def __init__(self, target=None, daemon=None):
            self.target = target
            self.daemon = daemon

        def start(self):
            started.append(self)

    namespace = {name: recorder(name) for name in loop_names}
    namespace.update({"threading": types.SimpleNamespace(Thread=FakeThread), "print": printed.append})
    (start_threads,) = load_background_functions(["start_background_task_threads"], namespace)
    app = object()

    threads = start_threads(app=app)
    for thread in threads:
        thread.target()

    assert all(thread.daemon for thread in started)
    assert (LOOP_NAME, {"app": app}) in loop_calls, "the delivery loop must receive the Flask app"
    assert loop_calls.count((LOOP_NAME, {"app": app})) == 1
    assert "Workflow chat delivery background task started." in printed


def test_the_workflow_scheduler_loop_does_no_delivery_work():
    scheduler = _module_functions()["run_workflow_scheduler_loop"]
    names = {
        getattr(node, "id", None) or getattr(node, "attr", None)
        for node in ast.walk(scheduler)
        if isinstance(node, (ast.Name, ast.Attribute))
    }
    assert not any("chat_delivery" in str(name) for name in names), (
        "delivery must never run on the workflow scheduler's thread"
    )


def real_lock_helpers():
    settings = FakeContainer("settings")
    logs = []
    namespace = {
        "cosmos_settings_container": settings,
        "MatchConditions": MatchConditions,
        "datetime": datetime,
        "timedelta": timedelta,
        "timezone": timezone,
        "uuid": uuid,
        "socket": socket,
        "os": os,
        "threading": threading,
        "logging": logging,
        "log_event": lambda *args, **kwargs: logs.append((args, kwargs)),
    }
    acquire, release = load_background_functions(
        ["_get_lock_holder_id", "_is_expired_timestamp", "acquire_distributed_task_lock",
         "release_distributed_task_lock"],
        namespace,
    )[2:]
    return settings, acquire, release, logs


def test_the_real_lock_helpers_gate_the_real_sweep():
    settings, acquire, release, logs = real_lock_helpers()
    world = make_world()
    world.services = replace(world.services, acquire_lock=acquire, release_lock=release)
    world.clock.advance(minutes=3)
    lock_id = f"background_task_lock_{delivery_contract.SWEEP_LOCK_NAME}"
    held_until = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    settings.put({"id": lock_id, "holder_id": "another-worker", "expires_at": held_until})

    blocked = delivery_worker.run_workflow_chat_delivery_sweep(world.services)

    assert blocked == {"locked": False, "processed": 0, "outcomes": {}}
    assert world.runs.query_calls == [], "another worker's live lease must keep this sweep from querying"
    assert settings.get(lock_id)["holder_id"] == "another-worker"

    settings.items.clear()
    summary = delivery_worker.run_workflow_chat_delivery_sweep(world.services)

    assert summary["locked"] is True
    assert summary["processed"] == 1
    assert summary["outcomes"] == {delivery_worker.OUTCOME_DELIVERED: 1}
    assert len(world.delivery_messages()) == 1
    assert settings.get(lock_id) is None, "the sweep must release the lease it took"
    assert ("create_item", lock_id) in settings.calls
    assert logs == []


def test_the_worker_calls_the_lock_helpers_with_compatible_arguments():
    _settings, acquire, release, _logs = real_lock_helpers()
    calls = []

    def record_acquire(*args, **kwargs):
        calls.append(("acquire", args, kwargs))
        return acquire(*args, **kwargs)

    def record_release(*args, **kwargs):
        calls.append(("release", args, kwargs))
        return release(*args, **kwargs)

    world = make_world()
    world.services = replace(world.services, acquire_lock=record_acquire, release_lock=record_release)

    summary = delivery_worker.run_workflow_chat_delivery_sweep(world.services)

    assert summary["locked"] is True
    assert calls[0] == (
        "acquire", (delivery_contract.SWEEP_LOCK_NAME, delivery_contract.SWEEP_LOCK_SECONDS), {},
    )
    assert calls[1][0] == "release" and calls[1][1][0]["task_name"] == delivery_contract.SWEEP_LOCK_NAME


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
