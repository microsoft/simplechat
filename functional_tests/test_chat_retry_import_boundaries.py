# test_chat_retry_import_boundaries.py
"""Retry metadata storage and bootstrap import regressions.

Version: 0.261.320
Implemented in: 0.261.320

Real modules run in fresh normal/optimized processes with networking blocked.
Storage success and exhausted conflicts must preserve the caller's exception.
"""

import ast
from pathlib import Path

import pytest

from test_orchestration_result_imports import APP_PROBE, run_probe


APP = Path(__file__).resolve().parents[1] / 'application' / 'single_app'
EARLY_PROBE = r'''
import builtins
from copy import deepcopy
import importlib
import socket
import sys
from unittest.mock import patch

sys.path[:0] = sys.argv[1:3]
real_import = builtins.__import__
forbidden = {'config', 'functions_settings', 'functions_chat_content_review', 'functions_orchestration_context'}

def guarded_import(name, *args, **kwargs):
    if name in forbidden:
        raise AssertionError('Unexpected owner import: ' + name)
    return real_import(name, *args, **kwargs)

def no_network(*args, **kwargs):
    raise AssertionError('Unexpected network access')

with patch.object(builtins, '__import__', guarded_import), patch.object(socket.socket, 'connect', no_network):
    for name in sys.argv[3:]:
        importlib.import_module(name)
    from azure.cosmos.exceptions import CosmosAccessConditionFailedError
    from functions_chat_message_metadata import patch_message_metadata
    from functions_chat_retry import ChatRetryError
    class Store:
        def __init__(self):
            self.fail = False
            self.writes = 0
            self.body = {'id': 'question', 'conversation_id': 'chat', '_etag': '1',
                         'metadata': {'response_attempt': {'state': 'completed'}, 'thread_info': {'thread_attempt': 2}}}
        def read_item(self, **kwargs):
            return deepcopy(self.body)
        def replace_item(self, **kwargs):
            self.writes += 1
            if self.fail:
                raise CosmosAccessConditionFailedError(status_code=412)
            self.body = deepcopy(kwargs['body'])
            return self.body
    store = Store()
    message = {'id': 'question', 'conversation_id': 'chat', 'metadata': {
        'thread_info': {'active_thread': False}, 'response_attempt': {'state': 'prepared'}}}
    result = patch_message_metadata(store, message, conflict_error=lambda: ChatRetryError('Retry changed'))
    if result['metadata']['response_attempt']['state'] != 'completed' or result['metadata']['thread_info'] != {
        'thread_attempt': 2, 'active_thread': False} or store.writes != 1:
        raise AssertionError('Metadata write replaced authoritative state or disappeared')
    store.fail = True
    try:
        patch_message_metadata(store, message, conflict_error=lambda: ChatRetryError('Retry changed'))
    except ChatRetryError as error:
        if error.public_message != 'Retry changed' or store.writes != 4:
            raise AssertionError('Conflict contract changed')
    else:
        raise AssertionError('Exhausted storage conflicts returned success')
print('PASS: owner-free imports and explicit storage failure')
'''


@pytest.mark.parametrize('optimized', [False, True])
@pytest.mark.parametrize('order', [
    ('functions_chat_retry', 'functions_chat_message_metadata'),
    ('functions_chat_message_metadata', 'functions_chat_retry'),
])
def test_retry_storage_cold_imports_and_conflicts(order, optimized):
    run_probe(EARLY_PROBE, order, optimized)


@pytest.mark.parametrize('optimized', [False, True])
@pytest.mark.parametrize('order', [
    ('functions_chat_retry', 'functions_orchestration_context', 'app', 'background_tasks'),
    ('functions_orchestration_context', 'functions_chat_retry', 'app', 'background_tasks'),
    ('app', 'functions_chat_retry', 'background_tasks'),
    ('background_tasks', 'functions_chat_retry', 'functions_orchestration_context'),
])
def test_retry_and_context_real_web_scheduler_bootstrap(order, optimized):
    run_probe(APP_PROBE, order, optimized)


def test_retry_transitive_imports_remain_owner_free_including_local_imports():
    pending = ['functions_chat_retry', 'functions_chat_message_metadata']
    visited = set()
    forbidden = {'config', 'functions_settings', 'functions_chat_content_review', 'functions_orchestration_context'}
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        tree = ast.parse((APP / f'{name}.py').read_text(encoding='utf-8'))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or '')
        assert not forbidden.intersection(imports), (name, imports)
        pending.extend(module for module in imports if (APP / f'{module}.py').is_file())
