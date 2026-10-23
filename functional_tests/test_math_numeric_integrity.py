# test_math_numeric_integrity.py
"""
Functional tests for finite decimal arithmetic and numeric tool-result integrity.
Version: 0.261.380
Implemented in: 0.261.380

Real plugins, invocation logging, Semantic Kernel calls, reasoning and citations
run in fresh offline processes, with both normal and optimized Python.
"""

import asyncio
from decimal import Decimal, InvalidOperation, getcontext, localcontext
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


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("mode", ["arithmetic", "outcomes", "kernel"])
def test_numeric_integrity(mode, optimized):
    completed = subprocess.run(
        [sys.executable, "-B", *(["-O"] if optimized else []),
         str(Path(__file__).resolve()), "--probe", mode],
        cwd=ROOT, text=True, capture_output=True, timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def _expect_error(call, fragment):
    try:
        call()
    except ValueError as exc:
        _check(fragment.lower() in str(exc).lower(), f"Unexpected safe error: {exc}")
    else:
        raise AssertionError(f"Expected failure containing {fragment!r}")


def _arithmetic_probe(math_module, logger, loop):
    plugin = math_module.MathPlugin()
    exact_cases = [
        ("add", ("1e308", "1e308"), "2E+308"),
        ("subtract", ("-1e308", "1e308"), "-2E+308"),
        ("multiply", ("1e308", "2"), "2E+308"),
        ("divide", ("1e308", "0.1"), "1E+309"),
        ("power", ("1e308", "2"), "1E+616"),
        ("square_root", ("1e616",), "1E+308"),
        ("modulus", ("1e308", "3"), "1"),
        ("add", ("9007199254740992", "1"), "9007199254740993"),
        ("add", ("0.1", "0.2"), "0.3"),
        ("add", (0.1, 0.2), "0.3"),
        ("add", (100000, 100000), "200000"),
        ("subtract", (10, 4), "6"),
        ("multiply", (4, 5), "20"),
        ("divide", (1, 8), "0.125"),
        ("power", (2, -3), "0.125"),
        ("power", (-2, 3), "-8"),
        ("power", (0, 0), "1"),
        ("square_root", (4,), "2"),
        ("modulus", (-5, 3), "1"),
        ("modulus", (5, -3), "-1"),
        ("modulus", (-5, -3), "-2"),
        ("modulus", (6, -3), "0"),
        ("add", ("-0", "0"), "0"),
        ("add", (" 1.2500 ", ".75"), "2"),
        ("add", ("1e10000", "1e10000"), "2E+10000"),
        ("divide", ("1e-9999", "10"), "1E-10000"),
        ("power", ("1", "10000"), "1"),
        ("power", ("10", "-10000"), "1E-10000"),
        ("add", ("9" * 64, "0"), "9" * 64),
        ("add", ("1." + "0" * 1000, 0), "1"),
    ]
    for method, arguments, expected in exact_cases:
        result = getattr(plugin, method)(*arguments)
        _check(result == expected, f"{method}{arguments}: {result!r} != {expected!r}")
        _check(isinstance(result, str) and Decimal(result).is_finite(), "Result is not finite decimal text")
        serialized = json.dumps(logger.invocations[-1].to_safe_dict(), allow_nan=False)
        _check(expected in serialized, "Invocation lost the numeric result")
        _check(logger.invocations[-1].success is True, "Finite calculation was not successful")

    for method, arguments in [
        ("divide", (1, 3)),
        ("square_root", (2,)),
        ("power", (2, "0.5")),
        ("add", ("1e308", "1")),
        ("modulus", ("-1e-100", "1")),
    ]:
        result = getattr(plugin, method)(*arguments)
        numeric, qualifier = result.split(" ", 1)
        _check(Decimal(numeric).is_finite(), "Rounded calculation is not finite")
        _check(qualifier == "(approximate; rounded half-even to 64 significant digits)",
               "Rounded calculation lacks an explicit approximation qualifier")
    third = plugin.divide(1, 3)
    _check(third.startswith("0." + "3" * 64 + " "), "Division precision is not 64 digits")
    half_even_down = plugin.add("1." + "0" * 62 + "2", "5e-64")
    half_even_up = plugin.add("1." + "0" * 62 + "3", "5e-64")
    _check(half_even_down.startswith("1." + "0" * 62 + "2 "), "Even tie did not round down")
    _check(half_even_up.startswith("1." + "0" * 62 + "4 "), "Odd tie did not round up")

    errors = [
        (lambda: plugin.divide(1, 0), "divide by zero"),
        (lambda: plugin.modulus(1, 0), "divide by zero"),
        (lambda: plugin.square_root(-1), "negative number"),
        (lambda: plugin.power(-1, "0.5"), "integer exponent"),
        (lambda: plugin.power(0, -1), "negative exponent"),
        (lambda: plugin.power(2, 10001), "calculation limit"),
        (lambda: plugin.power(2, -10001), "calculation limit"),
        (lambda: plugin.add("1e10001", 0), "numeric range"),
        (lambda: plugin.add("1e-10001", 0), "numeric range"),
        (lambda: plugin.add("99e10000", 0), "numeric range"),
        (lambda: plugin.add("1e999999999999999999999999999999", 0), "numeric range"),
        (lambda: plugin.multiply("1e10000", 10), "numeric range"),
        (lambda: plugin.divide("1e-10000", 10), "numeric range"),
        (lambda: plugin.add("9" * 65, 0), "significant digits"),
        (lambda: plugin.add("1" * 1025, 0), "length"),
        (lambda: plugin.add(1 << 100000, 0), "length"),
    ]
    for invalid in [True, False, None, {}, [], "NaN", "sNaN", "Infinity", "-Infinity",
                    "1_000", "1,000", "", " ", "1e", "１２", float("nan"), float("inf"), -float("inf")]:
        errors.append((lambda value=invalid: plugin.add(value, 1), "finite decimal"))
    for call, fragment in errors:
        _expect_error(call, fragment)
        _check(logger.invocations[-1].success is False, "Invalid calculation was logged as successful")
        _check(logger.invocations[-1].result is None, "Invalid calculation retained a successful result")

    ambient = getcontext().copy()
    with localcontext() as context:
        context.prec = 2
        context.traps[InvalidOperation] = False
        original_flags = dict(context.flags)
        result = plugin.add("123456789", "1")
        _expect_error(lambda: plugin.add("1e999999999999999999999999999999", 0), "numeric range")
        _check(result == "123456790", "Ambient decimal context changed calculator precision")
        _check(context.prec == 2 and dict(context.flags) == original_flags,
               "Calculator mutated ambient precision or flags")
    _check(getcontext().prec == ambient.prec, "Ambient context leaked")

    async def concurrent():
        async def calculate(precision):
            with localcontext() as context:
                context.prec = precision
                await asyncio.sleep(0)
                result = plugin.divide("1", "3")
                _check(context.prec == precision, "Concurrent decimal contexts leaked")
                return result
        return await asyncio.gather(calculate(2), calculate(7))

    values = loop.run_until_complete(concurrent())
    _check(values == [third, third], "Concurrent calculator precision changed")
    recovered = plugin.add(100000, 100000)
    _check(recovered == "200000", "A failure prevented subsequent valid arithmetic")


def _outcomes_probe(module, logger, loop):
    decorate = module.plugin_function_logger("NumericProbe")
    starts, completions = [], []
    logger.register_start_callback("numeric-probe:None", starts.append)
    logger.register_callback("numeric-probe:None", completions.append)
    try:
        for invalid in [float("inf"), -float("inf"), float("nan"), Decimal("Infinity"),
                        Decimal("-Infinity"), Decimal("NaN"), Decimal("sNaN")]:
            shapes = [invalid, {"nested": [None, {"value": invalid}]}, (invalid,)]
            if not isinstance(invalid, Decimal) or not invalid.is_snan():
                shapes.extend([{invalid}, frozenset({invalid})])
            for value in shapes:
                for mode in ("sync", "async", "awaitable"):
                    @decorate
                    def sync():
                        return value

                    @decorate
                    async def asynchronous():
                        await asyncio.sleep(0)
                        return value

                    @decorate
                    def awaitable():
                        return asynchronous.__wrapped__()

                    call = sync if mode == "sync" else (
                        lambda function=asynchronous if mode == "async" else awaitable: loop.run_until_complete(function())
                    )
                    before = len(logger.invocations)
                    _expect_error(call, "non-finite numeric result")
                    _check(len(logger.invocations) == before + 1, "Invalid result duplicated completion")
                    invocation = logger.invocations[-1]
                    _check(invocation.success is False and invocation.result is None, "Invalid result reported success")
                    _check("non-finite" in invocation.error_message, "Invalid result lost the explicit error")

        business_data = {"success": False, "error": "Infinity", "status_code": 503,
                         "valid": [1, 0.25, Decimal("2.5"), "NaN", "Infinity", None]}

        @decorate
        def valid():
            return business_data

        @decorate
        def declared_error():
            module.report_plugin_invocation_failure("Synthetic connector error.")
            return {"success": False, "error": "domain data"}

        result = valid()
        _check(result is business_data and logger.invocations[-1].success is True, "Business data was reclassified")
        result = declared_error()
        _check(result["success"] is False and logger.invocations[-1].success is False,
               "Connector-declared failure changed")
        result = valid()
        _check(result is business_data and logger.invocations[-1].success is True, "Failure leaked into recovery")
        _check(len(starts) == len(completions), "Start/completion count mismatch")
        _check({item.invocation_id for item in starts} == {item.invocation_id for item in completions},
               "Invocation identities changed")
    finally:
        logger.deregister_callbacks("numeric-probe:None")


def _kernel_probe(math_module, module, logger, loop):
    from semantic_kernel import Kernel
    from semantic_kernel.contents import ChatHistory, FunctionCallContent, FunctionResultContent
    from semantic_kernel.functions import kernel_function
    from route_backend_chats import _build_plugin_invocation_agent_citation
    from functions_message_artifacts import build_agent_citation_artifact_documents
    from semantic_kernel_plugins.plugin_invocation_thoughts import format_plugin_invocation_thought

    class InvalidNumericPlugin:
        @kernel_function(name="invalid_number")
        @module.plugin_function_logger("InvalidNumericPlugin")
        def invalid_number(self) -> float:
            return float("inf")

    kernel = Kernel()
    kernel.add_plugin(math_module.MathPlugin(), plugin_name="math")
    kernel.add_plugin(InvalidNumericPlugin(), plugin_name="invalid")
    metadata = kernel.get_function("math", "Add").metadata
    _check(metadata.return_parameter.type_ == "str", "Math schema still advertises numeric output")
    _check("64 significant digits" in metadata.description and "approximate" in metadata.description,
           "Tool metadata does not explain precision")
    _check([parameter.name for parameter in metadata.parameters] == ["input", "amount"],
           "Existing tool arguments changed")

    history = ChatHistory()
    history.add_user_message("Calculate a large sum and continue after genuine tool failures.")
    calls = [
        ("large-sum", "math-Add", {"input": "1e308", "amount": "1e308"}, True, "2E+308"),
        ("domain-error", "math-Divide", {"input": "1", "amount": "0"}, False, "divide by zero"),
        ("invalid-output", "invalid-invalid_number", {}, False, "non-finite numeric result"),
        ("valid-followup", "math-Add", {"input": "100000", "amount": "100000"}, True, "200000"),
    ]
    for call_id, name, arguments, success, expected in calls:
        call = FunctionCallContent(id=call_id, name=name, arguments=json.dumps(arguments))
        before = len(logger.invocations)
        loop.run_until_complete(kernel.invoke_function_call(call, history))
        _check(len(logger.invocations) == before + 1, "SDK invocation lost or duplicated evidence")
        invocation = logger.invocations[-1]
        _check(invocation.success is success, "SDK and invocation outcome differ")
        results = [item for message in history.messages for item in message.items
                   if isinstance(item, FunctionResultContent) and item.id == call_id]
        _check(len(results) == 1, "SDK did not retain exactly one tool result for this call")
        json.dumps(results[0].to_dict(), allow_nan=False)
        model_value = str(results[0].result)
        _check(expected.lower() in model_value.lower(), "Model lost result or safe error")
        citation = _build_plugin_invocation_agent_citation(invocation)
        thought = format_plugin_invocation_thought(invocation)
        _check(citation["success"] is success, "Saved citation outcome differs from model")
        _check(thought["activity"]["state"] == ("completed" if success else "failed"),
               "Reasoning outcome differs from model")
        if success:
            _check(citation["function_result"] == expected, "Saved result differs from model")
            _check(citation["error_message"] is None, "Successful result retained a failure")
        else:
            _check(citation["function_result"] is None and citation["error_message"],
                   "Failed citation lost the explicit error")
        compact, documents = build_agent_citation_artifact_documents(
            conversation_id="numeric-conversation", assistant_message_id=f"assistant-{call_id}",
            agent_citations=[citation], created_timestamp="2026-10-23T00:00:00Z",
            user_info={"userId": "numeric-probe"},
        )
        json.dumps(compact, allow_nan=False)
        json.dumps(documents, allow_nan=False)
        stored = json.loads(documents[0]["content"])["citation"]
        _check(stored["success"] is success, "Stored artifact changed the outcome")
        if success:
            _check(stored["function_result"] == expected, "Stored artifact lost large numeric text")


def _probe(mode):
    sys.path.insert(0, str(ROOT / "functional_tests"))
    sys.path.insert(0, str(ROOT / "application" / "single_app"))
    from test_support.offline_bootstrap import offline_app_imports

    with offline_app_imports() as offline:
        module = importlib.import_module("semantic_kernel_plugins.plugin_invocation_logger")
        math_module = importlib.import_module("semantic_kernel_plugins.math_plugin")
        logger = module.PluginInvocationLogger()
        logger.logger = Mock(spec=logging.Logger)
        with patch.object(module, "_plugin_logger", logger), \
                patch.object(module, "get_current_user_id", return_value="numeric-probe"), \
                patch.object(module, "log_event"):
            if mode == "arithmetic":
                _arithmetic_probe(math_module, logger, offline.loop)
            elif mode == "outcomes":
                _outcomes_probe(module, logger, offline.loop)
            else:
                _kernel_probe(math_module, module, logger, offline.loop)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--probe":
        _probe(sys.argv[2])
    else:
        raise SystemExit(pytest.main([__file__, "-q"]))
