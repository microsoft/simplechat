#!/usr/bin/env python3
"""
Functional test for Cosmos container startup conflict recovery.
Version: 0.250.060
Implemented in: 0.250.060

This test ensures local Docker gunicorn workers recover when concurrent startup
creates the same Cosmos container between the SDK's read and create calls.
"""

# test_cosmos_container_conflict_recovery.py
import ast
import os
import sys
import traceback
import types


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(REPO_ROOT, 'application', 'single_app', 'config.py')


class FakeCosmosResourceExistsError(Exception):
    """Stand-in for the Azure Cosmos conflict exception."""


class FakeContainer:
    def __init__(self, container_id):
        self.container_id = container_id
        self.read_count = 0

    def read(self):
        self.read_count += 1
        return {'id': self.container_id}


class FakeDatabase:
    def __init__(self):
        self.requested_container_ids = []
        self.containers = {}

    def get_container_client(self, container_id):
        self.requested_container_ids.append(container_id)
        container = FakeContainer(container_id)
        self.containers[container_id] = container
        return container


def load_conflict_recovery_function(original_create, database):
    with open(CONFIG_PATH, 'r', encoding='utf-8') as config_file:
        config_tree = ast.parse(config_file.read(), filename=CONFIG_PATH)

    helper_node = next(
        node for node in config_tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == '_create_container_if_not_exists_with_conflict_recovery'
    )

    module = ast.Module(body=[helper_node], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        '_cosmos_create_container_if_not_exists': original_create,
        'cosmos_database': database,
        'exceptions': types.SimpleNamespace(
            CosmosResourceExistsError=FakeCosmosResourceExistsError,
        ),
    }
    exec(compile(module, CONFIG_PATH, 'exec'), namespace)
    return namespace['_create_container_if_not_exists_with_conflict_recovery']


def test_conflict_recovery_returns_existing_container():
    print('Testing Cosmos container conflict recovery...')
    database = FakeDatabase()

    def original_create(*args, **kwargs):
        raise FakeCosmosResourceExistsError('container already exists')

    create_container = load_conflict_recovery_function(original_create, database)

    container = create_container(id='document_access_index', partition_key='ignored')

    assert container.container_id == 'document_access_index'
    assert container.read_count == 1
    assert database.requested_container_ids == ['document_access_index']
    print('Test passed!')
    return True


def test_conflict_without_container_id_is_not_swallowed():
    print('Testing Cosmos conflict without container id is re-raised...')
    database = FakeDatabase()

    def original_create(*args, **kwargs):
        raise FakeCosmosResourceExistsError('container already exists')

    create_container = load_conflict_recovery_function(original_create, database)

    try:
        create_container(partition_key='ignored')
    except FakeCosmosResourceExistsError:
        print('Test passed!')
        return True

    raise AssertionError('Expected conflict to be re-raised when container id is missing')


if __name__ == '__main__':
    tests = [
        test_conflict_recovery_returns_existing_container,
        test_conflict_without_container_id_is_not_swallowed,
    ]
    results = []

    for test in tests:
        try:
            results.append(test())
        except Exception as ex:
            print(f'Test failed: {ex}')
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f'Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)
