#!/usr/bin/env python3
# test_workflow_chat_delivery_concurrency.py
"""
Functional test for workflow chat delivery concurrency.
Version: 0.261.227
Implemented in: 0.261.227

This test ensures concurrent chat delivery workers publish each workflow result exactly once.
"""

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / "application" / "single_app", ROOT / "functional_tests"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest  # noqa: E402

import functions_workflow_chat_delivery_worker as worker  # noqa: E402
from functions_workflow_chat_delivery import (  # noqa: E402
    LEASE_SECONDS,
    RECENT_USER_MESSAGE_SECONDS,
    clear_workflow_chat_delivery_hints,
    workflow_delivery_message_id,
)
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_support.workflow_chat_delivery_fakes import (  # noqa: E402
    CONVERSATION_ID,
    RUN_ID,
    USER,
    make_world,
    require,
)


M5 = workflow_delivery_message_id(RUN_ID, CONVERSATION_ID, 5)
THREAD_TIMEOUT_SECONDS = 8.0
RENDEZVOUS_TIMEOUT_SECONDS = 5.0


@pytest.fixture(autouse=True)
def clear_delivery_hints():
    clear_workflow_chat_delivery_hints()
    yield
    clear_workflow_chat_delivery_hints()


def deliver(world):
    return worker.process_workflow_chat_delivery(USER, RUN_ID, services=world.services)


def _synchronize_container_writes(monkeypatch, *containers):
    for container in containers:
        write_lock = threading.Lock()
        for method_name in ("replace_item", "create_item", "upsert_item", "delete_item"):
            original = getattr(container, method_name)

            def synchronized(*args, _original=original, _lock=write_lock, **kwargs):
                with _lock:
                    return _original(*args, **kwargs)

            monkeypatch.setattr(container, method_name, synchronized)


def _barrier_first_run_reads(monkeypatch, world):
    barrier = threading.Barrier(2, timeout=RENDEZVOUS_TIMEOUT_SECONDS)
    original = world.runs.read_item
    seen_threads = set()
    seen_lock = threading.Lock()

    def read_item(*args, **kwargs):
        thread_id = threading.get_ident()
        with seen_lock:
            first_for_thread = thread_id not in seen_threads
            if first_for_thread:
                seen_threads.add(thread_id)
        item = original(*args, **kwargs)
        if first_for_thread:
            barrier.wait()
        return item

    monkeypatch.setattr(world.runs, "read_item", read_item)


def _patch_compose_rendezvous(monkeypatch, world):
    condition = threading.Condition()
    arrivals = {"count": 0}

    def arrive():
        with condition:
            arrivals["count"] += 1
            condition.notify_all()
            deadline = time.monotonic() + RENDEZVOUS_TIMEOUT_SECONDS
            while arrivals["count"] < 2:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AssertionError("timed out waiting for the other delivery worker")
                condition.wait(remaining)

    def returned():
        with condition:
            arrivals["count"] += 1
            condition.notify_all()

    for model in (world.models.selected, world.models.default):
        original = model.create_completion

        def create_completion(*args, _original=original, **kwargs):
            arrive()
            return _original(*args, **kwargs)

        monkeypatch.setattr(model, "create_completion", create_completion)

    return returned


