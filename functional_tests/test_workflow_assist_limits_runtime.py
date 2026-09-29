#!/usr/bin/env python3
# test_workflow_assist_limits_runtime.py
"""
Functional test for the AI workflow assistant's limits and its Azure-backed services.
Version: 0.261.205
Implemented in: 0.261.205

This test ensures that:

* the per-user limiter allows one request in flight and 20 requests per 10 minutes across workers
  and instances. It keeps its count in one Cosmos document under an etag compare-and-swap,
  answers 429 with the seconds until the window ends, refunds a request that never reached the
  model, lets a lease a dead worker left behind expire, and fails closed with a 503 when its
  store is down;
* the Cosmos store maps the SDK's statuses onto "missing", "lost a race" and "down", and replaces
  a document only under the etag it read;
* a lease that cannot be released never fails the request, and logs one content-free warning;
* the model invoker keeps its own output limits, classifies a deployment exactly as the
  draft-instructions assist does, asks for JSON and drops JSON mode only when the deployment
  refuses it, bounds each call by the time the core allows, and turns every provider failure into
  a closed code without the provider's text;
* the Azure-backed services call each dependency as the caller, map its failures to closed codes,
  and a whole request through them writes nothing but the caller's rate-limit document. The
  dependencies they call are read-only by contract; the real dry run's is proven in
  ``test_workflow_assist_dry_run_parity.py``.

The model and every Azure dependency are fakes; nothing here reaches Azure or a model.
"""

import ast
import copy
import hashlib
import json
import logging
import sys
import types
from pathlib import Path
from unittest.mock import patch

import httpx
import openai
import pytest
from azure.core import MatchConditions
from azure.core.exceptions import AzureError
from azure.cosmos.exceptions import CosmosHttpResponseError

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(ROOT / "functional_tests"))

import functions_workflow_assist as core  # noqa: E402
import functions_workflow_assist_limits as limits  # noqa: E402
import functions_workflow_assist_runtime as runtime  # noqa: E402
from functions_orchestration_context import ScopeReferenceError, _scope_reference_error  # noqa: E402
from functions_workflow_definitions import workflow_definition_revision  # noqa: E402
from functions_workflow_limits import WorkflowLoopLimitError  # noqa: E402
from test_support import workflow_assist as wa  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


START = 1_700_000_000.0
SENTINEL = "SENTINEL-LIMITS-RUNTIME-5c1e"
WRITE_METHODS = frozenset({
    "create_item", "replace_item", "upsert_item", "delete_item", "patch_item", "execute_item_batch",
})
MESSAGES = [{"role": "system", "content": "system"}, {"role": "user", "content": "{}"}]
REQUEST = httpx.Request("POST", "https://aoai.example.invalid/openai/deployments/assist/chat/completions")
EXPLAINED = json.dumps({"outcome": "explained", "reply": "It already runs on demand."})


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least("0.261.205")


def refused(call):
    with pytest.raises(core.WorkflowAssistError) as caught:
        call()
    return caught.value


# ---------------------------------------------------------------------------------------------
# The limiter
# ---------------------------------------------------------------------------------------------

class MemoryStore:
    """The limiter's store in memory, with Cosmos's etag compare-and-swap.

    ``down`` names the methods that fail as an outage. Each callable in ``races`` runs just before
    the next write lands, standing in for another worker's request.
    """

    def __init__(self):
        self.documents = {}
        self.version = 0
        self.down = set()
        self.races = []
        self.log = []

    def land(self, document):
        self.version += 1
        stored = copy.deepcopy(document)
        stored.update({"_etag": f"etag-{self.version}", "_ts": self.version})
        self.documents[document["id"]] = stored

    def _race(self):
        if self.races:
            self.races.pop(0)(self)

    def read(self, document_id):
        self.log.append(("read", document_id))
        if "read" in self.down:
            raise limits.AssistLimitStoreError("down")
        stored = self.documents.get(document_id)
        return copy.deepcopy(stored) if stored is not None else None

    def create(self, document):
        self.log.append(("create", document["id"]))
        if "create" in self.down:
            raise limits.AssistLimitStoreError("down")
        self._race()
        if document["id"] in self.documents:
            raise limits.AssistLimitConflict()
        self.land(document)

    def replace(self, document, etag):
        self.log.append(("replace", document["id"]))
        if "replace" in self.down:
            raise limits.AssistLimitStoreError("down")
        self._race()
        current = self.documents.get(document["id"])
        if current is None or current["_etag"] != etag:
            raise limits.AssistLimitConflict()
        self.land(document)

    def document(self, user_id=wa.USER_ID):
        stored = self.documents[limits.assist_limit_document_id(user_id)]
        return {key: value for key, value in stored.items() if not key.startswith("_")}


def another_write(store):
    """Another worker's write to the user's document: same content, new etag."""
    current = store.documents[limits.assist_limit_document_id(wa.USER_ID)]
    store.land({key: value for key, value in current.items() if not key.startswith("_")})


def make_limiter():
    store = MemoryStore()
    clock = wa.FakeClock(start=START)
    return limits.WorkflowAssistLimiter(store, clock=clock), store, clock


def test_the_limits_are_one_in_flight_and_twenty_per_ten_minutes():
    assert (limits.ASSIST_LIMIT_REQUESTS, limits.ASSIST_LIMIT_WINDOW_SECONDS) == (20, 600)
    # A lease outlives its request's deadline, so only a worker that died leaves one set.
    assert limits.ASSIST_LEASE_SECONDS > core.ASSIST_DEADLINE_SECONDS


def test_the_first_request_creates_the_users_document_and_holds_a_lease():
    limiter, store, _clock = make_limiter()

    lease = limiter.acquire(wa.USER_ID)

    document_id = "workflow_assist_rate_limit:" + hashlib.sha256(wa.USER_ID.encode("utf-8")).hexdigest()
    assert (lease.user_id, lease.document_id, lease.window_start) == (wa.USER_ID, document_id, int(START))
    assert store.log == [("read", document_id), ("create", document_id)]
    document = store.document()
    assert document == {
        "id": document_id, "type": "workflow_assist_rate_limit", "window_start_epoch": int(START),
        "window_seconds": 600, "count": 1, "lease_id": lease.lease_id, "lease_expires_at": int(START) + 180,
        "updated_at": document["updated_at"],
    }
    # A hash of the user, counts and times: never the user ID or anything the request carried.
    assert wa.USER_ID not in json.dumps(store.documents)


