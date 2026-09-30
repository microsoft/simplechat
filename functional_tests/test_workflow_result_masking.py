#!/usr/bin/env python3
# test_workflow_result_masking.py
"""
Functional test for withholding chat answers built from workflow results.
Version: 0.261.213
Implemented in: 0.261.213

This test ensures that an answer relying on a workflow result is withheld on every
new read once that result is unavailable to its owner (a deleted run, a changed
result, lost source access or a storage failure) or once the chat isn't the reader's
own private chat; that the question keeps its text; that a failed check never raises;
and that one read costs one authorization per distinct result and one conversation
read per distinct chat, with nothing read for messages that don't use a result.
"""

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from azure.core.exceptions import AzureError
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "single_app"))
sys.path.insert(0, str(ROOT / "functional_tests"))

import functions_saved_analysis as saved  # noqa: E402
import functions_workflow_result_reader as reader  # noqa: E402
from collaboration_models import (  # noqa: E402
    COLLABORATION_KIND,
    COLLABORATION_SOURCE_KIND,
    PERSONAL_MULTI_USER_CHAT_TYPE,
)
from functions_workflow_result_store import WorkflowResultStorageUnavailableError  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_support.workflow_result_chat import (  # noqa: E402
    OTHER_USER,
    RUN_ID,
    USER,
    WORKFLOW_ID,
    RunFixture,
    analysis_result,
    two_text_tasks,
)


CONVERSATION_ID = "conv-private-1"
SECOND_CONVERSATION_ID = "conv-private-2"
QUESTION = "What did the digest find?"
ANSWER = "The digest says markets rose. RESULT-DERIVED-CANARY"
ANALYSIS_CONTEXT = {"conversation_id": "conv-analysis", "message_id": "msg-analysis", "result_sha256": "d" * 64}
WITHHELD_KEYS = {
    "id", "conversation_id", "role", "timestamp", "model_deployment_name", "content",
    "metadata", "agent_citations", "hybrid_citations", "web_search_citations", "thoughts",
}


class Conversations:
    """The personal conversation container, read by id; a missing id is a not-found."""

    def __init__(self):
        self.documents = {
            conversation_id: {"id": conversation_id, "user_id": USER, "chat_type": "new", "title": "Digest"}
            for conversation_id in (CONVERSATION_ID, SECOND_CONVERSATION_ID)
        }
        self.reads = []
        self.error = None

    def __call__(self, conversation_id):
        self.reads.append(conversation_id)
        if self.error is not None:
            raise self.error
        if conversation_id not in self.documents:
            raise CosmosResourceNotFoundError(status_code=404, message="missing")
        return deepcopy(self.documents[conversation_id])


class Authorizer:
    """The real authorization-only reader, over the fixture's fake storage."""

    def __init__(self, fixture):
        self.fixture = fixture
        self.calls = []
        self.error = None

    def __call__(self, user_id, context):
        self.calls.append((user_id, reader.workflow_result_context_key(context)))
        if self.error is not None:
            raise self.error
        return reader.authorize_workflow_result_context(
            user_id, context, containers=self.fixture.containers, load_result=self.fixture.store.load,
            read_page=self.fixture.store.read_page, source_resolver=self.fixture.sources,
        )


