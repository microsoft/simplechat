# test_appinsights_streaming_context.py
"""
Functional regressions for instrumented Flask streaming cleanup.
Version: 0.261.365
Implemented in: 0.261.365

Exercise the real Flask/OpenTelemetry lifecycle offline in fresh processes.
The old Azure Monitor distribution leaves a single-use context token in the
request environment, so Flask 3.1 streaming teardown tries to detach it twice.
No Azure exporter, cloud application bootstrap, or model is needed to reproduce
the failure. Explicit probe checks also run under optimized Python.
"""

import json
import logging
import os
import queue
import socket
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest
from flask import (
    Flask,
    Response,
    copy_current_request_context,
    has_request_context,
    request,
    session,
    stream_with_context,
)
from flask_executor import Executor
from opentelemetry import trace
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from werkzeug.test import Client


SCENARIOS = (
    "plain",
    "raw",
    "complete",
    "early_close",
    "request_error",
    "generator_error",
    "thread",
    "executor",
    "repeated",
    "concurrent",
    "reattach",
)
FIRST_EVENT = b"data: first\n\n"
LAST_EVENT = b"data: done\n\n"


def _require(condition, message):
    """Probe checks must survive python -O, including in child processes."""
    if not condition:
        raise AssertionError(message)


class _TelemetryCapture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


