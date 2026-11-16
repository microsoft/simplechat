# test_chat_stream_conversation_reference_scope.py
"""Runtime regression for request-owned conversation-reference stream state.

Version: 0.261.387
Implemented in: 0.261.387

Exercise the real Flask SSE route in a fresh offline process, including document
grounding, reference re-resolution, retries/edits, and request isolation.
"""

from copy import deepcopy
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import werkzeug


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"


def test_stream_conversation_reference_scope_runtime():
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--probe"],
        cwd=ROOT, capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, f"{result.stdout[-4000:]}\n{result.stderr[-12000:]}"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def run_probe():
    # The harness imports real application modules only after isolating external I/O.
    sys.path.insert(0, str(APP))
    sys.path.insert(0, str(TESTS))
    from test_support.workflow_result_chat import USER, OTHER_USER
    from test_support.workflow_result_offline_app import offline_workflow_result_app

    with offline_workflow_result_app() as world:
        from functions_chat_retry import prepare_retry_attempt

        chats, config = world.chats, world.config
        # Flask 2's test client still reads the version attribute removed in Werkzeug 3.
        world.stack.enter_context(patch.object(werkzeug, "__version__", version("werkzeug"), create=True))
        requests = []
        reply = "The selected source contains the requested information."

        def complete(**kwargs):
            requests.append(deepcopy(kwargs))
            if kwargs.get("stream"):
                return iter([
                    SimpleNamespace(
                        choices=[SimpleNamespace(delta=SimpleNamespace(content=reply))],
                        usage=None,
                    ),
                    SimpleNamespace(
                        choices=[],
                        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                    ),
                ])
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="Source summary"))],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )

        model = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=complete)))
        world.stack.enter_context(patch.object(chats, "AzureOpenAI", lambda **kwargs: model))
        reference_resolver = world.stack.enter_context(patch.object(
            chats, "_resolve_chat_conversation_references",
            wraps=chats._resolve_chat_conversation_references,
        ))
        release_lease = world.stack.enter_context(patch.object(
            chats, "_release_chat_destination_lease", wraps=chats._release_chat_destination_lease,
        ))
        sessions = []
        start_session = chats.CHAT_STREAM_REGISTRY.start_session

        def track_session(*args, **kwargs):
            stream_session = start_session(*args, **kwargs)
            sessions.append(stream_session)
            return stream_session

        world.stack.enter_context(patch.object(chats.CHAT_STREAM_REGISTRY, "start_session", track_session))
        client = world.signed_in(USER, "Owner")

        def stream_requests():
            return [request for request in requests if request.get("stream")]

        def user_messages(conversation_id):
            return [
                message for message in config.cosmos_messages_container.items.values()
                if message.get("conversation_id") == conversation_id and message.get("role") == "user"
            ]

        def ask(**fields):
            response = client.post("/api/chat/stream", json={
                "message": "summarize", "doc_scope": "personal",
                "hybrid_search": False, **fields,
            })
            require(response.status_code == 200, f"Stream refused: {response.get_data(as_text=True)}")
            blocks = response.get_data(as_text=True).split("\n\n")
            events = [
                event for event in map(chats._extract_sse_event_payload, blocks)
                if isinstance(event, dict)
            ]
            errors = [event for event in events if event.get("error")]
            require(not errors, f"Stream failed: {errors}")
            require(any(event.get("done") for event in events), f"No terminal completion: {events}")
            content = "".join(event.get("content", "") for event in events)
            require(reply in content, f"No model content: {events}")
            terminal = next(event for event in events if event.get("done"))
            require(sessions[-1].get_status_snapshot()["status"] == "completed", "Stream did not complete.")
            answers = [
                message for message in config.cosmos_messages_container.items.values()
                if message.get("conversation_id") == terminal["conversation_id"]
                and message.get("id") == terminal["message_id"]
                and message.get("role") == "assistant" and message.get("content") == reply
            ]
            require(bool(answers), "The streamed response was not persisted.")
            return terminal, events

        # A first-send chat must reach the model even without any references.
        first, _ = ask()
        conversation_id = first["conversation_id"]
        second, _ = ask(conversation_id=conversation_id)
        require(second["conversation_id"] == conversation_id, "Existing chat was not reused.")
        require(len(stream_requests()) == 2, "Model was not invoked.")

        # A selected file must reach retrieval, the model prompt, and the final citations.
        document_id = "selected-report"
        document_text = "DOCUMENT_EVIDENCE: the quarterly revenue was 1200."
        config.cosmos_user_documents_container.upsert_item({
            "id": document_id, "user_id": USER, "file_name": "report.pdf",
            "title": "Quarterly report", "version": 1, "status": "Completed",
        })
        search = world.stack.enter_context(patch.object(chats, "hybrid_search", return_value=[{
            "id": f"{document_id}_1", "document_id": document_id,
            "chunk_id": f"{document_id}_1", "chunk_text": document_text,
            "file_name": "report.pdf", "page_number": 1, "chunk_sequence": 1,
        }]))
        for destination in (None, conversation_id):
            search.reset_mock()
            fields = {"conversation_id": destination} if destination else {}
            grounded, _ = ask(
                **fields, hybrid_search=True, selected_document_ids=[document_id],
            )
            require(search.call_count == 1, "Selected file did not reach search exactly once.")
            search_ids = search.call_args.kwargs
            require(
                document_id in (search_ids.get("document_ids") or [search_ids.get("document_id")]),
                f"Selected document filter was lost: {search_ids}",
            )
            require(document_text in json.dumps(stream_requests()[-1]["messages"]), "Document context was lost.")
            require(
                any(citation.get("document_id") == document_id for citation in grounded["hybrid_citations"]),
                "Grounded response lost its citation.",
            )

        # Resolve real private conversation evidence before and after creating its destination.
        source_id = "reference-source"
        source_text = "REFERENCE_EVIDENCE: the project budget is 4500."
        config.cosmos_conversations_container.upsert_item({
            "id": source_id, "user_id": USER, "title": "Budget source",
            "chat_type": "personal_single_user", "last_updated": "2026-01-01",
            "tags": [{"category": "participant", "user_id": USER}],
        })
        config.cosmos_messages_container.upsert_item({
            "id": "source-message", "conversation_id": source_id, "role": "user",
            "content": source_text, "timestamp": "2026-01-01",
        })
        references = [{"kind": "conversation", "id": source_id}]
        reference_resolver.reset_mock()
        referenced, _ = ask(conversation_references=references)
        destination_id = referenced["conversation_id"]
        destinations = [call.kwargs.get("destination_id") for call in reference_resolver.call_args_list]
        require(destinations == [None, destination_id], f"New destination was not revalidated: {destinations}")
        require(source_text in json.dumps(stream_requests()[-1]["messages"]), "Reference evidence was lost.")
        saved = user_messages(destination_id)
        require(len(saved) == 1, "Unexpected reference question count.")
        metadata = saved[0]["metadata"]
        require(metadata["conversation_references"][0]["id"] == source_id, "Reference metadata was lost.")
        require(bool(metadata.get("conversation_reference_revision")), "Reference revision was lost.")

        continued, _ = ask(conversation_id=destination_id, conversation_references=references)
        require(continued["conversation_id"] == destination_id, "Referenced chat was not reused.")
        require(source_text in json.dumps(stream_requests()[-1]["messages"]), "Existing chat lost its reference.")

        # Retry and edit recover saved references when the request omits them.
        for retry_field in ("retry_user_message_id", "edited_user_message_id"):
            reference_resolver.reset_mock()
            original = user_messages(destination_id)[0]
            replay_body = {
                "message": original["content"], "conversation_id": destination_id,
                "doc_scope": "personal", "hybrid_search": False,
            }
            prepared = prepare_retry_attempt(
                config.cosmos_messages_container, config.cosmos_conversations_container,
                USER, original, replay_body, edited=retry_field == "edited_user_message_id",
            )
            count_before = len(user_messages(destination_id))
            ask(
                conversation_id=destination_id,
                retry_thread_id=prepared["metadata"]["thread_info"]["thread_id"],
                retry_thread_attempt=prepared["metadata"]["thread_info"]["thread_attempt"],
                **{retry_field: prepared["id"]},
            )
            require(len(user_messages(destination_id)) == count_before, "Retry/edit duplicated the question.")
            require(
                any(
                    call.kwargs.get("fallback_references")
                    or call.args[1].get("conversation_references")
                    for call in reference_resolver.call_args_list
                ),
                f"{retry_field} did not resolve saved references.",
            )
            require(source_text in json.dumps(stream_requests()[-1]["messages"]), "Retry/edit lost reference evidence.")

        # Closure updates belong to this request, not the next independent chat.
        independent, _ = ask()
        independent_messages = user_messages(independent["conversation_id"])
        require(
            not independent_messages[0]["metadata"].get("conversation_references"),
            "A different request inherited reference metadata.",
        )
        require(source_text not in json.dumps(stream_requests()[-1]["messages"]), "Reference context leaked across requests.")

        # Reference authorization still rejects another user's private source before model invocation.
        foreign_id = "foreign-source"
        config.cosmos_conversations_container.upsert_item({
            "id": foreign_id, "user_id": OTHER_USER, "title": "Private foreign chat",
            "chat_type": "personal_single_user", "last_updated": "2026-01-01",
        })
        calls_before = len(requests)
        messages_before = len(config.cosmos_messages_container.items)
        release_lease.reset_mock()
        denied = client.post("/api/chat/stream", json={
            "message": "summarize", "conversation_references": [{"kind": "conversation", "id": foreign_id}],
        })
        require(denied.status_code == 404, f"Unauthorized source was not denied: {denied.status_code}")
        require(denied.get_json()["code"] == "conversation_unavailable", "Reference denial lost its safe error code.")
        require(sessions[-1].get_status_snapshot()["status"] == "error", "Reference refusal left a live stream.")
        require(not sessions[-1].is_active(), "Refused stream is still active.")
        require(release_lease.call_count == 1, "Reference refusal did not release its destination.")
        require(release_lease.call_args.args[0].stop.is_set(), "Destination lease heartbeat was not stopped.")
        require(len(requests) == calls_before, "Unauthorized reference reached the model.")
        require(len(config.cosmos_messages_container.items) == messages_before, "Unauthorized request saved messages.")

        # A busy destination must also close its just-created session without releasing the other owner.
        held_lease = chats._acquire_chat_destination_lease(USER, conversation_id)
        try:
            release_lease.reset_mock()
            busy = client.post("/api/chat/stream", json={
                "message": "summarize", "conversation_id": conversation_id,
            })
            require(busy.status_code == 409, f"Busy destination was not refused: {busy.status_code}")
            require(sessions[-1].get_status_snapshot()["status"] == "error", "Busy destination left a live stream.")
            require(not sessions[-1].is_active(), "Busy stream is still active.")
            require(release_lease.call_count == 0, "Busy request released another request's lease.")
            require(len(requests) == calls_before, "Busy destination reached the model.")
            require(len(config.cosmos_messages_container.items) == messages_before, "Busy request saved messages.")
        finally:
            chats._release_chat_destination_lease(held_lease, conversation_id)
        require(not world.network_attempts, "A cloud request escaped the offline harness.")


if __name__ == "__main__":
    if "--probe" in sys.argv:
        run_probe()
    else:
        test_stream_conversation_reference_scope_runtime()
