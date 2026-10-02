#!/usr/bin/env python3
# test_workflow_chat_delivery_refusals.py
"""
Functional test for refusing Retry and Edit on messages a workflow run posted to chat.
Version: 0.261.218
Implemented in: 0.261.218

This test ensures, in a fresh offline process that boots the real application, that the
classic Retry and Edit routes refuse every message the workflow chat delivery posted (a
delivered result, a failed note, a cancelled note and the note sent when workflow results are
off) with one closed 400 code, before any content check or write, whether the message is
recognised by its ID prefix or by its delivery metadata. A delivered result also carries 6a's
lineage keys, so the test proves the delivery code wins over 6a's Follow up refusal. Another
user's Retry is still refused by ownership first, ordinary turns in the same chat still replay,
and the V2 orchestration retry and edit routes, which take a run ID, answer 404 for a delivery
message ID. Only storage, the model and the network are faked.
"""

import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(TESTS))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


SCENARIOS_FINISHED = "WORKFLOW_CHAT_DELIVERY_REFUSAL_SCENARIOS_FINISHED"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def test_version_is_at_least_the_chat_delivery_release():
    assert_app_version_at_least("0.261.218")


def run_offline_scenarios():
    from copy import deepcopy
    from datetime import datetime, timedelta, timezone
    from unittest.mock import patch

    from test_support.workflow_result_offline_app import offline_workflow_result_app

    with offline_workflow_result_app({"enable_chat_orchestration": True}) as world:
        # Application modules are imported only once the harness has isolated external I/O.
        import functions_workflow_chat_delivery as delivery
        import functions_workflow_result_reader as reader
        import route_backend_conversations as conversations
        from test_support.workflow_result_chat import OTHER_USER, RUN_ID, USER, WORKFLOW_ID

        config = world.config
        messages, chats = config.cosmos_messages_container, config.cosmos_conversations_container
        owner, stranger = world.signed_in(USER, "Owner"), world.signed_in(OTHER_USER, "Stranger")

        retry_refusal, retry_status = delivery.workflow_delivery_refusal_payload(delivery.DELIVERY_RETRY_UNSUPPORTED)
        edit_refusal, edit_status = delivery.workflow_delivery_refusal_payload(delivery.DELIVERY_EDIT_UNSUPPORTED)
        follow_up_refusal, _ = reader.workflow_result_error_payload(
            reader.WorkflowResultUnavailable("workflow_result_retry_unsupported")
        )
        require(
            retry_status == edit_status == 400
            and retry_refusal["code"] == "workflow_delivery_retry_unsupported"
            and edit_refusal["code"] == "workflow_delivery_edit_unsupported"
            and retry_refusal != follow_up_refusal,
            f"Unexpected refusal bodies: {retry_refusal} {edit_refusal}",
        )
        unknown = delivery.workflow_delivery_refusal_payload("anything_else")
        require(unknown == (retry_refusal, 400), f"An unknown code wasn't closed: {unknown}")

        checks, records = [], []
        real_check = conversations.check_chat_content

        def check(content, kind, **kwargs):
            checks.append(content)
            return real_check(content, kind, **kwargs)

        def record(*args, **kwargs):
            records.append(args)

        world.stack.enter_context(patch.object(conversations, "check_chat_content", check))
        world.stack.enter_context(patch.object(conversations, "record_blocked_chat_attempt", record))

        conversation_id = "conv-delivery-refusals"
        asked_at = datetime.now(timezone.utc) - timedelta(hours=3)
        chats.upsert_item({
            "id": conversation_id, "user_id": USER, "title": "Digest", "last_updated": asked_at.isoformat(),
            "context": [], "tags": [], "classification": [],
        })

        def seeded(message_id, role, content, at, thread_id, previous_thread_id=None, **metadata):
            row = {
                "id": message_id, "conversation_id": conversation_id, "role": role, "content": content,
                "timestamp": at.isoformat(), "model_deployment_name": "gpt-4o" if role == "assistant" else None,
                "metadata": {
                    "user_info": {"user_id": USER, "display_name": "Owner"},
                    "thread_info": {
                        "thread_id": thread_id, "previous_thread_id": previous_thread_id,
                        "active_thread": True, "thread_attempt": 1,
                    },
                    **metadata,
                },
            }
            messages.upsert_item(row)
            return deepcopy(row)

        # The turn that started the run: an ordinary question and the plan's answer.
        question = seeded("msg-ask-q", "user", "Run my weekly digest.", asked_at, "thread-ask")
        answer = seeded(
            "msg-ask-a", "assistant", "I started the run.", asked_at + timedelta(seconds=5), "thread-ask",
        )

        def posted(kind, generation, run_status, *, message_id=None, with_metadata=True, **extra):
            message_id = message_id or delivery.workflow_delivery_message_id(RUN_ID, conversation_id, generation)
            metadata = dict(extra)
            if with_metadata:
                metadata[delivery.DELIVERY_METADATA_KEY] = delivery.build_delivery_metadata(
                    kind=kind, workflow_id=WORKFLOW_ID, run_id=RUN_ID, generation=generation,
                    run_status=run_status, orchestration_run_id="orch-run-1", step_id="step-1",
                    requested_at=asked_at.isoformat(),
                )
            return seeded(
                message_id, "assistant", f"A {kind} message.", asked_at + timedelta(hours=1, minutes=generation),
                delivery.delivery_thread_id(message_id), "thread-ask", token_usage={}, **metadata,
            )

        delivered = {
            "result": posted(
                delivery.KIND_RESULT, 1, "completed",
                workflow_result={"version": 1, "available": True}, workflow_result_contexts=[world.context],
            ),
            "failed note": posted(delivery.KIND_FAILED, 2, "failed"),
            "cancelled note": posted(delivery.KIND_CANCELLED, 3, "cancelled"),
            "results-off note": posted(delivery.KIND_STATUS, 4, "completed"),
            "metadata only": posted(delivery.KIND_FAILED, 5, "failed", message_id="msg-delivery-by-metadata"),
            "prefix only": posted(delivery.KIND_STATUS, 6, "completed", with_metadata=False),
        }
        require(
            all(delivery.is_workflow_delivery_message(row) for row in delivered.values())
            and not delivery.is_workflow_delivery_message(question)
            and not delivery.is_workflow_delivery_message(answer),
            "The seeded messages aren't classified as expected.",
        )
        require(
            conversations.message_asks_about_workflow_result(delivered["result"]),
            "The delivered result doesn't carry 6a's lineage, so the precedence check proves nothing.",
        )

        def stored():
            return deepcopy(messages.items), deepcopy(chats.items)

        def replay(client, kind, message, **body):
            return client.post(f"/api/message/{message['id']}/{kind}", json=body)

        for label, message in delivered.items():
            for kind, body, refusal in (
                ("retry", {}, retry_refusal),
                ("edit", {"content": "Say it differently."}, edit_refusal),
            ):
                before = stored()
                checks.clear()
                records.clear()
                refused = replay(owner, kind, message, **body)
                outcome = (refused.status_code, refused.get_json(silent=True))
                require(
                    outcome == (400, refusal),
                    f"{kind} of the {label} must be refused with 400 {refusal['code']}: got "
                    f"{refused.status_code} {refused.get_data(as_text=True)[:300]}",
                )
                require(not checks and not records, f"{kind} of the {label} was checked: {checks} {records}")
                require(stored() == before, f"{kind} of the {label} wrote to storage.")

        # Another user's Retry is refused by ownership before the message is inspected. Edit refuses
        # before ownership, as its role check already does for any assistant message, so a stranger
        # learns nothing a message ID with this prefix doesn't already say.
        before = stored()
        foreign_retry = replay(stranger, "retry", delivered["result"])
        require(
            foreign_retry.status_code == 403,
            f"A stranger's retry: {foreign_retry.status_code} {foreign_retry.get_data(as_text=True)[:300]}",
        )
        foreign_edit = replay(stranger, "edit", delivered["failed note"], content="Mine now.")
        require(
            (foreign_edit.status_code, foreign_edit.get_json(silent=True)) == (400, edit_refusal),
            f"A stranger's edit: {foreign_edit.status_code} {foreign_edit.get_data(as_text=True)[:300]}",
        )
        require(stored() == before and not checks, "A stranger's request wrote to storage or was checked.")

        # The V2 orchestration retry and edit take an orchestration run ID, so a delivery message ID
        # names no run.
        delivery_id = delivered["result"]["id"]
        v2_retry = owner.post(f"/api/v2/orchestration/runs/{delivery_id}/retry", json={
            "conversation_id": conversation_id, "submission_id": "submission-1", "expected_version": "version-1",
        })
        require(
            v2_retry.status_code == 404,
            f"V2 retry with a delivery ID: {v2_retry.status_code} {v2_retry.get_data(as_text=True)[:300]}",
        )
        v2_edit = owner.post(f"/api/v2/orchestration/runs/{delivery_id}/edit", json={
            "conversation_id": conversation_id,
        })
        require(
            v2_edit.status_code == 404,
            f"V2 edit with a delivery ID: {v2_edit.status_code} {v2_edit.get_data(as_text=True)[:300]}",
        )
        require(stored() == before, "A V2 retry or edit with a delivery ID wrote to storage.")

        # Ordinary turns in the same chat still replay, and each replays its own question.
        checks.clear()
        retried = replay(owner, "retry", answer)
        require(
            retried.status_code == 200 and retried.get_json().get("success") is True,
            f"An ordinary retry failed: {retried.status_code} {retried.get_data(as_text=True)[:300]}",
        )
        edited = replay(owner, "edit", question, content="Run my monthly digest.")
        require(
            edited.status_code == 200 and edited.get_json().get("success") is True,
            f"An ordinary edit failed: {edited.status_code} {edited.get_data(as_text=True)[:300]}",
        )
        require(checks == [question["content"], "Run my monthly digest."], f"Unexpected checks: {checks}")

        require(not world.normal_chat_clients, "The normal chat model was used.")
        require(not world.network_attempts, f"The routes attempted network access: {world.network_attempts}")
        print(SCENARIOS_FINISHED)


def child_failure(result):
    """The offline child's own failure line, so a failure leads with the broken rule, not the log tail."""
    lines = (result.stderr or "").splitlines()
    starts = [index for index, line in enumerate(lines) if line.startswith("Traceback (most recent call last):")]
    if starts:
        for line in lines[starts[-1] + 1:]:
            if line.strip() and not line.startswith((" ", "\t")):
                return line.removeprefix("AssertionError: ")
    return f"the offline scenarios exited with code {result.returncode} before finishing"


def test_retry_and_edit_refuse_every_message_a_workflow_run_posted():
    result = subprocess.run(
        [sys.executable, *(["-O"] if sys.flags.optimize else []), str(Path(__file__).resolve()), "--offline"],
        # app.py switches the child's output to UTF-8, which the parent's locale codec can't always decode.
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=240,
    )
    output = result.stdout[-3000:] + result.stderr[-6000:]

    require(result.returncode == 0, f"{child_failure(result)}\n\n{output}")
    require(SCENARIOS_FINISHED in result.stdout.splitlines(), f"the offline scenarios did not finish\n\n{output}")


if __name__ == "__main__":
    if "--offline" in sys.argv:
        run_offline_scenarios()
    else:
        raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
