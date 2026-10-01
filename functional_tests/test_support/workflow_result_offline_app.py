# workflow_result_offline_app.py
"""
Offline application harness for the workflow-results-in-chat route tests.
Version: 0.261.214
Implemented in: 0.261.214

Boots the real application with only storage, the chat model and the network
faked, so a test can drive the real JSON, SSE, history, export and collaboration
routes against a personal workflow run built through the real result contract.
Use it only from a fresh process: the application's imports and settings are
process-wide.
"""

from contextlib import ExitStack, contextmanager
from copy import deepcopy
import os
from pathlib import Path
import re
import shutil
import socket
import time
from types import SimpleNamespace
from unittest.mock import patch
import uuid

from azure.cosmos.exceptions import CosmosResourceNotFoundError

from test_support.m365 import Query
from test_support.offline_bootstrap import OfflineContainer, OfflineCosmos, OfflineDatabase


TESTS = Path(__file__).resolve().parents[1]
# Only AND-joined equality filters are honoured; anything else in a query is ignored.
_EQUALS_PARAMETER = re.compile(r"c\.([A-Za-z_][\w.]*)\s*=\s*(@\w+)")
_EQUALS_LITERAL = re.compile(r"c\.([A-Za-z_][\w.]*)\s*=\s*'([^']*)'")
_ARRAY_CONTAINS = re.compile(r"ARRAY_CONTAINS\(\s*(@\w+)\s*,\s*c\.(\w+)\s*\)")
BASE_SETTINGS = {
    "enable_chat_workflow_results": True, "allow_user_workflows": True,
    "require_member_of_workflow_user": False,
    "enable_semantic_kernel": False, "per_user_semantic_kernel": False,
    "enable_content_safety": False, "enable_thoughts": False,
    "enable_key_vault_secret_storage": False, "conversation_history_limit": 20,
    "azure_openai_gpt_authentication_type": "api_key",
    "azure_openai_gpt_endpoint": "https://model.invalid",
    "azure_openai_gpt_api_version": "2024-10-21",
    "azure_openai_gpt_key": "offline-model-key",
    "gpt_model": {"selected": [{"deploymentName": "gpt-4o"}]},
}


def field_value(row, path):
    """Read a dotted Cosmos path such as ``metadata.thread_info.thread_id`` from a stored row."""
    value = row
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


class Container(OfflineContainer):
    """Partition-aware offline storage that answers the queries these routes issue."""

    def __init__(self, partition_field="id"):
        super().__init__()
        self.partition_field = partition_field

    def read_item(self, item, partition_key, **kwargs):
        saved = super().read_item(item, partition_key, **kwargs)
        if saved.get(self.partition_field) != partition_key:
            raise CosmosResourceNotFoundError(status_code=404)
        return saved

    def replace_item(self, item, body, **kwargs):
        self.read_item(item, body[self.partition_field])
        return super().replace_item(item, body, **kwargs)

    def query_items(self, query, parameters=None, partition_key=None, max_item_count=100, **kwargs):
        values = {parameter["name"]: parameter["value"] for parameter in parameters or []}
        rows = deepcopy(list(self.items.values()))
        if partition_key is not None:
            rows = [row for row in rows if row.get(self.partition_field) == partition_key]
        for path, parameter in _EQUALS_PARAMETER.findall(query):
            if parameter in values:
                rows = [row for row in rows if field_value(row, path) == values[parameter]]
        for path, value in _EQUALS_LITERAL.findall(query):
            rows = [row for row in rows if field_value(row, path) == value]
        for parameter, field in _ARRAY_CONTAINS.findall(query):
            rows = [row for row in rows if row.get(field) in values.get(parameter, [])]
        rows.sort(
            key=lambda row: (row.get("timestamp") or row.get("created_at") or "", row["id"]),
            reverse="DESC" in query,
        )
        if "COUNT(" in query:
            return [len(rows)]
        maximum = re.search(r"SELECT VALUE MAX\(c\.([\w.]+)\)", query)
        if maximum:
            found = [value for value in (field_value(row, maximum.group(1)) for row in rows) if value is not None]
            return [max(found) if found else None]
        top = re.search(r"SELECT TOP (\d+)", query)
        if top:
            rows = rows[:int(top.group(1))]
        if "c.metadata.thread_info.thread_id as thread_id" in query:
            rows = [{"thread_id": field_value(row, "metadata.thread_info.thread_id")} for row in rows]
        return Query(rows, max_item_count or 100)


class Database(OfflineDatabase):
    def create_container_if_not_exists(self, id, **kwargs):
        partition = kwargs.get("partition_key") or {"paths": ["/id"]}
        return self.containers.setdefault(id, Container(partition["paths"][0].lstrip("/")))

    get_container_client = create_container_if_not_exists


