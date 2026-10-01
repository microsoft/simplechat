# test_workflow_result_review_paths.py
"""
Functional test for the workflow-result paths outside the chat history read.
Version: 0.261.213
Implemented in: 0.261.213

This test ensures, in a fresh offline process that boots the real application,
that a workflow result's answer never leaves the owner's private chat through a
copy, an export, a replay or the search cache. Converting the chat to a
collaboration stores its Follow up answers (and later answers that inherited
their context) withheld, keeps each question's text without its link to the run
and drops the chat summary on both chats, so the copies, the conversation
preview, a pending invitee's message metadata and history, the summary input,
MCP reads, mirrored messages and the summary sync only ever see the withheld
form. The Word, PowerPoint and email exports of a single message refuse an answer
whose run is gone or whose chat was converted. Retrying or editing a Follow up
turn is refused before any content check or write, while an ordinary turn still
replays. A search whose matches use a workflow result is never written to the
search cache. Only storage, the model and the network are faked.
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


SCENARIOS_FINISHED = "WORKFLOW_RESULT_REVIEW_PATH_SCENARIOS_FINISHED"
EXPORT_KINDS = ("word", "powerpoint", "email-draft")


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def test_version_is_at_least_the_workflow_results_release():
    assert_app_version_at_least("0.261.213")


def run_offline_scenarios():
    from contextlib import ExitStack
    from copy import deepcopy
    from datetime import datetime, timedelta
    import json
    from types import SimpleNamespace
    from unittest.mock import patch

    from test_support.workflow_result_offline_app import offline_workflow_result_app

    with offline_workflow_result_app({"enable_collaborative_conversations": True}) as world:
        # Application modules are imported only once the harness has isolated external I/O.
        import functions_collaboration as collaboration
        import functions_mcp_server_tools as mcp_tools
        import functions_workflow_result_masking as masking
        import route_backend_conversation_export as export
        import route_backend_conversations as conversations
        from collaboration_models import _truncate_preview
        from test_support.workflow_result_chat import OTHER_USER, RUN_ID, USER, WORKFLOW_ID

        config, fixture, context, reader = world.config, world.fixture, world.context, world.reader
        messages, chats = config.cosmos_messages_container, config.cosmos_conversations_container
        shared_chats = config.cosmos_collaboration_conversations_container
        shared_messages = config.cosmos_collaboration_messages_container
        owner, stranger = world.signed_in(USER, "Owner"), world.signed_in(OTHER_USER, "Stranger")
        owner_user = {"user_id": USER, "display_name": "Owner", "email": "owner@example.test"}
        unavailable = masking.WORKFLOW_RESULT_UNAVAILABLE_MESSAGE
        withheld_descriptor = {"version": masking.WORKFLOW_RESULT_VERSION, "available": False}
        # Identifiers of the run and its result; no participant-facing document may carry them.
        secrets = ("markets rose", WORKFLOW_ID, RUN_ID, context["result_sha256"])
        # Message text also may not quote the result or the disclosure that names the workflow.
        answer_text = (*secrets, "headlines.", "Weekly digest")
        refusal, refusal_status = reader.workflow_result_error_payload(
            reader.WorkflowResultUnavailable("workflow_result_retry_unsupported")
        )

        checks, records, blocking, summary_inputs = [], [], [], []
        real_check = conversations.check_chat_content

        def check(content, kind, **kwargs):
            checks.append(content)
            if blocking:
                return SimpleNamespace(blocked=True, notice="Blocked for the test.", status="blocked", metadata={})
            return real_check(content, kind, **kwargs)

        def record(*args, **kwargs):
            records.append(args)

        def summarize(*args, **kwargs):
            summary_inputs.append(deepcopy(kwargs.get("messages")))
            return {"content": "A summary of the shared chat.", "model_deployment": "gpt-4o"}

        def no_export_model(*args, **kwargs):
            raise RuntimeError("The export model is offline in this test.")

        world.stack.enter_context(patch.object(conversations, "check_chat_content", check))
        world.stack.enter_context(patch.object(conversations, "record_blocked_chat_attempt", record))
        world.stack.enter_context(patch.object(export, "_initialize_gpt_client", no_export_model))
        world.stack.enter_context(patch.object(export, "generate_conversation_summary", summarize))

        def leaked(text, needles=secrets):
            return [needle for needle in needles if needle in text]

        def messages_of(conversation_id):
            return sorted(
                (deepcopy(row) for row in messages.items.values() if row.get("conversation_id") == conversation_id),
                key=lambda row: row["timestamp"],
            )

        def copies_in(conversation_id):
            return {
                row["metadata"]["source_message_id"]: deepcopy(row) for row in shared_messages.items.values()
                if row.get("conversation_id") == conversation_id
            }

        def seeded(conversation_id, message_id, role, content, at, thread_id, **metadata):
            row = {
                "id": message_id, "conversation_id": conversation_id, "role": role, "content": content,
                "timestamp": at.isoformat(), "model_deployment_name": "gpt-4o" if role == "assistant" else None,
                "metadata": {
                    "user_info": {"user_id": USER, "display_name": "Owner"},
                    "thread_info": {
                        "thread_id": thread_id, "previous_thread_id": None, "active_thread": True,
                        "thread_attempt": 1,
                    },
                    **metadata,
                },
            }
            messages.upsert_item(row)
            return deepcopy(row)

        # A real Follow up writes the question and its answer in a new private chat.
        response = owner.post("/api/chat", json={
            "message": "What did the digest find?", "workflow_result_context": context,
            "time_zone": "America/New_York",
        })
        require(
            response.status_code == 200,
            f"The Follow up failed: {response.status_code} {response.get_data(as_text=True)[:300]}",
        )
        conversation_id = response.get_json()["conversation_id"]
        followed = messages_of(conversation_id)
        require([row["role"] for row in followed] == ["user", "assistant"], f"Unexpected Follow up turn: {followed}")
        q1, a1 = followed
        require(
            "markets rose" in a1["content"] and a1["metadata"].get("workflow_result_contexts") == [context]
            and q1["metadata"].get("workflow_result_context") == context,
            f"The Follow up didn't record its lineage: {followed}",
        )

        # Around it: an ordinary turn before, a Follow up question whose answer kept no lineage, and an
        # ordinary question whose answer inherited the result's context last.
        asked_at, answered_at = datetime.fromisoformat(q1["timestamp"]), datetime.fromisoformat(a1["timestamp"])
        later = lambda seconds: answered_at + timedelta(seconds=seconds)  # noqa: E731
        q2 = seeded(conversation_id, "msg-sunny-q", "user", "Is it sunny today?", asked_at - timedelta(seconds=20),
                    "thread-sunny")
        a2 = seeded(conversation_id, "msg-sunny-a", "assistant", "Sunny.", asked_at - timedelta(seconds=19),
                    "thread-sunny")
        qk = seeded(conversation_id, "msg-bonds-q", "user", "And what about bonds?", later(5), "thread-bonds",
                    workflow_result_context=context)
        ak = seeded(conversation_id, "msg-bonds-a", "assistant", "The stored result doesn't mention bonds.",
                    later(6), "thread-bonds")
        q3 = seeded(conversation_id, "msg-recap-q", "user", "Recap that for me.", later(7), "thread-recap")
        a3 = seeded(conversation_id, "msg-recap-a", "assistant", "Recap: markets rose.", later(8), "thread-recap",
                    workflow_result_contexts=[context])
        originals = (q2, a2, q1, a1, qk, ak, q3, a3)
        withheld_ids = {a1["id"], a3["id"]}
        source = chats.read_item(item=conversation_id, partition_key=conversation_id)
        source["summary"] = {
            "content": "The chat covered the digest: markets rose.", "model_deployment": "gpt-4o",
            "generated_at": later(9).isoformat(),
        }
        chats.upsert_item(source)

        plain_id = "conv-plain-1"
        chats.upsert_item({
            "id": plain_id, "user_id": USER, "title": "Picnic", "last_updated": later(2).isoformat(),
            "context": [], "tags": [], "classification": [],
        })
        qp = seeded(plain_id, "msg-picnic-q", "user", "Plan a picnic.", later(1), "thread-picnic")
        ap = seeded(plain_id, "msg-picnic-a", "assistant", "Bring sandwiches.", later(2), "thread-picnic")

        # R10: a search whose matches use a workflow result is never cached; an ordinary one is.
        cache_reads, cache_writes = [], []
        cache_patches = {
            "get_conversation_cache_settings": lambda *args, **kwargs: {"enabled": True, "ttl_seconds": 60},
            "_build_conversation_cache_access_parameters": lambda *args, **kwargs: {},
            "build_conversation_cache_key": lambda user_id, kind, parameters=None, **kwargs: (
                f"{kind}:{json.dumps(parameters, sort_keys=True, default=str)}"
            ),
            "get_cached_conversation_payload": lambda key, *args, **kwargs: cache_reads.append(key),
            "set_cached_conversation_payload": lambda key, payload, *args, **kwargs: cache_writes.append(key),
        }

        def search(term):
            cache_reads.clear()
            cache_writes.clear()
            with ExitStack() as scoped:
                for name, replacement in cache_patches.items():
                    scoped.enter_context(patch.object(conversations, name, replacement))
                found = owner.post("/api/search_conversations", json={"search_term": term})
            require(
                found.status_code == 200,
                f"Search failed: {found.status_code} {found.get_data(as_text=True)[:300]}",
            )
            return {
                item["conversation"]["id"]: len(item["messages"]) for item in found.get_json()["results"]
                if item["messages"]
            }

        hits = search("markets rose")
        require(hits == {conversation_id: 2}, f"Search didn't find the readable answers: {hits}")
        # The cache is read before matching, so only the write can depend on what matched.
        require(len(cache_reads) == 1, f"The search cache wasn't consulted: {cache_reads}")
        require(not cache_writes, f"A search over workflow-result answers was cached: {cache_writes}")
        hits = search("Sunny")
        require(hits == {conversation_id: 2}, f"Search didn't find the ordinary turn: {hits}")
        require(len(cache_writes) == 1, f"An ordinary search wasn't cached: {cache_writes}")

        # B3: retrying or editing a Follow up turn is refused before any content check or write.
        def stored():
            return deepcopy(messages.items), deepcopy(chats.items)

        def replay(kind, message, **body):
            return owner.post(f"/api/message/{message['id']}/{kind}", json=body)

        for kind, message, body in (
            ("retry", a1, {}), ("retry", q1, {}), ("retry", ak, {}),
            ("edit", q1, {"content": "What else did it find?"}), ("edit", qk, {"content": "And stocks?"}),
        ):
            before = stored()
            checks.clear()
            records.clear()
            refused = replay(kind, message, **body)
            require(
                refused.status_code == refusal_status == 400 and refused.get_json() == refusal,
                f"{kind} of {message['id']}: {refused.status_code} {refused.get_data(as_text=True)[:300]}",
            )
            require(not checks and not records, f"{kind} of {message['id']} was checked: {checks} {records}")
            require(stored() == before, f"{kind} of {message['id']} wrote to storage.")

        # An answer that only inherited the context replays an ordinary question, which is checked as usual.
        before = stored()
        checks.clear()
        records.clear()
        blocking.append(True)
        blocked = replay("retry", a3)
        blocking.clear()
        require(
            blocked.status_code == 422 and blocked.get_json().get("blocked") is True,
            f"The inherited answer's retry wasn't checked: {blocked.status_code} {blocked.get_data(as_text=True)[:300]}",
        )
        require(checks == [q3["content"]] and len(records) == 1, f"Unexpected checks: {checks} {records}")
        require(stored() == before, "A blocked retry wrote to storage.")

        checks.clear()
        retried = replay("retry", ap)
        require(
            retried.status_code == 200 and retried.get_json().get("success") is True,
            f"An ordinary retry failed: {retried.status_code} {retried.get_data(as_text=True)[:300]}",
        )
        edited = replay("edit", qp, content="Plan a beach day.")
        require(
            edited.status_code == 200 and edited.get_json().get("success") is True,
            f"An ordinary edit failed: {edited.status_code} {edited.get_data(as_text=True)[:300]}",
        )
        require(checks == [qp["content"], "Plan a beach day."], f"Unexpected checks: {checks}")

        # B2: a single-message export re-checks the answer's workflow result and its chat.
        def exported(message):
            return {
                kind: owner.post(
                    f"/api/message/export-{kind}",
                    json={"message_id": message["id"], "conversation_id": conversation_id},
                ) for kind in EXPORT_KINDS
            }

        def require_exports(message, status, why):
            responses = exported(message)
            # Word and PowerPoint bodies are binary documents, so only their leading bytes are reported.
            require(
                all(found.status_code == status for found in responses.values()),
                f"{why}: " + "; ".join(
                    f"{kind} {found.status_code} {found.get_data()[:200]!r}" for kind, found in responses.items()
                ),
            )
            if status == 403:
                for kind, found in responses.items():
                    require(not leaked(found.get_data(as_text=True), answer_text), f"{why}: {kind} leaked.")

        require_exports(a1, 200, "A readable answer")
        runs = deepcopy(fixture.containers["runs"].documents)
        fixture.containers["runs"].documents.clear()
        require_exports(a1, 403, "After the run was deleted, the Follow up answer")
        require_exports(a3, 403, "After the run was deleted, the inherited answer")
        require_exports(a2, 200, "After the run was deleted, an ordinary answer")
        fixture.containers["runs"].documents.extend(runs)
        require_exports(a1, 200, "After the run was restored")

        # B1: converting the chat stores the copies withheld and drops the summary on both chats.
        converted = owner.post(
            f"/api/collaboration/conversations/from-personal/{conversation_id}/members",
            json={"participants": [
                {"user_id": OTHER_USER, "display_name": "Stranger", "email": "stranger@example.test"},
            ]},
        )
        require(
            converted.status_code == 201,
            f"Conversion failed: {converted.status_code} {converted.get_data(as_text=True)[:300]}",
        )
        collaboration_id = converted.get_json()["conversation"]["id"]
        require(not leaked(converted.get_data(as_text=True), answer_text), "The conversion response leaked.")

        def require_copies(found, why):
            require(
                set(found) == {message["id"] for message in originals},
                f"{why}: unexpected copies {sorted(found)}",
            )
            for message in originals:
                copied = found[message["id"]]
                if message["id"] in withheld_ids:
                    require(
                        copied["content"] == unavailable
                        and copied["metadata"].get("workflow_result") == withheld_descriptor
                        and copied["metadata"].get("last_message_preview") == _truncate_preview(unavailable)
                        and not {"workflow_result_context", "workflow_result_contexts"} & set(copied["metadata"]),
                        f"{why}: an answer wasn't withheld: {copied}",
                    )
                else:
                    require(
                        copied["content"] == message["content"]
                        and not set(masking.WORKFLOW_RESULT_MESSAGE_KEYS) & set(copied["metadata"]),
                        f"{why}: a message lost its text or kept its link to the run: {copied}",
                    )
            text = json.dumps(found, default=str)
            require(not leaked(text, answer_text), f"{why}: the copies leaked {leaked(text, answer_text)}.")

        copies = copies_in(collaboration_id)
        require_copies(copies, "Conversion")
        shared = deepcopy(shared_chats.items[collaboration_id])
        require(
            shared.get("last_message_preview") == _truncate_preview(unavailable),
            f"The shared chat's preview wasn't withheld: {shared.get('last_message_preview')!r}",
        )
        require(not leaked(json.dumps(shared, default=str)), f"The shared chat leaked: {shared}")

        def summaries():
            return chats.items[conversation_id], shared_chats.items[collaboration_id]

        hidden_source, shared = summaries()
        require(
            "summary" in shared and shared["summary"] is None
            and "summary" in hidden_source and hidden_source["summary"] is None
            and hidden_source.get("converted_to_collaboration_at"),
            f"A summary survived conversion: {hidden_source.get('summary')} / {shared.get('summary')}",
        )
        require(
            [row["content"] for row in messages_of(conversation_id)] == [message["content"] for message in originals],
            "Conversion changed the original chat's stored messages.",
        )

        # Neither the AI bridge's source check nor its metadata sync brings a summary back, even one the
        # owner regenerated on the hidden source chat.
        shared = deepcopy(shared_chats.items[collaboration_id])
        for regenerated in (None, {"content": "Regenerated: markets rose.", "model_deployment": "gpt-4o"}):
            if regenerated is not None:
                hidden = deepcopy(chats.items[conversation_id])
                hidden["summary"] = regenerated
                chats.upsert_item(hidden)
            source_doc, shared = collaboration.ensure_collaboration_source_conversation(shared, owner_user)
            require(source_doc.get("id") == conversation_id, f"Unexpected source chat: {source_doc.get('id')}")
            shared, _synced = collaboration.sync_collaboration_conversation_metadata_from_source(shared, source_doc)
            hidden_source, stored_shared = summaries()
            require(
                stored_shared.get("summary") is None and shared.get("summary") is None
                and hidden_source.get("summary") is None,
                f"Syncing restored a summary ({regenerated}): {hidden_source.get('summary')} / "
                f"{stored_shared.get('summary')}",
            )

        # A pending invitee's metadata and history reads, MCP and the summary input see only the withheld form.
        a1_copy_id = copies[a1["id"]]["id"]
        metadata_read = stranger.get(f"/api/message/{a1_copy_id}/metadata")
        require(
            metadata_read.status_code == 200,
            f"The invitee's metadata read failed: {metadata_read.status_code} {metadata_read.get_data(as_text=True)[:300]}",
        )
        require(
            not leaked(metadata_read.get_data(as_text=True)),
            f"The metadata read leaked {leaked(metadata_read.get_data(as_text=True))}.",
        )

        history = stranger.get(f"/api/collaboration/conversations/{collaboration_id}/messages")
        require(
            history.status_code == 200,
            f"The invitee's history read failed: {history.status_code} {history.get_data(as_text=True)[:300]}",
        )
        shown = {item["id"]: item for item in history.get_json()["messages"]}
        require(
            shown.get(a1_copy_id, {}).get("content") == unavailable
            and not leaked(history.get_data(as_text=True), answer_text),
            f"The invitee's history leaked: {leaked(history.get_data(as_text=True), answer_text)}",
        )

        mcp_read = mcp_tools.get_conversation_messages(
            SimpleNamespace(delegated_user_id=USER), {"conversation_id": collaboration_id},
        )
        mcp_text = json.dumps(mcp_read, default=str)
        require(
            mcp_read.get("messages") and unavailable in mcp_text and not leaked(mcp_text, answer_text),
            f"The MCP read leaked or was empty: {mcp_text[:500]}",
        )

        summary_inputs.clear()
        summarized = stranger.post(f"/api/conversations/{collaboration_id}/summary", json={})
        require(
            summarized.status_code == 200 and len(summary_inputs) == 1 and summary_inputs[0],
            f"The summary wasn't generated: {summarized.status_code} {summarized.get_data(as_text=True)[:300]}",
        )
        summary_text = json.dumps(summary_inputs, default=str)
        require(
            unavailable in summary_text and not leaked(summary_text, answer_text),
            f"The summary input leaked: {summary_text[:500]}",
        )

        # A mirrored answer that relied on the result is stored withheld as well.
        mirror_source = {
            "id": "msg-mirror-a", "conversation_id": conversation_id, "role": "assistant",
            "content": "Mirrored: markets rose again.", "timestamp": later(30).isoformat(),
            "model_deployment_name": "gpt-4o",
            "metadata": {
                "workflow_result_contexts": [context], "user_info": {"user_id": USER},
                "thread_info": {
                    "thread_id": "thread-mirror", "previous_thread_id": None, "active_thread": True,
                    "thread_attempt": 1,
                },
            },
        }
        mirrored, shared, created = collaboration.mirror_source_message_to_collaboration(
            shared, mirror_source, owner_user,
        )
        mirrored_copy = copies_in(collaboration_id).get(mirror_source["id"])
        require(
            created and mirrored_copy and mirrored_copy["content"] == unavailable
            and not leaked(json.dumps([mirrored, mirrored_copy], default=str), answer_text),
            f"The mirrored answer wasn't withheld: {mirrored_copy}",
        )
        require(
            not leaked(json.dumps(shared_chats.items[collaboration_id], default=str)),
            "Mirroring leaked into the shared chat.",
        )

        # The copy step withholds both the messages it queries and the ones it's handed.
        for target, raw_messages in (
            ("collab-direct-query", None), ("collab-direct-tuple", tuple(messages_of(conversation_id))),
        ):
            returned = collaboration._copy_legacy_personal_messages_to_collaboration(
                conversation_id, target, owner_user, raw_messages=raw_messages,
            )
            require_copies(copies_in(target), f"Copying into {target}")
            require(
                not leaked(json.dumps(returned, default=str), answer_text),
                f"Copying into {target} returned an answer.",
            )

        # Once the chat is converted, even its owner can't export the answer.
        require_exports(a1, 403, "After conversion, the Follow up answer")
        require_exports(a2, 200, "After conversion, an ordinary answer")

        require(not world.normal_chat_clients, "The normal chat model was used.")
        require(not world.network_attempts, f"The routes attempted network access: {world.network_attempts}")
        print(SCENARIOS_FINISHED)


def test_review_paths_withhold_copies_exports_replays_and_cached_searches():
    result = subprocess.run(
        [sys.executable, *(["-O"] if sys.flags.optimize else []), str(Path(__file__).resolve()), "--offline"],
        # app.py switches the child's output to UTF-8, which the parent's locale codec can't always decode.
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=240,
    )
    output = result.stdout[-3000:] + result.stderr[-6000:]

    require(result.returncode == 0, output)
    require(SCENARIOS_FINISHED in result.stdout.splitlines(), output)


if __name__ == "__main__":
    if "--offline" in sys.argv:
        run_offline_scenarios()
    else:
        raise SystemExit(pytest.main([__file__, "-q"]))
