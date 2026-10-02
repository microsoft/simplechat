# workflow_chat_delivery_fakes.py
"""
Reusable fakes for the workflow chat delivery tests.

The fakes stand in for Cosmos containers, the durable runtime store, the result
reader, the chat model and the notification helpers. The delivery contract and the
worker under test stay real. Checks inside this module raise explicitly so they
still run under ``python -O``.
"""

import copy
import itertools
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosHttpResponseError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)

from functions_workflow_chat_delivery import (
    build_chat_delivery_seed,
    finalize_chat_delivery_seed,
)
from functions_conversation_unread import mark_conversation_unread_guarded
from functions_orchestration_memory import conversation_is_private
from functions_workflow_chat_delivery_worker import WorkflowChatDeliveryServices


USER = "user-delivery-1"
OTHER_USER = "user-delivery-2"
WORKFLOW_ID = "workflow-delivery-1"
RUN_ID = "run-delivery-1"
CONVERSATION_ID = "conversation-delivery-1"
USER_MESSAGE_ID = "message-user-1"
ORCHESTRATION_RUN_ID = "orchestration-run-1"
ATTEMPT_ROOT_RUN_ID = "orchestration-run-1"
STEP_ID = "step-1"
REQUESTED_AT = "2026-05-04T14:05:00+00:00"
NOW = "2026-05-04T15:00:00+00:00"


class FakeCheckFailed(AssertionError):
    """A fake saw a call it was not prepared for."""


def require(condition, message):
    if not condition:
        raise FakeCheckFailed(message)


_COSMOS_ERRORS = {
    404: CosmosResourceNotFoundError,
    409: CosmosResourceExistsError,
    412: CosmosAccessConditionFailedError,
}


def cosmos_error(status_code, message="fake cosmos error"):
    error_type = _COSMOS_ERRORS.get(status_code, CosmosHttpResponseError)
    error = error_type(status_code=status_code, message=message)
    error.status_code = status_code
    return error


def iso(value):
    return value.astimezone(timezone.utc).isoformat()


def parse_iso(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def shift(value, **delta):
    return iso(parse_iso(value) + timedelta(**delta))


class FakeClock:
    """A settable ISO clock; ``advance`` moves it forward."""

    def __init__(self, start=NOW):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, **delta):
        self.now = shift(self.now, **delta)
        return self.now


