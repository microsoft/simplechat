# functions_orchestration_external_sources.py
"""Server admission and current access for retained external content.

Version: 0.261.127

No fetch, recall, plugin invocation, settings discovery, or credential persistence
occurs here. Content digests attest the exact retained payload, not a remote page
revision. Committed result lineage supplies the binding after a process restart.
"""

from dataclasses import dataclass
import hashlib
import re

from functions_action_catalog import resolve_action_manifest
from functions_action_manifest import get_action_origin
from functions_agent_delegation import agent_reference, resolve_delegation_agent
from functions_orchestration_context import (
    build_capability_request_context,
    conversation_user_urls,
    resolve_action_catalog,
    resolve_agent_catalog,
    validate_clarification_answers,
)
from functions_orchestration_memory import (
    OrchestrationMemoryError,
    validate_memory_audience,
    validate_memory_context,
)
from functions_orchestration_registry import resolve_available_capability_ids
from functions_orchestration_result_contracts import (
    ExternalSourceRef,
    ProducerIdentity,
    ResultContractError,
    canonical_bytes,
    canonical_digest,
    identifier,
)
from functions_orchestration_results import (
    MAX_VALUE_BYTES,
    OrchestrationResultAccess,
    ResultUnavailableError,
)


_GATHER_SOURCES = {
    "web_search": "web",
    "url_fetch": "url",
    "deep_research": "deep_research",
    "agent_invoke": "agent",
    "action_invoke": "action",
}
_REQUIRED_SETTINGS = {
    "web": ("enable_web_search",),
    "url": ("enable_url_access",),
    "deep_research": ("enable_source_review",),
    "agent": ("enable_semantic_kernel",),
    "action": (
        "enable_chat_orchestration", "enable_semantic_kernel", "enable_chat_orchestration_actions",
    ),
    "fact_memory": ("enable_fact_memory_plugin",),
}
_OPAQUE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}\Z")
MAX_CATALOG_ITEMS = 4096


@dataclass(frozen=True)
class CurrentExternalSourceIdentity:
    """Returned by an owner callback that refreshes roles on EVERY access.

    A saved RunContext, session/login-time role snapshot, or persisted token is
    not a refresher. If current roles/account access cannot be established, the
    callback must fail rather than construct this value from cached claims.
    """

    user_id: str
    roles: tuple[str, ...]
    user_enable_agents: bool = False
    email: str | None = None

    def __post_init__(self):
        identifier(self.user_id)
        if (
            type(self.roles) is not tuple or len(self.roles) > 64
            or type(self.user_enable_agents) is not bool
        ):
            raise ResultContractError("result_external_identity_invalid")
        for role in self.roles:
            identifier(role, limit=128)
        if self.email is not None:
            identifier(self.email, limit=320)


@dataclass(frozen=True)
class ExternalSourceConfiguration:
    """Opaque server configuration identity/revision, never remote content state.

    The owner resolves these from the actual provider/agent/action configuration.
    Hash a Cosmos ETag or another non-opaque revision before supplying it. Do not
    supply a URL, credential, model-authored label, or an invented page revision.
    """

    identity: str
    revision: str

    def __post_init__(self):
        for value in (self.identity, self.revision):
            if type(value) is not str or _OPAQUE_TOKEN.fullmatch(value) is None:
                raise ResultContractError("result_external_configuration_invalid")


def _content_digest(prepared):
    value = canonical_bytes(prepared)
    if len(value) > MAX_VALUE_BYTES:
        raise ResultContractError("result_requires_streaming")
    return hashlib.sha256(value).hexdigest()


def _reference_id(producer, source_type, selector, content_sha256):
    return "retained:" + canonical_digest({
        "producer": producer.to_dict(), "source_type": source_type,
        "selector": selector, "content_sha256": content_sha256,
    })


