# test_orchestration_external_sources.py
"""
Functional coverage for retained external Gather source admission and access.
Version: 0.261.127
Implemented in: 0.261.127

Real result contracts/store/readers, capability gates, scoped integration
resolvers and memory authorization run with identity, configuration and storage
I/O doubled. Fresh-process reads and receipt recovery prove that committed
bindings do not depend on the live admission catalog. Network and implicit
memory recall are prohibited. Invocation preflight must reauthorize before
capture/effects without creating content authority or a URL fetch grant.
Refs microsoft/simplechat#1509.
"""

from contextlib import ExitStack
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from enum import Enum
import json
from pathlib import Path
import socket
import subprocess
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

# Import the real application boundaries, not extracted functions or config stubs.
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from functions_action_catalog import _action_ref
from functions_orchestration_external_sources import (
    CurrentExternalSourceIdentity,
    ExternalSourceConfiguration,
    OrchestrationExternalSourceProvider,
)
from functions_orchestration_external_identity import ExternalIdentityCancelledError, ExternalIdentityServiceError
from functions_orchestration_result_contracts import (
    ExternalSourceRef,
    ProducerIdentity,
    ResultContractError,
    ResultRef,
    canonical_digest,
    output_name,
)
from functions_orchestration_results import (
    NamedOutput,
    OrchestrationResultAccess,
    OrchestrationResults,
    ResultUnavailableError,
)
from test_support.agent_delegation import DelegationServices
from test_support.orchestration_results import ResultFixture, complete


class SecretReturnType(Enum):
    NAME = "name"