def test_a_second_request_while_one_is_in_flight_is_busy_and_not_counted():
    limiter, store, clock = make_limiter()
    limiter.acquire(wa.USER_ID)
    clock.advance(30)

    error = refused(lambda: limiter.acquire(wa.USER_ID))

    assert (error.status, error.code, error.retry_after) == (429, "assistant_busy", 1)
    assert error.payload({}) == {
        "error": error.message, "code": "assistant_busy", "rate_limited": True, "retry_after_seconds": 1,
    }
    assert store.document()["count"] == 1
    # Each user has a document of their own.
    other = limiter.acquire(wa.OTHER_USER_ID)
    assert store.document(wa.OTHER_USER_ID)["lease_id"] == other.lease_id


def test_releasing_clears_the_lease_and_keeps_the_count():
    limiter, store, clock = make_limiter()
    lease = limiter.acquire(wa.USER_ID)

    limiter.release(lease)

    document = store.document()
    assert (document["lease_id"], document["lease_expires_at"], document["count"]) == (None, 0, 1)
    clock.advance(5)
    second = limiter.acquire(wa.USER_ID)
    assert (store.document()["count"], second.window_start) == (2, int(START))
    limiter.release(None)
    assert store.document()["lease_id"] == second.lease_id


def test_a_lease_a_dead_worker_left_expires_on_its_own():
    limiter, store, clock = make_limiter()
    limiter.acquire(wa.USER_ID)
    clock.advance(179)
    assert refused(lambda: limiter.acquire(wa.USER_ID)).code == "assistant_busy"

    clock.advance(1)
    lease = limiter.acquire(wa.USER_ID)

    assert (store.document()["lease_id"], store.document()["count"]) == (lease.lease_id, 2)


def test_twenty_requests_fill_the_window_and_the_next_is_told_when_it_ends():
    limiter, store, clock = make_limiter()
    for _ in range(20):
        limiter.release(limiter.acquire(wa.USER_ID))
        clock.advance(10)

    error = refused(lambda: limiter.acquire(wa.USER_ID))

    assert (error.status, error.code, error.retry_after) == (429, "assistant_rate_limited", 400)
    payload = error.payload({})
    assert (payload["code"], payload["rate_limited"], payload["retry_after_seconds"]) == (
        "assistant_rate_limited", True, 400,
    )
    assert isinstance(payload["error"], str) and payload["error"].strip()
    assert store.document()["count"] == 20
    clock.advance(399)
    assert refused(lambda: limiter.acquire(wa.USER_ID)).retry_after == 1
    clock.advance(1)
    lease = limiter.acquire(wa.USER_ID)
    assert (lease.window_start, store.document()["count"]) == (int(START) + 600, 1)


def test_a_request_that_never_reached_the_model_is_refunded():
    limiter, store, _clock = make_limiter()
    for _ in range(19):
        limiter.release(limiter.acquire(wa.USER_ID))
    last = limiter.acquire(wa.USER_ID)
    assert store.document()["count"] == 20

    limiter.release(last, refund=True)

    assert (store.document()["count"], store.document()["lease_id"]) == (19, None)
    limiter.acquire(wa.USER_ID)
    assert store.document()["count"] == 20


def test_a_release_never_touches_a_lease_a_later_request_holds():
    limiter, store, clock = make_limiter()
    stale = limiter.acquire(wa.USER_ID)
    clock.advance(180)
    current = limiter.acquire(wa.USER_ID)
    before = store.document()
    seen = len(store.log)

    limiter.release(stale, refund=True)

    assert store.document() == before
    assert (before["lease_id"], before["count"]) == (current.lease_id, 2)
    assert [entry[0] for entry in store.log[seen:]] == ["read"]


@pytest.mark.parametrize("method", ["read", "create", "replace"])
def test_the_limit_fails_closed_when_its_store_is_down(method):
    limiter, store, _clock = make_limiter()
    if method == "replace":
        limiter.release(limiter.acquire(wa.USER_ID))
    store.down.add(method)

    error = refused(lambda: limiter.acquire(wa.USER_ID))

    assert (error.status, error.code, error.retry_after) == (503, "assistant_limit_unavailable", None)
    assert isinstance(error.__cause__, limits.AssistLimitStoreError)
    assert error.payload({}) == {"error": error.message, "code": "assistant_limit_unavailable"}


def test_two_requests_starting_together_get_one_lease():
    limiter, store, clock = make_limiter()
    rival = limits.WorkflowAssistLimiter(store, clock=clock)
    won = {}
    store.races.append(lambda _store: won.setdefault("lease", rival.acquire(wa.USER_ID)))

    error = refused(lambda: limiter.acquire(wa.USER_ID))

    assert (error.code, error.retry_after) == ("assistant_busy", 1)
    assert (store.document()["lease_id"], store.document()["count"]) == (won["lease"].lease_id, 1)


def test_a_write_that_lands_first_is_read_again_and_counted_after_it():
    limiter, store, clock = make_limiter()
    stale = limiter.acquire(wa.USER_ID)
    clock.advance(200)
    # The earlier request's worker refunds just as this request writes.
    store.races.append(lambda _store: limiter.release(stale, refund=True))

    lease = limiter.acquire(wa.USER_ID)

    assert (store.document()["lease_id"], store.document()["count"]) == (lease.lease_id, 1)


def test_four_lost_races_in_a_row_are_busy_and_write_nothing():
    limiter, store, _clock = make_limiter()
    limiter.release(limiter.acquire(wa.USER_ID))
    before = store.document()
    store.races.extend([another_write] * 4)

    error = refused(lambda: limiter.acquire(wa.USER_ID))

    assert (error.code, error.retry_after) == ("assistant_busy", 1)
    assert store.document() == before
    assert [entry[0] for entry in store.log[-8:]] == ["read", "replace"] * 4


