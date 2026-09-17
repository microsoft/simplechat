# test_action_auth_service_support.py
"""Isolated service seams for the real per-user authentication implementation.

Version: 0.261.107
Implemented in: 0.261.107

The real contract, state service, identity helpers, catalogs and Flask routes run
unchanged. Only external storage, membership, policy and Yamcs I/O are replaced.
"""

import importlib.util
import re
import sys
import threading
import types
import uuid
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from functools import wraps
from importlib.metadata import version
from pathlib import Path
from unittest.mock import Mock, patch

from flask import Blueprint, Flask, jsonify, session
import werkzeug

from test_support.agent_delegation import CosmosHttpResponseError, CosmosResourceNotFoundError, MatchConditions, module_stub


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
SECRET = "synthetic-PRIVATE-password-never-in-control-state"


class FakeCosmos:
    def __init__(self, partition="user_id", *, identity=False):
        self.partition = partition
        self.identity = identity
        self.records = {}
        self.lock = threading.RLock()
        self.serial = 0
        self.secret_reads = 0
        self.before_replace = None
        self.fail_create = False
        self.fail_replace = False
        self.fail_query = False
        self.writes = []
        self.queries = []

    def put(self, body):
        with self.lock:
            value = deepcopy(body)
            self.serial += 1
            value["_etag"] = f'"{self.serial}"'
            self.records[value[self.partition], value["id"]] = value
            self.writes.append(deepcopy(value))
            return deepcopy(value)

    def read_item(self, *, item, partition_key):
        with self.lock:
            result = self.records.get((partition_key, item))
            if result is None:
                raise CosmosResourceNotFoundError()
            if self.identity:
                self.secret_reads += 1
            return deepcopy(result)

    def create_item(self, *, body):
        with self.lock:
            if self.fail_create:
                raise CosmosHttpResponseError(500, SECRET)
            if (body[self.partition], body["id"]) in self.records:
                raise CosmosHttpResponseError(409, SECRET)
            return self.put(body)

    def replace_item(self, *, item, body, etag, match_condition):
        if self.before_replace:
            self.before_replace(body)
        with self.lock:
            if self.fail_replace:
                raise CosmosHttpResponseError(412, SECRET)
            current = self.records.get((body[self.partition], item))
            if current is None:
                raise CosmosResourceNotFoundError()
            if current.get("_etag") != etag:
                raise CosmosHttpResponseError(412, SECRET)
            assert match_condition is MatchConditions.IfNotModified
            return self.put(body)

    def upsert_item(self, body):
        return self.put(body)

    def delete_item(self, *, item, partition_key, etag=None, match_condition=None):
        with self.lock:
            current = self.records.get((partition_key, item))
            if current is None:
                raise CosmosResourceNotFoundError()
            if etag is not None and etag != current["_etag"]:
                raise CosmosHttpResponseError(412, SECRET)
            del self.records[partition_key, item]

    def query_items(self, *, query, parameters=None, partition_key=None, **kwargs):
        parameters = {entry["name"][1:]: entry["value"] for entry in parameters or []}
        self.queries.append({"query": query, "parameters": deepcopy(parameters), "partition_key": partition_key})
        if self.fail_query:
            raise CosmosHttpResponseError(500, SECRET)
        with self.lock:
            results = [
                deepcopy(record) for (partition, _), record in self.records.items()
                if partition_key is None or partition == partition_key
            ]
        for key, value in parameters.items():
            if key == "draft_roles":
                results = [record for record in results if record.get("role") not in value]
                continue
            if key == "scope_id":
                field = next((field for field in ("user_id", "group_id", "global_id", "public_workspace_id") if f"c.{field} = @scope_id" in query), None)
            elif key == "identity_id" and "c.id = @identity_id" in query:
                field = "id"
            else:
                field = key
            if field:
                results = [record for record in results if record.get(field) == value]
        if "AS auth_type" in query:
            results = [
                {
                    **{key: deepcopy(value) for key, value in record.items() if key != "auth"},
                    "auth_type": record.get("auth", {}).get("auth_type"),
                    "has_username": bool(record.get("auth", {}).get("username")),
                    "has_password": bool(record.get("auth", {}).get("password") or record.get("auth", {}).get("password_secret_name")),
                    "has_secret": bool(record.get("auth", {}).get("secret") or record.get("auth", {}).get("secret_secret_name")),
                } for record in results
            ]
        elif query.startswith("SELECT TOP 1 c.id"):
            results = [{"id": record["id"]} for record in results[:1]]
        return results


