#!/usr/bin/env python3
# test_session_store_merge.py
"""
Functional test for the merging server-side session store.
Version: 0.261.302
Implemented in: 0.261.302

Flask-Session 0.8 writes the whole stored session at the end of every request, so a slow
request that loaded the session before another request saved a change used to write its stale
copy over that change. In production a ~5 second V2 bootstrap request erased a pending
Microsoft 365 sign-in that a concurrent request had just saved, and the sign-in callback then
failed with m365_auth_state_invalid.

This test ensures that saves write only the keys a request changed, merged into the latest
stored copy (atomically for Redis), that unchanged sessions only refresh their expiry, that
sessions deleted mid-request are not recreated, and that app.py installs the merging interface
after every Session(app).
"""

import ast
import sys
import tempfile
from datetime import timedelta
from importlib.metadata import version as package_version
from pathlib import Path
from unittest.mock import patch

import flask
import redis
import werkzeug
from flask import Flask
from flask_session import Session
from redis.exceptions import WatchError

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import functions_session_store as store  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


class FakePipeline:
    """The subset of a redis-py transaction pipeline the session store uses."""

    def __init__(self, client):
        self.client = client
        self.reset()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.reset()

    def reset(self):
        self.watched = None
        self.watched_version = None
        self.commands = []

    def watch(self, name):
        self.watched = name
        self.watched_version = self.client.versions.get(name, 0)

    def get(self, name):
        return self.client.get(name)

    def multi(self):
        self.commands = []

    def set(self, name, value, ex=None):
        self.commands.append(("set", name, value, ex))

    def delete(self, name):
        self.commands.append(("delete", name))

    def execute(self):
        self.client.transactions += 1
        if self.client.before_execute is not None:
            self.client.before_execute()
        if self.watched is not None and self.client.versions.get(self.watched, 0) != self.watched_version:
            self.reset()
            raise WatchError("Watched variable changed.")
        for command in self.commands:
            if command[0] == "set":
                self.client.set(command[1], command[2], ex=command[3])
            else:
                self.client.delete(command[1])
        self.reset()
        return []


class FakeRedis(redis.Redis):
    """An in-memory Redis that records versions so WATCH conflicts can be simulated."""

    def __init__(self):
        self.data = {}
        self.ttls = {}
        self.versions = {}
        self.expire_calls = []
        self.transactions = 0
        self.before_execute = None

    def __del__(self):
        pass

    def close(self):
        pass

    def _bump(self, name):
        self.versions[name] = self.versions.get(name, 0) + 1

    def get(self, name):
        return self.data.get(name)

    def set(self, name, value, ex=None, **_kwargs):
        self.data[name] = value
        self.ttls[name] = ex
        self._bump(name)
        return True

    def expire(self, name, time, **_kwargs):
        self.expire_calls.append((name, time))
        if name not in self.data:
            return False
        self.ttls[name] = time
        return True

    def delete(self, *names):
        removed = 0
        for name in names:
            if name in self.data:
                del self.data[name]
                self.ttls.pop(name, None)
                self._bump(name)
                removed += 1
        return removed

    def pipeline(self, transaction=True, shard_hint=None):
        return FakePipeline(self)


def build_redis_app(client=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY="test-secret",
        SESSION_TYPE="redis",
        SESSION_REDIS=client or FakeRedis(),
        PERMANENT_SESSION_LIFETIME=timedelta(hours=2),
    )
    Session(app)
    store.install_merging_session_interface(app)
    return app


def build_filesystem_app(directory):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY="test-secret",
        SESSION_TYPE="filesystem",
        SESSION_FILE_DIR=directory,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=2),
    )
    Session(app)
    store.install_merging_session_interface(app)
    return app


def open_request(app, sid=None):
    """Open the session as a request carrying this session cookie would."""
    headers = {"Cookie": f"{app.config['SESSION_COOKIE_NAME']}={sid}"} if sid else {}
    with app.test_request_context("/", headers=headers):
        return app.session_interface.open_session(app, flask.request)