def test_a_release_that_keeps_losing_races_raises_for_the_caller_to_log():
    limiter, store, _clock = make_limiter()
    lease = limiter.acquire(wa.USER_ID)
    store.races.extend([another_write] * 4)

    with pytest.raises(limits.AssistLimitStoreError):
        limiter.release(lease)

    # The lease stays set until it expires.
    assert store.document()["lease_id"] == lease.lease_id


def test_a_release_that_cannot_read_raises_for_the_caller_to_log():
    limiter, store, _clock = make_limiter()
    lease = limiter.acquire(wa.USER_ID)
    store.down.add("read")

    with pytest.raises(limits.AssistLimitStoreError):
        limiter.release(lease)


# ---------------------------------------------------------------------------------------------
# The Cosmos store
# ---------------------------------------------------------------------------------------------

class ScriptedContainer:
    """A Cosmos container that answers each method from a script and records its arguments."""

    def __init__(self, **answers):
        self.answers = answers
        self.calls = []

    def _answer(self, name, kwargs):
        self.calls.append((name, copy.deepcopy(kwargs)))
        answer = self.answers.get(name)
        if isinstance(answer, BaseException):
            raise answer
        return copy.deepcopy(answer)

    def read_item(self, **kwargs):
        return self._answer("read_item", kwargs)

    def create_item(self, **kwargs):
        return self._answer("create_item", kwargs)

    def replace_item(self, **kwargs):
        return self._answer("replace_item", kwargs)


def cosmos_error(status):
    return CosmosHttpResponseError(status_code=status, message=f"{SENTINEL} cosmos message")


OUTAGES = [cosmos_error(429), cosmos_error(500), cosmos_error(503), AzureError(SENTINEL), ConnectionError(SENTINEL)]
OUTAGE_IDS = ["throttled", "server error", "unavailable", "azure error", "connection error"]


def test_the_store_reads_a_document_in_its_own_partition():
    container = ScriptedContainer(read_item={"id": "limit-1", "count": 3, "_etag": "etag-1"})
    store = limits.CosmosAssistLimitStore(container)

    assert store.read("limit-1") == {"id": "limit-1", "count": 3, "_etag": "etag-1"}
    assert container.calls == [("read_item", {"item": "limit-1", "partition_key": "limit-1"})]
    assert limits.CosmosAssistLimitStore(ScriptedContainer(read_item=cosmos_error(404))).read("limit-1") is None


@pytest.mark.parametrize("failure", OUTAGES, ids=OUTAGE_IDS)
def test_a_store_that_cannot_be_read_is_down(failure):
    with pytest.raises(limits.AssistLimitStoreError):
        limits.CosmosAssistLimitStore(ScriptedContainer(read_item=failure)).read("limit-1")


def test_a_create_that_finds_the_document_lost_a_race():
    container = ScriptedContainer()
    limits.CosmosAssistLimitStore(container).create({"id": "limit-1", "count": 1})
    assert container.calls == [("create_item", {"body": {"id": "limit-1", "count": 1}})]

    with pytest.raises(limits.AssistLimitConflict):
        limits.CosmosAssistLimitStore(ScriptedContainer(create_item=cosmos_error(409))).create({"id": "limit-1"})


@pytest.mark.parametrize("failure", OUTAGES, ids=OUTAGE_IDS)
def test_a_create_that_fails_otherwise_is_the_store_being_down(failure):
    with pytest.raises(limits.AssistLimitStoreError):
        limits.CosmosAssistLimitStore(ScriptedContainer(create_item=failure)).create({"id": "limit-1"})


def test_a_replace_lands_only_on_the_etag_it_read():
    container = ScriptedContainer()
    limits.CosmosAssistLimitStore(container).replace({"id": "limit-1", "count": 2}, "etag-7")
    assert container.calls == [("replace_item", {
        "item": "limit-1", "body": {"id": "limit-1", "count": 2}, "etag": "etag-7",
        "match_condition": MatchConditions.IfNotModified,
    })]


@pytest.mark.parametrize("status", [404, 409, 412])
def test_a_replace_that_finds_another_write_lost_a_race(status):
    with pytest.raises(limits.AssistLimitConflict):
        limits.CosmosAssistLimitStore(ScriptedContainer(replace_item=cosmos_error(status))).replace(
            {"id": "limit-1"}, "etag-7",
        )


@pytest.mark.parametrize("failure", OUTAGES, ids=OUTAGE_IDS)
def test_a_replace_that_fails_otherwise_is_the_store_being_down(failure):
    with pytest.raises(limits.AssistLimitStoreError):
        limits.CosmosAssistLimitStore(ScriptedContainer(replace_item=failure)).replace({"id": "limit-1"}, "etag-7")


# ---------------------------------------------------------------------------------------------
# A lease that cannot be released
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("answered", [True, False], ids=["answered", "refused"])
def test_a_lease_that_cannot_be_released_never_changes_the_answer_and_logs_one_warning(answered):
    stored = wa.stored_workflow()
    limiter = wa.FakeLimiter(release_error=limits.AssistLimitStoreError(f"{SENTINEL} release failure"))
    if answered:
        bundle = wa.services(wa.ScriptedModel(wa.reply("explained", "It already runs on demand.")),
                             stored=stored, limiter=limiter)
        assert wa.run(wa.request_body(stored=stored), bundle)["outcome"] == "explained"
    else:
        newer = wa.stored_workflow(definition_revision="rev-0002-newer")
        bundle = wa.services(wa.ScriptedModel(), stored=newer, limiter=limiter)
        assert wa.refusal(wa.request_body(stored=stored), bundle).code == "workflow_definition_conflict"

    warnings = [(extra, level) for message, extra, level in bundle.logs
                if message == "[WorkflowAssist] Rate-limit lease release failed"]
    assert warnings == [({
        "user_id": wa.USER_ID, "submission_id": "submission-0001", "error_type": "AssistLimitStoreError",
    }, logging.WARNING)]
    assert wa.finished_log(bundle)["status"] == (200 if answered else 409)
    assert SENTINEL not in json.dumps(bundle.logs)