class ExternalSourceWorld:
    """Existing in-memory result/delegation fixtures behind real access APIs."""

    def __init__(self, capability_id="web_search"):
        self.stack = ExitStack()
        self.fixture = ResultFixture()
        self.fixture.producer = ProducerIdentity(
            "owner", "conversation-1", "external-run", 1, "gather", capability_id, "external-test-v2",
        )
        self.fixture.add_producer(self.fixture.producer)
        self.run = self.fixture.runs["external-run"]
        self.run["plan"]["planner_contract_version"] = 2
        self.run["plan"]["steps"][0]["arguments"] = {}
        self.services = DelegationServices()
        self.services.roles = {("owner", "group-a"): "User"}
        self.services.groups.get_user_groups = Mock(side_effect=lambda user_id: [
            {"id": group_id, "name": "Group"}
            for (owner, group_id) in self.services.roles if owner == user_id
        ])
        self.services.add_agent("agent-1", scope="group", scope_id="group-a", name="Lookup")
        self.services.add("actions", "group", "group-a", {
            "id": "action-1", "name": "Lookup", "type": "openapi", "is_enabled": True,
            "endpoint": "https://private.invalid", "auth": {"secret": "synthetic-secret"},
        })
        self.agent_selector = "group:group-a:agent-1"
        self.action_selector = _action_ref("group", "group-a", "action-1")
        if capability_id == "agent_invoke":
            self.run["plan"]["steps"][0]["arguments"] = {"agent_name": "Lookup"}
        if capability_id == "action_invoke":
            self.run["plan"]["steps"][0]["arguments"] = {"action_ref": self.action_selector}
        self.roles = ("User", "UrlAccessUser", "DeepResearchUser")
        self.user_enable_agents = True
        self.settings = {
            **self.services.settings,
            "enable_chat_orchestration": True, "enable_chat_orchestration_harness": False,
            "enable_chat_orchestration_actions": True, "enable_web_search": True,
            "enable_url_access": True, "require_member_of_url_access_user": True,
            "enable_source_review": True, "require_member_of_deep_research_user": True,
            "enable_fact_memory_plugin": True, "enable_user_workspace": True,
            "per_user_semantic_kernel": True, "chat_orchestration_enabled_capabilities": [],
        }
        self.configuration_identity = "deployment-source"
        self.configuration_revision = "revision-1"
        self.identity_reads = 0
        self.catalog_reads = 0
        self.configuration_reads = []
        self.catalog_override = None
        self.prepared = {
            "version": "orchestration-gathered-content-v1", "capability_id": capability_id,
            "content_scope": "reported_external_content", "evidence": [],
            "notes": ["Retained excerpt\nincluding the final line: caf\u00e9."],
            "citations": [{"url": "https://public.example/page", "title": "Returned citation"}],
            "limitations": ["Returned content, not whole-source coverage."],
        }

    def __enter__(self):
        def no_network(*_args, **_kwargs):
            raise AssertionError("External source authorization must not fetch remote content")

        self.stack.enter_context(patch.object(socket.socket, "connect", no_network))
        keyvault = ModuleType("functions_keyvault")
        keyvault.SecretReturnType = SecretReturnType
        keyvault.keyvault_plugin_get_helper = Mock(side_effect=lambda value, **_kwargs: deepcopy(value))
        self.stack.enter_context(patch.dict(sys.modules, {
            "config": self.services.modules["config"],
            "functions_group": self.services.groups,
            "functions_governance": self.services.governance,
            "functions_keyvault": keyvault,
            "functions_fact_memory_context": None,
        }))
        return self

    def __exit__(self, *args):
        return self.stack.__exit__(*args)

    def identity(self, *, user_id, conversation_id):
        if user_id != "owner" or conversation_id != "conversation-1":
            raise PermissionError("Wrong test identity")
        self.identity_reads += 1
        return CurrentExternalSourceIdentity(
            user_id, self.roles, self.user_enable_agents, "owner@example.test",
        )

    def catalog(self, user_id, *, settings):
        self.catalog_reads += 1
        if self.catalog_override is not None:
            return deepcopy(self.catalog_override)
        values = []
        for (kind, scope), records in self.services.records.items():
            expected = "agents" if self.fixture.producer.capability_id == "agent_invoke" else "actions"
            if kind != expected:
                continue
            for (scope_id, _), source in records.items():
                scope_id = "global" if scope == "global" else scope_id
                record = {
                    "id": source["id"], "name": source["name"], "scope_type": scope, "scope_id": scope_id,
                    "is_global": scope == "global", "is_group": scope == "group",
                    "group_id": scope_id if scope == "group" else None,
                }
                if kind == "agents":
                    record["catalog_key"] = f'{scope}:{scope_id}:{source["id"]}'
                else:
                    record.update(type=source["type"], action_ref=_action_ref(scope, scope_id, source["id"]))
                values.append(record)
        return values

    def configuration(self, source_type, *, producer, settings, source):
        self.configuration_reads.append((source_type, deepcopy(source)))
        return ExternalSourceConfiguration(self.configuration_identity, self.configuration_revision)

    def admit_configuration(self, source_type, *, producer, settings, source, selector=None):
        return self.configuration(source_type, producer=producer, settings=settings, source=source)

    def provider(self, **overrides):
        options = {
            "user_id": "owner", "conversation_id": "conversation-1",
            "read_identity": self.identity, "read_settings": lambda: deepcopy(self.settings),
            "read_conversation": lambda conversation_id: deepcopy(self.fixture.conversation),
            "read_run": lambda run_id: deepcopy(self.fixture.runs.get(run_id)),
            "read_configuration": self.configuration,
            "configuration_admitter": self.admit_configuration,
            "agent_catalog_reader": self.catalog, "action_catalog_reader": self.catalog,
        }
        options.update(overrides)
        return OrchestrationExternalSourceProvider(**options)

    def service(self, provider, catalog=None):
        access = OrchestrationResultAccess(
            user_id="owner", conversation_id="conversation-1",
            read_conversation=lambda conversation_id: deepcopy(self.fixture.conversation),
            read_run=lambda run_id: deepcopy(self.fixture.runs.get(run_id)),
            external_source_catalog={} if catalog is None else catalog,
            external_source_authorizer=provider.authorize,
        )
        store = self.fixture.restart().store
        return OrchestrationResults(store, access)

    def selected_integration(self):
        return {
            "agent_invoke": self.agent_selector, "action_invoke": self.action_selector,
        }.get(self.fixture.producer.capability_id)

    def preflight(self, provider):
        return provider.preflight_gather_invocation(
            producer=self.fixture.producer, selector=self.selected_integration(),
        )

    def admit(self, provider, *, memory=False):
        if memory:
            return provider.admit_memory_result(producer=self.fixture.producer, prepared=self.prepared)
        return provider.admit_gather_result(
            producer=self.fixture.producer, prepared=self.prepared, selector=self.selected_integration(),
        )

    def persist(self, service, catalog, *, memory=False, input_fingerprint=None):
        return service.persist_task_result(
            producer=self.fixture.producer, role="reason" if memory else "gather", status="complete",
            outputs=[NamedOutput("prepared", "structured-v1", deepcopy(self.prepared), complete(1))],
            sources=[], origin="grounded", external_sources=tuple(catalog),
            guard_token="server-attempt-token", input_fingerprint=input_fingerprint,
        )

    def save(self, *, memory=False, input_fingerprint=None):
        provider = self.provider()
        catalog = self.admit(provider, memory=memory)
        service = self.service(provider, catalog)
        task = self.persist(service, catalog, memory=memory, input_fingerprint=input_fingerprint)
        return provider, catalog, task.output("prepared")

    def memory_scope(self, scope_type="user", scope_id="owner"):
        self.run["memory_scope"] = {"type": scope_type, "id": scope_id}
        self.run["memory_audience"] = {
            "kind": "personal", "owner_id": "owner", "collaboration_id": "",
        }


IMPORT_PROBE = r"""
import builtins
import importlib
import socket
import sys
from unittest.mock import patch

sys.path.insert(0, sys.argv[1])
original = builtins.__import__

def check_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level == 0 and (name == "config" or name == "functions_settings" or name.startswith("route_")):
        raise AssertionError("Unexpected application owner import: " + name)
    return original(name, globals, locals, fromlist, level)

def no_network(*args, **kwargs):
    raise AssertionError("Network during external-source import")

with patch.object(builtins, "__import__", check_import), patch.object(socket.socket, "connect", no_network):
    module = importlib.import_module("functions_orchestration_external_sources")
    identity = module.CurrentExternalSourceIdentity("owner", ("User",))
    if identity.user_enable_agents is not False:
        raise AssertionError("Agent access silently defaulted on")
    try:
        module.ExternalSourceConfiguration("https://private.invalid", "revision-1")
    except module.ResultContractError:
        pass
    else:
        raise AssertionError("A raw URL was accepted as configuration identity")
"""