def save(app, session):
    response = app.response_class()
    with app.test_request_context("/"):
        app.session_interface.save_session(app, session, response)
    return response


def stored(app, sid):
    interface = app.session_interface
    store_id = interface._get_store_id(sid)
    if isinstance(interface, store.MergingRedisSessionInterface):
        raw = interface.client.get(store_id)
        return None if raw is None else interface.serializer.decode(raw)
    return interface.cache.get(store_id)


def create_session(app, **values):
    session = open_request(app)
    session.update(values)
    save(app, session)
    return session.sid


def test_install_replaces_both_backends():
    """Session(app) is followed by the merging interface for Redis and the filesystem."""
    print("🔍 Testing merging interface installation...")
    assert_app_version_at_least("0.261.302")
    client = FakeRedis()
    redis_app = build_redis_app(client)
    assert isinstance(redis_app.session_interface, store.MergingRedisSessionInterface)
    assert redis_app.session_interface.client is client
    assert store.install_merging_session_interface(redis_app) is redis_app.session_interface
    with tempfile.TemporaryDirectory() as directory:
        file_app = build_filesystem_app(directory)
        assert isinstance(file_app.session_interface, store.MergingFileSystemSessionInterface)
    print("✅ Merging interfaces installed.")
    return True


def test_slow_request_does_not_erase_concurrent_write():
    """The production failure: a bootstrap that started first must not erase the sign-in flow."""
    print("🔍 Testing a slow request against a concurrent write...")
    app = build_redis_app()
    sid = create_session(app, user={"oid": "user-a"}, last_activity_epoch=100)

    bootstrap = open_request(app, sid)
    connect = open_request(app, sid)
    connect["m365_chat_auth_flow"] = {"state": "m365-chat-abc", "expires_at": "later"}
    save(app, connect)

    # The bootstrap read the session before the connect call saved and finishes after it.
    save(app, bootstrap)
    after_unchanged = stored(app, sid)
    assert after_unchanged["m365_chat_auth_flow"]["state"] == "m365-chat-abc"

    bootstrap_writer = open_request(app, sid)
    stale = open_request(app, sid)
    bootstrap_writer["m365_chat_auth_flow"] = {"state": "m365-chat-def", "expires_at": "later"}
    save(app, bootstrap_writer)
    stale["last_activity_epoch"] = 200
    save(app, stale)
    merged = stored(app, sid)
    assert merged["m365_chat_auth_flow"]["state"] == "m365-chat-def"
    assert merged["last_activity_epoch"] == 200
    assert merged["user"] == {"oid": "user-a"}
    print("✅ Concurrent write survived.")
    return True


def test_unchanged_request_only_refreshes_expiry():
    print("🔍 Testing that an unchanged session is not rewritten...")
    client = FakeRedis()
    app = build_redis_app(client)
    sid = create_session(app, user={"oid": "user-a"})
    store_id = app.session_interface._get_store_id(sid)
    version_before = client.versions[store_id]

    session = open_request(app, sid)
    assert session.get("user") == {"oid": "user-a"}
    save(app, session)

    assert client.versions[store_id] == version_before
    assert client.expire_calls[-1] == (store_id, 7200)
    print("✅ Only the expiry was refreshed.")
    return True


def test_session_deleted_mid_request_is_not_recreated():
    print("🔍 Testing that a signed-out session stays signed out...")
    app = build_redis_app()
    sid = create_session(app, user={"oid": "user-a"}, token_cache="cache")

    long_request = open_request(app, sid)
    idle_request = open_request(app, sid)
    logout = open_request(app, sid)
    logout.clear()
    save(app, logout)
    assert stored(app, sid) is None

    long_request["last_activity_epoch"] = 300
    save(app, long_request)
    save(app, idle_request)
    assert stored(app, sid) is None
    print("✅ Deleted session was not recreated.")
    return True