def test_a_logger_that_fails_during_release_changes_nothing():
    stored = wa.stored_workflow()
    limiter = wa.FakeLimiter(release_error=limits.AssistLimitStoreError("down"))
    bundle = wa.services(wa.ScriptedModel(wa.reply("explained", "It already runs on demand.")),
                         stored=stored, limiter=limiter)

    def failing_log(message, extra, level):
        raise RuntimeError("the log sink is down")

    bundle.log = failing_log
    assert wa.run(wa.request_body(stored=stored), bundle)["outcome"] == "explained"


# ---------------------------------------------------------------------------------------------
# The model invoker
# ---------------------------------------------------------------------------------------------

def draft_instructions_function():
    """``_build_agent_instruction_api_params`` from route_backend_agents.py, without importing the route."""
    path = APP / "route_backend_agents.py"
    function = next(
        node for node in ast.parse(path.read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef) and node.name == "_build_agent_instruction_api_params"
    )
    return path, function


def draft_instructions_parameters():
    path, function = draft_instructions_function()
    namespace = {"AGENT_INSTRUCTION_OUTPUT_TOKEN_LIMIT": 1400}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["_build_agent_instruction_api_params"]


DEPLOYMENTS = [
    "gpt-5", "GPT-5-mini", "gpt-5.1-chat", "o1", "o1-preview", "o3-mini", "team-o3-assist", "gpt-4o",
    "gpt-4o-2024-11-20", "gpt-4.1-mini", "gpt-35-turbo", "o4-mini", "", None,
]


def test_the_assistant_uses_the_draft_instructions_assists_family_markers():
    _path, function = draft_instructions_function()
    markers = [
        tuple(element.value for element in node.iter.elts)
        for node in ast.walk(function)
        if isinstance(node, ast.comprehension) and isinstance(node.iter, ast.Tuple)
    ]
    assert markers == [runtime.ASSIST_COMPLETION_TOKEN_MARKERS] == [("o1", "o3", "gpt-5")]


@pytest.mark.parametrize("model_name", DEPLOYMENTS)
def test_a_deployment_is_classified_as_the_draft_instructions_assist_classifies_it(model_name):
    theirs = draft_instructions_parameters()(model_name, MESSAGES)
    ours = runtime.assist_model_parameters(model_name, MESSAGES, json_mode=False)

    for field in ("max_completion_tokens", "max_tokens", "temperature"):
        assert (field in ours) == (field in theirs), (model_name, field)
    assert (ours["model"], ours["messages"]) == (model_name, MESSAGES)


def test_the_assistant_keeps_its_own_output_limits_and_asks_for_json():
    assert runtime.assist_model_parameters("gpt-5-mini", MESSAGES) == {
        "model": "gpt-5-mini", "messages": MESSAGES, "max_completion_tokens": 16000,
        "response_format": {"type": "json_object"},
    }
    assert runtime.assist_model_parameters("gpt-4o", MESSAGES) == {
        "model": "gpt-4o", "messages": MESSAGES, "max_tokens": 4000, "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    assert "response_format" not in runtime.assist_model_parameters("gpt-4o", MESSAGES, json_mode=False)
    # The draft-instructions assist's 1,400 tokens are too few for a changed workflow.
    theirs = draft_instructions_parameters()("gpt-4o", MESSAGES)["max_tokens"]
    assert min(runtime.ASSIST_MAX_TOKENS, runtime.ASSIST_MAX_COMPLETION_TOKENS) > theirs == 1400


class FakeClient:
    """An OpenAI client: ``with_options(...).chat.completions.create(...)`` answers from a script."""

    def __init__(self, *answers, on_request=None):
        self.answers = list(answers)
        self.requests = []
        self.on_request = on_request

    def with_options(self, **options):
        client = self

        def create(**parameters):
            client.requests.append((options, copy.deepcopy(parameters)))
            if client.on_request is not None:
                client.on_request(len(client.requests))
            answer = client.answers.pop(0)
            if isinstance(answer, BaseException):
                raise answer
            return answer

        return types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))


def completion(content=EXPLAINED, finish_reason="stop", refusal=None):
    message = types.SimpleNamespace(content=content, refusal=refusal)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message, finish_reason=finish_reason)])


def status_error(kind, status, *, body=None, headers=None):
    response = httpx.Response(status, request=REQUEST, headers=headers or {})
    return kind(f"{SENTINEL} provider message", response=response, body=body)


JSON_MODE_REJECTION = {
    "code": "unsupported_parameter", "param": "response_format",
    "message": "response_format is not supported with this model.",
}


def test_the_client_is_made_on_the_first_call_and_reused():
    made = []
    client = FakeClient(completion(), completion('{"outcome": "question"}', "length"))

    def factory():
        made.append(True)
        return client, "gpt-4o"

    model = runtime.WorkflowAssistModel(factory, clock=wa.FakeClock(start=50.0))
    assert made == []

    assert model(MESSAGES, 90) == (EXPLAINED, "stop")
    assert model(MESSAGES, 40) == ('{"outcome": "question"}', "length")

    assert made == [True]
    assert [options for options, _parameters in client.requests] == [
        {"timeout": 90, "max_retries": 0}, {"timeout": 40, "max_retries": 0},
    ]
    assert client.requests[0][1] == runtime.assist_model_parameters("gpt-4o", MESSAGES)