class OrchestrationExternalSourceProvider:
    """Actor/conversation-scoped adapter for OrchestrationResultAccess.

    Required callbacks:
      read_identity(*, user_id, conversation_id) -> CurrentExternalSourceIdentity
      read_settings() -> current normalized settings
      read_conversation(id), read_run(id) -> current server records
      read_configuration(source_type, *, producer, settings, source)
          -> ExternalSourceConfiguration
      configuration_admitter(source_type, *, producer, settings, source, selector)
          -> the captured ExternalSourceConfiguration, after current validation
      acquisition_validator(source_type, *, producer, settings, source, selector,
                            current_settings, current_source)
          -> None after checking current support and actual acquisition evidence

    Catalog callbacks have the existing resolve_*_catalog protocol. Exact
    resolvers default to real agent/action authorization, not catalog membership
    alone. All callbacks run again on reads, including with a fresh provider and
    an empty admission catalog. The owner must supply restart-capable callbacks.
    """

    def __init__(
        self, *, user_id, conversation_id, read_identity, read_settings,
        read_conversation, read_run, read_configuration=None,
        configuration_admitter=None, acquisition_validator=None,
        agent_catalog_reader=resolve_agent_catalog,
        action_catalog_reader=resolve_action_catalog,
        agent_resolver=resolve_delegation_agent,
        action_resolver=resolve_action_manifest,
    ):
        self.access = OrchestrationResultAccess(
            user_id=user_id, conversation_id=conversation_id,
            read_conversation=read_conversation, read_run=read_run,
        )
        if not callable(read_identity) or not callable(read_settings):
            raise ResultContractError("result_external_reader_required")
        for callback in (
            read_configuration, configuration_admitter, acquisition_validator,
            agent_catalog_reader, action_catalog_reader,
            agent_resolver, action_resolver,
        ):
            if callback is not None and not callable(callback):
                raise ResultContractError("result_external_reader_required")
        self.read_identity = read_identity
        self.read_settings = read_settings
        self.read_configuration = read_configuration
        self.configuration_admitter = configuration_admitter
        self.acquisition_validator = acquisition_validator
        self.agent_catalog_reader = agent_catalog_reader
        self.action_catalog_reader = action_catalog_reader
        self.agent_resolver = agent_resolver
        self.action_resolver = action_resolver

    def _current(self, producer, *, for_write):
        self.access.authorize_producer(producer, for_write=for_write)
        identity = self.read_identity(
            user_id=self.access.user_id, conversation_id=self.access.conversation_id,
        )
        if (
            type(identity) is not CurrentExternalSourceIdentity
            or identity.user_id != self.access.user_id
            or not {"User", "Admin"}.intersection(identity.roles)
        ):
            raise ResultUnavailableError("result_external_identity_unavailable")
        settings = self.read_settings()
        conversation = self.access.read_conversation(self.access.conversation_id)
        run = self.access.read_run(producer.run_id)
        if (
            type(settings) is not dict or type(conversation) is not dict
            or conversation.get("id") != self.access.conversation_id
            or conversation.get("orchestration_deleted")
            or type(run) is not dict or run.get("id") != producer.run_id
            or run.get("user_id") != self.access.user_id
            or run.get("conversation_id") != self.access.conversation_id
            or run.get("attempt_index", 1) != producer.attempt_index
            or run.get("checkpoints_deleted")
            or type(run.get("plan")) is not dict
            or type(run["plan"].get("planner_contract_version")) is not int
            or run["plan"]["planner_contract_version"] != 2
        ):
            raise ResultUnavailableError("result_external_context_unavailable")
        try:
            audience = validate_memory_audience(conversation, identity.user_id)
        except OrchestrationMemoryError as exc:
            raise ResultUnavailableError("result_external_audience_unavailable") from exc
        return identity, settings, conversation, run, audience

    def _catalog(self, source_type, identity, settings):
        callback = self.agent_catalog_reader if source_type == "agent" else self.action_catalog_reader
        if callback is None:
            raise ResultUnavailableError("result_external_catalog_required")
        catalog = callback(identity.user_id, settings=settings)
        if (
            type(catalog) is not list or len(catalog) > MAX_CATALOG_ITEMS
            or any(type(item) is not dict for item in catalog)
        ):
            raise ResultUnavailableError("result_external_catalog_invalid")
        return catalog

    def _capability(self, source_type, producer, identity, settings, catalog, *, invocation_user_urls=None):
        if any(settings.get(key) is not True for key in _REQUIRED_SETTINGS[source_type]):
            raise ResultUnavailableError("result_external_capability_unavailable")
        if source_type == "fact_memory":
            return
        if source_type != _GATHER_SOURCES.get(producer.capability_id):
            raise ResultUnavailableError("result_external_capability_mismatch")
        allowed = settings.get("chat_orchestration_enabled_capabilities")
        if allowed is not None and (
            type(allowed) is not list or any(type(item) is not str for item in allowed)
        ):
            raise ResultUnavailableError("result_external_capability_unavailable")
        context = build_capability_request_context(
            identity.user_id,
            {
                "user_roles": list(identity.roles), "user_email": identity.email,
                "user_enable_agents": identity.user_enable_agents,
            },
            "", catalog if source_type == "agent" else [],
            catalog if source_type == "action" else [],
            allowed_user_urls=invocation_user_urls,
        )
        # Only retained reads may omit URL provenance. Invocation preflight
        # supplies server-owned user inputs and runs the normal request gate.
        available = resolve_available_capability_ids(
            settings, allowed_ids=allowed,
            request_context=None if source_type == "url" and invocation_user_urls is None else context,
            candidate_ids=(producer.capability_id,),
        )
        if producer.capability_id not in available:
            raise ResultUnavailableError("result_external_capability_unavailable")
        if source_type == "url":
            # Source-review parsing/client dependencies are only needed for URL authorization.
            from functions_source_review import is_url_access_enabled_for_user

            if not is_url_access_enabled_for_user(settings, user_roles=identity.roles):
                raise ResultUnavailableError("result_external_capability_unavailable")

    def _configuration(self, source_type, producer, settings, source, *, selector=None, for_admission=False):
        if self.read_configuration is None:
            raise ResultUnavailableError("result_external_configuration_required")
        options = {"producer": producer, "settings": settings, "source": source}
        callback = self.read_configuration
        if for_admission:
            if self.configuration_admitter is None:
                raise ResultUnavailableError("result_external_capture_required")
            callback = self.configuration_admitter
            options["selector"] = selector
        configuration = callback(source_type, **options)
        if type(configuration) is not ExternalSourceConfiguration:
            raise ResultUnavailableError("result_external_configuration_unavailable")
        if for_admission:
            current = self.read_configuration(
                source_type, producer=producer, settings=settings, source=source,
            )
            if type(current) is not ExternalSourceConfiguration:
                raise ResultUnavailableError("result_external_configuration_unavailable")
            if current != configuration:
                raise ResultUnavailableError("result_external_configuration_changed")
        return configuration

    def _resolve_integration(self, source_type, selected, identity, settings):
        try:
            if source_type == "agent":
                if self.agent_resolver is None:
                    raise ResultUnavailableError("result_external_resolver_required")
                expected = agent_reference(selected, identity.user_id)
                resolved = self.agent_resolver(expected, user_id=identity.user_id, settings=settings)
                if type(resolved) is not dict or agent_reference(resolved, identity.user_id) != expected:
                    raise ResultUnavailableError("result_external_source_unavailable")
            else:
                if self.action_resolver is None:
                    raise ResultUnavailableError("result_external_resolver_required")
                resolved = self.action_resolver(
                    identity.user_id, selected["action_ref"], settings=settings,
                )
                origin = get_action_origin(resolved)
                if not isinstance(resolved, dict) or origin is None or any(
                    resolved.get(key) != selected.get(key)
                    for key in ("action_ref", "id", "scope_type", "scope_id")
                ) or (
                    origin.action_id, origin.scope_type, origin.scope_id
                ) != (selected.get("id"), selected.get("scope_type"), selected.get("scope_id")):
                    raise ResultUnavailableError("result_external_source_unavailable")
        except ResultUnavailableError:
            raise
        except (PermissionError, LookupError) as exc:
            raise ResultUnavailableError("result_external_source_unavailable") from exc
        return resolved

    @staticmethod
    def _step_arguments(run, producer):
        steps = run["plan"].get("steps")
        if type(steps) is not list or any(type(step) is not dict for step in steps):
            raise ResultUnavailableError("result_external_selection_mismatch")
        matches = [step for step in steps if step.get("step_id") == producer.step_id]
        if (
            len(matches) != 1 or matches[0].get("capability_id") != producer.capability_id
            or matches[0].get("enabled", True) is not True
            or type(matches[0].get("arguments")) is not dict
        ):
            raise ResultUnavailableError("result_external_selection_mismatch")
        return matches[0]["arguments"]

    @classmethod
    def _check_integration_selection(cls, source_type, producer, run, selected, selector):
        arguments = cls._step_arguments(run, producer)
        argument = "agent_name" if source_type == "agent" else "action_ref"
        expected = selected.get("name") if source_type == "agent" else selector
        if type(expected) is not str or not expected or arguments.get(argument) != expected:
            raise ResultUnavailableError("result_external_selection_mismatch")

    @staticmethod
    def _invocation_user_urls(run):
        """Use the same server user-input provenance as execution, never plan URLs."""
        message = run.get("user_message", "")
        snapshot = run.get("conversation_context")
        resolution = run.get("request_resolution")
        answers = run.get("answered_questions")
        edits = run.get("edit_user_urls")
        if (
            type(message) is not str
            or snapshot is not None and type(snapshot) is not dict
            or resolution is not None and type(resolution) is not dict
            or answers is not None and (
                type(answers) is not list or any(
                    type(answer) is not dict
                    or answer.get("context") is not None and type(answer["context"]) is not dict
                    for answer in answers
                )
            )
            or edits is not None and (type(edits) is not list or any(type(url) is not str for url in edits))
        ):
            raise ResultUnavailableError("result_external_url_grant_unavailable")
        message_ids = (resolution or {}).get("message_ids")
        if message_ids is not None and (
            type(message_ids) is not list or any(type(value) is not str for value in message_ids)
        ):
            raise ResultUnavailableError("result_external_url_grant_unavailable")
        try:
            validate_clarification_answers(answers or [])
            urls = conversation_user_urls(message, snapshot, message_ids, answers)
            edit_urls = conversation_user_urls("\n".join(edits or []))
        except (KeyError, TypeError, ValueError):
            raise ResultUnavailableError("result_external_url_grant_unavailable") from None
        return list(dict.fromkeys([*edit_urls, *urls]))[:8]

    def preflight_gather_invocation(self, *, producer, selector=None):
        """Recheck current access before acquisition; this creates no content authority.

        The owner still applies current conversation-context validation, exact
        user-URL approval, transport safety, and execution/budget guards. Success
        is not a URL grant, configuration attestation, or retained-result alias.
        """
        self._gather_invocation_state(producer, selector)

    def preflight_gather_acquisition(self, source_type, *, producer, settings, source=None, selector=None):
        """Check current authority/support and actual configuration before effects.

        The validator receives current settings and the exact authorized source
        from the same resolution as auth-only preflight, never from the engine's
        acquisition envelope. No permission snapshot or capture proof is returned.
        """
        if (
            type(producer) is not ProducerIdentity or type(source_type) is not str
            or _GATHER_SOURCES.get(producer.capability_id) != source_type
        ):
            raise ResultContractError("result_external_producer_invalid")
        if self.acquisition_validator is None:
            raise ResultUnavailableError("result_external_acquisition_validator_required")
        _, current_settings, current_source = self._gather_invocation_state(producer, selector)
        validated = self.acquisition_validator(
            source_type, producer=producer, settings=settings, source=source, selector=selector,
            current_settings=current_settings, current_source=current_source,
        )
        if validated is not None:
            raise ResultContractError("result_external_acquisition_validation_invalid")

    def _gather_invocation_state(self, producer, selector):
        if type(producer) is not ProducerIdentity or producer.capability_id not in _GATHER_SOURCES:
            raise ResultContractError("result_external_producer_invalid")
        source_type = _GATHER_SOURCES[producer.capability_id]
        identity, settings, _conversation, run, audience = self._current(producer, for_write=True)
        self._step_arguments(run, producer)
        if run.get("memory_audience") is not None and run["memory_audience"] != audience:
            raise ResultUnavailableError("result_external_audience_unavailable")
        catalog = self._catalog(source_type, identity, settings) if source_type in {"agent", "action"} else []
        self._capability(
            source_type, producer, identity, settings, catalog,
            invocation_user_urls=self._invocation_user_urls(run) if source_type == "url" else None,
        )
        resolved = None
        if source_type in {"agent", "action"}:
            key = "catalog_key" if source_type == "agent" else "action_ref"
            selected = [
                entry for entry in catalog
                if type(entry.get(key)) is str and entry[key] and entry[key] == selector
            ]
            if len(selected) != 1:
                raise ResultUnavailableError("result_external_source_unavailable")
            self._check_integration_selection(source_type, producer, run, selected[0], selector)
            resolved = self._resolve_integration(source_type, selected[0], identity, settings)
        elif selector is not None:
            raise ResultContractError("result_external_selection_invalid")
        return source_type, settings, resolved

    def _memory_scope(self, identity, settings, conversation, run, audience):
        scope = run.get("memory_scope")
        if (
            audience["kind"] != "personal" or run.get("memory_audience") != audience
            or type(scope) is not dict or set(scope) != {"type", "id"}
            or scope.get("type") not in {"user", "group"}
            or (scope["type"] == "group" and settings.get("enable_group_workspaces") is not True)
        ):
            raise ResultUnavailableError("result_external_memory_unavailable")
        try:
            validate_memory_context(conversation, identity.user_id, audience, scope)
        except OrchestrationMemoryError as exc:
            raise ResultUnavailableError("result_external_memory_unavailable") from exc
        return scope

    def _reference(
        self, *, producer, source_type, content_sha256, state, selector=None, previous=None,
    ):
        identity, settings, conversation, run, audience = state
        catalog = self._catalog(source_type, identity, settings) if source_type in {"agent", "action"} else []
        self._capability(source_type, producer, identity, settings, catalog)
        revision = None
        configuration_identity = None
        if source_type == "fact_memory":
            selector = self._memory_scope(identity, settings, conversation, run, audience)
        elif source_type in {"agent", "action"}:
            key = "catalog_key" if source_type == "agent" else "action_ref"
            matches = [
                item for item in catalog
                if type(item.get(key)) is str and item[key] and (
                    item[key] == selector if previous is None else
                    _reference_id(producer, source_type, item[key], content_sha256)
                    == previous.reference_id.rsplit(":", 1)[0]
                )
            ]
            if len(matches) != 1:
                raise ResultUnavailableError("result_external_source_unavailable")
            selected = matches[0]
            selector = selected[key]
            if previous is None:
                self._check_integration_selection(source_type, producer, run, selected, selector)
            source = self._resolve_integration(source_type, selected, identity, settings)
            configuration = self._configuration(
                source_type, producer, settings, source,
                selector=selector, for_admission=previous is None,
            )
            configuration_identity = configuration.identity
            revision = "configuration:" + canonical_digest({
                "identity": configuration.identity, "revision": configuration.revision,
            })
        else:
            if selector is not None:
                raise ResultContractError("result_external_selection_invalid")
            configuration = self._configuration(
                source_type, producer, settings, None, for_admission=previous is None,
            )
            selector = configuration.identity
            revision = "configuration:" + canonical_digest({
                "identity": configuration.identity, "revision": configuration.revision,
            })
        reference_id = _reference_id(producer, source_type, selector, content_sha256)
        if configuration_identity is not None:
            reference_id += ":" + canonical_digest(configuration_identity)
        return ExternalSourceRef(
            source_type, producer.capability_id, reference_id,
            "audience:" + canonical_digest(audience), content_sha256, revision,
        )

    def admit_gather_result(self, *, producer, prepared, selector=None):
        """Admit the exact prepared structured-v1 value returned by a Gather adapter.

        Integration selectors are the original server-selected catalog_key or
        action_ref, never a browser label. The caller installs the returned mapping
        in result access and persists only its aliases alongside this same value.
        """
        if (
            type(producer) is not ProducerIdentity or producer.capability_id not in _GATHER_SOURCES
            or type(prepared) is not dict
            or prepared.get("version") != "orchestration-gathered-content-v1"
            or prepared.get("capability_id") != producer.capability_id
        ):
            raise ResultContractError("result_external_content_invalid")
        reference = self._reference(
            producer=producer, source_type=_GATHER_SOURCES[producer.capability_id],
            content_sha256=_content_digest(prepared),
            state=self._current(producer, for_write=True), selector=selector,
        )
        return {"external_" + canonical_digest(reference.to_dict())[:48]: reference}

    def admit_memory_result(self, *, producer, prepared):
        """Attest explicit retained memory use; never search or refresh saved facts."""
        reference = self._reference(
            producer=producer, source_type="fact_memory",
            content_sha256=_content_digest(prepared), state=self._current(producer, for_write=True),
        )
        return {"external_" + canonical_digest(reference.to_dict())[:48]: reference}

    def authorize(self, reference, *, producer, user_id, conversation_id):
        """Return current exact identity from a trusted committed binding, not a catalog."""
        if (
            type(reference) is not ExternalSourceRef or type(producer) is not ProducerIdentity
            or user_id != self.access.user_id or conversation_id != self.access.conversation_id
            or reference.capability_id != producer.capability_id or reference.content_sha256 is None
        ):
            raise ResultUnavailableError("result_external_source_unavailable")
        current = self._reference(
            producer=producer, source_type=reference.source_type,
            content_sha256=reference.content_sha256,
            state=self._current(producer, for_write=False), previous=reference,
        )
        if current.identity() != reference.identity():
            raise ResultUnavailableError("result_external_source_unavailable")
        return current