def _run_threads(actions, *, on_return=None):
    results = {}
    errors = {}

    def target(name, action):
        try:
            results[name] = action()
        except Exception as exc:
            errors[name] = exc
        finally:
            if on_return is not None:
                on_return()

    threads = [
        threading.Thread(target=target, args=(name, action), daemon=True)
        for name, action in actions.items()
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(THREAD_TIMEOUT_SECONDS)

    unfinished = [thread.name for thread in threads if thread.is_alive()]
    require(not unfinished, f"delivery threads did not finish: {unfinished}")
    if errors:
        name, error = next(iter(errors.items()))
        raise AssertionError(f"delivery thread {name} failed") from error
    silent = [name for name in actions if name not in results]
    require(not silent, f"delivery threads ended without a result: {silent}")
    return results


def _require_one_delivery_side_effect(world):
    messages = world.delivery_messages()
    message_ids = [message["id"] for message in messages]
    require(message_ids == [M5], f"expected exactly one delivery message, got {message_ids}")
    chat_notice_count = len(world.notifications.chat_calls)
    require(chat_notice_count == 1, f"expected one chat notice, got {chat_notice_count}")
    unread_count = len(world.unread_calls)
    require(unread_count == 1, f"expected one unread mark, got {unread_count}")
    model_request_count = len(world.models.requests)
    require(model_request_count == 1, f"expected one model request, got {model_request_count}")


def test_version_is_at_least_the_chat_delivery_release():
    assert_app_version_at_least("0.261.227")


def test_claim_race_allows_one_worker_to_deliver_and_the_other_to_stay_busy(monkeypatch):
    world = make_world()
    _synchronize_container_writes(monkeypatch, world.runs, world.messages, world.conversations)
    _barrier_first_run_reads(monkeypatch, world)
    mark_worker_returned = _patch_compose_rendezvous(monkeypatch, world)

    results = _run_threads(
        {
            "worker-a": lambda: deliver(world),
            "worker-b": lambda: deliver(world),
        },
        on_return=mark_worker_returned,
    )

    outcomes = set(results.values())
    expected_outcomes = {worker.OUTCOME_DELIVERED, worker.OUTCOME_BUSY}
    require(
        outcomes == expected_outcomes,
        "two workers racing for one claim: exactly one delivers and the other stays busy; "
        f"got {dict(sorted(results.items()))}",
    )
    _require_one_delivery_side_effect(world)
    record = world.record()
    status = record.get("status")
    attempts = record.get("attempts")
    require(status == "delivered", f"expected delivered record, got {status}")
    require(attempts == 1, f"expected one attempt, got {attempts}")


def test_hint_and_sweep_race_delivers_once(monkeypatch):
    world = make_world()
    world.clock.advance(minutes=3)
    world.hints.signal(USER, RUN_ID)
    _synchronize_container_writes(monkeypatch, world.runs, world.messages, world.conversations)
    _barrier_first_run_reads(monkeypatch, world)

    results = _run_threads({
        "hint": lambda: worker.process_workflow_chat_delivery_hints(world.services),
        "sweep": lambda: worker.run_workflow_chat_delivery_sweep(world.services),
    })

    hint_outcomes = results["hint"]
    sweep_summary = results["sweep"]
    require(len(hint_outcomes) == 1, f"expected one hint outcome, got {hint_outcomes}")
    require(sweep_summary["locked"] is True, f"expected locked sweep, got {sweep_summary}")
    require(sweep_summary["processed"] == 1, f"expected one sweep row, got {sweep_summary}")
    _require_one_delivery_side_effect(world)
    record = world.record()
    status = record.get("status")
    attempts = record.get("attempts")
    require(status == "delivered", f"expected delivered record, got {status}")
    require(attempts == 1, f"expected one attempt, got {attempts}")


def test_stale_worker_loses_lease_after_reclaimed_delivery(monkeypatch):
    world = make_world()
    _synchronize_container_writes(monkeypatch, world.runs, world.messages, world.conversations)
    original = world.models.selected.create_completion
    reentered = {"done": False}
    reclaimed_outcomes = []

    def create_completion(*args, **kwargs):
        if not reentered["done"]:
            reentered["done"] = True
            seconds = max(LEASE_SECONDS, RECENT_USER_MESSAGE_SECONDS) + 1
            world.clock.advance(seconds=seconds)
            reclaimed_outcomes.append(deliver(world))
        return original(*args, **kwargs)

    monkeypatch.setattr(world.models.selected, "create_completion", create_completion)

    stale_outcome = deliver(world)

    require(reclaimed_outcomes == [worker.OUTCOME_DELIVERED], f"unexpected reclaimed outcomes: {reclaimed_outcomes}")
    require(stale_outcome == worker.OUTCOME_LOST_LEASE, f"expected lost lease, got {stale_outcome}")
    messages = world.delivery_messages()
    message_ids = [message["id"] for message in messages]
    require(message_ids == [M5], f"expected one delivery message, got {message_ids}")
    chat_notice_count = len(world.notifications.chat_calls)
    require(chat_notice_count == 1, f"expected one chat notice, got {chat_notice_count}")
    unread_count = len(world.unread_calls)
    require(unread_count == 1, f"expected one unread mark, got {unread_count}")
    record = world.record()
    status = record.get("status")
    lease_id = record.get("lease_id")
    lease_expires_at = record.get("lease_expires_at")
    attempts = record.get("attempts")
    require(status == "delivered", f"expected delivered record, got {status}")
    require(lease_id is None, f"expected cleared lease id, got {lease_id}")
    require(lease_expires_at is None, f"expected cleared lease expiry, got {lease_expires_at}")
    require(attempts == 2, f"expected two attempts, got {attempts}")


def test_two_sequential_sweeps_after_delivery_do_not_repeat_side_effects():
    world = make_world()
    world.clock.advance(minutes=3)

    first_summary = worker.run_workflow_chat_delivery_sweep(world.services)
    first_messages = world.delivery_messages()
    first_message_count = len(first_messages)
    first_notice_count = len(world.notifications.chat_calls)
    first_unread_count = len(world.unread_calls)
    first_model_count = len(world.models.requests)

    second_summary = worker.run_workflow_chat_delivery_sweep(world.services)
    second_messages = world.delivery_messages()
    second_message_count = len(second_messages)
    second_notice_count = len(world.notifications.chat_calls)
    second_unread_count = len(world.unread_calls)
    second_model_count = len(world.models.requests)

    require(first_summary["outcomes"] == {worker.OUTCOME_DELIVERED: 1}, f"unexpected first sweep: {first_summary}")
    require(second_summary["processed"] == 0, f"unexpected second sweep: {second_summary}")
    require(first_message_count == 1, f"expected first sweep to create one message, got {first_message_count}")
    require(second_message_count == first_message_count, "second sweep created another delivery message")
    require(second_notice_count == first_notice_count, "second sweep sent another chat notice")
    require(second_unread_count == first_unread_count, "second sweep marked unread again")
    require(second_model_count == first_model_count, "second sweep made another model request")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
