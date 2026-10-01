# workflow_ask_ai.py
"""
Browser stubs for the workflow editor's Ask AI tab (Phase 3c).
Version: 0.261.211
Implemented in: 0.261.211
Refs: microsoft/simplechat#1548

`POST /api/user/workflows/assist` is answered inside the page, never by a live model. A normal
answer comes from 3b's real pipeline (`run_workflow_assist`) over the request the browser sent,
with a scripted model and the fixture's own records, so its candidate, change list, warnings and
documents are what the server would send for that draft. A refusal is the real
`WorkflowAssistError` payload. Both are serialized the way the route does it: strict JSON with
sorted keys, `Cache-Control: no-store, private`, and `Retry-After` when the error carries one.

`POST /api/workflows/draft-instructions` is answered with fixed instructions, in the route's shape.

A handler never raises: a problem is recorded in `unexpected` and answered with a 500, because a
raise inside a Playwright route handler would leave the request hanging.
"""

import copy
import json
import sys
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError

ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT / "application" / "single_app", ROOT / "functional_tests"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

# The application and functional-test helpers are importable only after the path setup above.
import functions_workflow_assist as core  # noqa: E402
from test_support import workflow_assist as wa  # noqa: E402


ASSIST_ROUTE = "**/api/user/workflows/assist"
DRAFT_INSTRUCTIONS_ROUTE = "**/api/workflows/draft-instructions"


def _fulfill(route, status, payload, headers=None):
    route.fulfill(
        status=status,
        body=json.dumps(payload, allow_nan=False, sort_keys=True) + "\n",
        content_type="application/json",
        headers={"Cache-Control": "no-store, private", **(headers or {})},
    )


def _failure(exc, settings):
    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else {}
    return exc.status, exc.payload(settings), headers