def test_a_deployment_that_refuses_json_mode_is_asked_again_without_it():
    rejection = status_error(openai.BadRequestError, 400, body=JSON_MODE_REJECTION)
    # The shared classifier, as the chat and plan assists use it.
    assert runtime.is_json_mode_rejection(rejection) is True
    clock = wa.FakeClock(start=0.0)
    client = FakeClient(rejection, completion(), completion(), on_request=lambda _count: clock.advance(30))
    model = runtime.WorkflowAssistModel(lambda: (client, "gpt-4o"), clock=clock)

    assert model(MESSAGES, 90) == (EXPLAINED, "stop")
    assert model(MESSAGES, 90) == (EXPLAINED, "stop")

    # JSON mode stays off for the rest of the request, and the retry gets only the time left.
    assert ["response_format" in parameters for _options, parameters in client.requests] == [True, False, False]
    assert [options["timeout"] for options, _parameters in client.requests] == [90, 60, 90]


def test_a_json_mode_rejection_that_leaves_no_time_is_a_timeout():
    rejection = status_error(openai.BadRequestError, 400, body={"error": JSON_MODE_REJECTION})
    clock = wa.FakeClock(start=0.0)
    client = FakeClient(rejection, on_request=lambda _count: clock.advance(89.5))
    model = runtime.WorkflowAssistModel(lambda: (client, "gpt-4o"), clock=clock)

    error = refused(lambda: model(MESSAGES, 90))

    assert (error.status, error.code) == (503, "assistant_timeout")
    assert len(client.requests) == 1


def test_any_other_rejection_is_not_retried():
    other = status_error(openai.BadRequestError, 400, body={"code": "invalid_prompt", "message": SENTINEL})
    assert runtime.is_json_mode_rejection(other) is False
    assert runtime.is_json_mode_rejection(RuntimeError("response_format is not supported")) is False
    client = FakeClient(other)
    model = runtime.WorkflowAssistModel(lambda: (client, "gpt-4o"), clock=wa.FakeClock())

    error = refused(lambda: model(MESSAGES, 90))

    assert (error.status, error.code) == (503, "assistant_unavailable")
    assert error.__cause__ is other and len(client.requests) == 1
    assert SENTINEL not in json.dumps(error.payload({}))


def test_no_call_starts_with_less_than_a_second_left():
    client = FakeClient(completion())
    model = runtime.WorkflowAssistModel(lambda: (client, "gpt-4o"), clock=wa.FakeClock())

    error = refused(lambda: model(MESSAGES, 0.5))

    assert (error.status, error.code) == (503, "assistant_timeout")
    assert client.requests == []


def test_a_model_that_cannot_be_set_up_is_unavailable():
    def factory():
        raise RuntimeError(f"{SENTINEL} endpoint and key")

    model = runtime.WorkflowAssistModel(factory, clock=wa.FakeClock())

    error = refused(lambda: model(MESSAGES, 90))

    assert (error.status, error.code) == (503, "assistant_unavailable")
    assert SENTINEL not in json.dumps(error.payload({}))


def _provider_cases():
    throttled = openai.RateLimitError
    yield "timeout", openai.APITimeoutError(request=REQUEST), 503, "assistant_timeout", None
    yield "connection", openai.APIConnectionError(request=REQUEST), 503, "assistant_unavailable", None
    yield "throttled for seconds", status_error(throttled, 429, headers={"retry-after": "7"}), 503, (
        "assistant_unavailable"), 7
    yield "throttled for milliseconds", status_error(throttled, 429, headers={"retry-after-ms": "2500"}), 503, (
        "assistant_unavailable"), 3
    yield "throttled for too long", status_error(throttled, 429, headers={"retry-after": "600"}), 503, (
        "assistant_unavailable"), 60
    yield "throttled for no time", status_error(throttled, 429, headers={"retry-after": "0"}), 503, (
        "assistant_unavailable"), 1
    yield "throttled until a date", status_error(
        throttled, 429, headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}), 503, "assistant_unavailable", 10
    yield "throttled without a header", status_error(throttled, 429), 503, "assistant_unavailable", 10
    yield "context too long", status_error(openai.BadRequestError, 400, body={
        "code": "context_length_exceeded", "message": SENTINEL}), 400, "assistant_input_too_large", None
    yield "context too long, wrapped", status_error(openai.BadRequestError, 400, body={
        "error": {"code": "context_length_exceeded", "message": SENTINEL}}), 400, "assistant_input_too_large", None
    yield "content filter", status_error(openai.BadRequestError, 400, body={
        "code": "content_filter", "message": SENTINEL}), 502, "assistant_refused", None
    yield "content policy", status_error(openai.BadRequestError, 400, body={
        "error": {"code": "content_policy_violation", "message": SENTINEL}}), 502, "assistant_refused", None
    yield "other bad request", status_error(openai.BadRequestError, 400, body={
        "code": "invalid_prompt", "message": SENTINEL}), 503, "assistant_unavailable", None
    yield "not authorized", status_error(openai.AuthenticationError, 401), 503, "assistant_unavailable", None
    yield "server error", status_error(openai.InternalServerError, 500), 503, "assistant_unavailable", None
    yield "unexpected", RuntimeError(SENTINEL), 503, "assistant_unavailable", None


PROVIDER_CASES = list(_provider_cases())


@pytest.mark.parametrize("label, failure, status, code, retry_after", PROVIDER_CASES,
                         ids=[case[0] for case in PROVIDER_CASES])
def test_a_provider_failure_is_a_closed_code_without_the_providers_text(label, failure, status, code, retry_after):
    client = FakeClient(failure)
    model = runtime.WorkflowAssistModel(lambda: (client, "gpt-4o"), clock=wa.FakeClock())

    error = refused(lambda: model(MESSAGES, 90))

    assert (error.status, error.code, error.retry_after) == (status, code, retry_after), label
    assert error.__cause__ is failure
    assert SENTINEL not in json.dumps(error.payload({})) and SENTINEL not in error.message


def test_a_reply_is_its_content_and_finish_reason_and_a_refusal_is_filtered():
    assert runtime.model_reply(completion("{}", "length")) == ("{}", "length")
    assert runtime.model_reply(completion(None, "content_filter")) == (None, "content_filter")
    assert runtime.model_reply(completion("{}", "stop", refusal=f"{SENTINEL} I can't help")) == (None, "content_filter")
    assert runtime.model_reply(types.SimpleNamespace(choices=[])) == (None, None)
    assert runtime.model_reply(types.SimpleNamespace()) == (None, None)