def _run_probe(scenario):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    app = Flask("offline-stream-cleanup")
    app.config.update(
        SECRET_KEY="offline-test-only",
        EXECUTOR_TYPE="thread",
        EXECUTOR_MAX_WORKERS=2,
    )
    capture = _TelemetryCapture()
    loggers = [
        logging.getLogger("opentelemetry.context"),
        logging.getLogger("opentelemetry.instrumentation.flask"),
    ]
    original_levels = [logger.level for logger in loggers]
    executor = None
    instrumented = False
    threads = []
    futures = []
    worker_observations = []
    worker_errors = []
    observation_lock = threading.Lock()
    stream_closed = []
    concurrent_gate = threading.Barrier(4) if scenario == "concurrent" else None

    def no_network(*args, **kwargs):
        raise AssertionError("Telemetry regression probes must not use the network.")

    def record_worker():
        observation = (
            has_request_context(),
            request.args["identity"],
            session["identity"],
        )
        with observation_lock:
            worker_observations.append(observation)

    def chunks():
        identity = request.args["identity"]
        _require(session["identity"] == identity, "Stream lost its session.")
        try:
            if concurrent_gate is not None:
                concurrent_gate.wait(timeout=10)
            yield FIRST_EVENT
            _require(request.args["identity"] == identity, "Stream changed requests.")
            if scenario == "generator_error":
                raise RuntimeError("synthetic generator failure")
            yield LAST_EVENT
        finally:
            with observation_lock:
                stream_closed.append(identity)

    def view():
        identity = request.args["identity"]
        session["identity"] = identity
        if scenario == "request_error":
            raise RuntimeError("synthetic request failure")
        if scenario == "plain":
            return Response(b"plain")
        if scenario == "raw":
            return Response(iter((FIRST_EVENT, LAST_EVENT)), mimetype="text/event-stream")
        if scenario in {"thread", "executor"}:
            events = queue.Queue()

            @copy_current_request_context
            def worker():
                try:
                    record_worker()
                    events.put(FIRST_EVENT)
                    events.put(LAST_EVENT)
                except Exception as error:
                    with observation_lock:
                        worker_errors.append(error)
                finally:
                    events.put(None)

            if scenario == "executor":
                futures.append(executor.submit(worker))
            else:
                thread = threading.Thread(target=worker, daemon=True)
                threads.append(thread)
                thread.start()

            def consume():
                try:
                    while True:
                        event = events.get(timeout=10)
                        if event is None:
                            break
                        _require(session["identity"] == identity, "Consumer lost its session.")
                        yield event
                finally:
                    with observation_lock:
                        stream_closed.append(identity)

            return Response(stream_with_context(consume()), mimetype="text/event-stream")
        return Response(stream_with_context(chunks()), mimetype="text/event-stream")

    app.add_url_rule("/stream", view_func=view)

    def perform_request(identity, early_close=False):
        before = trace.get_current_span().get_span_context()
        client = Client(app, Response)
        response = client.get(f"/stream?identity={identity}", buffered=False)
        try:
            if scenario == "request_error":
                body = response.get_data()
                _require(response.status_code == 500, "Request error was hidden.")
                _require(b"Internal Server Error" in body, "Error response was replaced.")
            elif early_close:
                body = next(iter(response.response))
                _require(body == FIRST_EVENT, f"Unexpected first event: {body!r}")
            elif scenario == "generator_error":
                received = []
                try:
                    for event in response.response:
                        received.append(event)
                except RuntimeError as error:
                    _require(str(error) == "synthetic generator failure", str(error))
                else:
                    raise AssertionError("Generator error was swallowed.")
                _require(received == [FIRST_EVENT], f"Unexpected events: {received!r}")
            else:
                body = response.get_data()
                expected = b"plain" if scenario == "plain" else FIRST_EVENT + LAST_EVENT
                _require(body == expected, f"Response changed: {body!r}")
            if scenario != "request_error":
                _require(response.status_code == 200, f"Unexpected status: {response.status_code}")
        finally:
            response.close()
        after = trace.get_current_span().get_span_context()
        _require(after == before, "Request span leaked into the caller's context.")
        _require(not has_request_context(), "Flask request context leaked after close.")

    with patch.object(socket.socket, "connect", no_network), patch.object(
        socket, "getaddrinfo", no_network
    ):
        try:
            for logger in loggers:
                logger.addHandler(capture)
                logger.setLevel(logging.DEBUG)
            FlaskInstrumentor().instrument_app(app, tracer_provider=provider)
            instrumented = True
            if scenario == "executor":
                executor = Executor(app)

            request_count = 1
            if scenario == "concurrent":
                request_count = 4
                with ThreadPoolExecutor(max_workers=4) as pool:
                    requests = [
                        pool.submit(perform_request, f"request-{index}")
                        for index in range(request_count)
                    ]
                    for result in requests:
                        result.result(timeout=20)
            elif scenario == "repeated":
                request_count = 4
                for index in range(request_count):
                    perform_request(f"request-{index}")
            elif scenario == "reattach":
                request_count = 2
                perform_request("detached", early_close=True)
                perform_request("reattached")
            else:
                perform_request("request-0", early_close=scenario == "early_close")

            for thread in threads:
                thread.join(timeout=10)
                _require(not thread.is_alive(), "Background worker did not terminate.")
            for future in futures:
                future.result(timeout=10)
            _require(not worker_errors, f"Worker errors: {worker_errors!r}")
            if scenario in {"thread", "executor"}:
                _require(
                    worker_observations == [(True, "request-0", "request-0")],
                    f"Worker request/session context changed: {worker_observations!r}",
                )
            if scenario not in {"plain", "raw", "request_error"}:
                _require(len(stream_closed) == request_count, "A stream was not closed.")

            provider.force_flush()
            spans = exporter.get_finished_spans()
            _require(len(spans) == request_count, f"Expected {request_count} spans, got {len(spans)}.")
            span_ids = {span.context.span_id for span in spans}
            trace_ids = {span.context.trace_id for span in spans}
            _require(len(span_ids) == request_count, "Duplicate request spans.")
            _require(len(trace_ids) == request_count, "Independent requests shared a trace.")
            for span in spans:
                _require(span.kind == trace.SpanKind.SERVER, "Request instrumentation was disabled.")
                _require(span.end_time is not None, "Request span did not finish.")
                _require(span.name == "GET /stream", f"Unexpected span: {span.name}")
            if scenario == "request_error":
                _require(
                    spans[0].status.status_code == trace.StatusCode.ERROR,
                    "Request exception was not recorded in telemetry.",
                )
            cleanup_errors = [
                record.getMessage()
                for record in capture.records
                if record.levelno >= logging.ERROR
                or "detach" in record.getMessage().lower()
                or "cleanup failed" in record.getMessage().lower()
                or "error during request teardown" in record.getMessage().lower()
            ]
            _require(not cleanup_errors, f"Telemetry cleanup failed: {cleanup_errors!r}")
            return {"scenario": scenario, "requests": request_count, "spans": len(spans)}
        finally:
            for thread in threads:
                thread.join(timeout=10)
            if executor is not None:
                executor.shutdown(wait=True)
            if instrumented:
                FlaskInstrumentor().uninstrument_app(app)
            provider.shutdown()
            for logger, level in zip(loggers, original_levels):
                logger.removeHandler(capture)
                logger.setLevel(level)


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_instrumented_flask_streaming_context(scenario):
    """Use process isolation so SDK singleton state cannot mask lifecycle failures."""
    environment = os.environ.copy()
    environment.pop("APPLICATIONINSIGHTS_CONNECTION_STRING", None)
    command = [sys.executable]
    if sys.flags.optimize:
        command.append("-O")
    command.extend(["-B", str(Path(__file__).resolve()), "--probe", scenario])
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        env=environment,
        timeout=60,
        check=False,
    )
    _require(result.returncode == 0, f"{scenario} probe failed:\n{result.stdout}\n{result.stderr}")
    evidence = json.loads(result.stdout)
    _require(evidence["scenario"] == scenario, f"Wrong probe result: {evidence!r}")
    _require(evidence["requests"] == evidence["spans"], f"Missing telemetry: {evidence!r}")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--probe" and sys.argv[2] in SCENARIOS:
        print(json.dumps(_run_probe(sys.argv[2])))
    else:
        raise SystemExit(pytest.main([__file__, "-q"]))
