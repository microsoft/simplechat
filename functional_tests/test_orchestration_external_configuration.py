# test_orchestration_external_configuration.py
"""
Functional tests for opaque external invocation-configuration attestation.
Version: 0.261.139
Implemented in: 0.261.127
Single orchestration contract updated in: 0.261.139

Use real source-review normalization and configuration contracts. Owner metadata
I/O is doubled; no source fetch, model/tool invocation or client initialization.
Refs microsoft/simplechat#1509.
"""

from contextlib import ExitStack
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import hmac
import json
from pathlib import Path
import socket
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from azure.core.exceptions import HttpResponseError
from azure.ai.agents.models import Agent, BingGroundingTool, ThreadRun
from requests import Response
from requests.exceptions import ConnectionError, HTTPError, Timeout

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP))

from functions_orchestration_external_configuration import (
    EXTERNAL_ACQUISITION_VERSION,
    FOUNDRY_PINNED_REQUEST,
    ExternalConfigurationCancelledError,
    ExternalConfigurationServiceError,
    OrchestrationExternalConfigurationAttestor,
    foundry_definition_snapshot,
    foundry_run_snapshot,
    project_external_configuration,
)
from functions_action_catalog import _action_ref
from functions_action_manifest import McpActionOrigin, ScopedActionManifest
from functions_orchestration_external_sources import ExternalSourceConfiguration
from functions_orchestration_result_contracts import ProducerIdentity, ResultContractError
from functions_orchestration_results import ResultUnavailableError
from test_orchestration_external_sources import ExternalSourceWorld


def producer(capability="url_fetch", step_id="gather"):
    return ProducerIdentity("owner", "conversation", "run", 1, step_id, capability, "test-v2")


def private_digest(value):
    return hmac.new(b"synthetic-stable-configuration-key", value, hashlib.sha256).hexdigest()


def model_metadata():
    return {
        "provider": "aoai", "protocol": "azure_openai",
        "endpoint": "https://model.private.example", "api_version": "2025-01-01-preview",
        "deployment": "model-deployment", "endpoint_id": "endpoint-1", "model_id": "model-1",
        "parameters": {"temperature": 0.2, "max_completion_tokens": 2000},
    }


def web_settings():
    return {
        "enable_web_search": True,
        "web_search_agent": {"other_settings": {"azure_ai_foundry": {
            "agent_id": "agent-remote", "endpoint": "https://project.private.example/api/projects/project",
            "api_version": "2025-05-01", "authentication_type": "managed_identity",
        }}},
    }


def foundry_evidence(phase="run"):
    settings = web_settings()["web_search_agent"]["other_settings"]["azure_ai_foundry"]
    definition = {
        "id": "agent-remote", "model": "model-deployment", "instructions": "Use verified search results.",
        "tools": [{"type": "bing_grounding", "bing_grounding": {"search_configurations": [
            {"connection_id": "connection-1"},
        ]}}],
        "tool_resources": {}, "response_format": "auto", "temperature": 0.2, "top_p": 0.9,
    }
    result = {
        "version": EXTERNAL_ACQUISITION_VERSION, "kind": "foundry", "phase": phase,
        "endpoint": settings["endpoint"], "api_version": settings["api_version"],
        "foundry_settings": deepcopy(settings), "definition": definition,
        "overrides": {"max_completion_tokens": 2000},
    }
    if phase == "run":
        result["run"] = {
            **{key: value for key, value in definition.items() if key != "id"},
            "id": "run-remote", "thread_id": "thread-remote", "agent_id": "agent-remote",
            "max_completion_tokens": 2000,
        }
    return result


def pinned_foundry_evidence(phase="pinned"):
    source = foundry_evidence("definition")
    source.update(phase=phase, binding=FOUNDRY_PINNED_REQUEST)
    source["definition"] = foundry_definition_snapshot(
        Agent(source["definition"]), binding=FOUNDRY_PINNED_REQUEST,
    )
    if phase == "pinned":
        source["request"] = {
            "agent_id": source["definition"]["id"],
            **{key: value for key, value in source["definition"].items() if key != "id"},
            **source["overrides"],
        }
    return source


def agent_evidence(phase="resolved"):
    return {
        "version": EXTERNAL_ACQUISITION_VERSION, "kind": "agent", "phase": phase,
        "reference": {"id": "agent-1", "scope_type": "group", "scope_id": "group-a"},
        "resolved_config": {
            "id": "agent-1", "name": "Lookup", "agent_type": "local",
            "instructions": "Find the requested information.", "api_key": "synthetic-private-api-key",
            "deployment_name": "model-deployment",
        },
        "prepared_plugins": [], "model": model_metadata(),
    }


def action_evidence(phase="resolved"):
    reference = _action_ref("group", "group-a", "action-1")
    manifest = ScopedActionManifest({
        "id": "action-1", "type": "openapi", "name": "Lookup", "action_ref": reference,
        "scope_type": "group", "scope_id": "group-a", "endpoint": "https://action.private.example",
        "auth": {"type": "api_key", "api_key": "synthetic-private-action-key"},
        "openapi_spec": {"paths": {"/lookup": {"get": {"operationId": "lookup"}}}},
    }, McpActionOrigin("group", "group-a", "action-1"))
    return {
        "version": EXTERNAL_ACQUISITION_VERSION, "kind": "action", "phase": phase,
        "reference": {"id": "action-1", "scope_type": "group", "scope_id": "group-a"},
        "manifest": manifest, "prepared_manifest": deepcopy(manifest), "model": model_metadata(),
    }


def current_source(source):
    value = deepcopy(source)
    value["phase"] = "current"
    value.pop("run", None)
    value.pop("request", None)
    for name in ("web", "foundry"):
        if value.get(name) is not None:
            value[name] = current_source(value[name])
    return value


class ExternalConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(socket.socket, "connect", side_effect=AssertionError("No network")))
        self.stack.enter_context(patch.object(socket, "getaddrinfo", side_effect=AssertionError("No DNS")))
        self.addCleanup(self.stack.close)

    def attestor(self, **options):
        return OrchestrationExternalConfigurationAttestor(
            user_id="owner", conversation_id="conversation", private_digest=private_digest, **options,
        )

    def project(self, source_type, *, settings=None, source=None, selector=None):
        return project_external_configuration(
            source_type, settings={} if settings is None else settings,
            source=source, selector=selector, private_digest=private_digest,
        )

    def test_url_projection_is_source_specific_and_contains_only_opaque_tokens(self):
        settings = {
            "url_access_allowed_domains": ["private.example.test"],
            "source_review_timeout_seconds": 12,
            "azure_openai_gpt_key": "synthetic-sensitive-secret",
            "azure_openai_gpt_endpoint": "https://private.example.test/internal",
            "app_title": "An unrelated setting",
        }
        before = deepcopy(settings)
        config = project_external_configuration("url", settings=settings)
        changed = project_external_configuration(
            "url", settings={**settings, "_etag": "changed", "app_title": "Renamed",
                             "azure_openai_gpt_key": "rotated"},
        )
        wire = json.dumps(asdict(config))
        self.assertIs(type(config), ExternalSourceConfiguration)
        self.assertEqual(config, changed)
        self.assertEqual(settings, before)
        self.assertNotIn("private.example.test", wire)
        self.assertNotIn("secret", wire)
        self.assertNotIn("https:", wire)

    def test_url_projection_matches_effective_clamping_aliases_and_chat_only_behavior(self):
        normalized = project_external_configuration("url", settings={
            "source_review_timeout_seconds": 30,
            "url_access_allowed_domains": ["a.example", "b.example"],
            "url_access_max_chat_urls_per_turn": 3,
        })
        equivalent = project_external_configuration("url", settings={
            "source_review_timeout_seconds": 100,
            "source_review_allowed_domains": "B.EXAMPLE, a.example, a.example",
            "url_access_max_chat_urls_per_turn": "3",
            "url_access_max_workflow_urls_per_run": 500,
            "source_review_max_depth": 0,
            "source_review_enable_llm_planning": False,
            "deep_research_enable_ledger_artifact": False,
            "source_review_audit_logging": False,
        })
        self.assertEqual(normalized, equivalent)

    def test_acquisition_policy_changes_revoke_current_configuration(self):
        baseline = project_external_configuration("url", settings={})
        for field, value in (
            ("url_access_allowed_domains", ["only.example"]),
            ("url_access_blocked_domains", ["blocked.example"]),
            ("source_review_allow_internal_hosts", True),
            ("source_review_max_pages_per_turn", 2),
            ("source_review_max_seed_pages_per_turn", 2),
            ("source_review_timeout_seconds", 3),
            ("source_review_max_redirects", 0),
            ("source_review_max_bytes_per_page", 100000),
            ("source_review_allow_js_rendering", False),
            ("source_review_js_load_more_clicks", 0),
            ("source_review_respect_robots_txt", False),
            ("url_access_max_chat_urls_per_turn", 2),
        ):
            with self.subTest(field=field):
                current = project_external_configuration("url", settings={field: value})
                self.assertEqual(current.identity, baseline.identity)
                self.assertNotEqual(current.revision, baseline.revision)

    def test_new_admission_requires_original_capture_and_returns_it_not_a_replacement(self):
        proof = self.attestor()
        original = producer()
        with self.assertRaises(ResultUnavailableError):
            proof.for_admission("url", producer=original, settings={})
        proof.capture("url", producer=original, settings={})
        captured = proof.for_admission("url", producer=original, settings={})
        with self.assertRaises(ResultUnavailableError):
            proof.for_admission("url", producer=original, settings={"source_review_timeout_seconds": 3})
        after = proof.for_admission("url", producer=original, settings={})
        selector = proof.selector_for(original)
        self.assertIs(after, captured)
        self.assertIsNone(selector)

    def test_capture_records_are_immutable_proofs_not_raw_settings(self):
        proof = self.attestor()
        original = producer()
        settings = {"url_access_allowed_domains": ["private.example"], "credential": "synthetic-secret"}
        proof.capture("url", producer=original, settings=settings)
        before = json.dumps([asdict(value) for value in proof._captures.values()])
        settings["url_access_allowed_domains"].append("another.example")
        after = json.dumps([asdict(value) for value in proof._captures.values()])
        self.assertEqual(before, after)
        self.assertNotIn("private.example", before)
        self.assertNotIn("synthetic-secret", before)

    def test_recapture_cannot_hide_a_changed_invocation_even_after_config_reversion(self):
        proof = self.attestor()
        original = producer()
        proof.capture("url", producer=original, settings={})
        proof.capture("url", producer=original, settings={})
        with self.assertRaises(ResultUnavailableError):
            proof.capture("url", producer=original, settings={"source_review_max_redirects": 0})
        for settings in ({}, {"source_review_max_redirects": 0}):
            with self.assertRaises(ResultUnavailableError):
                proof.for_admission("url", producer=original, settings=settings)

    def test_current_and_restarted_reads_require_no_capture_map_or_source_refetch(self):
        metadata = Mock(side_effect=AssertionError("URL policy must not fetch metadata or a source"))
        first = self.attestor(read_current_source=metadata)
        first.capture("url", producer=producer(), settings={})
        admitted = first.for_admission("url", producer=producer(), settings={})
        restart = self.attestor(read_current_source=metadata)
        current = restart.current("url", producer=producer(), settings={})
        self.assertEqual(current, admitted)
        self.assertEqual(restart._captures, {})
        metadata.assert_not_called()
        with self.assertRaises(ResultUnavailableError):
            restart.for_admission("url", producer=producer(), settings={})

    def test_provider_uses_captured_url_policy_and_reads_after_restart_without_capture(self):
        with ExternalSourceWorld("url_fetch") as world:
            proof = OrchestrationExternalConfigurationAttestor(
                user_id="owner", conversation_id="conversation-1",
            )
            access = world.provider(
                read_configuration=proof.current, configuration_admitter=proof.for_admission,
            )
            with self.assertRaises(ResultUnavailableError):
                world.admit(access)
            proof.capture("url", producer=world.fixture.producer, settings=world.settings)
            aliases = world.admit(access)
            results = world.service(access, aliases)
            saved = world.persist(results, aliases)
            restarted = OrchestrationExternalConfigurationAttestor(
                user_id="owner", conversation_id="conversation-1",
            )
            current = world.provider(read_configuration=restarted.current, configuration_admitter=None)
            value = world.service(current).open_result(saved.output("prepared")).read_value()
            self.assertEqual(value, world.prepared)
            self.assertEqual(restarted._captures, {})
            world.settings["source_review_allow_internal_hosts"] = True
            with self.assertRaises(ResultUnavailableError):
                world.service(current).open_result(saved.output("prepared"))

    def test_capture_binding_checks_actor_conversation_step_attempt_and_capability(self):
        proof = self.attestor()
        original = producer()
        proof.capture("url", producer=original, settings={})
        for changed in (
            replace(original, user_id="someone-else"), replace(original, conversation_id="another-conversation"),
            replace(original, step_id="another-step"), replace(original, attempt_index=2),
            replace(original, run_id="another-run"), replace(original, capability_id="web_search"),
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(ResultUnavailableError):
                    proof.for_admission("url", producer=changed, settings={})

    def test_capture_bound_and_owner_execution_checks_fail_closed(self):
        proof = self.attestor(max_captures=1)
        proof.capture("url", producer=producer(), settings={})
        with self.assertRaises(ExternalConfigurationServiceError):
            proof.capture("url", producer=producer(step_id="second"), settings={})
        stopped = self.attestor(execution_check=lambda: False)
        with self.assertRaises(ExternalConfigurationCancelledError):
            stopped.capture("url", producer=producer(), settings={})
        with self.assertRaises(ResultContractError):
            self.attestor(max_captures=True)

    def test_url_source_cannot_be_invented_from_a_saved_fetch_url(self):
        for extra in ({"source": {"url": "https://private.example"}}, {"selector": "https://public.example"}):
            with self.subTest(extra=extra), self.assertRaises(ResultContractError):
                project_external_configuration("url", settings={}, **extra)
        for settings in (None, [], True):
            with self.subTest(settings=settings), self.assertRaises(ResultContractError):
                project_external_configuration("url", settings=settings)

    def test_current_metadata_denial_is_distinct_from_transient_service_failure(self):
        failures = [
            (PermissionError("sensitive-provider-text"), ResultUnavailableError, None),
            (Timeout("sensitive-provider-text"), ExternalConfigurationServiceError, True),
            (ConnectionError("sensitive-provider-text"), ExternalConfigurationServiceError, True),
            (ValueError("sensitive-provider-text"), ExternalConfigurationServiceError, False),
        ]
        for status in (400, 401, 403, 404, 410, 422, 429, 503):
            azure_error = HttpResponseError("sensitive-provider-text")
            azure_error.status_code = status
            response = Response()
            response.status_code = status
            http_error = HTTPError("sensitive-provider-text", response=response)
            denied = status in (401, 403, 404, 410)
            for error in (azure_error, http_error):
                failures.append((
                    error, ResultUnavailableError if denied else ExternalConfigurationServiceError,
                    None if denied else status == 429 or status >= 500,
                ))
        for failure, exception_type, retryable in failures:
            with self.subTest(error=type(failure).__name__, retryable=retryable):
                callback = Mock(side_effect=failure)
                proof = self.attestor(read_current_source=callback)
                with self.assertRaises(exception_type) as caught:
                    proof.current("web", producer=producer("web_search"), settings={})
                self.assertNotIn("sensitive-provider-text", str(caught.exception))
                self.assertIsNone(caught.exception.__cause__)
                self.assertIsNone(caught.exception.__context__)
                if retryable is not None:
                    self.assertIs(caught.exception.retryable, retryable)

    def test_owner_cancellation_and_lease_errors_are_not_reclassified_as_source_denial(self):
        for error in (ExternalConfigurationCancelledError(), InterruptedError("Stopped"), RuntimeError("Lease lost")):
            with self.subTest(error=type(error).__name__):
                proof = self.attestor(read_current_source=Mock(side_effect=error))
                with self.assertRaises(type(error)) as caught:
                    proof.current("web", producer=producer("web_search"), settings={})
                self.assertIs(caught.exception, error)

    def test_current_metadata_must_not_return_success_booleans_or_prebuilt_fingerprints(self):
        for returned in (None, True, [], ExternalSourceConfiguration("identity", "revision")):
            with self.subTest(returned=returned):
                proof = self.attestor(read_current_source=lambda *_args, **_kwargs: returned)
                with self.assertRaises(ExternalConfigurationServiceError) as caught:
                    proof.current("web", producer=producer("web_search"), settings={})
                self.assertEqual(caught.exception.code, "external_configuration_metadata_invalid")
                self.assertFalse(caught.exception.retryable)

    def test_web_prepare_and_definition_do_not_prove_actual_execution(self):
        settings = web_settings()
        metadata = Mock(return_value=foundry_evidence("current"))
        proof = self.attestor(read_current_source=metadata)
        owner = producer("web_search")
        proof.capture("web", producer=owner, settings=settings)
        with self.assertRaises(ResultUnavailableError):
            proof.for_admission("web", producer=owner, settings=settings)
        proof.capture("web", producer=owner, settings=settings, source=foundry_evidence("definition"))
        with self.assertRaises(ResultUnavailableError):
            proof.for_admission("web", producer=owner, settings=settings)
        proof.capture("web", producer=owner, settings=settings, source=foundry_evidence())
        saved = proof.for_admission("web", producer=owner, settings=settings)
        restarted = self.attestor(read_current_source=metadata)
        now = restarted.current("web", producer=owner, settings=settings)
        self.assertEqual(saved, now)
        self.assertEqual(restarted._captures, {})
        self.assertEqual(metadata.call_count, 2)

    def test_each_new_foundry_invocation_requires_its_own_matching_run(self):
        settings = web_settings()
        proof = self.attestor(read_current_source=lambda *_args, **_kwargs: foundry_evidence("current"))
        owner = producer("web_search")
        proof.capture("web", producer=owner, settings=settings, source=foundry_evidence())
        proof.capture("web", producer=owner, settings=settings, source=foundry_evidence("definition"))
        with self.assertRaises(ResultUnavailableError):
            proof.for_admission("web", producer=owner, settings=settings)
        another = foundry_evidence()
        another["run"].update(id="another-run", thread_id="another-thread")
        proof.capture("web", producer=owner, settings=settings, source=another)
        admitted = proof.for_admission("web", producer=owner, settings=settings)
        self.assertIs(type(admitted), ExternalSourceConfiguration)

    def test_foundry_run_mismatch_or_missing_snapshot_cannot_poison_a_success_into_authority(self):
        for field, value in (
            ("agent_id", "wrong-agent"), ("model", "different-model"), ("instructions", "Changed instructions."),
            ("tools", []), ("tool_resources", {"file_search": {"vector_store_ids": ["different"]}}),
            ("temperature", 1), ("top_p", 0.2), ("max_completion_tokens", 100),
        ):
            with self.subTest(field=field):
                settings = web_settings()
                proof = self.attestor(read_current_source=lambda *_args, **_kwargs: foundry_evidence("current"))
                owner = producer("web_search")
                proof.capture("web", producer=owner, settings=settings, source=foundry_evidence())
                changed = foundry_evidence()
                changed["run"][field] = value
                with self.assertRaises(ResultUnavailableError):
                    proof.capture("web", producer=owner, settings=settings, source=changed)
                with self.assertRaises(ResultUnavailableError):
                    proof.for_admission("web", producer=owner, settings=settings)
        missing = foundry_evidence()
        del missing["run"]["tool_resources"]
        with self.assertRaises(ResultUnavailableError):
            self.attestor().capture("web", producer=producer("web_search"), settings=web_settings(), source=missing)

    def test_changed_definition_between_runs_is_sticky_and_not_replaced(self):
        proof = self.attestor()
        owner = producer("web_search")
        first = foundry_evidence()
        proof.capture("web", producer=owner, settings=web_settings(), source=first)
        changed = foundry_evidence()
        changed["definition"]["instructions"] = "A different search policy."
        changed["run"]["instructions"] = changed["definition"]["instructions"]
        with self.assertRaises(ResultUnavailableError):
            proof.capture("web", producer=owner, settings=web_settings(), source=changed)
        with self.assertRaises(ResultUnavailableError):
            proof.capture("web", producer=owner, settings=web_settings(), source=first)

    def test_web_current_revision_tracks_actual_definition_and_effective_config_only(self):
        original = foundry_evidence("current")
        baseline = self.project("web", settings=web_settings(), source=original)
        unrelated = deepcopy(original)
        unrelated["definition"].update(name="Renamed", metadata={"description": "Updated"}, created_at=1)
        unchanged = self.project("web", settings={**web_settings(), "_etag": "changed", "app_title": "Renamed"}, source=unrelated)
        self.assertEqual(baseline, unchanged)
        for name, value in (("instructions", "Changed"), ("tools", []), ("model", "new-model")):
            changed = deepcopy(original)
            changed["definition"][name] = value
            revision = self.project("web", settings=web_settings(), source=changed)
            self.assertNotEqual(revision.revision, baseline.revision)

    def test_private_configuration_requires_a_stable_keyed_digest_and_never_persists_secrets(self):
        evidence = agent_evidence()
        selector = "group:group-a:agent-1"
        with self.assertRaises(ResultUnavailableError):
            project_external_configuration("agent", settings={}, source=evidence, selector=selector)
        proof = self.attestor()
        proof.capture("agent", producer=producer("agent_invoke"), settings={}, source=evidence, selector=selector)
        wire = json.dumps([asdict(value) for value in proof._captures.values()])
        self.assertNotIn("synthetic-private-api-key", wire)
        self.assertNotIn("model.private.example", wire)
        self.assertNotIn("Find the requested information", wire)
        changed = deepcopy(evidence)
        changed["resolved_config"]["api_key"] = "rotated-secret"
        first = self.project("agent", source=evidence, selector=selector)
        second = self.project("agent", source=changed, selector=selector)
        self.assertNotEqual(first.revision, second.revision)
        with self.assertRaises(ResultContractError):
            project_external_configuration("agent", settings={}, source=evidence, selector=selector, private_digest=lambda _: True)

    def test_action_requires_actual_scoped_manifest_prepared_configuration_and_model(self):
        evidence = action_evidence()
        selector = evidence["manifest"]["action_ref"]
        current = current_source(evidence)
        proof = self.attestor(read_current_source=lambda *_args, **_kwargs: deepcopy(current))
        owner = producer("action_invoke")
        proof.capture("action", producer=owner, settings={}, source=evidence, selector=selector)
        admitted = proof.for_admission("action", producer=owner, settings={}, source=evidence["manifest"], selector=selector)
        restarted = self.attestor(read_current_source=lambda *_args, **_kwargs: deepcopy(current))
        restored = restarted.current("action", producer=owner, settings={}, source=evidence["manifest"])
        self.assertEqual(admitted, restored)
        for field in ("manifest", "prepared_manifest", "model"):
            missing = deepcopy(evidence)
            del missing[field]
            with self.subTest(field=field), self.assertRaises((ResultUnavailableError, ExternalConfigurationServiceError)):
                self.project("action", source=missing, selector=selector)
        forged = deepcopy(evidence)
        forged["manifest"] = dict(forged["manifest"])
        with self.assertRaises(ResultUnavailableError):
            self.project("action", source=forged, selector=selector)

    def test_actual_agent_or_action_re_resolution_cannot_change_selected_identity_or_config(self):
        for kind, capability, source, selector in (
            ("agent", "agent_invoke", agent_evidence(), "group:group-a:agent-1"),
            ("action", "action_invoke", action_evidence(), _action_ref("group", "group-a", "action-1")),
        ):
            with self.subTest(kind=kind):
                proof = self.attestor()
                owner = producer(capability)
                proof.capture(kind, producer=owner, settings={}, source=source, selector=selector)
                changed = deepcopy(source)
                if kind == "agent":
                    changed["resolved_config"]["instructions"] = "Changed"
                else:
                    changed["prepared_manifest"]["endpoint"] = "https://changed.private.example"
                with self.assertRaises(ResultUnavailableError):
                    proof.capture(kind, producer=owner, settings={}, source=changed, selector=selector)
                with self.assertRaises(ResultUnavailableError):
                    proof.selector_for(owner)

    def test_agent_foundry_requires_root_selection_and_remote_run_proof(self):
        proof = self.attestor()
        owner = producer("agent_invoke")
        selector = "group:group-a:agent-1"
        root = agent_evidence()
        root["resolved_config"]["agent_type"] = "aifoundry"
        root.pop("model")
        root.pop("prepared_plugins")
        proof.capture("agent", producer=owner, settings={}, source=root, selector=selector)
        with self.assertRaises(ResultUnavailableError):
            proof.selector_for(owner)
        proof.capture("agent", producer=owner, settings={}, source=foundry_evidence("definition"), selector=selector)
        with self.assertRaises(ResultUnavailableError):
            proof.selector_for(owner)
        proof.capture("agent", producer=owner, settings={}, source=foundry_evidence(), selector=selector)
        selected = proof.selector_for(owner)
        composite = {**root, "foundry": foundry_evidence("current"), "phase": "current"}
        current = self.attestor(read_current_source=lambda *_args, **_kwargs: composite)
        configuration = current.current(
            "agent", producer=owner, settings={}, source={**root["reference"], "agent_type": "aifoundry"},
        )
        self.assertEqual(selected, selector)
        self.assertEqual(configuration, proof._captured(owner).configuration)

    def test_research_requires_actual_planner_construction_and_every_enabled_component(self):
        for web_enabled in (False, True):
            with self.subTest(web=web_enabled):
                settings = {**web_settings(), "enable_web_search": web_enabled}
                proof = self.attestor()
                owner = producer("deep_research")
                proof.capture("deep_research", producer=owner, settings=settings)
                with self.assertRaises(ResultUnavailableError):
                    proof.selector_for(owner)
                planner = {
                    "version": EXTERNAL_ACQUISITION_VERSION, "kind": "planner", "phase": "resolved",
                    "model": model_metadata(),
                }
                proof.capture("deep_research", producer=owner, settings=settings, source=planner)
                if web_enabled:
                    with self.assertRaises(ResultUnavailableError):
                        proof.selector_for(owner)
                    proof.capture("deep_research", producer=owner, settings=settings, source=foundry_evidence())
                current_payload = {
                    "version": EXTERNAL_ACQUISITION_VERSION, "kind": "deep_research", "phase": "current",
                    "model": model_metadata(), "web": foundry_evidence("current") if web_enabled else None,
                }
                current = self.attestor(read_current_source=lambda *_args, **_kwargs: deepcopy(current_payload))
                restored = current.current("deep_research", producer=owner, settings=settings)
                self.assertEqual(restored, proof._captured(owner).configuration)

    def test_no_display_name_dynamic_child_or_current_snapshot_can_be_invocation_proof(self):
        source = agent_evidence()
        for selector, changes in (
            ("Lookup", {}), ("group:group-a:agent-1", {"phase": "current"}),
            ("group:group-a:agent-1", {"dependencies": [{"selector": "another-agent"}]}),
        ):
            with self.subTest(selector=selector, changes=changes), self.assertRaises(ResultUnavailableError):
                self.attestor().capture(
                    "agent", producer=producer("agent_invoke"), settings={},
                    source={**source, **changes}, selector=selector,
                )

    def test_current_metadata_cannot_recycle_an_invocation_snapshot(self):
        proof = self.attestor(read_current_source=lambda *_args, **_kwargs: foundry_evidence())
        with self.assertRaises(ExternalConfigurationServiceError):
            proof.current("web", producer=producer("web_search"), settings=web_settings())

    def test_composite_current_metadata_rejects_nested_run_or_preparation_evidence(self):
        for remote in (foundry_evidence(), foundry_evidence("definition"), {
            **foundry_evidence(), "phase": "current",
        }):
            with self.subTest(phase=remote["phase"]):
                composite = {
                    "version": EXTERNAL_ACQUISITION_VERSION, "kind": "deep_research", "phase": "current",
                    "model": model_metadata(), "web": remote,
                }
                proof = self.attestor(read_current_source=lambda *_args, **_kwargs: composite)
                with self.assertRaises(ExternalConfigurationServiceError):
                    proof.current("deep_research", producer=producer("deep_research"), settings=web_settings())
        stale = {**foundry_evidence(), "phase": "current"}
        proof = self.attestor(read_current_source=lambda *_args, **_kwargs: stale)
        with self.assertRaises(ExternalConfigurationServiceError):
            proof.current("web", producer=producer("web_search"), settings=web_settings())

    def test_foundry_observed_endpoint_and_api_version_must_match_explicit_configuration(self):
        for field, value in (("endpoint", "https://another.private.example"), ("api_version", "2024-01-01")):
            with self.subTest(field=field):
                source = foundry_evidence()
                source[field] = value
                with self.assertRaises(ResultUnavailableError):
                    self.attestor().capture("web", producer=producer("web_search"), settings=web_settings(), source=source)
        normalized = foundry_evidence("current")
        normalized["endpoint"] = "https://PROJECT.PRIVATE.EXAMPLE:443/api/projects/project/"
        first = self.project("web", settings=web_settings(), source=foundry_evidence("current"))
        second = self.project("web", settings=web_settings(), source=normalized)
        self.assertEqual(first, second)

    def test_foundry_run_comparison_normalizes_numbers_without_boolean_coercion(self):
        evidence = foundry_evidence()
        evidence["overrides"]["temperature"] = 0
        evidence["run"]["temperature"] = 0.0
        proof = self.attestor()
        proof.capture("web", producer=producer("web_search"), settings=web_settings(), source=evidence)
        selector = proof.selector_for(producer("web_search"))
        self.assertIsNone(selector)
        wrong = foundry_evidence()
        wrong["overrides"]["max_completion_tokens"] = 1
        wrong["run"]["max_completion_tokens"] = True
        with self.assertRaises(ResultUnavailableError):
            self.attestor().capture("web", producer=producer("web_search"), settings=web_settings(), source=wrong)

    def test_capture_selectors_and_dependency_shapes_are_bounded_and_typed(self):
        for source_type, capability in (("web", "web_search"), ("deep_research", "deep_research")):
            with self.subTest(source_type=source_type), self.assertRaises(ResultContractError):
                self.attestor().capture(source_type, producer=producer(capability), settings=web_settings(), selector="invented")
        for value in (False, None, {}, "child"):
            with self.subTest(dependencies=value), self.assertRaises(ExternalConfigurationServiceError):
                self.attestor().capture(
                    "agent", producer=producer("agent_invoke"), settings={},
                    source={**agent_evidence(), "dependencies": value}, selector="group:group-a:agent-1",
                )
        for selector in (None, True, "x" * 2049):
            with self.subTest(selector=type(selector).__name__), self.assertRaises((
                ResultContractError, ExternalConfigurationServiceError,
            )):
                self.attestor().capture(
                    "agent", producer=producer("agent_invoke"), settings={},
                    source=agent_evidence(), selector=selector,
                )

    def test_capture_preserves_supported_long_stored_integration_ids(self):
        stored_id = "a" * 1023
        agent = agent_evidence()
        agent["reference"]["id"] = stored_id
        agent["resolved_config"]["id"] = stored_id
        action = action_evidence()
        action["reference"]["id"] = stored_id
        action_selector = _action_ref("group", "group-a", stored_id)
        action["manifest"] = ScopedActionManifest(
            {**action["manifest"], "id": stored_id, "action_ref": action_selector},
            McpActionOrigin("group", "group-a", stored_id),
        )
        action["prepared_manifest"] = deepcopy(action["manifest"])
        for kind, capability, source, selector in (
            ("agent", "agent_invoke", agent, f"group:group-a:{stored_id}"),
            ("action", "action_invoke", action, action_selector),
        ):
            with self.subTest(kind=kind):
                proof = self.attestor()
                owner = producer(capability)
                proof.capture(kind, producer=owner, settings={}, source=source, selector=selector)
                captured_selector = proof.selector_for(owner)
                self.assertEqual(captured_selector, selector)

    def test_real_foundry_sdk_snapshots_are_normalized_without_inventing_missing_fields(self):
        evidence = foundry_evidence()
        definition = Agent(evidence["definition"])
        run_data = deepcopy(evidence["run"])
        run_data["assistant_id"] = run_data.pop("agent_id")
        run = ThreadRun(run_data)
        definition_value = foundry_definition_snapshot(definition)
        run_value = foundry_run_snapshot(run)
        self.assertEqual(definition_value, evidence["definition"])
        self.assertEqual(run_value, evidence["run"])
        evidence.update(definition=definition_value, run=run_value)
        proof = self.attestor()
        proof.capture("web", producer=producer("web_search"), settings=web_settings(), source=evidence)
        with self.assertRaises(ResultUnavailableError):
            foundry_definition_snapshot(Agent({"id": "agent-remote", "model": "deployment"}))
        with self.assertRaises(ResultUnavailableError):
            foundry_run_snapshot(ThreadRun({"id": "run", "thread_id": "thread", "assistant_id": "agent-remote"}))
        with self.assertRaises(ResultUnavailableError):
            foundry_run_snapshot({"id": "invented-from-a-message"})

    def test_pinned_sdk_definition_omits_unused_resources_without_inventing_run_fields(self):
        raw = foundry_evidence("definition")["definition"]
        raw.pop("tool_resources")
        definition = Agent(raw)
        with self.assertRaises(ResultUnavailableError):
            foundry_definition_snapshot(definition)
        pinned = foundry_definition_snapshot(definition, binding=FOUNDRY_PINNED_REQUEST)
        self.assertEqual(pinned, raw)
        self.assertNotIn("tool_resources", pinned)
        self.assertNotIn("thread_id", pinned)

    def test_pinned_request_uses_actual_explicit_overrides_for_absent_definition_fields(self):
        source = pinned_foundry_evidence()
        source["definition"] = foundry_definition_snapshot(Agent({
            "id": "agent-remote", "model": "model-deployment",
            "tools": [item.as_dict() for item in BingGroundingTool(connection_id="connection-1").definitions],
        }), binding=FOUNDRY_PINNED_REQUEST)
        source["overrides"].update(
            instructions_override="Actual configured instructions.", response_format="auto",
            temperature=0.2, top_p=0.9,
        )
        source["request"].update(
            instructions=source["overrides"]["instructions_override"],
            tools=deepcopy(source["definition"]["tools"]),
        )
        for name in ("instructions", "temperature", "top_p", "response_format"):
            self.assertNotIn(name, source["definition"])
        current_metadata = current_source(source)
        proof = self.attestor(read_current_source=lambda *_args, **_kwargs: deepcopy(current_metadata))
        owner = producer("web_search")
        proof.capture("web", producer=owner, settings=web_settings(), source=source)
        configuration = proof.for_admission("web", producer=owner, settings=web_settings())
        self.assertIs(type(configuration), ExternalSourceConfiguration)
        del source["overrides"]["response_format"]
        with self.assertRaises(ResultUnavailableError):
            self.attestor().capture("web", producer=owner, settings=web_settings(), source=source)

    def test_fully_pinned_request_is_admissible_without_a_run_or_live_restart_capture(self):
        source = pinned_foundry_evidence()
        metadata = current_source(source)
        proof = self.attestor(read_current_source=lambda *_args, **_kwargs: deepcopy(metadata))
        owner = producer("web_search")
        proof.capture("web", producer=owner, settings=web_settings(), source=pinned_foundry_evidence("definition"))
        with self.assertRaises(ResultUnavailableError):
            proof.for_admission("web", producer=owner, settings=web_settings())
        proof.capture("web", producer=owner, settings=web_settings(), source=source)
        admitted = proof.for_admission("web", producer=owner, settings=web_settings())
        restarted = self.attestor(read_current_source=lambda *_args, **_kwargs: deepcopy(metadata))
        current = restarted.current("web", producer=owner, settings=web_settings())
        self.assertEqual(admitted, current)
        self.assertEqual(restarted._captures, {})
        private_map = json.dumps([asdict(value) for value in proof._captures.values()])
        self.assertNotIn("project.private.example", private_map)
        self.assertNotIn("Use verified search results", private_map)
        self.assertNotIn("connection-1", private_map)

    def test_pinned_request_must_match_all_transmitted_configuration_and_options(self):
        for field, value in (
            ("agent_id", "other-agent"), ("model", "other-model"), ("instructions", "Other instructions"),
            ("tools", [{"type": "bing_grounding", "bing_grounding": {"search_configurations": []}}]),
            ("response_format", "json_object"), ("temperature", 0.8), ("top_p", 0.5),
            ("max_completion_tokens", 1000), ("tool_choice", "auto"),
        ):
            with self.subTest(field=field):
                source = pinned_foundry_evidence()
                source["request"][field] = value
                with self.assertRaises(ResultUnavailableError):
                    self.attestor().capture(
                        "web", producer=producer("web_search"), settings=web_settings(), source=source,
                    )
        for field in pinned_foundry_evidence()["request"]:
            with self.subTest(missing=field):
                source = pinned_foundry_evidence()
                del source["request"][field]
                with self.assertRaises((ResultUnavailableError, ExternalConfigurationServiceError)):
                    self.attestor().capture(
                        "web", producer=producer("web_search"), settings=web_settings(), source=source,
                    )

    def test_pinned_configuration_refuses_nullable_or_empty_inherited_fields(self):
        for field, values in (
            ("instructions", (None, "")), ("tools", ([],)),
            ("response_format", (None, "", {})), ("temperature", (None,)), ("top_p", (None,)),
        ):
            for value in values:
                with self.subTest(field=field, value=value):
                    source = pinned_foundry_evidence()
                    source["definition"][field] = value
                    source["request"][field] = value
                    with self.assertRaises(ResultUnavailableError):
                        self.attestor().capture(
                            "web", producer=producer("web_search"), settings=web_settings(), source=source,
                        )
        source = pinned_foundry_evidence()
        for field in ("temperature", "top_p"):
            source["definition"][field] = 0
            source["request"][field] = 0.0
        proof = self.attestor()
        proof.capture("web", producer=producer("web_search"), settings=web_settings(), source=source)
        selector = proof.selector_for(producer("web_search"))
        self.assertIsNone(selector)

    def test_pinned_configuration_refuses_resource_tools_and_unrepresented_runtime_overrides(self):
        for tool in ("file_search", "code_interpreter", "function", "openapi", "bing_custom_search"):
            with self.subTest(tool=tool):
                source = pinned_foundry_evidence()
                source["definition"]["tools"] = [{"type": tool}]
                source["request"]["tools"] = [{"type": tool}]
                with self.assertRaises(ResultUnavailableError):
                    self.attestor().capture(
                        "web", producer=producer("web_search"), settings=web_settings(), source=source,
                    )
        for location in ("definition", "request", "overrides"):
            with self.subTest(location=location):
                source = pinned_foundry_evidence()
                source[location]["tool_resources"] = {"file_search": {"vector_store_ids": ["mutable-store"]}}
                with self.assertRaises(ResultUnavailableError):
                    self.attestor().capture(
                        "web", producer=producer("web_search"), settings=web_settings(), source=source,
                    )
        for field in ("additional_instructions", "additional_messages", "credentials"):
            with self.subTest(field=field):
                source = pinned_foundry_evidence()
                source["request"][field] = "unrepresented-runtime-value"
                with self.assertRaises(ResultUnavailableError):
                    self.attestor().capture(
                        "web", producer=producer("web_search"), settings=web_settings(), source=source,
                    )

    def test_pinned_bing_configuration_requires_actual_bounded_connection_parameters(self):
        for tool in (
            {"type": "bing_grounding"},
            {"type": "bing_grounding", "bing_grounding": {"search_configurations": []}},
            {"type": "bing_grounding", "bing_grounding": {"search_configurations": [{}]}},
            {"type": "bing_grounding", "bing_grounding": {"search_configurations": [{
                "connection_id": "connection-1", "count": True,
            }]}},
            {"type": "bing_grounding", "bing_grounding": {"search_configurations": [{
                "connection_id": "connection-1", "inherited_agent_resource": True,
            }]}},
        ):
            with self.subTest(tool=tool):
                source = pinned_foundry_evidence()
                source["definition"]["tools"] = [tool]
                source["request"]["tools"] = [tool]
                with self.assertRaises((ResultUnavailableError, ExternalConfigurationServiceError)):
                    self.attestor().capture(
                        "web", producer=producer("web_search"), settings=web_settings(), source=source,
                    )

    def test_caught_pinned_capture_failures_remain_sticky(self):
        source = pinned_foundry_evidence()
        metadata = current_source(source)
        proof = self.attestor(read_current_source=lambda *_args, **_kwargs: metadata)
        owner = producer("web_search")
        proof.capture("web", producer=owner, settings=web_settings(), source=source)
        changed = deepcopy(source)
        changed["request"]["instructions"] = "Changed after configuration capture."
        with self.assertRaises(ResultUnavailableError):
            proof.capture("web", producer=owner, settings=web_settings(), source=changed)
        with self.assertRaises(ResultUnavailableError):
            proof.for_admission("web", producer=owner, settings=web_settings())
        with self.assertRaises(ResultUnavailableError):
            proof.capture("web", producer=owner, settings=web_settings(), source=source)

    def test_pinned_current_metadata_cannot_recycle_requests_and_modes_are_not_interchangeable(self):
        stale = {**pinned_foundry_evidence(), "phase": "current"}
        proof = self.attestor(read_current_source=lambda *_args, **_kwargs: stale)
        with self.assertRaises(ExternalConfigurationServiceError):
            proof.current("web", producer=producer("web_search"), settings=web_settings())
        for changes in ({"binding": "foundry-application-v1"}, {"binding": "observed-run-v1"}, {"phase": "run"}):
            with self.subTest(changes=changes), self.assertRaises(ResultUnavailableError):
                self.attestor().capture(
                    "web", producer=producer("web_search"), settings=web_settings(),
                    source={**pinned_foundry_evidence(), **changes},
                )

    def test_pinned_web_persists_exact_content_and_reauthorizes_after_restart(self):
        with ExternalSourceWorld("web_search") as world:
            world.settings.update(web_settings())
            metadata = pinned_foundry_evidence("current")
            proof = OrchestrationExternalConfigurationAttestor(
                user_id="owner", conversation_id="conversation-1", private_digest=private_digest,
                read_current_source=lambda *_args, **_kwargs: deepcopy(metadata),
            )
            access = world.provider(read_configuration=proof.current, configuration_admitter=proof.for_admission)
            proof.capture("web", producer=world.fixture.producer, settings=world.settings, source=pinned_foundry_evidence())
            aliases = world.admit(access)
            saved = world.persist(world.service(access, aliases), aliases)
            restarted = OrchestrationExternalConfigurationAttestor(
                user_id="owner", conversation_id="conversation-1", private_digest=private_digest,
                read_current_source=lambda *_args, **_kwargs: deepcopy(metadata),
            )
            reader = world.provider(read_configuration=restarted.current, configuration_admitter=None)
            value = world.service(reader).open_result(saved.output("prepared")).read_value()
            self.assertEqual(value, world.prepared)
            self.assertEqual(restarted._captures, {})
            metadata["definition"]["instructions"] = "A changed remote definition."
            with self.assertRaises(ResultUnavailableError):
                world.service(reader).open_result(saved.output("prepared"))

    def test_web_retained_result_uses_real_provider_capture_and_capture_free_current_metadata(self):
        with ExternalSourceWorld("web_search") as world:
            world.settings.update(web_settings())
            metadata = foundry_evidence("current")
            actual_producer = world.fixture.producer
            proof = OrchestrationExternalConfigurationAttestor(
                user_id="owner", conversation_id="conversation-1", private_digest=private_digest,
                read_current_source=lambda *_args, **_kwargs: deepcopy(metadata),
            )
            access = world.provider(read_configuration=proof.current, configuration_admitter=proof.for_admission)
            proof.capture("web", producer=actual_producer, settings=world.settings)
            with self.assertRaises(ResultUnavailableError):
                world.admit(access)
            proof.capture("web", producer=actual_producer, settings=world.settings, source=foundry_evidence())
            aliases = world.admit(access)
            results = world.service(access, aliases)
            saved = world.persist(results, aliases)
            restarted = OrchestrationExternalConfigurationAttestor(
                user_id="owner", conversation_id="conversation-1", private_digest=private_digest,
                read_current_source=lambda *_args, **_kwargs: deepcopy(metadata),
            )
            reader = world.provider(read_configuration=restarted.current, configuration_admitter=None)
            value = world.service(reader).open_result(saved.output("prepared")).read_value()
            self.assertEqual(value, world.prepared)
            self.assertEqual(restarted._captures, {})
            metadata["definition"]["instructions"] = "A changed remote definition."
            with self.assertRaises(ResultUnavailableError):
                world.service(reader).open_result(saved.output("prepared"))

    def test_real_module_cold_import_and_restart_without_clients_in_normal_and_optimized_python(self):
        for optimized in (False, True):
            with self.subTest(optimized=optimized):
                command = [sys.executable, "-B"] + (["-O"] if optimized else [])
                result = subprocess.run(
                    command + ["-c", CONFIGURATION_PROCESS_PROBE, str(APP), str(Path(__file__).resolve().parent)],
                    capture_output=True, text=True, cwd=ROOT, timeout=60, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


CONFIGURATION_PROCESS_PROBE = r"""
import builtins
from contextlib import ExitStack
import importlib
import socket
import sys
from unittest.mock import patch

sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
original_import = builtins.__import__

def checked_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level == 0 and (
        name in {"config", "functions_settings", "functions_authentication", "semantic_kernel_loader"}
        or name.startswith("route_")
    ):
        raise AssertionError("Configuration projection discovered an application owner")
    return original_import(name, globals, locals, fromlist, level)

def no_io(*args, **kwargs):
    raise AssertionError("Unexpected I/O or credential/client construction")

with (
    patch.object(socket.socket, "connect", no_io),
    patch.object(socket, "getaddrinfo", no_io),
    patch.object(builtins, "__import__", checked_import),
):
    import azure.identity
    import requests

    with ExitStack() as constructors:
        for name, credential in vars(azure.identity).items():
            if name.endswith("Credential") and isinstance(credential, type):
                constructors.enter_context(patch.object(credential, "__init__", no_io))
        constructors.enter_context(patch.object(requests.Session, "__init__", no_io))
        module = importlib.import_module("functions_orchestration_external_configuration")
    fixtures = importlib.import_module("test_orchestration_external_configuration")
    source = fixtures.foundry_evidence()
    settings = fixtures.web_settings()
    producer = fixtures.producer("web_search")
    callbacks = {
        "user_id": "owner", "conversation_id": "conversation",
        "private_digest": fixtures.private_digest,
        "read_current_source": lambda *args, **kwargs: fixtures.current_source(source),
    }
    original = module.OrchestrationExternalConfigurationAttestor(**callbacks)
    original.capture("web", producer=producer, settings=settings, source=source)
    captured = original.for_admission("web", producer=producer, settings=settings)
    restarted = module.OrchestrationExternalConfigurationAttestor(**callbacks)
    current = restarted.current("web", producer=producer, settings=settings)
    if current != captured or restarted._captures:
        raise AssertionError("Restart required or reused live capture state")
    source["definition"]["instructions"] = "A revoked configuration"
    changed = restarted.current("web", producer=producer, settings=settings)
    if changed == captured:
        raise AssertionError("Required current configuration read was skipped")
"""

if __name__ == "__main__":
    unittest.main()