class FakeVault:
    def __init__(self):
        self.values = {}
        self.reads = []
        self.deleted = []
        self.fail_set = False
        self.fail_get = False
        self.fail_delete = False

    def set_secret(self, name, value):
        if self.fail_set:
            raise RuntimeError(SECRET)
        self.values[name] = value

    def get_secret(self, name):
        self.reads.append(name)
        if self.fail_get or name not in self.values:
            raise RuntimeError(SECRET)
        return types.SimpleNamespace(value=self.values[name])

    def begin_delete_secret(self, name):
        if self.fail_delete:
            raise RuntimeError(SECRET)
        self.deleted.append(name)
        self.values.pop(name, None)


class YamcsAuthenticationError(RuntimeError):
    pass


class YamcsPermissionError(RuntimeError):
    pass


class YamcsConnectionError(RuntimeError):
    pass


class AuthEnvironment:
    def __init__(self):
        self.settings = {
            "enable_semantic_kernel": True,
            "per_user_semantic_kernel": False,
            "merge_global_semantic_kernel_with_workspace": True,
            "allow_user_agents": True, "allow_group_agents": True,
            "allow_user_plugins": False, "allow_group_plugins": True,
            "enable_user_workspace": False, "enable_group_workspaces": True,
            "enable_collaborative_conversations": True,
            "enable_chat_orchestration": True,
            "enable_key_vault_secret_storage": False,
        }
        self.state_store = FakeCosmos()
        self.personal_identities = FakeCosmos(identity=True)
        self.conversations = FakeCosmos("id")
        self.messages = FakeCosmos("conversation_id")
        self.shared_conversations = FakeCosmos("id")
        self.actions = {scope: FakeCosmos("id" if scope == "global" else "user_id" if scope == "personal" else "group_id") for scope in ("personal", "group", "global")}
        self.agents = {scope: FakeCosmos("id" if scope == "global" else "user_id" if scope == "personal" else "group_id") for scope in ("personal", "group", "global")}
        self.roles = {("alice", "group-a"), ("bob", "group-a")}
        self.denied_actions = set()
        self.denied_agents = set()
        self.runs = {}
        self.vault = FakeVault()
        self.validation_calls = []
        self.validation_hook = None
        self.log_event = Mock()
        config = module_stub(
            "config", cosmos_personal_action_auth_container=self.state_store,
            cosmos_conversations_container=self.conversations,
            cosmos_messages_container=self.messages,
            cosmos_personal_workspace_identities_container=self.personal_identities,
            cosmos_global_workspace_identities_container=FakeCosmos("global_id", identity=True),
            cosmos_group_workspace_identities_container=FakeCosmos("group_id", identity=True),
            cosmos_public_workspace_identities_container=FakeCosmos("public_workspace_id", identity=True),
        )
        for scope in self.agents:
            setattr(config, f"cosmos_{scope}_agents_container", self.agents[scope])
            setattr(config, f"cosmos_{scope}_actions_container", self.actions[scope])
        self.config = config

        def parse_secret_name(name):
            parts = name.split("--") if isinstance(name, str) else []
            if len(parts) != 4:
                return None
            return dict(zip(("scope_value", "source", "scope", "secret_name"), parts))

        def matches(name, *, scope_value, scope, allowed_sources):
            parsed = parse_secret_name(name)
            return bool(parsed and parsed["scope_value"] == scope_value and parsed["scope"] == scope and parsed["source"] in allowed_sources)

        self.modules = {
            "config": config,
            "azure.core": module_stub("azure.core", MatchConditions=MatchConditions),
            "azure.cosmos.exceptions": module_stub(
                "azure.cosmos.exceptions", CosmosResourceNotFoundError=CosmosResourceNotFoundError,
                CosmosHttpResponseError=CosmosHttpResponseError,
            ),
            "functions_settings": module_stub("functions_settings", get_settings=lambda: deepcopy(self.settings)),
            "functions_appinsights": module_stub("functions_appinsights", log_event=self.log_event),
            "functions_keyvault": module_stub(
                "functions_keyvault", KEY_VAULT_DOMAIN=".vault.example", SecretClient=lambda **kwargs: self.vault,
                SecretReturnType=types.SimpleNamespace(TRIGGER="trigger", NAME="name", VALUE="value"),
                ui_trigger_word="********", get_keyvault_credential=lambda **kwargs: object(),
                build_full_secret_name=lambda name, owner, source, scope: f"{owner}--{source}--{scope}--{name}",
                clean_name_for_keyvault=lambda value: re.sub(r"[^a-zA-Z0-9-]", "-", value),
                parse_secret_name_dynamic=parse_secret_name, secret_reference_matches_context=matches,
                keyvault_plugin_get_helper=lambda manifest, **kwargs: deepcopy(manifest),
            ),
            "functions_governance": module_stub(
                "functions_governance", ensure_global_action_access=self.authorize_action,
                ensure_governance_access=self.authorize_agent, ensure_action_type_access=lambda *args, **kwargs: None,
                filter_governed_global_actions_for_user=lambda user, actions: [action for action in actions if action["id"] not in self.denied_actions],
                filter_actions_by_action_type_access=lambda user, actions, *args: actions,
            ),
            "functions_group": module_stub(
                "functions_group", assert_group_role=self.group_role,
                get_user_groups=lambda actor: [{"id": group, "name": "Group"} for user, group in self.roles if user == actor],
                require_active_group=lambda actor: "group-a",
            ),
            "functions_collaboration": module_stub(
                "functions_collaboration",
                get_collaboration_conversation=lambda identifier: self.shared_conversations.read_item(item=identifier, partition_key=identifier),
                assert_user_can_participate_in_collaboration_conversation=self.participate,
                is_collaboration_source_conversation=lambda item: bool(item.get("collaboration_conversation_id")),
                build_conversation_participation_context=self.personal_access,
            ),
            "functions_orchestration_runs": module_stub(
                "functions_orchestration_runs", get_orchestration_run=self.get_run,
            ),
            "functions_yamcs_client": module_stub(
                "functions_yamcs_client", validate_yamcs_credentials=self.validate,
                YamcsAuthenticationError=YamcsAuthenticationError, YamcsPermissionError=YamcsPermissionError,
                YamcsConnectionError=YamcsConnectionError,
            ),
            "functions_authentication": module_stub(
                "functions_authentication", get_current_user_id=lambda: (session.get("user") or {}).get("oid"),
                login_required=self.auth_decorator, user_required=self.auth_decorator,
            ),
            "swagger_wrapper": module_stub(
                "swagger_wrapper", swagger_route=lambda **kwargs: lambda function: function,
                get_auth_security=lambda: [{"test_auth": []}],
            ),
        }

    def authorize_action(self, actor, action):
        if action["id"] in self.denied_actions:
            raise PermissionError(SECRET)

    def authorize_agent(self, feature, actor, **kwargs):
        if kwargs.get("item_id") in self.denied_agents:
            raise PermissionError(SECRET)

    def group_role(self, actor, group, **kwargs):
        if (actor, group) not in self.roles:
            raise PermissionError(SECRET)
        return "User"

    def participate(self, actor, conversation):
        if actor not in conversation.get("participants", []):
            raise PermissionError(SECRET)
        return {}

    def personal_access(self, actor, conversation):
        if actor != conversation.get("user_id"):
            raise PermissionError(SECRET)
        return {"user_id": actor}

    def get_run(self, run_id, actor, conversation_id=None, **kwargs):
        run = self.runs.get(run_id)
        if not run or run.get("user_id") != actor or (conversation_id and run.get("conversation_id") != conversation_id):
            return None
        return deepcopy(run)

    def validate(self, action, credentials):
        self.validation_calls.append((deepcopy(action), deepcopy(credentials)))
        if self.validation_hook:
            self.validation_hook(action, credentials)
        return {"success": True}

    @staticmethod
    def auth_decorator(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            if not (session.get("user") or {}).get("oid"):
                return jsonify({"error": "Authentication required."}), 401
            if not set((session.get("user") or {}).get("roles", [])).intersection({"User", "Admin"}):
                return jsonify({"error": "User access required."}), 403
            return function(*args, **kwargs)
        return wrapped

    def add_action(self, *, profile="yamcs_login", endpoint="https://yamcs.example", name="Telemetry", action_id=None, **overrides):
        action = {
            "id": action_id or str(uuid.uuid4()), "name": name, "type": "yamcs", "is_enabled": True,
            "endpoint": endpoint, "auth": {"type": "username_password"},
            "additionalFields": {"server_url": endpoint, "instance": "simulator", "processor": "realtime", "tls_verify": True},
            "credential_requirement": {"id": str(uuid.uuid4()), "source": "current_user", "identity_name": "Yamcs", "profile": profile},
            **overrides,
        }
        action = self.contract.normalize_action_credential_requirement(action)
        return self.actions["global"].put(action)

    def action_ref(self, action):
        return self.catalog._action_ref("global", "global", action["id"])

    def add_agent(self, action_ids, *, agent_id=None, name="Mission assistant", scope="global", owner="alice"):
        agent = {"id": agent_id or str(uuid.uuid4()), "name": name, "agent_type": "local", "actions_to_load": list(action_ids), "is_enabled": True}
        if scope != "global":
            agent["user_id" if scope == "personal" else "group_id"] = owner
        self.agents[scope].put(agent)
        return {"id": agent["id"], "name": name, "scope_type": scope, "scope_id": "global" if scope == "global" else owner}

    def identity(self, actor="alice", *, name="Yamcs", auth_type="username_password", secret=SECRET, usage=None):
        credentials = {"auth_type": auth_type}
        credentials.update({"username": f"{actor}-login", "password": secret} if auth_type == "username_password" else {"secret": secret})
        return self.identities.create_workspace_identity(
            "personal", actor, {"name": name, "usage_contexts": usage or ["action"], "supported_source_types": ["action"], "credentials": credentials}, actor,
        )

    def connect(self, actor, action, *, identity_id=None, secret=SECRET):
        context = {"action_ref": self.action_ref(action)}
        state = self.state.preflight_action_auth(actor, context)
        if state["status"] == "ready":
            return state
        payload = {"requirement_id": action["credential_requirement"]["id"], "confirm_destination": True}
        if identity_id:
            payload["identity_id"] = identity_id
        else:
            profile = action["credential_requirement"]["profile"]
            payload["credentials"] = {"username": f"{actor}-login", "password": secret} if profile in ("yamcs_login", "http_basic") else {"secret": secret}
        return self.state.save_action_auth_credentials(actor, state["request_id"], payload)

    def client(self, actor="alice"):
        client = self.app.test_client()
        if actor:
            with client.session_transaction() as state:
                state["user"] = {"oid": actor, "roles": ["User"]}
        return client


@contextmanager
def auth_environment():
    env = AuthEnvironment()
    with ExitStack() as stack:
        stack.enter_context(patch.dict(sys.modules, env.modules))
        if not hasattr(werkzeug, "__version__"):
            stack.enter_context(patch.object(werkzeug, "__version__", version("werkzeug"), create=True))
        loaded = {}
        for name in (
            "functions_action_auth", "agent_execution_context", "functions_agent_delegation", "functions_action_catalog",
            "functions_workspace_identities", "functions_action_auth_state", "route_backend_action_auth",
        ):
            spec = importlib.util.spec_from_file_location(name, APP_ROOT / f"{name}.py")
            module = importlib.util.module_from_spec(spec)
            stack.enter_context(patch.dict(sys.modules, {name: module}))
            spec.loader.exec_module(module)
            loaded[name] = module
        env.contract = loaded["functions_action_auth"]
        env.state = loaded["functions_action_auth_state"]
        env.catalog = loaded["functions_action_catalog"]
        env.identities = loaded["functions_workspace_identities"]
        env.execution = loaded["agent_execution_context"]
        env.app = Flask(__name__)
        env.app.secret_key = "synthetic-test-session"
        bp = Blueprint("backend_action_auth", __name__)
        loaded["route_backend_action_auth"].register_route_backend_action_auth(bp)
        env.app.register_blueprint(bp)
        yield env
