# test_plugin_invocation_outcomes.py
"""
Functional regressions for explicit connector outcomes and plugin invocation logging.
Version: 0.261.365
Implemented in: 0.261.365

Real modules run in fresh processes with the existing offline bootstrap and mocked HTTP.
This isolates application imports, callbacks, execution contexts, and logging from other tests.
Application imports are deliberately deferred until the subprocess offline bootstrap is active.
"""

import asyncio
import importlib
import json
import logging
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock, patch

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _check(condition, message):
    if not condition:
        raise AssertionError(message)


def _run_probe(mode, optimized):
    completed = subprocess.run(
        [sys.executable, "-B", *(["-O"] if optimized else []), str(Path(__file__).resolve()), "--probe", mode],
        cwd=ROOT, text=True, capture_output=True, timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.parametrize("optimized", [False, True])
def test_openapi_declared_failures_are_recorded_without_changing_results(optimized):
    _run_probe("openapi", optimized)


@pytest.mark.parametrize("optimized", [False, True])
def test_sync_async_awaitable_outcomes_and_context_isolation(optimized):
    _run_probe("decorator", optimized)


def _openapi_probe(logger):
    import requests
    from route_backend_chats import _build_plugin_invocation_agent_citation
    from semantic_kernel_plugins.openapi_plugin import OpenApiPlugin
    from semantic_kernel_plugins.plugin_invocation_thoughts import format_plugin_invocation_thought

    spec = {
        "openapi": "3.0.0", "info": {"title": "Records", "version": "1"},
        "paths": {"/records/{record_id}": {"get": {
            "operationId": "lookupRecord",
            "parameters": [{"name": "record_id", "in": "path", "required": True, "schema": {"type": "string"}}],
            "responses": {"200": {"description": "OK"}},
        }}},
    }
    plugin = OpenApiPlugin(base_url="https://example.test", openapi_spec_content=spec)
    business_data = {"error": "business field", "status_code": 503, "success": False}
    for caller in (plugin.lookupRecord, lambda **kwargs: plugin.call_operation("lookupRecord", **kwargs)):
        for status in (400, 429, 502, 503):
            response = requests.Response()
            response.status_code = status
            response.url = "https://example.test/records/record-42"
            response._content = b'{"message":"Synthetic upstream unavailable"}'
            baseline = len(logger.invocations)
            with patch("requests.get", return_value=response) as get:
                result = caller(record_id="record-42")
            _check(get.call_count == 1, "outcome reporting must not retry an HTTP call")
            _check(type(result) is dict and result["status_code"] == status, "public error payload changed")
            _check(len(logger.invocations) == baseline + 1, "one call must record one completion")
            invocation = logger.invocations[-1]
            _check(invocation.result is result, "failure result must be retained")
            _check(invocation.success is False, "HTTP error was recorded as successful")
            _check(invocation.error_message == f"HTTP {status}", "failure reason missing")
            thought = format_plugin_invocation_thought(invocation)
            _check(thought["activity"]["state"] == "failed", "reasoning must reflect the recorded failure")
            citation = _build_plugin_invocation_agent_citation(invocation)
            _check(citation["success"] is False and citation["error_message"] == f"HTTP {status}",
                   "citation must carry the same outcome as logging and reasoning")
            _check(citation["function_arguments"]["record_id"] == "record-42"
                   and citation["function_result"]["status_code"] == status,
                   "citation lost arguments or returned error evidence")

        response = requests.Response()
        response.status_code = 200
        response.url = "https://example.test/records/record-42"
        response._content = json.dumps(business_data).encode()
        with patch("requests.get", return_value=response):
            result = caller(record_id="record-42")
        _check(result == business_data and logger.invocations[-1].success is True,
               "business JSON must not be reclassified by key names")

        response._content = b'not JSON'
        with patch("requests.get", return_value=response):
            result = caller(record_id="record-42")
        _check(result["error"] == "JSON parse error" and logger.invocations[-1].success is False,
               "JSON parse failure was recorded as successful")

        with patch("requests.get", side_effect=requests.exceptions.Timeout("Synthetic timeout")) as get:
            result = caller(record_id="record-42")
        _check(get.call_count == 1 and type(result) is dict, "transport failure must not raise or retry")
        _check(logger.invocations[-1].success is False, "transport failure was recorded as successful")

        with patch("requests.get", side_effect=ValueError("Synthetic connector failure")):
            result = caller(record_id="record-42")
        _check(result["exception_type"] == "ValueError" and logger.invocations[-1].success is False,
               "unexpected connector failure was recorded as successful")

    # Direct helper callers keep plain dictionaries, without requiring a logging scope.
    operation = spec["paths"]["/records/{record_id}"]["get"]
    with patch("requests.get", return_value=response):
        result = plugin._call_api_operation("lookupRecord", "/records/{record_id}", "get", operation, record_id="record-42")
    _check(type(result) is dict, "direct OpenAPI helper compatibility changed")


def _decorator_probe(module, logger, loop):
    report = module.report_plugin_invocation_failure
    decorate = module.plugin_function_logger("Example")
    payload = {"error": "domain data", "status_code": 503, "success": False}

    @decorate
    def normal():
        return payload

    @decorate
    def sync_failure():
        report("HTTP 502")
        return payload

    @decorate
    def sensitive_failure():
        report("Authorization: Bearer SyntheticSecret")
        report("second report must not replace the cause")
        return payload

    @decorate
    async def async_failure():
        await asyncio.sleep(0)
        report("HTTP 429")
        return payload

    @decorate
    def awaitable_failure():
        async def finish():
            await asyncio.sleep(0)
            report("HTTP 504")
            return payload
        return finish()

    @decorate
    def before_await_failure():
        report("HTTP 409")

        async def finish():
            await asyncio.sleep(0)
            return payload
        return finish()

    @decorate
    async def concurrent_success():
        await asyncio.sleep(0)
        return payload

    @decorate
    def nested_success():
        sync_failure()
        return payload

    @decorate
    def throws():
        raise ValueError("Synthetic failure")

    @decorate
    async def cancelled():
        raise asyncio.CancelledError()

    @decorate
    def awaitable_throws():
        async def finish():
            raise ValueError("Synthetic deferred failure")
        return finish()

    starts, completions = [], []
    logger.register_start_callback("outcome-user:None", starts.append)
    logger.register_callback("outcome-user:None", completions.append)
    try:
        normal_result = normal()
        _check(normal_result is payload and logger.invocations[-1].success is True, "unmarked return changed")
        failed_result = sync_failure()
        _check(failed_result is payload and logger.invocations[-1].success is False, "sync outcome not recorded")
        sensitive_failure()
        safe_error = logger.invocations[-1].error_message
        _check("SyntheticSecret" not in safe_error and "REDACTED" in safe_error,
               "declared failure reason was not sanitized or its first report was lost")
        nested_result = nested_success()
        _check(nested_result is payload and logger.invocations[-1].success is True, "nested failure leaked into parent")

        async def run():
            for call in (async_failure, awaitable_failure, before_await_failure):
                before = len(logger.invocations)
                result = await call()
                _check(result is payload and len(logger.invocations) == before + 1, "async result or count changed")
                _check(logger.invocations[-1].success is False, "async failure was recorded as success")
            before = len(logger.invocations)
            await asyncio.gather(async_failure(), asyncio.to_thread(normal), awaitable_failure(), concurrent_success())
            outcomes = {item.function_name: item.success for item in logger.invocations[before:]}
            _check(outcomes == {"async_failure": False, "normal": True,
                                "awaitable_failure": False, "concurrent_success": True},
                   "concurrent failure leaked across invocations")
            try:
                await cancelled()
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("cancellation was swallowed")
            _check(logger.invocations[-1].success is False, "cancellation must still fail")
            before = len(logger.invocations)
            try:
                await awaitable_throws()
            except ValueError:
                pass
            else:
                raise AssertionError("deferred exception was swallowed")
            _check(len(logger.invocations) == before + 1 and logger.invocations[-1].success is False,
                   "deferred exception lost or duplicated completion")

        loop.run_until_complete(run())
        try:
            throws()
        except ValueError:
            pass
        else:
            raise AssertionError("plugin exception was swallowed")
        _check(logger.invocations[-1].result is None and logger.invocations[-1].success is False,
               "exception result changed")
        report("outside any invocation")
        normal()
        _check(logger.invocations[-1].success is True, "outcome scope leaked after completion")
        _check(len(starts) == len(completions), "completion callbacks were lost or duplicated")
        _check({item.invocation_id for item in starts} == {item.invocation_id for item in completions},
               "start/completion identity changed")
    finally:
        logger.deregister_callbacks("outcome-user:None")


def _probe(mode):
    sys.path.insert(0, str(ROOT / "functional_tests"))
    sys.path.insert(0, str(ROOT / "application" / "single_app"))
    from test_support.offline_bootstrap import offline_app_imports

    with offline_app_imports() as offline:
        module = importlib.import_module("semantic_kernel_plugins.plugin_invocation_logger")
        logger = module.PluginInvocationLogger()
        logger.logger = Mock(spec=logging.Logger)
        with patch.object(module, "_plugin_logger", logger), \
                patch.object(module, "get_current_user_id", return_value="outcome-user"), \
                patch.object(module, "log_event"):
            if mode == "openapi":
                _openapi_probe(logger)
            else:
                _decorator_probe(module, logger, offline.loop)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--probe":
        _probe(sys.argv[2])
    else:
        raise SystemExit(pytest.main([__file__, "-q"]))