RESTART_PROBE = r"""
import json
import sys

sys.path.insert(0, sys.argv[1])
from test_orchestration_external_sources import ExternalSourceWorld, ResultRef, ResultUnavailableError

payload = json.load(sys.stdin)
with ExternalSourceWorld("url_fetch") as world:
    world.fixture.container.items = {tuple(key): value for key, value in payload["items"]}
    world.fixture.runs = payload["runs"]
    world.fixture.conversation = payload["conversation"]
    world.roles = ("User",) if sys.argv[2] == "revoked" else ("User", "UrlAccessUser")
    provider = world.provider()
    service = world.service(provider)
    if service.access.external_source_catalog:
        raise AssertionError("Restart unexpectedly retained a live admission catalog")
    reference = ResultRef.from_dict(payload["reference"])
    try:
        if "input_fingerprint" in payload:
            task = service.recover_task_result(
                producer=world.fixture.producer, input_fingerprint=payload["input_fingerprint"],
            )
            if task is None or task.output("prepared") != reference:
                raise AssertionError("Receipt recovery lost the exact committed reference")
            reference = task.output("prepared")
        value = service.open_result(reference, require_current_sources=True).read_value()
    except ResultUnavailableError:
        if sys.argv[2] != "revoked":
            raise
    else:
        if sys.argv[2] == "revoked" or value != payload["prepared"]:
            raise AssertionError("Restart ignored current roles or lost retained content")
    if world.identity_reads == 0:
        raise AssertionError("Restart did not refresh identity")
"""