class AssistStub:
    """Answers each assist request with the next queued answer, optionally holding the response.

    An answer is a callable taking the raw request body and returning ``(status, payload, headers)``.
    Build them with ``pipeline``, ``changed``, ``said``, ``refused``, ``canned`` or ``custom``.
    """

    def __init__(self, *, user_id, record_error, options, read_base, resolve, settings=None):
        self.user_id = user_id
        self.record_error = record_error
        self.options = options
        self.read_base = read_base
        self.resolve = resolve
        self.settings = settings if settings is not None else {}
        self.bodies = []
        self.headers = []
        self.answers = []
        self.models = []
        self.hold = 0
        self.held = []
        self.unexpected = []

    # -- answers -------------------------------------------------------------------------------

    def queue(self, *answers):
        self.answers.extend(answers)
        return self

    def pipeline(self, *replies, limiter=None):
        """3b's pipeline over the sent request, with ``replies`` as the model's scripted answers.

        A reply is the model's text, or a callable that gets the parsed request and returns that
        text, for answers that name the request's own `task_N` handles.
        """

        def answer(raw):
            try:
                body = core.parse_assist_body(raw)
            except core.WorkflowAssistError as exc:
                # The route answers a body it can't read before the run, without Retry-After.
                return exc.status, exc.payload(self.settings), {}
            request = json.loads(raw.decode("utf-8"))
            model = wa.ScriptedModel(*(reply(request) if callable(reply) else reply for reply in replies))
            self.models.append(model)
            services = wa.services(
                model, options=self.options(), resolve=self.resolve, read_base=self.read_base,
                limiter=limiter,
            )
            try:
                return 200, core.run_workflow_assist(body, user_id=self.user_id, services=services), {}
            except core.WorkflowAssistError as exc:
                return _failure(exc, self.settings)

        return answer

    def changed(self, *operations, text="Done."):
        """A ``changed`` answer. An operation may be a callable that gets the parsed request."""
        return self.pipeline(lambda body: wa.reply(
            "changed", text, [operation(body) if callable(operation) else operation for operation in operations],
        ))

    def said(self, outcome, text):
        return self.pipeline(wa.reply(outcome, text))

    def refused(self, code, message=None, retry_after=None):
        """A refusal the pipeline raises before or around the model, as the route answers it."""
        exc = core.WorkflowAssistError(code, message, retry_after=retry_after)
        return lambda _raw: _failure(exc, self.settings)

    @staticmethod
    def canned(status, payload, headers=None):
        return lambda _raw: (status, copy.deepcopy(payload), dict(headers or {}))

    @staticmethod
    def custom(build):
        """``build(body)`` gets the parsed request and returns ``(status, payload, headers)``."""
        return lambda raw: build(json.loads(raw.decode("utf-8")))

    # -- the route -----------------------------------------------------------------------------

    def handle(self, route):
        request = route.request
        if request.method != "POST":
            self.unexpected.append(f"{request.method} {request.url}")
            self._send(route, 405, {"error": "Method not allowed."})
            return
        headers = request.headers
        self.headers.append(dict(headers))
        if "application/json" not in headers.get("content-type", ""):
            self.unexpected.append(f"assist request without a JSON body: {headers.get('content-type')!r}")
        raw = request.post_data_buffer or b""
        try:
            self.bodies.append(json.loads(raw.decode("utf-8")))
        except (UnicodeDecodeError, ValueError):
            self.bodies.append(None)
            self.unexpected.append("assist request body was not JSON")
        if not self.answers:
            self.unexpected.append("an assist request arrived with no answer queued")
            self._send(route, 500, core.WorkflowAssistError("assistant_failed").payload())
            return
        answer = self.answers.pop(0)
        try:
            status, payload, reply_headers = answer(raw)
        except Exception as exc:  # A raise here would leave the browser waiting forever.
            self.unexpected.append(f"the assist stub failed: {type(exc).__name__}: {exc}")
            status, payload, reply_headers = 500, core.WorkflowAssistError("assistant_failed").payload(), {}
        if self.hold:
            self.hold -= 1
            if status >= 400:
                self.record_error(request.url, status)
            self.held.append((route, status, payload, reply_headers))
            return
        self._send(route, status, payload, reply_headers)

    def _send(self, route, status, payload, headers=None):
        if status >= 400:
            self.record_error(route.request.url, status)
        _fulfill(route, status, payload, headers)

    def release(self):
        """Answer every held request. One the browser cancelled is gone, and that is fine."""
        held, self.held = self.held, []
        for route, status, payload, headers in held:
            try:
                _fulfill(route, status, payload, headers)
            except PlaywrightError:
                pass

    def wait_for_requests(self, page, count, timeout_ms=10000):
        waited = 0
        while len(self.bodies) < count:
            if waited >= timeout_ms:
                raise AssertionError(f"expected {count} assist requests, saw {len(self.bodies)}")
            page.wait_for_timeout(50)
            waited += 50
        return self.bodies[count - 1]

    def assert_clean(self):
        assert not self.unexpected, self.unexpected
        assert not self.answers, f"{len(self.answers)} queued assist answer(s) were never requested"
        assert not self.held and not self.hold, "an assist response was left held"


class DraftInstructionsStub:
    """Answers the draft-instructions route with the next queued instructions, or an error."""

    def __init__(self, *, record_error):
        self.record_error = record_error
        self.bodies = []
        self.answers = []
        self.unexpected = []

    def queue(self, instructions=None, *, status=200, error=None):
        self.answers.append((status, {"success": True, "instructions": instructions} if status == 200 else {"error": error}))
        return self

    def handle(self, route):
        request = route.request
        try:
            self.bodies.append(request.post_data_json)
        except (ValueError, PlaywrightError):
            self.bodies.append(None)
            self.unexpected.append("draft-instructions body was not JSON")
        if request.method != "POST" or not self.answers:
            self.unexpected.append(f"unexpected {request.method} {request.url}")
            status, payload = 500, {"error": "Failed to draft workflow instructions."}
        else:
            status, payload = self.answers.pop(0)
        if status >= 400:
            self.record_error(request.url, status)
        route.fulfill(status=status, json=payload)

    def assert_clean(self):
        assert not self.unexpected, self.unexpected
        assert not self.answers, "a queued draft-instructions answer was never requested"