# ---------------------------------------------------------------------------------------------
# Refused `#` references
# ---------------------------------------------------------------------------------------------

def test_a_refused_reference_keeps_only_the_authorizers_own_words():
    too_many = runtime.reference_error(_scope_reference_error("too_many", None, 20))
    assert (too_many.status, too_many.code, too_many.message) == (
        400, "reference_limit", core.WorkflowAssistError("reference_limit").message,
    )
    for reason in ("invalid_reference", "unsupported_kind"):
        error = runtime.reference_error(_scope_reference_error(reason, {"kind": "document", "label": "x"}, 20))
        assert (error.status, error.code) == (400, "invalid_request"), reason
    unchecked = runtime.reference_error(_scope_reference_error("verification_failed", None, 20))
    assert (unchecked.status, unchecked.code) == (503, "reference_check_failed")

    gone = runtime.reference_error(_scope_reference_error(
        "document_unavailable", {"kind": "document", "label": "Q3 budget.xlsx"}, 20,
    ))
    assert (gone.status, gone.code) == (400, "reference_unavailable")
    assert gone.message == "\u201cQ3 budget.xlsx\u201d is no longer available to you. Remove it and pick another document."
    unnamed = runtime.reference_error(ScopeReferenceError("", reason="document_not_ready"))
    assert unnamed.message == core.WorkflowAssistError("reference_unavailable").message


def test_an_excerpt_is_read_as_a_reference_to_the_one_document():
    assert runtime.excerpt_reference(("group", "group-0004-stuvwx", "doc-guide-0003")) == {
        "id": "excerpt", "name": "excerpt", "document_id": "doc-guide-0003",
        "scope_type": "group", "scope_id": "group-0004-stuvwx",
    }


# ---------------------------------------------------------------------------------------------
# The Azure-backed services
# ---------------------------------------------------------------------------------------------

class ReadOnlyContainer:
    """A Cosmos container that serves reads and fails the test on any write."""

    def __init__(self, name, items=None):
        self.name = name
        self.items = items or {}
        self.calls = []

    def read_item(self, item, partition_key, **kwargs):
        self.calls.append(("read_item", item, partition_key))
        if (item, partition_key) not in self.items:
            raise CosmosHttpResponseError(status_code=404, message="Not found")
        return copy.deepcopy(self.items[(item, partition_key)])

    def __getattr__(self, attribute):
        if attribute in WRITE_METHODS:
            raise AssertionError(f"The assistant called {self.name}.{attribute}.")
        raise AttributeError(attribute)


class LimitContainer:
    """The settings container: accepts writes only to rate-limit documents, under an etag compare-and-swap."""

    def __init__(self):
        self.items = {}
        self.writes = []
        self.version = 0

    def _allowed(self, item_id):
        if not str(item_id).startswith("workflow_assist_rate_limit:"):
            raise AssertionError(f"The assistant wrote {item_id!r} to the settings container.")

    def _land(self, body):
        self.version += 1
        self.items[body["id"]] = {**copy.deepcopy(body), "_etag": f"etag-{self.version}"}

    def read_item(self, item, partition_key, **kwargs):
        if item not in self.items:
            raise CosmosHttpResponseError(status_code=404, message="Not found")
        return copy.deepcopy(self.items[item])

    def create_item(self, body, **kwargs):
        self._allowed(body["id"])
        self.writes.append(("create_item", body["id"]))
        if body["id"] in self.items:
            raise CosmosHttpResponseError(status_code=409, message="Conflict")
        self._land(body)

    def replace_item(self, item, body, etag=None, match_condition=None, **kwargs):
        self._allowed(item)
        self.writes.append(("replace_item", item))
        assert match_condition == MatchConditions.IfNotModified and etag
        if self.items.get(item, {}).get("_etag") != etag:
            raise CosmosHttpResponseError(status_code=412, message="Precondition failed")
        self._land(body)

    def __getattr__(self, attribute):
        if attribute in WRITE_METHODS:
            raise AssertionError(f"The assistant called settings.{attribute}.")
        raise AttributeError(attribute)


class Dependencies:
    """Stand-ins for the modules ``build_workflow_assist_services`` imports, recording every call."""

    def __init__(self, stored=None):
        self.calls = []
        self.workflows = ReadOnlyContainer("personal_workflows", {
            (stored["id"], stored["user_id"]): stored,
        } if stored else {})
        self.settings_container = LimitContainer()
        self.resolve_error = None
        self.options_error = None
        self.dry_run_error = None
        self.excerpt = {"text": f"{SENTINEL} excerpt text. " * 3}
        self.sources = {"email"}
        self.connection = {"status": "connected"}
        self.connection_error = None

    def resolve_scope_references(self, references, user_id, settings=None, *, allowed_workspaces=None, limit=None):
        self.calls.append(("resolve_scope_references", user_id, settings, allowed_workspaces, limit))
        if self.resolve_error is not None:
            raise self.resolve_error
        return [wa.resolved_document(reference) for reference in references]

    def get_workflow_editor_options(self, user_id, settings):
        self.calls.append(("get_workflow_editor_options", user_id, settings))
        if self.options_error is not None:
            raise self.options_error
        return copy.deepcopy(wa.OPTIONS)

    def load_workflow_reference(self, workflow, reference, *, actor_user_id=None):
        self.calls.append(("load_workflow_reference", workflow, reference, actor_user_id))
        return copy.deepcopy(self.excerpt)

    def dry_run_personal_workflow(self, user_id, payload, *, actor_user_id=None, settings=None):
        self.calls.append(("dry_run_personal_workflow", user_id, actor_user_id, settings))
        if self.dry_run_error is not None:
            raise self.dry_run_error
        return {"ok": True, "workflow": copy.deepcopy(payload), "errors": []}

    def workflow_m365_manifests(self, workflow):
        self.calls.append(("workflow_m365_manifests", copy.deepcopy(workflow)))
        return ["action-1"], workflow

    def _manifest_sources(self, action):
        return set(self.sources)

    def current_connection(self, user_id, tenant_id):
        self.calls.append(("current_connection", user_id, tenant_id))
        if self.connection_error is not None:
            raise self.connection_error
        return copy.deepcopy(self.connection)

    def modules(self):
        """Only what the services import; a new import fails the test until it is reviewed here."""
        def module(name, **attributes):
            stub = types.ModuleType(name)
            stub.__dict__.update(attributes)
            return stub

        service = types.SimpleNamespace(current_connection=self.current_connection)
        return {
            "config": module(
                "config", TENANT_ID="tenant-0001", cosmos_personal_workflows_container=self.workflows,
                cosmos_settings_container=self.settings_container,
            ),
            "functions_m365_connections": module("functions_m365_connections", get_m365_connection_service=lambda: service),
            "functions_m365_runtime": module(
                "functions_m365_runtime", _manifest_sources=self._manifest_sources,
                workflow_m365_manifests=self.workflow_m365_manifests,
            ),
            "functions_orchestration_context": module(
                "functions_orchestration_context", ScopeReferenceError=ScopeReferenceError,
                resolve_scope_references=self.resolve_scope_references,
            ),
            "functions_workflow_bindings": module(
                "functions_workflow_bindings", load_workflow_reference=self.load_workflow_reference,
            ),
            "functions_workflow_drafts": module(
                "functions_workflow_drafts", dry_run_personal_workflow=self.dry_run_personal_workflow,
            ),
            "functions_workflow_editor": module(
                "functions_workflow_editor", get_workflow_editor_options=self.get_workflow_editor_options,
            ),
        }

    def named(self, name):
        return [call[1:] for call in self.calls if call[0] == name]