class OrchestrationExternalSourceTests(unittest.TestCase):
    def test_preflight_checks_every_gather_without_configuration_or_content_authority(self):
        for capability in ("web_search", "url_fetch", "deep_research", "agent_invoke", "action_invoke"):
            with self.subTest(capability=capability), ExternalSourceWorld(capability) as world:
                world.run["user_message"] = "Read https://public.example/page."
                configuration = Mock(side_effect=AssertionError("Preflight must not attest configuration"))
                provider = world.provider(
                    read_configuration=configuration, configuration_admitter=configuration,
                )
                with (
                    patch.object(provider, "_reference", side_effect=AssertionError("No source refs before content")),
                    patch("functions_orchestration_external_sources._content_digest",
                          side_effect=AssertionError("No content digest before acquisition")),
                ):
                    result = world.preflight(provider)
                self.assertIsNone(result)
                self.assertEqual(world.identity_reads, 1)
                self.assertEqual(provider.access.external_source_catalog, {})
                configuration.assert_not_called()
                self.assertEqual(world.configuration_reads, [])

    def test_preflight_refreshes_identity_each_time_and_denies_before_capture_or_transport(self):
        with ExternalSourceWorld() as world:
            provider = world.provider()
            capture = Mock()
            transport = Mock()

            def invoke():
                world.preflight(provider)
                capture()
                transport()

            invoke()
            world.roles = ()
            with self.assertRaises(ResultUnavailableError):
                invoke()
            self.assertEqual(world.identity_reads, 2)
            self.assertEqual(capture.call_count, 1)
            self.assertEqual(transport.call_count, 1)
            with self.assertRaises(ResultUnavailableError):
                world.preflight(world.provider())
            self.assertEqual(world.identity_reads, 3)

    def test_preflight_does_not_accept_missing_or_captured_identity_claims(self):
        for returned in (
            None, True, {"user_id": "owner", "roles": ["User"]},
            CurrentExternalSourceIdentity("another-owner", ("User",)),
            CurrentExternalSourceIdentity("owner", ()),
        ):
            with self.subTest(identity=returned), ExternalSourceWorld() as world:
                provider = world.provider(read_identity=lambda **_kwargs: returned)
                with self.assertRaises(ResultUnavailableError):
                    world.preflight(provider)

    def test_preflight_preserves_directory_operational_and_execution_errors(self):
        for error in (
            ExternalIdentityServiceError(),
            ExternalIdentityServiceError("external_identity_response_invalid"),
            ExternalIdentityCancelledError(),
        ):
            with self.subTest(error=error.code), ExternalSourceWorld() as world:
                provider = world.provider(read_identity=Mock(side_effect=error))
                with self.assertRaises(type(error)) as caught:
                    world.preflight(provider)
                self.assertIs(caught.exception, error)
                self.assertNotIsInstance(caught.exception, ResultUnavailableError)
                self.assertEqual(world.configuration_reads, [])

    def test_preflight_uses_current_capability_settings_narrowing_and_preferences(self):
        for capability, setting in (
            ("web_search", "enable_web_search"), ("url_fetch", "enable_url_access"),
            ("deep_research", "enable_source_review"), ("agent_invoke", "enable_semantic_kernel"),
            ("action_invoke", "enable_chat_orchestration_actions"),
        ):
            with self.subTest(capability=capability), ExternalSourceWorld(capability) as world:
                world.run["user_message"] = "Read https://public.example/page."
                provider = world.provider()
                world.preflight(provider)
                for value in (False, "false"):
                    world.settings[setting] = value
                    with self.assertRaises(ResultUnavailableError):
                        world.preflight(provider)
                world.settings[setting] = True
                world.settings["chat_orchestration_enabled_capabilities"] = ["document_search"]
                with self.assertRaises(ResultUnavailableError):
                    world.preflight(provider)
        with ExternalSourceWorld("agent_invoke") as world:
            world.user_enable_agents = False
            with self.assertRaises(ResultUnavailableError):
                world.preflight(world.provider())

    def test_preflight_rechecks_integration_membership_and_governance_before_effects(self):
        for capability, feature in (
            ("agent_invoke", "governance_group_agents"), ("action_invoke", "governance_group_actions"),
        ):
            with self.subTest(capability=capability), ExternalSourceWorld(capability) as world:
                provider = world.provider()
                world.preflight(provider)
                world.services.roles.clear()
                with self.assertRaises(ResultUnavailableError):
                    world.preflight(provider)
                world.services.roles = {("owner", "group-a"): "User"}
                world.services.denied_features.add(feature)
                with self.assertRaises(ResultUnavailableError):
                    world.preflight(provider)
                self.assertGreaterEqual(world.catalog_reads, 3)

    def test_preflight_requires_exact_selector_and_authoritative_saved_step_selection(self):
        for capability in ("agent_invoke", "action_invoke"):
            with self.subTest(capability=capability), ExternalSourceWorld(capability) as world:
                provider = world.provider()
                for selector in (None, "Lookup", "another-source"):
                    with self.assertRaises(ResultUnavailableError):
                        provider.preflight_gather_invocation(producer=world.fixture.producer, selector=selector)
                with patch.object(provider, "_resolve_integration") as resolver:
                    argument = "agent_name" if capability == "agent_invoke" else "action_ref"
                    world.run["plan"]["steps"][0]["arguments"][argument] = "different-approved-selection"
                    with self.assertRaises(ResultUnavailableError):
                        world.preflight(provider)
                    resolver.assert_not_called()
                self.assertEqual(world.configuration_reads, [])

    def test_preflight_rejects_replaced_integration_identity_or_forged_action_origin(self):
        with ExternalSourceWorld("agent_invoke") as world:
            provider = world.provider()
            world.services.records["agents", "group"].clear()
            world.services.add_agent("replacement", scope="group", scope_id="group-a", name="Lookup")
            with self.assertRaises(ResultUnavailableError):
                world.preflight(provider)
        with ExternalSourceWorld("action_invoke") as world:
            source = world.catalog("owner", settings=world.settings)[0]
            provider = world.provider(action_resolver=lambda *_args, **_kwargs: source)
            with self.assertRaises(ResultUnavailableError):
                world.preflight(provider)

    def test_preflight_refuses_stale_producers_disabled_steps_and_changed_audiences(self):
        with ExternalSourceWorld() as world:
            provider = world.provider()
            for changes in (
                {"user_id": "other"}, {"conversation_id": "other"}, {"run_id": "other"},
                {"attempt_index": 2}, {"step_id": "other"},
            ):
                with self.subTest(changes=changes), self.assertRaises(ResultUnavailableError):
                    provider.preflight_gather_invocation(producer=replace(world.fixture.producer, **changes))
            world.run["plan"]["steps"][0]["enabled"] = False
            with self.assertRaises(ResultUnavailableError):
                world.preflight(provider)
            world.run["plan"]["steps"][0]["enabled"] = True
            world.run["memory_audience"] = {"kind": "personal", "owner_id": "owner", "collaboration_id": ""}
            world.fixture.conversation["is_hidden"] = True
            with self.assertRaises(ResultUnavailableError):
                world.preflight(provider)

    def test_url_preflight_never_uses_retained_content_or_plan_arguments_as_a_new_grant(self):
        with ExternalSourceWorld("url_fetch") as world:
            provider, _catalog, reference = world.save()
            world.run["plan"]["steps"][0]["arguments"] = {"urls": ["https://public.example/page"]}
            with self.assertRaises(ResultUnavailableError):
                world.preflight(provider)
            retained = world.service(provider).open_result(reference).read_value()
            self.assertEqual(retained, world.prepared)
            world.run["user_message"] = "Read https://public.example/page."
            result = world.preflight(provider)
            self.assertIsNone(result)
            world.roles = ("User",)
            with self.assertRaises(ResultUnavailableError):
                world.preflight(provider)

    def test_url_preflight_reuses_server_user_message_edit_clarification_and_history_provenance(self):
        for record in (
            {"user_message": "Read https://public.example/page."},
            {"edit_user_urls": ["https://public.example/page"]},
            {"answered_questions": [{"action": "accept", "answer": "Read https://public.example/page."}]},
            {
                "conversation_context": {"messages": [{
                    "id": "user-1", "role": "user", "content": "Read https://public.example/page.",
                }]},
                "request_resolution": {"message_ids": ["user-1"]},
            },
        ):
            with self.subTest(record=record), ExternalSourceWorld("url_fetch") as world:
                world.run.update(record)
                result = world.preflight(world.provider())
                self.assertIsNone(result)
                self.assertNotIn("allowed_user_urls", world.run)

    def test_url_preflight_rejects_assistant_truncated_unselected_or_declined_url_provenance(self):
        for record in (
            {"conversation_context": {"messages": [{
                "id": "assistant-1", "role": "assistant", "content": "https://public.example/page",
            }]}, "request_resolution": {"message_ids": ["assistant-1"]}},
            {"conversation_context": {"messages": [{
                "id": "user-1", "role": "user", "content": "https://public.example/page", "truncated": True,
            }]}, "request_resolution": {"message_ids": ["user-1"]}},
            {"conversation_context": {"messages": [{
                "id": "user-1", "role": "user", "content": "https://public.example/page",
            }]}},
            {"answered_questions": [{"action": "decline", "answer": "https://public.example/page"}]},
            {"edit_user_urls": ["not a URL"]},
        ):
            with self.subTest(record=record), ExternalSourceWorld("url_fetch") as world:
                world.run.update(record)
                with self.assertRaises(ResultUnavailableError):
                    world.preflight(world.provider())

    def test_url_preflight_rejects_malformed_server_provenance_without_coercion(self):
        for record in (
            {"user_message": None}, {"conversation_context": True},
            {"conversation_context": {"messages": [None]}},
            {"request_resolution": []}, {"request_resolution": {"message_ids": "user-1"}},
            {"answered_questions": False}, {"answered_questions": [{"context": True}]},
            {"edit_user_urls": "https://public.example/page"}, {"edit_user_urls": [True]},
        ):
            with self.subTest(record=record), ExternalSourceWorld("url_fetch") as world:
                world.run.update(record)
                with self.assertRaises(ResultUnavailableError):
                    world.preflight(world.provider())

    def test_preflight_does_not_expand_to_fact_memory_or_accept_url_selectors(self):
        with ExternalSourceWorld("compose") as world:
            with self.assertRaises(ResultContractError):
                world.preflight(world.provider())
            self.assertEqual(world.identity_reads, 0)
        with ExternalSourceWorld("url_fetch") as world:
            world.run["user_message"] = "Read https://public.example/page."
            with self.assertRaises(ResultContractError):
                world.provider().preflight_gather_invocation(
                    producer=world.fixture.producer, selector="https://public.example/page",
                )

    def test_each_gather_source_keeps_exact_content_after_catalog_free_restart(self):
        for capability_id, source_type in (
            ("web_search", "web"), ("url_fetch", "url"), ("deep_research", "deep_research"),
            ("agent_invoke", "agent"), ("action_invoke", "action"),
        ):
            with self.subTest(capability=capability_id), ExternalSourceWorld(capability_id) as world:
                _provider, catalog, reference = world.save()
                alias, external = next(iter(catalog.items()))
                checked_alias = output_name(alias)
                expected_digest = canonical_digest(world.prepared)
                wire = json.dumps(external.to_dict())
                restored = ResultRef.from_dict(json.loads(json.dumps(reference.to_dict())))
                restart = world.service(world.provider())
                reader = restart.open_result(restored, require_current_sources=True)
                value = reader.read_value()
                self.assertEqual(value, world.prepared)
                self.assertEqual(external.source_type, source_type)
                self.assertEqual(external.content_sha256, expected_digest)
                self.assertEqual(checked_alias, alias)
                self.assertLessEqual(len(alias), 64)
                self.assertLessEqual(len(external.reference_id), 256)
                self.assertTrue(external.source_revision.startswith("configuration:"))
                self.assertEqual(restart.access.external_source_catalog, {})
                self.assertNotIn("synthetic-secret", wire)
                self.assertNotIn("https:", wire)
                self.assertGreater(world.identity_reads, 1)
                with self.assertRaises(FrozenInstanceError):
                    external.content_sha256 = "a" * 64

    def test_role_revocation_blocks_live_and_restarted_reads(self):
        for capability, roles in (
            ("web_search", ()), ("url_fetch", ("User",)), ("deep_research", ("User",)),
        ):
            with self.subTest(capability=capability), ExternalSourceWorld(capability) as world:
                provider, catalog, reference = world.save()
                live = world.service(provider, catalog).open_result(reference)
                world.roles = roles
                with self.assertRaises(ResultUnavailableError):
                    live.read_value()
                with self.assertRaises(ResultUnavailableError):
                    world.service(world.provider()).open_result(reference)

    def test_settings_and_capability_narrowing_are_current_not_plan_snapshots(self):
        for capability, setting in (
            ("web_search", "enable_web_search"), ("url_fetch", "enable_url_access"),
            ("deep_research", "enable_source_review"), ("agent_invoke", "enable_semantic_kernel"),
            ("action_invoke", "enable_chat_orchestration_actions"),
        ):
            with self.subTest(capability=capability), ExternalSourceWorld(capability) as world:
                _provider, _catalog, reference = world.save()
                world.settings[setting] = False
                with self.assertRaises(ResultUnavailableError):
                    world.service(world.provider()).open_result(reference)
                world.settings[setting] = "false"
                with self.assertRaises(ResultUnavailableError):
                    world.service(world.provider()).open_result(reference)
                world.settings[setting] = True
                world.settings["chat_orchestration_enabled_capabilities"] = ["document_search"]
                with self.assertRaises(ResultUnavailableError):
                    world.service(world.provider()).open_result(reference)

    def test_new_plan_rollout_rollback_does_not_revoke_saved_content(self):
        with ExternalSourceWorld() as world:
            world.settings["enable_chat_orchestration_harness"] = True
            _provider, _catalog, reference = world.save()
            world.settings["enable_chat_orchestration_harness"] = False
            value = world.service(world.provider()).open_result(reference).read_value()
            self.assertEqual(value, world.prepared)

    def test_configuration_admission_is_required_only_for_new_external_gathers(self):
        with ExternalSourceWorld() as world:
            _provider, _catalog, reference = world.save()
            readonly = world.provider(configuration_admitter=None)
            with self.assertRaises(ResultUnavailableError) as rejected:
                world.admit(readonly)
            self.assertEqual(rejected.exception.code, "result_external_capture_required")
            value = world.service(readonly).open_result(reference).read_value()
            self.assertEqual(value, world.prepared)

    def test_configuration_admitter_receives_the_original_exact_integration_selector(self):
        for capability in ("web_search", "url_fetch", "deep_research", "agent_invoke", "action_invoke"):
            with self.subTest(capability=capability), ExternalSourceWorld(capability) as world:
                admission = Mock(side_effect=world.admit_configuration)
                provider = world.provider(configuration_admitter=admission)
                world.admit(provider)
                self.assertEqual(admission.call_count, 1)
                self.assertEqual(admission.call_args.kwargs["producer"], world.fixture.producer)
                expected = {"agent_invoke": world.agent_selector, "action_invoke": world.action_selector}.get(capability)
                self.assertEqual(admission.call_args.kwargs["selector"], expected)

    def test_current_configuration_cannot_replace_the_captured_admission_configuration(self):
        with ExternalSourceWorld() as world:
            original = ExternalSourceConfiguration("original-provider", "original-revision")
            provider = world.provider(configuration_admitter=lambda *_args, **_kwargs: original)
            with self.assertRaises(ResultUnavailableError) as rejected:
                world.admit(provider)
            self.assertEqual(rejected.exception.code, "result_external_configuration_changed")

    def test_agent_and_action_membership_revocation_ignores_stale_catalog_entries(self):
        for capability in ("agent_invoke", "action_invoke"):
            with self.subTest(capability=capability), ExternalSourceWorld(capability) as world:
                _provider, _catalog, reference = world.save()
                world.services.roles.clear()
                with self.assertRaises(ResultUnavailableError):
                    world.service(world.provider()).open_result(reference)
                self.assertGreater(world.catalog_reads, 1)
                self.assertGreater(world.services.groups.assert_group_role.call_count, 0)

    def test_integration_governance_and_enabled_state_are_rechecked(self):
        for capability, kind, feature in (
            ("agent_invoke", "agents", "governance_group_agents"),
            ("action_invoke", "actions", "governance_group_actions"),
        ):
            with self.subTest(capability=capability), ExternalSourceWorld(capability) as world:
                _provider, _catalog, reference = world.save()
                world.services.denied_features.add(feature)
                with self.assertRaises(ResultUnavailableError):
                    world.service(world.provider()).open_result(reference)
                world.services.denied_features.clear()
                record = next(iter(world.services.records[kind, "group"].values()))
                record["is_enabled"] = False
                with self.assertRaises(ResultUnavailableError):
                    world.service(world.provider()).open_result(reference)

    def test_agent_preference_and_exact_selection_cannot_fall_back_to_a_name(self):
        with ExternalSourceWorld("agent_invoke") as world:
            provider = world.provider()
            with self.assertRaises(ResultUnavailableError):
                provider.admit_gather_result(
                    producer=world.fixture.producer, prepared=world.prepared, selector="Lookup",
                )
            _provider, _catalog, reference = world.save()
            world.user_enable_agents = False
            with self.assertRaises(ResultUnavailableError):
                world.service(world.provider()).open_result(reference)
            world.user_enable_agents = True
            world.services.records["agents", "group"].clear()
            world.services.add_agent("replacement-agent", scope="group", scope_id="group-a", name="Lookup")
            with self.assertRaises(ResultUnavailableError):
                world.service(world.provider()).open_result(reference)

    def test_current_configuration_revision_is_not_a_remote_content_revision(self):
        for capability in ("web_search", "agent_invoke", "action_invoke"):
            with self.subTest(capability=capability), ExternalSourceWorld(capability) as world:
                provider, catalog, reference = world.save()
                external = next(iter(catalog.values()))
                world.configuration_revision = "revision-2"
                current = provider.authorize(
                    external, producer=world.fixture.producer, user_id="owner", conversation_id="conversation-1",
                )
                self.assertEqual(current.identity(), external.identity())
                self.assertEqual(current.content_sha256, external.content_sha256)
                self.assertNotEqual(current.source_revision, external.source_revision)
                with self.assertRaises(ResultUnavailableError):
                    world.service(world.provider()).open_result(reference, require_current_sources=True)
                world.configuration_revision = "revision-1"
                world.configuration_identity = "replacement-configuration"
                with self.assertRaises(ResultUnavailableError):
                    provider.authorize(
                        external, producer=world.fixture.producer, user_id="owner", conversation_id="conversation-1",
                    )

    def test_missing_or_untrusted_callbacks_fail_closed(self):
        with ExternalSourceWorld() as world:
            for callback in (None, lambda **_kwargs: {}, lambda **_kwargs: True):
                with self.subTest(callback=callback):
                    if callback is None:
                        with self.assertRaises(ResultContractError):
                            world.provider(read_identity=callback)
                    else:
                        provider = world.provider(read_identity=callback)
                        with self.assertRaises(ResultUnavailableError):
                            world.admit(provider)
            for override in (
                {"read_configuration": None},
                {"read_configuration": lambda *_args, **_kwargs: {}},
                {"read_settings": lambda: None},
            ):
                provider = world.provider(**override)
                with self.assertRaises(ResultUnavailableError):
                    world.admit(provider)
        for capability, option in (
            ("agent_invoke", "agent_catalog_reader"), ("action_invoke", "action_catalog_reader"),
            ("agent_invoke", "agent_resolver"), ("action_invoke", "action_resolver"),
        ):
            with self.subTest(capability=capability, option=option), ExternalSourceWorld(capability) as world:
                provider = world.provider(**{option: None})
                with self.assertRaises(ResultUnavailableError):
                    world.admit(provider)

    def test_saved_url_is_neither_a_selector_nor_permission_to_fetch(self):
        with ExternalSourceWorld("url_fetch") as world:
            provider = world.provider()
            with self.assertRaises(ResultContractError):
                provider.admit_gather_result(
                    producer=world.fixture.producer, prepared=world.prepared,
                    selector="https://public.example/page",
                )
            world.roles = ("User",)
            with self.assertRaises(ResultUnavailableError):
                world.admit(provider)
            with self.assertRaises(ResultContractError):
                ExternalSourceConfiguration("https://private.invalid?secret=synthetic-secret", "revision-1")

    def test_action_dictionary_claims_cannot_replace_a_server_authorized_origin(self):
        with ExternalSourceWorld("action_invoke") as world:
            catalog = world.catalog("owner", settings=world.settings)
            provider = world.provider(action_resolver=lambda *_args, **_kwargs: catalog[0])
            with self.assertRaises(ResultUnavailableError):
                world.admit(provider)

    def test_explicit_memory_reuses_only_the_recorded_scope_and_rechecks_membership(self):
        for scope_type, scope_id in (("user", "owner"), ("group", "group-a")):
            with self.subTest(scope=scope_type), ExternalSourceWorld("compose") as world:
                world.memory_scope(scope_type, scope_id)
                _provider, catalog, reference = world.save(memory=True)
                external = next(iter(catalog.values()))
                value = world.service(world.provider()).open_result(reference).read_value()
                self.assertEqual(value, world.prepared)
                self.assertEqual(external.source_type, "fact_memory")
                self.assertIsNone(external.source_revision)
                self.assertEqual(world.configuration_reads, [])
                if scope_type == "group":
                    world.services.roles.clear()
                else:
                    world.settings["enable_fact_memory_plugin"] = False
                with self.assertRaises(ResultUnavailableError):
                    world.service(world.provider()).open_result(reference)

    def test_memory_requires_explicit_scope_and_private_unchanged_audience(self):
        with ExternalSourceWorld("compose") as world:
            with self.assertRaises(ResultUnavailableError):
                world.admit(world.provider(), memory=True)
            world.memory_scope("user", "someone-else")
            with self.assertRaises(ResultUnavailableError):
                world.admit(world.provider(), memory=True)
            world.memory_scope()
            _provider, _catalog, reference = world.save(memory=True)
            world.fixture.conversation.update(
                is_hidden=True, conversation_kind="collaboration_source",
                collaboration_conversation_id="shared-chat",
            )
            with self.assertRaises(ResultUnavailableError):
                world.service(world.provider()).open_result(reference)

    def test_conversation_audience_changes_block_non_memory_sources_too(self):
        with ExternalSourceWorld() as world:
            _provider, _catalog, reference = world.save()
            world.fixture.conversation["is_hidden"] = True
            with self.assertRaises(ResultUnavailableError):
                world.service(world.provider()).open_result(reference)

    def test_frozen_aliases_are_required_for_new_writes_and_access_is_rechecked(self):
        with ExternalSourceWorld() as world:
            provider = world.provider()
            catalog = world.admit(provider)
            with self.assertRaises(ResultContractError):
                world.persist(world.service(provider), catalog)
            world.roles = ()
            with self.assertRaises(ResultUnavailableError):
                world.persist(world.service(provider, catalog), catalog)

    def test_late_admission_installs_bindings_on_live_access_not_constructor_input(self):
        with ExternalSourceWorld() as world:
            provider = world.provider()
            initial_catalog = {}
            service = world.service(provider, initial_catalog)
            admitted = world.admit(provider)
            initial_catalog.update(admitted)
            self.assertEqual(service.access.external_source_catalog, {})
            with self.assertRaises(ResultContractError):
                world.persist(service, admitted)
            service.access.external_source_catalog.update(admitted)
            task = world.persist(service, admitted)
            reference = task.output("prepared")
            value = service.open_result(reference).read_value()
            external = next(iter(admitted.values()))
            self.assertEqual(value, world.prepared)
            self.assertEqual(reference.content_sha256, external.content_sha256)

    def test_committed_receipt_recovery_rechecks_each_source_without_an_admission_catalog(self):
        for capability in (
            "web_search", "url_fetch", "deep_research", "agent_invoke", "action_invoke", "compose",
        ):
            with self.subTest(capability=capability), ExternalSourceWorld(capability) as world:
                memory = capability == "compose"
                if memory:
                    world.memory_scope("group", "group-a")
                provider = world.provider()
                catalog = world.admit(provider, memory=memory)
                service = world.service(provider, catalog)
                fingerprint = canonical_digest(world.run["plan"]["steps"][0])
                original = world.persist(
                    service, catalog, memory=memory, input_fingerprint=fingerprint,
                )
                reads_before = world.identity_reads
                restarted = world.service(world.provider())
                recovered = restarted.recover_task_result(
                    producer=world.fixture.producer, input_fingerprint=fingerprint,
                )
                self.assertEqual(recovered, original)
                self.assertEqual(restarted.access.external_source_catalog, {})
                self.assertGreater(world.identity_reads, reads_before)
                if not memory:
                    world.configuration_revision = "revision-2"
                    with self.assertRaises(ResultUnavailableError):
                        restarted.recover_task_result(
                            producer=world.fixture.producer, input_fingerprint=fingerprint,
                        )
                    world.configuration_revision = "revision-1"
                if capability in {"agent_invoke", "action_invoke", "compose"}:
                    world.services.roles.clear()
                elif capability in {"url_fetch", "deep_research"}:
                    world.roles = ("User",)
                else:
                    world.roles = ()
                with self.assertRaises(ResultUnavailableError):
                    restarted.recover_task_result(
                        producer=world.fixture.producer, input_fingerprint=fingerprint,
                    )

    def test_crash_after_external_commit_recovers_without_readmission_or_fetching(self):
        with ExternalSourceWorld("url_fetch") as world:
            provider = world.provider()
            catalog = world.admit(provider)
            service = world.service(provider, catalog)
            fingerprint = canonical_digest(world.run["plan"]["steps"][0])
            original_commit = service.store.commit_orchestration_result

            def commit_then_crash(*args, **kwargs):
                original_commit(*args, **kwargs)
                raise RuntimeError("Injected crash after external result commit")

            with patch.object(service.store, "commit_orchestration_result", commit_then_crash):
                with self.assertRaisesRegex(RuntimeError, "Injected crash"):
                    world.persist(service, catalog, input_fingerprint=fingerprint)
            world.run["status"] = "failed"
            current_provider = world.provider()
            with patch.object(
                current_provider, "admit_gather_result",
                side_effect=AssertionError("Recovery must not readmit a Gather result"),
            ):
                restarted = world.service(current_provider)
                recovered = restarted.recover_task_result(
                    producer=world.fixture.producer, input_fingerprint=fingerprint,
                )
                value = restarted.open_result(recovered.output("prepared")).read_value()
            self.assertEqual(value, world.prepared)
            self.assertEqual(restarted.access.external_source_catalog, {})
            self.assertEqual(world.fixture.container.queries, [])

    def test_wrong_owner_producer_and_changed_content_digest_are_not_authorized(self):
        with ExternalSourceWorld() as world:
            provider, catalog, _reference = world.save()
            external = next(iter(catalog.values()))
            for changed in (
                {"user_id": "someone-else"},
                {"conversation_id": "another-conversation"},
                {"producer": replace(world.fixture.producer, attempt_index=2)},
                {"reference": replace(external, content_sha256="a" * 64)},
                {"reference": replace(external, capability_id="url_fetch")},
            ):
                options = {
                    "reference": external, "producer": world.fixture.producer,
                    "user_id": "owner", "conversation_id": "conversation-1",
                    **changed,
                }
                with self.subTest(changed=changed), self.assertRaises(ResultUnavailableError):
                    provider.authorize(**options)

    def test_unsupported_payload_and_legacy_or_stopped_producer_are_refused(self):
        with ExternalSourceWorld() as world:
            provider = world.provider()
            for prepared in (
                {}, [], {**world.prepared, "capability_id": "agent_invoke"},
                {**world.prepared, "unserializable": object()},
            ):
                with self.subTest(prepared=prepared), self.assertRaises(ResultContractError):
                    provider.admit_gather_result(producer=world.fixture.producer, prepared=prepared)
            world.run["plan"]["planner_contract_version"] = 1
            with self.assertRaises(ResultUnavailableError):
                world.admit(provider)
            world.run["plan"]["planner_contract_version"] = 2
            world.run["cancellation_requested_at"] = "now"
            with self.assertRaises(ResultUnavailableError):
                world.admit(provider)

    def test_actual_fresh_process_reads_without_a_catalog_and_observes_role_revocation(self):
        with ExternalSourceWorld("url_fetch") as world:
            _provider, _catalog, reference = world.save()
            payload = json.dumps({
                "items": list(world.fixture.container.items.items()),
                "runs": world.fixture.runs, "conversation": world.fixture.conversation,
                "reference": reference.to_dict(), "prepared": world.prepared,
            })
        self._assert_fresh_process_access(payload)

    def test_actual_fresh_process_receipt_recovery_observes_current_role_revocation(self):
        with ExternalSourceWorld("url_fetch") as world:
            fingerprint = canonical_digest(world.run["plan"]["steps"][0])
            _provider, _catalog, reference = world.save(input_fingerprint=fingerprint)
            payload = json.dumps({
                "items": list(world.fixture.container.items.items()),
                "runs": world.fixture.runs, "conversation": world.fixture.conversation,
                "reference": reference.to_dict(), "prepared": world.prepared,
                "input_fingerprint": fingerprint,
            })
        self._assert_fresh_process_access(payload)

    def _assert_fresh_process_access(self, payload):
        for optimized in (False, True):
            for state in ("allowed", "revoked"):
                with self.subTest(optimized=optimized, state=state):
                    command = [sys.executable, "-B"] + (["-O"] if optimized else [])
                    result = subprocess.run(
                        command + ["-c", RESTART_PROBE, str(Path(__file__).resolve().parent), state],
                        input=payload, capture_output=True, text=True, cwd=ROOT, timeout=60, check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_cold_import_does_not_bootstrap_settings_routes_or_clients(self):
        for optimized in (False, True):
            with self.subTest(optimized=optimized):
                command = [sys.executable, "-B"] + (["-O"] if optimized else [])
                result = subprocess.run(
                    command + ["-c", IMPORT_PROBE, str(APP)], cwd=ROOT,
                    capture_output=True, text=True, timeout=60, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