class World:
    def __init__(self, *, with_analysis=False):
        self.fixture = RunFixture()
        two_text_tasks(self.fixture)
        if with_analysis:
            self.fixture.add_task("task-analyze-73", analysis_result(), order=3, label="Analyze the sources")
        self.descriptor = self.fixture.read()["descriptor"]
        self.context = {"workflow_id": WORKFLOW_ID, "run_id": RUN_ID, "result_sha256": self.descriptor["result_sha256"]}
        self.conversations = Conversations()
        self.authorizer = Authorizer(self.fixture)
        self.analysis_reads = []

    def analysis_reader(self, user_id, context):
        self.analysis_reads.append(context)

    def sanitize(self, messages, user_id=USER, **options):
        arguments = {
            "workflow_result_reader": self.authorizer, "conversation_reader": self.conversations,
            "result_reader": self.analysis_reader,
        }
        arguments.update(options)
        return saved.sanitize_saved_analysis_messages(messages, user_id, **arguments)

    def question(self, *, conversation_id=CONVERSATION_ID, message_id="msg-question-1", context=None):
        return {
            "id": message_id, "conversation_id": conversation_id, "role": "user", "content": QUESTION,
            "timestamp": "2026-01-06T10:00:00", "model_deployment_name": "gpt-4o",
            "metadata": {
                "workflow_result_context": dict(context or self.context),
                "user_info": {"user_id": USER, "display_name": "Owner"},
                "thread_info": {"thread_id": "thread-1", "active_thread": True, "thread_attempt": 1},
                "prompt_selection": {"source": "typed"},
            },
        }

    def answer(self, *, conversation_id=CONVERSATION_ID, message_id="msg-answer-1", contexts=None, descriptor=True):
        metadata = {
            "workflow_result_contexts": [dict(context) for context in (contexts or [self.context])],
            "token_usage": {"total_tokens": 15},
            "context_budget": {"limit": 1000},
            "user_info": {"user_id": USER, "display_name": "Owner"},
            "thread_info": {"thread_id": "thread-1", "active_thread": True, "thread_attempt": 1},
            "masked": False,
        }
        if descriptor:
            metadata["workflow_result"] = dict(self.descriptor)
        return {
            "id": message_id, "conversation_id": conversation_id, "role": "assistant",
            "content": f"{ANSWER}\n\n_This answer uses the stored result of the Weekly digest run._",
            "timestamp": "2026-01-06T10:00:05", "model_deployment_name": "gpt-4o",
            "agent_display_name": "Digest helper", "agent_name": "digest-helper", "augmented": False,
            "agent_citations": [{"function_result": "AGENT-CITATION-CANARY"}],
            "hybrid_citations": [{"file_name": "HYBRID-CITATION-CANARY"}],
            "web_search_citations": [{"url": "https://example.test/WEB-CITATION-CANARY"}],
            "thoughts": [{"content": "THOUGHT-CANARY"}],
            "generated_outputs": [{"name": "GENERATED-OUTPUT-CANARY"}],
            "metadata": metadata,
        }

    def delete_run(self):
        self.fixture.containers["runs"].documents.clear()

    def change_result(self):
        # resume-failed re-runs a failed task inside the same run.
        self.fixture.add_task("task-summary-72", {"reply": "A revised digest."}, order=2, label="Write the digest")

    def restore_result(self):
        self.fixture.add_task(
            "task-summary-72", {"reply": "The digest: markets rose."}, order=2, label="Write the digest",
        )


def assert_withheld(message, original):
    assert set(message) == WITHHELD_KEYS | ({"agent_display_name", "agent_name"} & set(original))
    assert message["content"] == reader.WORKFLOW_RESULT_UNAVAILABLE_MESSAGE
    for field in ("id", "conversation_id", "role", "timestamp", "model_deployment_name"):
        assert message[field] == original[field]
    assert message["metadata"] == {
        "thread_info": original["metadata"]["thread_info"],
        "user_info": original["metadata"]["user_info"],
        "masked": original["metadata"]["masked"],
        "workflow_result": {"version": reader.WORKFLOW_RESULT_VERSION, "available": False},
    }
    for field in ("agent_citations", "hybrid_citations", "web_search_citations", "thoughts"):
        assert message[field] == []
    shown = json.dumps(message)
    for private in (
        WORKFLOW_ID, RUN_ID, "Weekly digest", "CANARY", "result_sha256", "workflow_result_contexts",
        original["metadata"]["workflow_result_contexts"][0]["result_sha256"],
    ):
        assert private not in shown