SETTINGS = {"allow_user_workflows": True, "enable_workflow_ai_assistant": True, "azure_openai_gpt_key": SENTINEL}


def build(dependencies, client_factory=None):
    with patch.dict(sys.modules, dependencies.modules()):
        return runtime.build_workflow_assist_services(
            SETTINGS, client_factory=client_factory or (lambda: (FakeClient(completion()), "gpt-4o")),
        )


def saved_workflow(**fields):
    """A stored workflow carrying the revision the editor computes when it loads the workflow.

    A real read recomputes ``definition_revision`` from the authored fields, as the save route
    checks it, so the editor's ``base`` holds that value rather than a stored literal.
    """
    stored = wa.stored_workflow(**fields)
    stored["definition_revision"] = workflow_definition_revision(stored)
    return stored


def test_the_services_read_the_callers_workflow_as_the_editor_loads_it():
    stored = wa.stored_workflow()
    dependencies = Dependencies(stored)
    services = build(dependencies)

    loaded = services.read_base(wa.USER_ID, wa.WORKFLOW_ID)

    assert loaded == runtime.read_workflow_base(dependencies.workflows, wa.USER_ID, wa.WORKFLOW_ID)
    # The revision is recomputed from the authored fields, exactly as the editor receives it.
    assert loaded["definition_revision"] == workflow_definition_revision(stored) != wa.REVISION
    assert services.read_base(wa.OTHER_USER_ID, wa.WORKFLOW_ID) is None
    assert {call[2] for call in dependencies.workflows.calls} == {wa.USER_ID, wa.OTHER_USER_ID}
    assert {call[2] for call in dependencies.workflows.calls} == {wa.USER_ID, wa.OTHER_USER_ID}


def test_the_services_authorize_references_as_the_caller_within_the_assistants_bound():
    dependencies = Dependencies()
    services = build(dependencies)

    documents = services.resolve_references(wa.USER_ID, [wa.CHECKLIST])

    assert [document["id"] for document in documents] == [wa.CHECKLIST["id"]]
    assert dependencies.named("resolve_scope_references") == [(wa.USER_ID, SETTINGS, None, 20)]
    dependencies.resolve_error = _scope_reference_error("too_many", None, 20)
    assert refused(lambda: services.resolve_references(wa.USER_ID, [wa.CHECKLIST])).code == "reference_limit"
    dependencies.resolve_error = _scope_reference_error("verification_failed", None, 20)
    assert refused(lambda: services.resolve_references(wa.USER_ID, [wa.CHECKLIST])).status == 503


def test_the_services_offer_the_editors_own_choices():
    dependencies = Dependencies()
    services = build(dependencies)

    assert services.load_options(wa.USER_ID) == wa.OPTIONS
    assert dependencies.named("get_workflow_editor_options") == [(wa.USER_ID, SETTINGS)]
    dependencies.options_error = CosmosHttpResponseError(status_code=503, message=SENTINEL)
    error = refused(lambda: services.load_options(wa.USER_ID))
    assert (error.status, error.code) == (503, "assistant_unavailable")
    dependencies.options_error = KeyError("a bug")
    with pytest.raises(KeyError):
        services.load_options(wa.USER_ID)


def test_the_services_read_an_excerpt_through_the_workflow_reference_loader():
    dependencies = Dependencies()
    services = build(dependencies)
    identity = ("personal", wa.USER_ID, wa.CHECKLIST["id"])

    assert services.load_excerpt(wa.USER_ID, identity) == dependencies.excerpt["text"]
    assert dependencies.named("load_workflow_reference") == [(
        {"user_id": wa.USER_ID, "group_id": ""}, runtime.excerpt_reference(identity), wa.USER_ID,
    )]
    dependencies.excerpt = None
    assert services.load_excerpt(wa.USER_ID, identity) is None


@pytest.mark.parametrize("failure", [
    WorkflowLoopLimitError("The loop limit could not be checked."),
    CosmosHttpResponseError(status_code=503, message=SENTINEL),
], ids=["loop limit", "cosmos"])
def test_the_services_dry_run_as_the_caller_and_an_outage_is_unavailable(failure):
    dependencies = Dependencies()
    services = build(dependencies)

    assert services.dry_run(wa.USER_ID, {"name": "Review"})["ok"] is True
    assert dependencies.named("dry_run_personal_workflow") == [(wa.USER_ID, wa.USER_ID, SETTINGS)]
    dependencies.dry_run_error = failure
    error = refused(lambda: services.dry_run(wa.USER_ID, {"name": "Review"}))
    assert (error.status, error.code) == (503, "assistant_unavailable")


