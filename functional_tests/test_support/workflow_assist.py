# workflow_assist.py
"""
Shared fixtures for the AI workflow assistant tests (Phase 3b).
Version: 0.261.208
Implemented in: 0.261.208

A personal V2 workflow as the editor holds it, the editor options, a recording limiter, a scripted
model and the service bundle ``run_workflow_assist`` takes, so each test states only what it
changes. Nothing here reaches Azure or a model; the model is always scripted.
"""

import copy
import json

import functions_workflow_assist as core
from functions_workflow_assist_editor import normalize_workflow_definition, strip_undefined


USER_ID = "user-0001-abcdef"
OTHER_USER_ID = "user-0002-ghijkl"
WORKFLOW_ID = "workflow-0001-saved"
REVISION = "rev-0001-abcdef"
TIME_ZONE = "America/New_York"
RUN_AS_ID = "runas-0003-mnopqr"

COLLECT_ID = "task-collect-0001"
REVIEW_ID = "task-review-0002"

AGENT = {
    "id": "agent-mailer-0001", "name": "mailer", "display_name": "Mail agent", "is_global": False,
    "is_group": False, "group_id": None, "loop_eligible": True,
}
GLOBAL_AGENT = {
    "id": "agent-global-0002", "name": "researcher", "display_name": "Researcher", "is_global": True,
    "is_group": False, "group_id": None, "loop_eligible": True,
}
MODEL = {
    "endpoint_id": "endpoint-global-0001", "model_id": "gpt-4o", "label": "GPT-4o", "provider": "aoai",
    "loop_eligible": True,
}
OPTIONS = {
    "agents": [AGENT, GLOBAL_AGENT],
    "models": [MODEL],
    "default_model": {"label": "Default model", "valid": True, "loop_eligible": True},
    "max_tasks": 100,
    "schedule": {"min_interval_seconds": 300},
}

CHECKLIST = {"kind": "document", "id": "doc-checklist-0001", "label": "Security checklist.pdf", "scope": {"kind": "personal"}}
INCIDENT = {"kind": "document", "id": "doc-incident-0002", "label": "Incident report.docx", "scope": {"kind": "personal"}}
BUDGET = {"kind": "document", "id": "doc-budget-0005", "label": "Q3 budget.xlsx", "scope": {"kind": "personal"}}
TEAM_GUIDE = {
    "kind": "document", "id": "doc-guide-0003", "label": "Team guide.md",
    "scope": {"kind": "group", "id": "group-0004-stuvwx", "name": "Team"},
}
DOCUMENT_LABELS = {
    CHECKLIST["id"]: CHECKLIST["label"],
    INCIDENT["id"]: INCIDENT["label"],
    BUDGET["id"]: BUDGET["label"],
    TEAM_GUIDE["id"]: TEAM_GUIDE["label"],
}
EXCERPT_TEXT = "Checklist: encrypt data at rest, log every access, review quarterly. "


def json_copy(value):
    return json.loads(json.dumps(value))


def task(task_id, name, instructions, order, **extra):
    record = {
        "id": task_id, "type": "instructions", "name": name, "instructions": instructions, "order": order,
        "runner": {"type": "inherit"},
    }
    record.update(extra)
    return record


def stored_workflow(**fields):
    """A saved personal workflow as ``read_base`` returns it: the record the editor loads."""
    record = {
        "id": WORKFLOW_ID,
        "user_id": USER_ID,
        "definition_version": 2,
        "definition_revision": REVISION,
        "name": "Document review",
        "description": "Review new documents.",
        "runner_type": "model",
        "model_endpoint_id": "",
        "model_id": "",
        "m365_run_as_user_id": "",
        "chat_capabilities_enabled": False,
        "trigger_type": "manual",
        "schedule": {"unit": "minutes", "value": 15},
        "is_enabled": True,
        "error_handling": {"strategy": "halt", "retry_count": 0},
        "durable_execution": True,
        "task_prompt": "Collect the new documents.",
        "tasks": [
            task(COLLECT_ID, "Collect", "Collect the new documents.", 1, reference_ids=[]),
            task(REVIEW_ID, "Review", "Review each new document and list any problems.", 2),
        ],
        "reference_inputs": [],
        "created_at": "2026-09-01T12:00:00+00:00",
        "modified_at": "2026-09-02T12:00:00+00:00",
    }
    record.update(copy.deepcopy(fields))
    return record