class Cosmos(OfflineCosmos):
    def __init__(self, *args, **kwargs):
        self.database = Database()


class Model:
    """The selected chat model; records exactly what the route sent it."""

    def __init__(self):
        self.requests = []
        self.reply = "The digest says markets rose."
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, *, model, messages, **kwargs):
        self.requests.append(deepcopy(messages))
        # Windows clocks tick about once a millisecond; the answer must sort after its question.
        time.sleep(0.003)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.reply))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15), model="gpt-4o",
        )


@contextmanager
def offline_workflow_result_app(settings_overrides=None):
    """Boot the real application offline with a readable personal workflow run.

    Yields a namespace with the Flask app (``web``), the ``config``, ``chats`` and
    ``reader`` modules, the fake ``model``, the run ``fixture`` and its result
    ``context``, a ``signed_in(user_id, name)`` client factory, the recorded
    ``network_attempts`` and ``normal_chat_clients``, and the ``stack`` that
    owns every patch, so a test can add its own.
    """
    normal_chat_clients = []

    class NormalChatClient:
        def __init__(self, *args, **kwargs):
            normal_chat_clients.append(True)
            raise AssertionError("A workflow-result question reached the normal chat model.")

    state_dir = TESTS / f".workflow-result-chat-state-{uuid.uuid4().hex}"
    state_dir.mkdir()
    network_attempts = []
    original_connect = socket.socket.connect

    def no_network(connection, address):
        # asyncio's Windows selector builds a local wake-up socket pair.
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(connection, address)
        network_attempts.append(address)
        raise AssertionError("The workflow result test attempted network access.")

    def no_http(*args, **kwargs):
        network_attempts.append("http")
        raise AssertionError("The workflow result test attempted an HTTP request.")

    try:
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {
                "SESSION_FILE_DIR": str(state_dir), "SIMPLECHAT_RUN_BACKGROUND_TASKS": "0",
                "DISABLE_FLASK_INSTRUMENTATION": "1", "TENANT_ID": "tenant", "CLIENT_ID": "client",
                "MICROSOFT_PROVIDER_AUTHENTICATION_SECRET": "offline-client-secret",
                "APPLICATIONINSIGHTS_CONNECTION_STRING": "",
            }))
            stack.enter_context(patch("azure.cosmos.CosmosClient", Cosmos))
            stack.enter_context(patch.object(socket.socket, "connect", no_network))
            stack.enter_context(patch("requests.sessions.Session.request", no_http))

            # Real application imports occur only after external I/O is isolated.
            import app
            import config
            import functions_workflow_result_reader as reader
            import route_backend_chats as chats
            from functions_settings import update_settings
            from test_support.workflow_result_chat import OTHER_USER, RUN_ID, USER, WORKFLOW_ID, RunFixture, two_text_tasks

            settings = {**BASE_SETTINGS, **(settings_overrides or {})}
            app.configure_application_cache(
                settings, None, redis_client_factory=app.functions_redis_client.create_redis_client,
            )
            saved = update_settings(settings)
            if not saved:
                raise AssertionError("Offline settings were not saved through the real settings owner.")
            app.initialize_application(force=True)

            model = Model()
            fixture = RunFixture()
            two_text_tasks(fixture)
            stack.enter_context(patch.object(
                chats, "_resolve_model_workflow_client", lambda binding, current: (model, "gpt-4o", "aoai"),
            ))
            stack.enter_context(patch.object(chats, "AzureOpenAI", NormalChatClient))
            stack.enter_context(patch.object(reader, "_default_containers", lambda: fixture.containers))
            stack.enter_context(patch.object(reader, "load_workflow_task_result", fixture.store.load))
            stack.enter_context(patch.object(reader, "read_workflow_task_result_page", fixture.store.read_page))

            for user_id in (USER, OTHER_USER):
                config.cosmos_user_settings_container.upsert_item({
                    "id": user_id, "user_id": user_id, "settings": {"profileImage": None, "enable_thoughts": False},
                })
            web = app.app
            web.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

            def signed_in(user_id, name):
                client = web.test_client()
                with client.session_transaction() as session:
                    session["user"] = {
                        "oid": user_id, "tid": "tenant", "roles": ["User"],
                        "preferred_username": f"{name.lower()}@example.test", "name": name,
                    }
                    session["token_cache"] = "{}"
                return client

            yield SimpleNamespace(
                app=app, web=web, config=config, chats=chats, reader=reader, model=model, fixture=fixture,
                context={
                    "workflow_id": WORKFLOW_ID, "run_id": RUN_ID,
                    "result_sha256": fixture.read()["descriptor"]["result_sha256"],
                },
                signed_in=signed_in, update_settings=update_settings, stack=stack,
                network_attempts=network_attempts, normal_chat_clients=normal_chat_clients,
            )
    finally:
        shutil.rmtree(state_dir, ignore_errors=True)