def assert_question_kept_without_context(message, original):
    expected = deepcopy(original)
    expected["metadata"].pop("workflow_result_context")
    assert message == expected


def test_messages_that_use_no_workflow_result_are_untouched_and_read_nothing():
    world = World()
    messages = [
        {"id": "m1", "conversation_id": CONVERSATION_ID, "role": "user", "content": "Hello"},
        {"id": "m2", "conversation_id": CONVERSATION_ID, "role": "assistant", "content": "Hi", "metadata": {}},
        {"id": "m3", "conversation_id": CONVERSATION_ID, "role": "assistant", "content": "Hi", "metadata": {"x": 1}},
    ]

    result = world.sanitize(messages)

    assert all(returned is original for returned, original in zip(result, messages))
    assert world.authorizer.calls == []
    assert world.conversations.reads == []
    assert world.analysis_reads == []


def test_a_readable_result_in_the_owners_private_chat_is_shown_unchanged():
    world = World()
    messages = [world.question(), world.answer()]
    before = deepcopy(messages)

    result = world.sanitize(messages)

    assert result == before
    assert messages == before
    assert world.authorizer.calls == [(USER, reader.workflow_result_context_key(world.context))]
    assert world.conversations.reads == [CONVERSATION_ID]


def test_one_authorization_per_distinct_result_and_one_read_per_chat():
    world = World()
    stale = {**world.context, "result_sha256": "e" * 64}
    messages = []
    for index in range(3):
        messages.append(world.question(message_id=f"q-{index}"))
        messages.append(world.answer(message_id=f"a-{index}"))
    messages.append(world.answer(conversation_id=SECOND_CONVERSATION_ID, message_id="a-second"))
    messages.append(world.answer(message_id="a-stale", contexts=[stale], descriptor=False))
    messages.append(world.answer(conversation_id=SECOND_CONVERSATION_ID, message_id="a-stale-2", contexts=[stale]))

    result = world.sanitize(messages)

    assert result[:7] == messages[:7]
    assert result[7]["content"] == result[8]["content"] == reader.WORKFLOW_RESULT_UNAVAILABLE_MESSAGE
    assert sorted(world.authorizer.calls) == sorted([
        (USER, reader.workflow_result_context_key(world.context)),
        (USER, reader.workflow_result_context_key(stale)),
    ])
    assert sorted(world.conversations.reads) == [CONVERSATION_ID, SECOND_CONVERSATION_ID]


def test_a_deleted_run_withholds_answers_and_keeps_the_question_text():
    world = World()
    question, answer = world.question(), world.answer()
    world.delete_run()

    result = world.sanitize([question, answer])

    assert_question_kept_without_context(result[0], question)
    assert_withheld(result[1], answer)
    assert len(world.authorizer.calls) == 1


def test_a_changed_result_is_withheld_until_it_matches_again():
    world = World()
    messages = [world.question(), world.answer()]
    before = deepcopy(messages)
    world.change_result()

    changed = world.sanitize(messages)

    assert_withheld(changed[1], before[1])
    assert messages == before

    world.restore_result()
    assert world.sanitize(messages) == before


def test_lost_source_access_withholds_an_answer_that_used_an_analysis_output():
    world = World(with_analysis=True)
    answer = world.answer()
    assert world.sanitize([answer]) == [answer]

    world.fixture.sources.allowed = False

    assert_withheld(world.sanitize([answer])[0], answer)


@pytest.mark.parametrize("failure", [
    "run_read", "items_query", "result_load", "unexpected_reader_error", "conversation_read",
])
def test_storage_failures_withhold_and_never_raise(failure):
    world = World()
    question, answer = world.question(), world.answer()
    if failure == "run_read":
        world.fixture.containers["runs"].read_error = CosmosHttpResponseError(status_code=503, message="down")
    elif failure == "items_query":
        world.fixture.containers["run_items"].query_error = AzureError("down")
    elif failure == "result_load":
        world.fixture.store.load_error = WorkflowResultStorageUnavailableError("down")
    elif failure == "unexpected_reader_error":
        world.authorizer.error = RuntimeError("down")
    else:
        world.conversations.error = CosmosHttpResponseError(status_code=503, message="down")

    result = world.sanitize([question, answer])

    assert_question_kept_without_context(result[0], question)
    assert_withheld(result[1], answer)