def test_the_services_ask_whether_an_agent_can_send_email_as_a_run_would():
    dependencies = Dependencies()
    services = build(dependencies)

    assert services.agent_email_capable(wa.USER_ID, wa.AGENT) is True
    assert dependencies.named("workflow_m365_manifests") == [(
        {"user_id": wa.USER_ID, "group_id": "", "selected_agent": wa.AGENT, "tasks": []},
    )]
    dependencies.sources = {"calendar"}
    assert services.agent_email_capable(wa.USER_ID, wa.AGENT) is False


def test_the_services_read_the_callers_stored_m365_connection():
    dependencies = Dependencies()
    services = build(dependencies)

    assert services.m365_connected(wa.USER_ID) is True
    assert dependencies.named("current_connection") == [(wa.USER_ID, "tenant-0001")]
    dependencies.connection = {"status": "expired"}
    assert services.m365_connected(wa.USER_ID) is False
    for code in ("m365_connection_required", "m365_connection_binding_changed"):
        dependencies.connection_error = type("ConnectionStateError", (Exception,), {"code": code})()
        assert services.m365_connected(wa.USER_ID) is False
    # Anything else is unknown; the core adds no warning for it.
    dependencies.connection_error = RuntimeError(SENTINEL)
    with pytest.raises(RuntimeError):
        services.m365_connected(wa.USER_ID)


def test_the_services_log_through_log_event(monkeypatch):
    logged = []
    monkeypatch.setattr(runtime, "log_event", lambda message, extra=None, level=None: logged.append(
        (message, extra, level)))
    services = build(Dependencies())

    services.log("[WorkflowAssist] Assist request finished", {"status": 200}, logging.INFO)

    assert logged == [("[WorkflowAssist] Assist request finished", {"status": 200}, logging.INFO)]


def test_a_whole_request_writes_only_the_callers_rate_limit_document(monkeypatch):
    logged = []
    monkeypatch.setattr(runtime, "log_event", lambda message, extra=None, level=None: logged.append(
        (message, extra, level)))
    stored = saved_workflow(m365_run_as_user_id=wa.RUN_AS_ID)
    dependencies = Dependencies(stored)
    client = FakeClient(completion(wa.reply(
        "changed", f"{SENTINEL} Review now uses the checklist.",
        [{"op": "bind_reference", "document": "ref_1", "tasks": ["task_2"]},
         {"op": "set_schedule_calendar", "frequency": "weekdays", "time_of_day": "07:00"}],
    )))
    services = build(dependencies, client_factory=lambda: (client, "gpt-4o"))
    body = wa.request_body(
        stored=stored, instruction=f"{SENTINEL} Compare every new document against #checklist at 7 on weekdays.",
        references=[wa.CHECKLIST],
    )

    result = core.run_workflow_assist(copy.deepcopy(body), user_id=wa.USER_ID, services=services)

    assert result["outcome"] == "changed"
    assert [warning["code"] for warning in result["warnings"]] == ["run_as_reapproval"]
    assert [reference["document_id"] for reference in result["candidate"]["reference_inputs"]] == [wa.CHECKLIST["id"]]
    # The limiter's document is the only write: counted, then its lease released.
    document_id = limits.assist_limit_document_id(wa.USER_ID)
    assert dependencies.settings_container.writes == [("create_item", document_id), ("replace_item", document_id)]
    document = dependencies.settings_container.items[document_id]
    assert (document["count"], document["lease_id"]) == (1, None)
    assert wa.USER_ID not in json.dumps(document) and SENTINEL not in json.dumps(document)
    assert [call[0] for call in dependencies.workflows.calls] == ["read_item"]
    # Each dependency ran as the caller.
    assert dependencies.named("resolve_scope_references") == [(wa.USER_ID, SETTINGS, None, 20)]
    assert [call[2] for call in dependencies.named("load_workflow_reference")] == [wa.USER_ID]
    assert dependencies.named("dry_run_personal_workflow") == [(wa.USER_ID, wa.USER_ID, SETTINGS)]
    # The draft-instructions deployment, asked once, bounded by the request's deadline.
    [(options, parameters)] = client.requests
    assert options["max_retries"] == 0 and 0 < options["timeout"] <= core.ASSIST_DEADLINE_SECONDS
    assert parameters["model"] == "gpt-4o" and parameters["response_format"] == {"type": "json_object"}
    # The logs are content-free, and no setting reached the model.
    [finished] = [extra for message, extra, _level in logged if message == "[WorkflowAssist] Assist request finished"]
    assert (finished["status"], finished["outcome"], finished["model_calls"]) == (200, "changed", 1)
    assert SENTINEL not in json.dumps(logged, default=str)
    assert SENTINEL not in json.dumps(parameters["messages"][0]) and "azure_openai_gpt_key" not in json.dumps(
        parameters["messages"])


def test_a_request_the_limit_refuses_reaches_nothing_else():
    stored = wa.stored_workflow()
    dependencies = Dependencies(stored)
    client = FakeClient()
    services = build(dependencies, client_factory=lambda: (client, "gpt-4o"))
    document_id = limits.assist_limit_document_id(wa.USER_ID)
    dependencies.settings_container.items[document_id] = {
        "id": document_id, "type": "workflow_assist_rate_limit", "window_start_epoch": 0, "window_seconds": 600,
        "count": 0, "lease_id": "held-elsewhere", "lease_expires_at": 2 ** 40, "_etag": "etag-0",
    }

    error = refused(lambda: core.run_workflow_assist(
        wa.request_body(stored=stored), user_id=wa.USER_ID, services=services,
    ))

    assert (error.status, error.code, error.retry_after) == (429, "assistant_busy", 1)
    assert dependencies.settings_container.writes == [] and dependencies.workflows.calls == []
    assert dependencies.calls == [] and client.requests == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