class FakeContainer:
    """An in-memory container with ETag, 404, 409 and 412 semantics."""

    def __init__(self, name, items=None, query_handler=None, clock=None):
        self.name = name
        self.items = {}
        self.calls = []
        self.query_calls = []
        self.query_handler = query_handler
        self.clock = clock
        self.fail_next = {}
        self._etags = itertools.count(1)
        for item in items or []:
            self.put(item)

    def _key(self, item_id):
        return str(item_id)

    def _stamp(self, body):
        stored = copy.deepcopy(body)
        stored["_etag"] = f"etag-{self.name}-{next(self._etags)}"
        if self.clock is not None:
            stored["_ts"] = int(parse_iso(self.clock()).timestamp())
        else:
            stored.setdefault("_ts", 1777900000)
        return stored

    def put(self, body):
        stored = self._stamp(body)
        self.items[self._key(stored["id"])] = stored
        return copy.deepcopy(stored)

    def get(self, item_id):
        stored = self.items.get(self._key(item_id))
        return copy.deepcopy(stored) if stored is not None else None

    def fail(self, operation, *errors):
        """Queue errors for the next calls of ``operation``."""
        self.fail_next.setdefault(operation, []).extend(errors)

    def _maybe_fail(self, operation):
        queued = self.fail_next.get(operation) or []
        if queued:
            error = queued.pop(0)
            if callable(error) and not isinstance(error, BaseException):
                error = error()
            if error is not None:
                raise error

    def read_item(self, item=None, partition_key=None, **kwargs):
        self.calls.append(("read_item", item, partition_key))
        self._maybe_fail("read_item")
        stored = self.items.get(self._key(item))
        if stored is None:
            raise cosmos_error(404, "not found")
        return copy.deepcopy(stored)

    def replace_item(self, item=None, body=None, etag=None, match_condition=None, **kwargs):
        item_id = item.get("id") if isinstance(item, dict) else item
        self.calls.append(("replace_item", item_id, etag))
        self._maybe_fail("replace_item")
        stored = self.items.get(self._key(item_id))
        if stored is None:
            raise cosmos_error(404, "not found")
        if etag is not None and stored.get("_etag") != etag:
            raise cosmos_error(412, "precondition failed")
        updated = self._stamp(body)
        self.items[self._key(item_id)] = updated
        return copy.deepcopy(updated)

    def create_item(self, body=None, **kwargs):
        self.calls.append(("create_item", body.get("id")))
        self._maybe_fail("create_item")
        if self._key(body.get("id")) in self.items:
            raise cosmos_error(409, "conflict")
        return self.put(body)

    def upsert_item(self, body=None, **kwargs):
        self.calls.append(("upsert_item", body.get("id")))
        self._maybe_fail("upsert_item")
        return self.put(body)

    def delete_item(self, item=None, partition_key=None, **kwargs):
        item_id = item.get("id") if isinstance(item, dict) else item
        self.calls.append(("delete_item", item_id))
        self._maybe_fail("delete_item")
        if self.items.pop(self._key(item_id), None) is None:
            raise cosmos_error(404, "not found")

    def query_items(self, query=None, parameters=None, partition_key=None,
                    enable_cross_partition_query=None, **kwargs):
        self.query_calls.append({
            "query": query,
            "parameters": copy.deepcopy(parameters or []),
            "partition_key": partition_key,
            "enable_cross_partition_query": enable_cross_partition_query,
        })
        self._maybe_fail("query_items")
        if self.query_handler is None:
            raise FakeCheckFailed(f"{self.name}: unexpected query {query!r}")
        params = {entry["name"]: entry["value"] for entry in parameters or []}
        rows = self.query_handler(self, query, params, partition_key)
        return iter([copy.deepcopy(row) for row in rows])

    def writes(self, operation=None):
        names = ("replace_item", "create_item", "upsert_item", "delete_item")
        return [call for call in self.calls if call[0] in names and (operation is None or call[0] == operation)]


class FakeRuntimeConflict(Exception):
    def __init__(self, code="conflict"):
        super().__init__(code)
        self.code = code


class FakeRuntimeUnavailable(Exception):
    pass