def editor_draft(stored):
    """The draft the V2 editor holds for a stored workflow (``normalizeWorkflowDefinition``)."""
    return json_copy(strip_undefined(normalize_workflow_definition(copy.deepcopy(stored))))


def new_draft(**fields):
    """A new personal draft with the two review tasks, as the editor holds it before a first save."""
    draft = editor_draft(stored_workflow())
    for field in ("id", "user_id", "definition_revision", "created_at", "modified_at", "task_prompt"):
        draft.pop(field, None)
    draft.update(copy.deepcopy(fields))
    return draft


def base_for(stored):
    return {"workflow_id": stored["id"], "definition_revision": stored["definition_revision"]}


def request_body(draft=None, *, stored=None, **fields):
    """A valid request body. With ``stored`` the draft edits that saved workflow; otherwise it is new."""
    if draft is None:
        draft = editor_draft(stored) if stored is not None else new_draft()
    body = {
        "submission_id": "submission-0001",
        "base": base_for(stored) if stored is not None else None,
        "instruction": "Rename the workflow to Nightly review.",
        "conversation": [],
        "focus": None,
        "time_zone": TIME_ZONE,
        "draft": draft,
        "references": [],
    }
    body.update(copy.deepcopy(fields))
    return body


def reply(outcome="changed", text="Done.", operations=None, email_tasks=None, **extra):
    """A model reply as the JSON text the model returns."""
    payload = {"outcome": outcome, "reply": text}
    if operations is not None:
        payload["operations"] = operations
    if email_tasks is not None:
        payload["email_tasks"] = email_tasks
    payload.update(extra)
    return json.dumps(payload)


class FakeClock:
    """A monotonic clock that moves only when told to, or by ``tick`` on every read."""

    def __init__(self, start=1000.0, tick=0.0):
        self.now = start
        self.tick = tick

    def __call__(self):
        value = self.now
        self.now += self.tick
        return value

    def advance(self, seconds):
        self.now += seconds


class FakeLimiter:
    """Records every acquire and release; can refuse or fail on either."""

    def __init__(self, acquire_error=None, release_error=None):
        self.events = []
        self.acquire_error = acquire_error
        self.release_error = release_error

    def acquire(self, user_id):
        self.events.append(("acquire", user_id))
        if self.acquire_error is not None:
            raise self.acquire_error
        return "lease-1"

    def release(self, lease, *, refund=False):
        self.events.append(("release", lease, refund))
        if self.release_error is not None:
            raise self.release_error


class ScriptedModel:
    """Answers each call with the next scripted reply: a string, ``(content, finish_reason)``, or an exception."""

    def __init__(self, *replies, on_call=None):
        self.replies = list(replies)
        self.calls = []
        self.timeouts = []
        self.on_call = on_call

    def __call__(self, messages, timeout):
        self.calls.append(copy.deepcopy(messages))
        self.timeouts.append(timeout)
        if self.on_call is not None:
            self.on_call(len(self.calls))
        if not self.replies:
            raise AssertionError("The model was called more times than the test scripted.")
        answer = self.replies.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, tuple):
            return answer
        return answer, "stop"

    def envelope(self, call=0):
        """The JSON document the model received as its user message on ``call``."""
        return json.loads(self.calls[call][1]["content"])

    def text(self):
        """Every message the model received, as one string."""
        return "\n".join(message["content"] for messages in self.calls for message in messages)


def resolved_document(reference):
    """What ``resolve_scope_references`` returns for a readable document reference."""
    scope = reference.get("scope") or {}
    scope_id = scope.get("id") or (USER_ID if scope.get("kind") == "personal" else None)
    return {
        "kind": "document",
        "id": reference["id"],
        "label": DOCUMENT_LABELS.get(reference["id"], "Document"),
        "scope": {"kind": scope.get("kind"), "id": scope_id, "name": scope.get("name") or "Personal"},
    }


