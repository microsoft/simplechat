#!/usr/bin/env python3
# test_chat_semantic_kernel_return_contract.py
"""
Functional test for chat Semantic Kernel return contract cleanup.
Version: 0.250.118
Implemented in: 0.250.118

This test ensures the nested chat route run_sk_call helper keeps explicit
return behavior for Semantic Kernel result shapes, including empty async
generators that intentionally resolve to None.
"""

import ast
import asyncio
import logging
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "application" / "single_app" / "config.py"
CHAT_ROUTE_FILE = ROOT / "application" / "single_app" / "route_backend_chats.py"
IMPLEMENTED_VERSION = "0.250.118"


def read_text(path):
    """Return UTF-8 source text for simple contract assertions."""
    return path.read_text(encoding="utf-8")


def read_current_version():
    """Return the application version declared in config.py."""
    for line in read_text(CONFIG_FILE).splitlines():
        stripped_line = line.strip()
        if stripped_line.startswith('VERSION = '):
            return stripped_line.split('"')[1]
    raise AssertionError("Expected config.py to define VERSION")


def parse_version(version):
    """Return a comparable tuple for SimpleChat version strings."""
    return tuple(int(part) for part in version.split('.'))


def find_run_sk_call_node():
    """Return the nested run_sk_call async function from the chat route AST."""
    parsed_route = ast.parse(read_text(CHAT_ROUTE_FILE), filename=str(CHAT_ROUTE_FILE))
    for node in ast.walk(parsed_route):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == 'run_sk_call':
            return node
    raise AssertionError("Expected route_backend_chats.py to define nested run_sk_call")


def find_async_generator_branch(run_sk_call_node):
    """Return the branch that handles async generator results."""
    for node in ast.walk(run_sk_call_node):
        if not isinstance(node, ast.If):
            continue
        if ast.unparse(node.test) == 'isinstance(result, types.AsyncGeneratorType)':
            return node
    raise AssertionError("Expected run_sk_call to handle types.AsyncGeneratorType")


def load_run_sk_call():
    """Compile the nested helper as an isolated async function."""
    run_sk_call_node = find_run_sk_call_node()
    module = ast.Module(body=[run_sk_call_node], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        'asyncio': asyncio,
        'logging': logging,
        'log_event': lambda *args, **kwargs: None,
        'types': types,
    }
    exec(compile(module, str(CHAT_ROUTE_FILE), 'exec'), namespace)
    return namespace['run_sk_call']


def test_async_generator_branch_has_explicit_none_return():
    """Verify the async-generator branch has an explicit terminal return None."""
    print("Testing explicit async-generator return contract...")

    current_version = read_current_version()
    run_sk_call_node = find_run_sk_call_node()
    async_generator_branch = find_async_generator_branch(run_sk_call_node)

    explicit_none_returns = [
        statement for statement in async_generator_branch.body
        if (
            isinstance(statement, ast.Return)
            and isinstance(statement.value, ast.Constant)
            and statement.value.value is None
        )
    ]

    assert parse_version(current_version) >= parse_version(IMPLEMENTED_VERSION), (
        f"Expected config.py version at least {IMPLEMENTED_VERSION} for the return-contract cleanup."
    )
    assert explicit_none_returns, (
        "Expected run_sk_call to return None explicitly when an async generator yields no values."
    )

    print("Explicit async-generator return contract checks passed")


def test_run_sk_call_result_shapes():
    """Verify run_sk_call preserves direct, coroutine, and async-generator results."""
    print("Testing Semantic Kernel helper result shapes...")

    run_sk_call = load_run_sk_call()

    async def coroutine_value():
        return "awaited-value"

    async def async_generator_value():
        yield "first-yielded-value"
        yield "second-yielded-value"

    async def empty_async_generator():
        if False:
            yield "unreachable-value"

    assert asyncio.run(run_sk_call(lambda: "direct-value")) == "direct-value"
    assert asyncio.run(run_sk_call(coroutine_value)) == "awaited-value"
    assert asyncio.run(run_sk_call(async_generator_value)) == "first-yielded-value"
    assert asyncio.run(run_sk_call(empty_async_generator)) is None

    print("Semantic Kernel helper result shape checks passed")


if __name__ == "__main__":
    tests = [
        test_async_generator_branch_has_explicit_none_return,
        test_run_sk_call_result_shapes,
    ]

    for test in tests:
        test()

    print(f"Passed {len(tests)}/{len(tests)} chat Semantic Kernel return contract tests")