class FakeResultUnavailable(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class FakeModelError(Exception):
    pass


class FakeRuntime:
    """Runtime controls by run ID. ``factory`` returns a store whose ``read`` honors tombstones."""

    def __init__(self):
        self.controls = {}
        self.errors = {}
        self.reads = []

    def set(self, run_id=RUN_ID, *, state="completed", version=5, deleted=False, gate_reason_code=None,
            deadline_at=None, phase=None, schema_version=2):
        control = {"state": state, "version": version, "deleted": deleted, "schema_version": schema_version}
        if phase is not None:
            control["phase"] = phase
        if gate_reason_code is not None:
            control["gate"] = {"reason_code": gate_reason_code}
        if deadline_at is not None:
            control["limits"] = {"deadline_at": deadline_at}
        self.controls[run_id] = control
        return copy.deepcopy(control)

    def update(self, run_id=RUN_ID, **changes):
        control = self.controls[run_id]
        control.update(changes)
        return copy.deepcopy(control)

    def tombstone(self, run_id=RUN_ID):
        control = self.controls[run_id]
        control.update({"deleted": True, "state": "cancelled", "version": control["version"] + 1})
        return copy.deepcopy(control)

    def remove(self, run_id=RUN_ID):
        self.controls.pop(run_id, None)

    def fail(self, run_id, *errors):
        self.errors.setdefault(run_id, []).extend(errors)

    def factory(self, user_id, workflow_id, run_id):
        runtime = self

        class _Store:
            def read(self, allow_deleted=False):
                runtime.reads.append((user_id, workflow_id, run_id, allow_deleted))
                queued = runtime.errors.get(run_id) or []
                if queued:
                    raise queued.pop(0)
                control = runtime.controls.get(run_id)
                if control is None or (control.get("deleted") and not allow_deleted):
                    raise FakeRuntimeConflict("not_found")
                return copy.deepcopy(control)

        return _Store()


RESULT_SHA = "a" * 64
RESULT_TEXT = "The digest found three new files and one changed report."


def make_result(*, text=RESULT_TEXT, budget=None, saved_inputs=None, truncated=False, partial=False,
                analysis_only=False, skipped_reports=False, sha=RESULT_SHA):
    descriptor = {
        "workflow_id": WORKFLOW_ID,
        "run_id": RUN_ID,
        "result_sha256": sha,
        "workflow_name": "Daily digest",
        "status": "completed",
        "completed_at": "2026-05-04T14:30:00+00:00",
    }
    return {
        "descriptor": descriptor,
        "excerpts": [{"text": text}] if text else [],
        "truncated": truncated,
        "partial": partial,
        "analysis_only": analysis_only,
        "skipped_reports": skipped_reports,
        "saved_inputs": list(saved_inputs or []),
        "budget": budget,
    }


class FakeResultReader:
    """``read_workflow_result``: queued outcomes first, then the default result at the asked budget."""

    def __init__(self):
        self.calls = []
        self.outcomes = []
        self.text = RESULT_TEXT
        self.saved_inputs = None

    def __call__(self, user_id, workflow_id, run_id, *, expected_sha256=None, include_excerpts=True,
                 excerpt_budget_bytes=None):
        self.calls.append({
            "user_id": user_id,
            "workflow_id": workflow_id,
            "run_id": run_id,
            "expected_sha256": expected_sha256,
            "include_excerpts": include_excerpts,
            "budget": excerpt_budget_bytes,
        })
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            if callable(outcome):
                return outcome(excerpt_budget_bytes)
            return copy.deepcopy(outcome)
        return make_result(text=self.text, budget=excerpt_budget_bytes, saved_inputs=self.saved_inputs)


def fake_workflow_result_context(descriptor):
    if not isinstance(descriptor, dict) or not descriptor.get("result_sha256"):
        raise FakeResultUnavailable("workflow_result_invalid")
    return {
        "workflow_id": descriptor["workflow_id"],
        "run_id": descriptor["run_id"],
        "result_sha256": descriptor["result_sha256"],
    }


def fake_format_run_time(value, time_zone):
    if not value:
        return ""
    return f"May 4, 2026 at 10:05 AM ({time_zone})"


class FakeDisclosure:
    def __init__(self):
        self.calls = []

    def __call__(self, descriptor, time_zone, *, truncated=False, partial=False, analysis_only=False,
                 skipped_reports=False):
        self.calls.append({
            "descriptor": copy.deepcopy(descriptor),
            "time_zone": time_zone,
            "truncated": truncated,
            "partial": partial,
            "analysis_only": analysis_only,
            "skipped_reports": skipped_reports,
        })
        flags = [name for name, value in (("truncated", truncated), ("partial", partial)) if value]
        suffix = f" ({', '.join(flags)})" if flags else ""
        return f"Source: workflow run from May 4, 2026{suffix}."


class FakePromptBuilder:
    """``build_workflow_result_messages``: records the excerpt budget, question and nonce."""

    def __init__(self):
        self.calls = []
        self.error = None

    def __call__(self, settings, result, history, question, time_zone, *, nonce):
        self.calls.append({"budget": result.get("budget"), "question": question, "nonce": nonce, "time_zone": time_zone})
        if self.error is not None:
            raise self.error
        excerpt = (result.get("excerpts") or [{}])[0].get("text", "")
        return [
            {"role": "system", "content": f"Answer from the fenced result. Fence code: {nonce}.", "budget": result.get("budget")},
            {"role": "user", "content": f"<<{nonce}>>\n{excerpt}\n<</{nonce}>>\n\n{question}"},
        ]


class FakeNonces:
    def __init__(self):
        self.issued = []

    def __call__(self):
        nonce = f"nonce-{len(self.issued) + 1}"
        self.issued.append(nonce)
        return nonce


class FakeBudget:
    """``calculate_workflow_context_budget``: fits when the excerpt budget is at most ``max_budget``."""

    def __init__(self):
        self.calls = []
        self.max_budget = None

    def __call__(self, messages, model_name, provider=None, output_tokens=None):
        budget = messages[0].get("budget") if messages else None
        self.calls.append({"budget": budget, "model": model_name, "output_tokens": output_tokens})
        fits = self.max_budget is None or (budget is not None and budget <= self.max_budget)
        return {"decision": "full_input" if fits else "blocked"}


class FakeUsage:
    def __init__(self, prompt_tokens, completion_tokens, total_tokens):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens


class FakeChatMessage:
    def __init__(self, content, refusal=None):
        self.content = content
        self.refusal = refusal


class FakeChoice:
    def __init__(self, message, finish_reason):
        self.message = message
        self.finish_reason = finish_reason


class FakeResponse:
    def __init__(self, choices, usage):
        self.choices = choices
        self.usage = usage


COMPOSED_REPLY = "Your daily digest found three new files and one changed report."


def fake_response(text=COMPOSED_REPLY, *, finish_reason="stop", refusal=None, usage=(120, 30, 150)):
    tokens = FakeUsage(*usage) if usage is not None else None
    return FakeResponse([FakeChoice(FakeChatMessage(text, refusal), finish_reason)], tokens)


def fake_extract_text(response):
    return response.choices[0].message.content


class FakeModel:
    def __init__(self, deployment, *, provider="aoai", endpoint_id="endpoint-1", model_id=None):
        self.deployment = deployment
        self.provider = provider
        self.behavior_name = deployment
        self.model_metadata = None
        self.endpoint_id = endpoint_id
        self.model_id = model_id or f"model-{deployment}"
        self.replies = []
        self.requests = []
        self.closed = 0

    def metadata(self):
        return {
            "model_deployment_name": self.deployment,
            "model_provider": self.provider,
            "model_endpoint_id": self.endpoint_id,
            "model_id": self.model_id,
        }

    def create_completion(self, messages=None, temperature=None, max_tokens=None):
        self.requests.append({"messages": copy.deepcopy(messages), "temperature": temperature, "max_tokens": max_tokens})
        reply = self.replies.pop(0) if self.replies else fake_response()
        if isinstance(reply, BaseException):
            raise reply
        return reply

    def close(self):
        self.closed += 1


class FakeModels:
    """``resolve_orchestration_model``: the request's selected model, then the default model."""

    def __init__(self):
        self.selected = FakeModel("gpt-selected")
        self.default = FakeModel("gpt-default")
        self.unavailable = set()
        self.calls = []

    def __call__(self, settings, user_id=None, seeds=None, identity_context=None):
        which = "selected" if isinstance(seeds, dict) and seeds.get("model") else "default"
        self.calls.append({"which": which, "seeds": copy.deepcopy(seeds), "user_id": user_id, "identity": identity_context})
        if which in self.unavailable:
            raise FakeModelError(which)
        return self.selected if which == "selected" else self.default

    @property
    def requests(self):
        return self.selected.requests + self.default.requests


class FakeCheck:
    def __init__(self, blocked=False, categories=()):
        self.blocked = blocked
        self.categories = list(categories)


class FakeContentChecker:
    def __init__(self):
        self.calls = []
        self.block = False
        self.error = None

    def __call__(self, text, surface, user_id=None, settings=None):
        self.calls.append({"text": text, "surface": surface, "user_id": user_id})
        if self.error is not None:
            raise self.error
        return FakeCheck(blocked=self.block, categories=["hate"] if self.block else [])


def fake_attach_chat_check(document, check):
    document["content_check"] = {
        "blocked": bool(getattr(check, "blocked", False)),
        "categories": list(getattr(check, "categories", [])),
    }
    return document


class Recorder:
    """A callable that records its calls and raises queued errors first."""

    def __init__(self, result=None):
        self.calls = []
        self.errors = []
        self.result = result

    def __call__(self, *args, **kwargs):
        self.calls.append({"args": copy.deepcopy(args), "kwargs": copy.deepcopy(kwargs)})
        if self.errors:
            raise self.errors.pop(0)
        return self.result


class FakeNotifications:
    """Both notification helpers. Each idempotency key stores one notice, like the real helpers."""

    def __init__(self):
        self.chat_calls = []
        self.notice_calls = []
        self.stored = {}
        self.chat_errors = []
        self.notice_errors = []

    def chat_response(self, user_id, conversation_id, message_id, conversation_title=None, response_preview=None,
                      idempotency_key=None, strict=False):
        call = {
            "type": "chat_response",
            "user_id": user_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "conversation_title": conversation_title,
            "response_preview": response_preview,
            "idempotency_key": idempotency_key,
            "strict": strict,
        }
        self.chat_calls.append(call)
        if self.chat_errors:
            raise self.chat_errors.pop(0)
        self.stored.setdefault(idempotency_key, call)
        return {"id": f"notice-{len(self.stored)}"}

    def create(self, user_id=None, notification_type=None, title=None, message=None, link_url=None, metadata=None,
               idempotency_key=None, strict=False, **kwargs):
        call = {
            "type": notification_type,
            "user_id": user_id,
            "title": title,
            "message": message,
            "link_url": link_url,
            "metadata": copy.deepcopy(metadata),
            "idempotency_key": idempotency_key,
            "strict": strict,
        }
        self.notice_calls.append(call)
        if self.notice_errors:
            raise self.notice_errors.pop(0)
        self.stored.setdefault(idempotency_key, call)
        return {"id": f"notice-{len(self.stored)}"}

    def notices(self, notification_type=None):
        return [call for call in self.stored.values() if notification_type is None or call["type"] == notification_type]


class FakeLock:
    def __init__(self, available=True):
        self.available = available
        self.acquired = []
        self.released = []

    def acquire(self, name, seconds):
        self.acquired.append((name, seconds))
        return {"id": name, "seconds": seconds} if self.available else None

    def release(self, lock):
        self.released.append(lock)


class FakeHints:
    def __init__(self):
        self.queue = []
        self.signals = []

    def drain(self, limit):
        drained = self.queue[:limit]
        del self.queue[:limit]
        return drained

    def signal(self, user_id, run_id):
        self.signals.append((user_id, run_id))
        if (user_id, run_id) not in self.queue:
            self.queue.append((user_id, run_id))
        return True


class FakeGates:
    def __init__(self):
        self.workflows = True
        self.results = True
        self.calls = []

    def workflows_enabled(self, settings, user_roles=None):
        self.calls.append(("workflows", copy.deepcopy(user_roles)))
        return self.workflows

    def results_enabled(self, settings, user_roles=None):
        self.calls.append(("results", copy.deepcopy(user_roles)))
        return self.results


class FakeStreamProbe:
    def __init__(self):
        self.active = False
        self.calls = []

    def __call__(self, user_id, conversation_id, now):
        self.calls.append((user_id, conversation_id, now))
        return self.active


class FakeMonotonic:
    def __init__(self):
        self.value = 1000.0
        self.step = 0.0

    def __call__(self):
        self.value += self.step
        return self.value


WORKFLOW_NAME = "Daily digest"
REQUEST_TEXT = "Run my daily digest and tell me what it found."
SELECTED_MODEL = {"model": {"model_deployment": "gpt-selected"}, "reasoning_effort": "", "active_group_ids": []}
# Mirrors functions_workflow_result_followup.EXCERPT_BUDGET_STEPS; only steps below 48 KiB are used.
EXCERPT_STEPS = (48 * 1024, 24 * 1024, 12 * 1024, 6 * 1024)


def make_workflow(**overrides):
    workflow = {
        "id": WORKFLOW_ID,
        "user_id": USER,
        "name": WORKFLOW_NAME,
        "durable_execution": True,
        "definition_revision": "rev-1",
    }
    workflow.update(overrides)
    return workflow


def make_conversation(**overrides):
    conversation = {
        "id": CONVERSATION_ID,
        "user_id": USER,
        "title": "Planning chat",
        "chat_type": "personal",
        "last_updated": "2026-05-04T14:05:10.000000",
        "has_unread_assistant_response": False,
        "last_unread_assistant_message_id": None,
        "last_unread_assistant_at": None,
    }
    conversation.update(overrides)
    return conversation


def _thread(thread_id):
    return {"thread_id": thread_id, "previous_thread_id": None, "active_thread": True, "thread_attempt": 1}


def make_request_messages():
    return [
        {
            "id": USER_MESSAGE_ID,
            "conversation_id": CONVERSATION_ID,
            "role": "user",
            "content": REQUEST_TEXT,
            "timestamp": "2026-05-04T14:05:00.000000",
            "metadata": {"thread_info": _thread("thread-request")},
        },
        {
            "id": "message-assistant-1",
            "conversation_id": CONVERSATION_ID,
            "role": "assistant",
            "content": "I started Daily digest. I'll post the results here when the run finishes.",
            "timestamp": "2026-05-04T14:05:10.000000",
            "metadata": {"thread_info": _thread("thread-request")},
        },
    ]


def make_invocation(**overrides):
    invocation = {
        "version": 1,
        "source": "chat_orchestration",
        "conversation_id": CONVERSATION_ID,
        "user_message_id": USER_MESSAGE_ID,
        "orchestration_run_id": ORCHESTRATION_RUN_ID,
        "attempt_root_run_id": ATTEMPT_ROOT_RUN_ID,
        "step_id": STEP_ID,
        "requested_by": USER,
        "requested_at": REQUESTED_AT,
    }
    invocation.update(overrides)
    return invocation


def make_record(*, time_zone="America/New_York", model_selection=None, roles=("User",), deadline_at=None, **overrides):
    seed = build_chat_delivery_seed(
        time_zone=time_zone,
        model_selection=SELECTED_MODEL if model_selection is None else model_selection,
        requester_roles=list(roles),
        now=parse_iso(REQUESTED_AT),
    )
    record = finalize_chat_delivery_seed(seed, {"limits": {"deadline_at": deadline_at}} if deadline_at else None)
    record.update(overrides)
    return record


def make_run(*, status="completed", record=None, **overrides):
    run = {
        "id": RUN_ID,
        "user_id": USER,
        "workflow_id": WORKFLOW_ID,
        "workflow_name": WORKFLOW_NAME,
        "status": status,
        "trigger_source": "chat_orchestration",
        "definition_revision": "rev-1",
        "chat_invocation": make_invocation(),
        "chat_delivery": make_record() if record is None else record,
    }
    run.update(overrides)
    return run


def newest_message_handler(container, query, params, partition_key):
    require("ORDER BY c.timestamp DESC" in query and "TOP 1" in query, f"unexpected message query {query!r}")
    conversation_id = params.get("@conversation_id")
    require(partition_key == conversation_id, "the newest-message query must stay in the chat's partition")
    rows = [item for item in container.items.values() if item.get("conversation_id") == conversation_id]
    rows.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
    return [
        {
            "id": row["id"],
            "role": row.get("role"),
            "timestamp": row.get("timestamp"),
            "thread_info": (row.get("metadata") or {}).get("thread_info"),
        }
        for row in rows[:1]
    ]


def _at_or_before(value, moment):
    return isinstance(value, str) and value <= moment


def sweep_handler(container, query, params, partition_key):
    """A Python mirror of the sweep's WHERE clause, so the sweep can be driven end to end."""
    require("IS_DEFINED(c.chat_delivery)" in query, f"unexpected run query {query!r}")
    now = params["@now"]
    rows = []
    for item in container.items.values():
        record = item.get("chat_delivery")
        if not isinstance(record, dict):
            continue
        next_attempt = record.get("next_attempt_at")
        if next_attempt is not None and not _at_or_before(next_attempt, now):
            continue
        status = record.get("status")
        due = (
            status == params["@ready"]
            or (status == params["@delivering"] and _at_or_before(record.get("lease_expires_at"), now))
            or (
                status == params["@pending"]
                and (
                    _at_or_before(record.get("expires_at"), now)
                    or (item.get("status") in params["@terminal"] and item.get("_ts", 0) <= params["@grace_ts"])
                )
            )
        )
        if due:
            rows.append({"id": item["id"], "user_id": item["user_id"]})
    return rows[: params["@top"]]


@dataclass
class DeliveryWorld:
    services: object
    settings: dict
    clock: FakeClock
    runs: FakeContainer
    workflows: FakeContainer
    conversations: FakeContainer
    messages: FakeContainer
    runtime: FakeRuntime
    reader: FakeResultReader
    disclosure: FakeDisclosure
    prompts: FakePromptBuilder
    nonces: FakeNonces
    budget: FakeBudget
    models: FakeModels
    checker: FakeContentChecker
    notifications: FakeNotifications
    tokens: Recorder
    incidents: Recorder
    cache_bumps: Recorder
    identities: Recorder
    lock: FakeLock
    hints: FakeHints
    gates: FakeGates
    stream: FakeStreamProbe
    monotonic: FakeMonotonic
    unread_calls: list = field(default_factory=list)

    def run(self, run_id=RUN_ID):
        return self.runs.get(run_id)

    def record(self, run_id=RUN_ID):
        return (self.run(run_id) or {}).get("chat_delivery")

    def conversation(self):
        return self.conversations.get(CONVERSATION_ID)

    def delivery_messages(self):
        return sorted(
            (item for item in self.messages.items.values() if str(item["id"]).startswith("assistant_workflow_delivery_")),
            key=lambda item: item["timestamp"],
        )

    def set_record(self, run_id=RUN_ID, **changes):
        run = self.runs.items[run_id]
        record = dict(run["chat_delivery"])
        record.update(changes)
        run["chat_delivery"] = record
        self.runs.put(run)
        return record


def make_world(*, run=None, state="completed", version=5, control=True, settings=None):
    clock = FakeClock()
    world_settings = {"enable_workflows": True, "enable_chat_workflow_results": True} if settings is None else settings
    runtime = FakeRuntime()
    if control:
        runtime.set(state=state, version=version)
    unread_calls = []

    def mark_unread(container, conversation_id, user_id, message_id, planned_at, *, require_private=True,
                    skip_if_read_since=None):
        unread_calls.append({
            "conversation_id": conversation_id,
            "user_id": user_id,
            "message_id": message_id,
            "planned_at": planned_at,
            "require_private": require_private,
            "skip_if_read_since": skip_if_read_since,
        })
        return mark_conversation_unread_guarded(
            container, conversation_id, user_id, message_id, planned_at,
            require_private=require_private, skip_if_read_since=skip_if_read_since,
        )

    world = DeliveryWorld(
        services=None,
        settings=world_settings,
        clock=clock,
        runs=FakeContainer("runs", [make_run() if run is None else run], query_handler=sweep_handler, clock=clock),
        workflows=FakeContainer("workflows", [make_workflow()]),
        conversations=FakeContainer("conversations", [make_conversation()]),
        messages=FakeContainer("messages", make_request_messages(), query_handler=newest_message_handler),
        runtime=runtime,
        reader=FakeResultReader(),
        disclosure=FakeDisclosure(),
        prompts=FakePromptBuilder(),
        nonces=FakeNonces(),
        budget=FakeBudget(),
        models=FakeModels(),
        checker=FakeContentChecker(),
        notifications=FakeNotifications(),
        tokens=Recorder(),
        incidents=Recorder(),
        cache_bumps=Recorder(),
        identities=Recorder(result={"identity": "captured"}),
        lock=FakeLock(),
        hints=FakeHints(),
        gates=FakeGates(),
        stream=FakeStreamProbe(),
        monotonic=FakeMonotonic(),
        unread_calls=unread_calls,
    )
    world.services = WorkflowChatDeliveryServices(
        runs=world.runs,
        workflows=world.workflows,
        conversations=world.conversations,
        messages=world.messages,
        get_settings=lambda: dict(world.settings),
        runtime_store_factory=runtime.factory,
        runtime_conflict_error=FakeRuntimeConflict,
        runtime_unavailable_error=FakeRuntimeUnavailable,
        read_workflow_result=world.reader,
        result_unavailable_error=FakeResultUnavailable,
        workflow_result_context=fake_workflow_result_context,
        format_run_time=fake_format_run_time,
        format_disclosure=world.disclosure,
        build_result_messages=world.prompts,
        new_fence_nonce=world.nonces,
        excerpt_budget_steps=EXCERPT_STEPS,
        calculate_budget=world.budget,
        resolve_model=world.models,
        model_error=FakeModelError,
        capture_identity=world.identities,
        extract_text=fake_extract_text,
        check_content=world.checker,
        attach_chat_check=fake_attach_chat_check,
        record_incident=world.incidents,
        is_message_retracted=lambda message: bool(message.get("retracted")),
        create_chat_response_notification=world.notifications.chat_response,
        create_notification=world.notifications.create,
        log_token_usage=world.tokens,
        bump_cache_version=world.cache_bumps,
        mark_unread_guarded=mark_unread,
        is_conversation_private=conversation_is_private,
        is_user_workflows_enabled=world.gates.workflows_enabled,
        is_chat_workflow_results_enabled=world.gates.results_enabled,
        stream_activity_probe=world.stream,
        acquire_lock=world.lock.acquire,
        release_lock=world.lock.release,
        drain_hints=world.hints.drain,
        signal_delivery=world.hints.signal,
        clock=clock,
        compose_output_tokens=None,
        monotonic=world.monotonic,
    )
    return world