def test_removals_keep_concurrent_additions():
    print("🔍 Testing removals alongside concurrent additions...")
    app = build_redis_app()
    sid = create_session(app, user={"oid": "user-a"}, m365_workflow_oauth_binding="binding")

    callback = open_request(app, sid)
    other = open_request(app, sid)
    other["m365_csrf_token"] = "csrf"
    save(app, other)
    callback.pop("m365_workflow_oauth_binding")
    save(app, callback)

    result = stored(app, sid)
    assert "m365_workflow_oauth_binding" not in result
    assert result["m365_csrf_token"] == "csrf"
    assert result["user"] == {"oid": "user-a"}
    print("✅ Removal applied without dropping the concurrent key.")
    return True


def test_same_key_is_last_writer_wins():
    app = build_redis_app()
    sid = create_session(app, user={"oid": "user-a"}, token_cache="v0")
    first = open_request(app, sid)
    second = open_request(app, sid)
    first["token_cache"] = "v1"
    second["token_cache"] = "v2"
    save(app, first)
    save(app, second)
    assert stored(app, sid)["token_cache"] == "v2"
    return True


def test_nested_in_place_change_is_saved():
    """A nested value changed in place is still detected and written."""
    app = build_redis_app()
    sid = create_session(app, user={"oid": "user-a", "roles": ["User"]})
    session = open_request(app, sid)
    session["user"]["roles"].append("Admin")
    save(app, session)
    assert stored(app, sid)["user"]["roles"] == ["User", "Admin"]
    return True


def test_watch_conflict_retries_and_merges():
    print("🔍 Testing optimistic-lock retry...")
    client = FakeRedis()
    app = build_redis_app(client)
    sid = create_session(app, user={"oid": "user-a"})
    store_id = app.session_interface._get_store_id(sid)
    session = open_request(app, sid)
    session["a"] = 1

    def concurrent_write():
        client.before_execute = None
        current = app.session_interface.serializer.decode(client.get(store_id))
        current["b"] = 2
        client.set(store_id, app.session_interface.serializer.encode(current), ex=7200)

    client.before_execute = concurrent_write
    save(app, session)

    result = stored(app, sid)
    assert result["a"] == 1 and result["b"] == 2
    assert client.transactions == 2
    print("✅ Retried once and merged both writes.")
    return True


def test_contention_falls_back_to_lock_free_merge():
    client = FakeRedis()
    app = build_redis_app(client)
    sid = create_session(app, user={"oid": "user-a"})
    store_id = app.session_interface._get_store_id(sid)
    session = open_request(app, sid)
    session["mine"] = "kept"
    counter = {"writes": 0}

    def always_conflict():
        counter["writes"] += 1
        current = app.session_interface.serializer.decode(client.get(store_id))
        current[f"other_{counter['writes']}"] = counter["writes"]
        client.set(store_id, app.session_interface.serializer.encode(current), ex=7200)

    client.before_execute = always_conflict
    save(app, session)
    client.before_execute = None

    result = stored(app, sid)
    assert counter["writes"] == store.MERGE_ATTEMPTS
    assert result["mine"] == "kept"
    assert all(result[f"other_{index}"] == index for index in range(1, store.MERGE_ATTEMPTS + 1))
    return True


def test_new_and_cleared_sessions_are_written_whole():
    app = build_redis_app()
    sid = create_session(app, user={"oid": "user-a"}, stale="value")
    replacing = open_request(app, sid)
    concurrent = open_request(app, sid)
    concurrent["added_meanwhile"] = True
    save(app, concurrent)
    replacing.clear()
    replacing["user"] = {"oid": "user-a", "fresh": True}
    save(app, replacing)
    result = stored(app, sid)
    assert result["user"] == {"oid": "user-a", "fresh": True}
    assert "stale" not in result and "added_meanwhile" not in result
    return True