@pytest.mark.parametrize("change", [
    {"converted_to_collaboration_at": "2026-01-07T09:00:00"},
    {"is_hidden": True, "collaboration_conversation_id": "collab-1"},
    {"conversation_kind": COLLABORATION_KIND},
    {"conversation_kind": COLLABORATION_SOURCE_KIND},
    {"chat_type": PERSONAL_MULTI_USER_CHAT_TYPE},
    {"user_id": OTHER_USER},
    None,
])
def test_a_chat_that_isnt_the_readers_own_private_chat_withholds_before_any_result_read(change):
    world = World()
    if change is None:
        del world.conversations.documents[CONVERSATION_ID]
    else:
        world.conversations.documents[CONVERSATION_ID].update(change)
    question, answer = world.question(), world.answer()

    result = world.sanitize([question, answer])

    assert_question_kept_without_context(result[0], question)
    assert_withheld(result[1], answer)
    assert world.authorizer.calls == []
    assert world.conversations.reads == [CONVERSATION_ID]


def test_another_reader_and_a_message_without_a_chat_are_withheld():
    world = World()
    answer = world.answer()
    assert_withheld(world.sanitize([answer], user_id=OTHER_USER)[0], answer)

    orphan = world.answer()
    del orphan["conversation_id"]
    withheld = world.sanitize([orphan])[0]
    assert withheld["content"] == reader.WORKFLOW_RESULT_UNAVAILABLE_MESSAGE
    assert "conversation_id" not in withheld
    assert world.authorizer.calls == []


@pytest.mark.parametrize("metadata", [
    {"workflow_result_contexts": "not-a-list"},
    {"workflow_result_contexts": [{"workflow_id": WORKFLOW_ID}]},
    {"workflow_result": {"available": False}},
    {"workflow_result": None},
    {"workflow_result_context": {"workflow_id": WORKFLOW_ID, "run_id": RUN_ID, "result_sha256": "short"}},
])
def test_malformed_lineage_is_withheld_without_reads(metadata):
    world = World()
    answer = world.answer()
    answer["metadata"] = {**{
        key: value for key, value in answer["metadata"].items()
        if key not in ("workflow_result", "workflow_result_contexts")
    }, **metadata}
    question = world.question()
    question["metadata"].pop("workflow_result_context")
    question["metadata"].update(metadata)

    result = world.sanitize([question, answer])

    assert result[1]["content"] == reader.WORKFLOW_RESULT_UNAVAILABLE_MESSAGE
    assert result[1]["metadata"]["workflow_result"] == {"version": reader.WORKFLOW_RESULT_VERSION, "available": False}
    assert result[0]["content"] == QUESTION
    assert not reader.message_uses_workflow_result(result[0])
    assert world.authorizer.calls == []
    assert world.conversations.reads == []


def test_withholding_is_idempotent_and_reads_nothing_the_second_time():
    world = World()
    question, answer = world.question(), world.answer()
    world.delete_run()
    first = world.sanitize([question, answer])
    world.authorizer.calls.clear()
    world.conversations.reads.clear()

    second = world.sanitize(first)

    assert second == first
    assert world.authorizer.calls == []
    assert world.conversations.reads == []


def test_an_ordinary_answer_that_inherited_the_lineage_follows_it():
    world = World()
    inherited = world.answer(descriptor=False)
    assert world.sanitize([inherited]) == [inherited]

    world.delete_run()

    assert_withheld(world.sanitize([inherited])[0], inherited)