class Recorder:
    """The injected services' calls, by service name."""

    def __init__(self):
        self.calls = []

    def record(self, name, *args):
        self.calls.append((name, copy.deepcopy(args)))

    def named(self, name):
        return [args for call_name, args in self.calls if call_name == name]


def services(model=None, *, stored=None, limiter=None, options=None, dry_run=None, excerpts=None,
             resolve=None, agent_email_capable=None, m365_connected=None, clock=None, logs=None,
             recorder=None, read_base=None):
    """The assistant's services over fakes. Every argument replaces one default."""
    recorder = recorder if recorder is not None else Recorder()
    logs = logs if logs is not None else []

    def default_read_base(user_id, workflow_id):
        recorder.record("read_base", user_id, workflow_id)
        if stored is not None and stored.get("id") == workflow_id:
            return copy.deepcopy(stored)
        return None

    def default_resolve(user_id, references):
        recorder.record("resolve_references", user_id, references)
        return [resolved_document(reference) for reference in references]

    def load_options(user_id):
        recorder.record("load_options", user_id)
        return copy.deepcopy(OPTIONS if options is None else options)

    def load_excerpt(user_id, identity):
        recorder.record("load_excerpt", user_id, identity)
        texts = excerpts if excerpts is not None else {}
        if callable(texts):
            return texts(identity)
        return texts.get(identity[2], EXCERPT_TEXT)

    def default_dry_run(user_id, payload):
        recorder.record("dry_run", user_id, payload)
        return {"ok": True, "workflow": copy.deepcopy(payload), "errors": []}

    def recorded_dry_run(user_id, payload):
        recorder.record("dry_run", user_id, payload)
        return dry_run(user_id, payload)

    def log(message, extra, level):
        logs.append((message, copy.deepcopy(extra), level))

    bundle = core.WorkflowAssistServices(
        limiter=limiter if limiter is not None else FakeLimiter(),
        read_base=read_base or default_read_base,
        resolve_references=resolve or default_resolve,
        load_options=load_options,
        load_excerpt=load_excerpt,
        call_model=model if model is not None else ScriptedModel(),
        dry_run=recorded_dry_run if dry_run is not None else default_dry_run,
        agent_email_capable=agent_email_capable,
        m365_connected=m365_connected,
        log=log,
        clock=clock if clock is not None else FakeClock(),
    )
    bundle.recorder = recorder
    bundle.logs = logs
    return bundle


def run(body, bundle, user_id=USER_ID):
    """``run_workflow_assist`` for the default user."""
    return core.run_workflow_assist(copy.deepcopy(body), user_id=user_id, services=bundle)


def refusal(body, bundle, user_id=USER_ID):
    """The ``WorkflowAssistError`` a request is refused with; fails when it is answered."""
    try:
        core.run_workflow_assist(copy.deepcopy(body), user_id=user_id, services=bundle)
    except core.WorkflowAssistError as exc:
        return exc
    raise AssertionError("The request was answered, but the test expected it to be refused.")


def finished_log(bundle):
    """The single content-free record a request logs when it finishes."""
    records = [extra for message, extra, _level in bundle.logs if message == "[WorkflowAssist] Assist request finished"]
    # An explicit check, not ``assert``: this helper is not assert-rewritten, so ``-O`` would drop one.
    if len(records) != 1:
        raise AssertionError(f"expected one finished record, saw {len(records)}")
    return records[0]


def task_by_id(workflow, task_id):
    return next(item for item in workflow["tasks"] if item["id"] == task_id)


FLOW_FIXTURE = "workflow_flow_authoring.json"


def flow_stored():
    """3a's v3 flow fixture as a saved workflow of the default user."""
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "fixtures" / FLOW_FIXTURE
    stored = copy.deepcopy(json.loads(path.read_text(encoding="utf-8"))["initial"])
    stored["user_id"] = USER_ID
    return stored


def strings_in(value):
    """Every key and string value in a decoded JSON document."""
    found = set()
    stack = [value]
    while stack:
        node = stack.pop()
        if isinstance(node, str):
            found.add(node)
        elif isinstance(node, dict):
            found.update(node)
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return found