def test_unreadable_stored_session_is_written_whole():
    client = FakeRedis()
    app = build_redis_app(client)
    sid = create_session(app, user={"oid": "user-a"})
    store_id = app.session_interface._get_store_id(sid)
    session = open_request(app, sid)
    session["after"] = True
    client.data[store_id] = b"\x00not-a-session"
    save(app, session)
    result = stored(app, sid)
    assert result["user"] == {"oid": "user-a"} and result["after"] is True
    return True


def test_filesystem_backend_merges_and_respects_deletion():
    print("🔍 Testing the filesystem backend...")
    with tempfile.TemporaryDirectory() as directory:
        app = build_filesystem_app(directory)
        sid = create_session(app, user={"oid": "user-a"})

        slow = open_request(app, sid)
        fast = open_request(app, sid)
        fast["m365_chat_auth_flow"] = {"state": "m365-chat-xyz"}
        save(app, fast)
        slow["last_activity_epoch"] = 5
        save(app, slow)
        result = stored(app, sid)
        assert result["m365_chat_auth_flow"] == {"state": "m365-chat-xyz"}
        assert result["last_activity_epoch"] == 5

        late = open_request(app, sid)
        logout = open_request(app, sid)
        logout.clear()
        save(app, logout)
        late["after_logout"] = True
        save(app, late)
        assert stored(app, sid) is None
    print("✅ Filesystem backend merged and stayed signed out.")
    return True


def _flask_requests_round_trip():
    app = build_redis_app()

    @app.route("/set/<key>/<value>")
    def set_value(key, value):
        flask.session[key] = value
        return "ok"

    @app.route("/pop/<key>")
    def pop_value(key):
        flask.session.pop(key, None)
        return "ok"

    @app.route("/read")
    def read_values():
        return flask.jsonify({key: value for key, value in flask.session.items() if key != "_permanent"})

    client = app.test_client()
    assert client.get("/set/user/alice").status_code == 200
    assert client.get("/set/flow/one").status_code == 200
    assert client.get("/pop/flow").status_code == 200
    assert client.get("/read").get_json() == {"user": "alice"}
    with client.session_transaction() as session:
        session["transaction"] = "yes"
    assert client.get("/read").get_json() == {"user": "alice", "transaction": "yes"}
    return True


def test_flask_requests_round_trip():
    """Ordinary requests and the test client's session_transaction still work."""
    # Flask 2.x test clients read werkzeug.__version__, which Werkzeug 3 no longer defines.
    with patch.object(werkzeug, "__version__", package_version("werkzeug"), create=True):
        return _flask_requests_round_trip()


def test_app_installs_merging_interface_after_every_session_init():
    source = (APP_DIR / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    def is_call(statement, name):
        return (
            isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Name) and statement.value.func.id == name
        )

    session_inits = 0
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        for index, statement in enumerate(body):
            if is_call(statement, "Session"):
                session_inits += 1
                assert index + 1 < len(body) and is_call(body[index + 1], "install_merging_session_interface"), (
                    f"Session(app) on line {statement.lineno} is not followed by install_merging_session_interface(app)."
                )
    assert session_inits >= 2
    assert "from functions_session_store import install_merging_session_interface" in source
    return True


if __name__ == "__main__":
    tests = [
        test_install_replaces_both_backends,
        test_slow_request_does_not_erase_concurrent_write,
        test_unchanged_request_only_refreshes_expiry,
        test_session_deleted_mid_request_is_not_recreated,
        test_removals_keep_concurrent_additions,
        test_same_key_is_last_writer_wins,
        test_nested_in_place_change_is_saved,
        test_watch_conflict_retries_and_merges,
        test_contention_falls_back_to_lock_free_merge,
        test_new_and_cleared_sessions_are_written_whole,
        test_unreadable_stored_session_is_written_whole,
        test_filesystem_backend_merges_and_respects_deletion,
        test_flask_requests_round_trip,
        test_app_installs_merging_interface_after_every_session_init,
    ]
    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        try:
            results.append(test() is not False)
        except Exception as exc:
            import traceback
            print(f"❌ {test.__name__} failed: {exc}")
            traceback.print_exc()
            results.append(False)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