def test_saved_analysis_checks_still_run_after_the_workflow_check():
    world = World()
    answer = world.answer()
    answer["metadata"]["analysis_result_contexts"] = [dict(ANALYSIS_CONTEXT)]

    assert world.sanitize([answer]) == [answer]
    assert world.analysis_reads == [ANALYSIS_CONTEXT]

    def lost(user_id, context):
        raise PermissionError("lost")

    analysis_withheld = world.sanitize([answer], result_reader=lost)[0]
    assert analysis_withheld["content"] == saved.UNAVAILABLE_ANALYSIS_MESSAGE
    assert not reader.message_uses_workflow_result(analysis_withheld)

    world.analysis_reads.clear()
    world.delete_run()
    workflow_withheld = world.sanitize([answer])[0]
    assert workflow_withheld["content"] == reader.WORKFLOW_RESULT_UNAVAILABLE_MESSAGE
    assert world.analysis_reads == []


def test_a_withheld_workflow_answer_counts_as_unavailable():
    world = World()
    answer = world.answer()
    world.delete_run()

    withheld = world.sanitize([answer])[0]

    assert saved.is_saved_analysis_unavailable(withheld) is True
    assert saved.is_saved_analysis_unavailable(answer) is False
    assert saved.is_saved_analysis_unavailable({"metadata": {"workflow_result": "x"}}) is False


def test_message_views_follow_the_workflow_lineage():
    world = World()
    answer = world.answer()

    def authorize(message, **options):
        arguments = {
            "message_loader": lambda *args: deepcopy(message), "workflow_result_reader": world.authorizer,
            "conversation_reader": world.conversations, "result_reader": world.analysis_reader,
        }
        arguments.update(options)
        return saved.authorize_saved_analysis_message_read(USER, CONVERSATION_ID, message["id"], **arguments)

    assert authorize(answer) is True
    plain = {"id": "plain", "conversation_id": CONVERSATION_ID, "role": "assistant", "metadata": {}}
    world.authorizer.calls.clear()
    world.conversations.reads.clear()
    assert authorize(plain) is True
    assert world.authorizer.calls == [] and world.conversations.reads == []

    world.authorizer.error = AzureError("down")
    with pytest.raises(PermissionError):
        authorize(answer)
    world.authorizer.error = None

    world.conversations.documents[CONVERSATION_ID]["converted_to_collaboration_at"] = "2026-01-07T09:00:00"
    with pytest.raises(PermissionError):
        authorize(answer)
    del world.conversations.documents[CONVERSATION_ID]["converted_to_collaboration_at"]

    world.delete_run()
    with pytest.raises(PermissionError) as caught:
        authorize(answer)
    assert WORKFLOW_ID not in str(caught.value) and RUN_ID not in str(caught.value)


def test_withholding_logs_fixed_messages_with_codes_only(monkeypatch):
    world = World()
    logged = []
    monkeypatch.setattr(saved, "log_event", lambda message, extra=None, **kwargs: logged.append((message, extra)))
    answers = [world.answer(), world.answer(conversation_id=SECOND_CONVERSATION_ID, message_id="a-2")]
    world.conversations.documents[SECOND_CONVERSATION_ID]["converted_to_collaboration_at"] = "2026-01-07T09:00:00"
    world.delete_run()

    world.sanitize(answers)

    assert logged
    assert {message for message, _ in logged} == {"[WorkflowResults] A chat answer's workflow result was withheld on read."}
    for _, extra in logged:
        assert set(extra) <= {"check", "code", "error_type"}
        shown = json.dumps(extra)
        assert WORKFLOW_ID not in shown and RUN_ID not in shown and CONVERSATION_ID not in shown
    assert {"check": "result", "code": "workflow_result_not_found", "error_type": "WorkflowResultUnavailable"} in [
        extra for _, extra in logged
    ]


def test_version_is_at_least_the_implementation_version():
    assert_app_version_at_least("0.261.213")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
