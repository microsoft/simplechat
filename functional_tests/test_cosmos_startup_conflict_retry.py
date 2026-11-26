# test_cosmos_startup_conflict_retry.py
"""
Functional test for Cosmos container startup conflict recovery.
Version: 0.261.462
Implemented in: 0.261.462

This test ensures a Gunicorn worker retries a transient NotFound response
after another worker wins the create-container race.
"""

import ast
from pathlib import Path
from types import SimpleNamespace


CONFIG_PATH = (
    Path(__file__).resolve().parents[1]
    / "application"
    / "single_app"
    / "config.py"
)


def test_conflict_recovery_retries_transient_container_not_found(monkeypatch=None):
    tree = ast.parse(CONFIG_PATH.read_text(encoding="utf-8"))
    helper = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_create_container_if_not_exists_with_conflict_recovery"
    )

    class Conflict(Exception):
        pass

    class NotFound(Exception):
        pass

    create = lambda *args, **kwargs: (_ for _ in ()).throw(Conflict())
    reads = []

    class Container:
        def read(self):
            reads.append(1)
            if len(reads) < 3:
                raise NotFound()
            return {"id": "bitbucket_connections"}

    container = Container()
    sleeps = []
    namespace = {
        "_cosmos_create_container_if_not_exists": create,
        "exceptions": SimpleNamespace(
            CosmosResourceExistsError=Conflict,
            CosmosResourceNotFoundError=NotFound,
        ),
        "cosmos_database": SimpleNamespace(
            get_container_client=lambda container_id: container,
        ),
        "time": SimpleNamespace(sleep=sleeps.append),
    }
    exec(
        compile(ast.Module(body=[helper], type_ignores=[]), str(CONFIG_PATH), "exec"),
        namespace,
    )

    resolved = namespace["_create_container_if_not_exists_with_conflict_recovery"](
        id="bitbucket_connections"
    )
    assert resolved is container
    assert len(reads) == 3
    assert sleeps == [0.1, 0.2]


def test_conflict_recovery_rethrows_after_bounded_read_retries(monkeypatch=None):
    tree = ast.parse(CONFIG_PATH.read_text(encoding="utf-8"))
    helper = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_create_container_if_not_exists_with_conflict_recovery"
    )

    class Conflict(Exception):
        pass

    class NotFound(Exception):
        pass

    create = lambda *args, **kwargs: (_ for _ in ()).throw(Conflict())

    class Container:
        def read(self):
            raise NotFound()

    sleeps = []
    namespace = {
        "_cosmos_create_container_if_not_exists": create,
        "exceptions": SimpleNamespace(
            CosmosResourceExistsError=Conflict,
            CosmosResourceNotFoundError=NotFound,
        ),
        "cosmos_database": SimpleNamespace(
            get_container_client=lambda container_id: Container(),
        ),
        "time": SimpleNamespace(sleep=sleeps.append),
    }
    exec(
        compile(ast.Module(body=[helper], type_ignores=[]), str(CONFIG_PATH), "exec"),
        namespace,
    )

    try:
        namespace["_create_container_if_not_exists_with_conflict_recovery"](
            id="bitbucket_connections"
        )
    except NotFound:
        pass
    else:
        raise AssertionError("The final transient read failure must remain visible.")
    assert sleeps == [0.1, 0.2, 0.4, 0.8, 1.6, 2.0, 2.0]
