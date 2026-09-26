# functions_orchestration_scheduler.py
"""One bounded scheduler tick over saved runs; no thread, admission gate or client startup.

Version: 0.261.140
The application supplies initialized resources. Results contain private selectors
and safe processing facts, never model output, credentials or artifact locators.
Deletion enrollment has its own run budget and consumes only a persisted owner
policy. Each selected run has at most MAX_OUTPUTS_PER_RUN admitted outputs; the
output budget independently bounds due cleanup/render work. No retention policy
is inferred from a missing conversation or a saved success.
Authority infrastructure failures retain their declared retryability. A genuine
document hold is denial; uncertain authority is not permission to replay work.
Declared headless publication and cancellation outcomes take precedence over
their diagnostic cause chains.
The headless execution owner supplies the initial result binding and closes the
accepted execution; the scheduler does not repeat those operations after handoff.
"""

import logging
import re
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import islice
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from functions_orchestration_artifacts import OrchestrationOutputCleanupService
    from functions_orchestration_services import OrchestrationServices


MAX_SCAN_LIMIT = 200
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}\Z")
_CODE = re.compile(r"[a-z][a-z0-9_]{0,79}\Z")
_STATES = frozenset({"running", "waiting", "completed", "failed", "cancelled"})


def _utc_now():
    return datetime.now(timezone.utc)


def _aware_time(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("An aware scheduler timestamp is required.")
    return value.astimezone(timezone.utc)


def _limit(value, *, allow_zero=False):
    if type(value) is not int or not (0 if allow_zero else 1) <= value <= MAX_SCAN_LIMIT:
        raise ValueError("The scheduler budget is outside its supported bounds.")
    return value


def _identifier(value):
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError("A saved scheduler selector is invalid.")
    return value


def enumerate_due_runs(container, *, now=None, limit=64):
    """Read bounded selectors, including terminal outcomes awaiting publication."""
    _limit(limit)
    timestamp = _aware_time(_utc_now() if now is None else now).isoformat()
    query = (
        f"SELECT TOP {limit} c.id, c.user_id, c.conversation_id FROM c WHERE "
        '(c.record_type = "run" OR c.record_type = "orchestration_run") '
        "AND c.planner_contract_version = 2 AND c.plan.planner_contract_version = 2 "
        "AND IS_DEFINED(c.started_at) AND NOT IS_NULL(c.started_at) "
        "AND (NOT IS_DEFINED(c.checkpoints_deleted) OR c.checkpoints_deleted != true) "
        "AND (NOT IS_DEFINED(c.outputs_deleted) OR c.outputs_deleted != true) "
        "AND (NOT IS_DEFINED(c.superseded_by_run_id) OR IS_NULL(c.superseded_by_run_id)) "
        "AND (NOT IS_DEFINED(c.latest_attempt_run_id) OR IS_NULL(c.latest_attempt_run_id) "
        'OR c.latest_attempt_run_id = "") '
        "AND (NOT IS_DEFINED(c.execution_lease) OR IS_NULL(c.execution_lease) "
        "OR c.execution_lease.expires_at <= @now) "
        'AND (c.status IN ("waiting", "running") OR '
        '(c.status IN ("completed", "failed", "cancelled") AND c.finalization_status = "pending")) '
        "ORDER BY c.updated_at ASC"
    )
    rows = container.query_items(
        query=query, parameters=[{"name": "@now", "value": timestamp}],
        enable_cross_partition_query=True, max_item_count=limit,
    )
    selectors = []
    seen = set()
    for row in islice(rows, limit):
        if type(row) is not dict:
            raise ValueError("A saved scheduler selector is invalid.")
        selector = {
            "run_id": _identifier(row.get("id")),
            "user_id": _identifier(row.get("user_id")),
            "conversation_id": _identifier(row.get("conversation_id")),
        }
        key = _run_key(selector)
        if key not in seen:
            seen.add(key)
            selectors.append(selector)
    return selectors


def enumerate_cleanup_enrollment_runs(container, *, limit=4):
    """Deduplicate the output owner's bounded, non-authoritative enrollment selectors."""
    from functions_orchestration_output_store import enumerate_output_cleanup_enrollments

    _limit(limit)
    rows = enumerate_output_cleanup_enrollments(container, limit=limit)
    selectors, seen = [], set()
    for row in islice(rows, limit):
        if type(row) is not dict:
            raise ValueError("A saved cleanup enrollment selector is invalid.")
        selector = {
            "run_id": _identifier(row.get("run_id")),
            "user_id": _identifier(row.get("user_id")),
            "conversation_id": _identifier(row.get("conversation_id")),
        }
        key = _run_key(selector)
        if key not in seen:
            seen.add(key)
            selectors.append(selector)
    return selectors


@dataclass(frozen=True)
class OrchestrationSchedulerResources:
    runs_container: object
    messages_container: object
    settings: dict
    read_conversation: Callable[[str, str], dict]
    read_run: Callable[[str, str, str], dict]
    build_services: Callable[..., "OrchestrationServices"]
    build_cleanup_service: Callable[[str, str], "OrchestrationOutputCleanupService"]
    log: Callable[..., None]
    clock: Callable[[], datetime] = _utc_now


def _initialized_resources():
    # Only the already initialized application root may discover its owned handles.
    import config
    from functions_appinsights import log_event
    from functions_orchestration_bootstrap import (
        build_orchestration_cleanup_service,
        build_orchestration_services,
        read_owned_conversation,
    )
    from functions_orchestration_plan_revisions import read_revision_run
    from functions_settings import get_settings

    return OrchestrationSchedulerResources(
        runs_container=config.cosmos_orchestration_runs_container,
        messages_container=config.cosmos_messages_container,
        settings=get_settings(), read_conversation=read_owned_conversation,
        read_run=read_revision_run, build_services=build_orchestration_services,
        build_cleanup_service=build_orchestration_cleanup_service, log=log_event,
    )


def _run_key(selector):
    return selector["user_id"], selector["conversation_id"], selector["run_id"]


def _selector(record):
    return {
        "run_id": record["id"], "user_id": record["user_id"],
        "conversation_id": record["conversation_id"],
    }


def _error_facts(error):
    # These owner modules are resolved during a tick, never at scheduler import.
    from azure.core.exceptions import AzureError
    from content_screening.contracts import DocumentHeldError, ScreeningError
    from functions_orchestration_checkpoints import CheckpointError
    from functions_orchestration_execution import HarnessExecutionError
    from functions_orchestration_external_configuration import ExternalConfigurationServiceError
    from functions_orchestration_external_identity import ExternalIdentityServiceError
    from functions_orchestration_output_store import OutputConflictError, OutputError, OutputStorageError, OutputUnavailableError
    from functions_orchestration_plan_revisions import PlanRevisionError
    from functions_orchestration_recovery import RecoveryError
    from functions_orchestration_rendering import raise_output_read_infrastructure_failure

    if isinstance(error, HarnessExecutionError) and error.code in {"message_not_saved", "user_cancelled"}:
        return {
            "code": error.code, "retryable": error.retryable is True,
            "error_type": type(error).__name__,
        }
    try:
        raise_output_read_infrastructure_failure(error)
    except Exception as infrastructure:
        error = infrastructure
    code, retryable = "scheduler_item_failed", False
    if isinstance(error, (OutputStorageError, AzureError, ConnectionError, TimeoutError)):
        code, retryable = "storage_unavailable", True
    elif isinstance(error, DocumentHeldError):
        code = "context_unavailable"
    elif isinstance(error, (
        CheckpointError, HarnessExecutionError, OutputError, OutputUnavailableError,
        OutputConflictError, PlanRevisionError, RecoveryError,
        ExternalIdentityServiceError, ExternalConfigurationServiceError, ScreeningError,
    )):
        candidate = error.code
        if type(candidate) is str and _CODE.fullmatch(candidate):
            code = candidate
        retryable = getattr(error, "retryable", False) is True
    elif isinstance(error, PermissionError):
        code = "context_unavailable"
    elif isinstance(error, (ValueError, TypeError)):
        code = "scheduler_invalid_state"
    return {"code": code, "retryable": retryable, "error_type": type(error).__name__}


class _Tick:
    def __init__(self, resources):
        self.resources = resources
        self.now = _aware_time(resources.clock())
        self.result = {
            "ok": True, "runs": [], "outputs": [], "cleanup_enrollments": [], "errors": [],
            "counts": {
                "run_selectors": 0, "output_selectors": 0, "cleanup_run_selectors": 0,
                "runs_executed": 0, "outputs_processed": 0, "cleanup_runs_enrolled": 0,
                "cleanup_outputs_enrolled": 0,
            },
        }

    def failure(self, scope, error, selector=None):
        # Keep telemetry dependencies below the initialized scheduler boundary.
        from functions_appinsights import workflow_log_context

        facts = {"scope": scope, **(selector or {}), **_error_facts(error)}
        self.result["ok"] = False
        self.result["errors"].append(facts)
        self.resources.log(
            "[ORCHESTRATION_RUNS] Scheduler item could not be confirmed.",
            level=logging.ERROR, extra={
                **workflow_log_context(
                    conversation_id=facts.get("conversation_id"), run_id=facts.get("run_id"),
                ),
                "stage": "scheduler_item", "scope": scope,
                "execution_code": facts["code"], "retryable": facts["retryable"],
                "error_type": facts["error_type"],
            },
        )
        return facts

    def read_run(self, selector):
        user_id, conversation_id, run_id = _run_key(selector)
        self.resources.read_conversation(user_id, conversation_id)
        record = self.resources.read_run(run_id, user_id, conversation_id)
        if (
            type(record) is not dict
            or any(record.get(key) != value for key, value in (
                ("id", run_id), ("run_id", run_id), ("user_id", user_id), ("conversation_id", conversation_id),
            ))
            or type(record.get("planner_contract_version")) is not int
            or record["planner_contract_version"] != 2
            or type((record.get("plan") or {}).get("planner_contract_version")) is not int
            or record["plan"]["planner_contract_version"] != 2
        ):
            raise ValueError("The authoritative run does not match its selector.")
        return record

    def services(self, selector):
        return self.resources.build_services(
            selector["user_id"], selector["conversation_id"], settings=self.resources.settings,
        )

    def claim(self, selector, mode):
        # Recovery depends on initialized run containers and the real owning lease.
        from functions_orchestration_continuation import claim_run_continuation

        return claim_run_continuation(
            selector["run_id"], selector["user_id"], selector["conversation_id"],
            authorize=lambda: self.resources.read_conversation(
                selector["user_id"], selector["conversation_id"],
            ),
            message_container=self.resources.messages_container, mode=mode,
        )

    def close(self, lease, selector):
        if lease is not None and not lease.stopped.is_set():
            try:
                lease.close(release=True)
            except Exception as exc:
                self.failure("lease_release", exc, selector)

    def published(self, selector, action):
        record = self.read_run(selector)
        state = record.get("status")
        saved = record.get("message_saved") is True and record.get("finalization_status") == "saved"
        self.result["runs"].append({
            **selector, "action": action, "state": state if state in _STATES else "unconfirmed",
            "message_saved": saved,
        })
        if not saved:
            # A nonempty final-frame list is not a durable publication receipt.
            from functions_orchestration_execution import HarnessExecutionError

            self.failure("publication", HarnessExecutionError("message_not_saved"), selector)

    def terminal_condition(self, record):
        if record.get("cancellation_requested_at") or record.get("status") == "cancelled":
            return "user_cancelled"
        if record.get("status") in {"completed", "failed"}:
            return None
        # Tick callers have initialized the application-owned checkpoint boundary.
        from functions_orchestration_checkpoints import CheckpointError

        if not record.get("execution_deadline_at"):
            raise CheckpointError("checkpoint_unavailable")
        try:
            deadline = _aware_time(datetime.fromisoformat(record["execution_deadline_at"]))
        except (TypeError, ValueError) as exc:
            raise CheckpointError("checkpoint_invalid") from exc
        states = {step["step_id"]: step["status"] for step in record.get("execution_steps") or []}
        enabled = [step for step in record["plan"]["steps"] if step.get("enabled", True)]
        required = [step for step in enabled if not step.get("optional", False)] or enabled
        if _aware_time(deadline) <= _aware_time(self.resources.clock()) and any(
            states.get(step["step_id"]) != "completed" for step in required
        ):
            return "run_timeout"
        return None

    def refresh(self, record, lease, services):
        from functions_orchestration_execution import finalize_harness_failure, refresh_harness_delivery

        failure_code = self.terminal_condition(record)
        if failure_code is not None:
            finalize_harness_failure(
                record, failure_code=failure_code, services=services,
                settings=self.resources.settings, lease=lease,
            )
        else:
            refresh_harness_delivery(
                record, services=services, settings=self.resources.settings, lease=lease,
            )

    def cleanup_output(self, service, selector):
        from functions_orchestration_output_store import OutputUnavailableError
        from functions_orchestration_rendering import raise_output_read_infrastructure_failure

        try:
            fact = service.cleanup(selector["output_id"])
        except OutputUnavailableError as exc:
            raise_output_read_infrastructure_failure(exc)
            if exc.code != "output_cleanup_denied":
                raise
            # Cleanup refusal grants no execution access; normal ownership is checked below.
            return False
        self.result["outputs"].append({
            **selector, "action": "cleanup", "state": fact["state"],
            "cleanup_status": fact["cleanup_status"],
            "cleanup_pending": fact["cleanup_pending"],
        })
        self.result["counts"]["outputs_processed"] += 1
        return True

    def enroll_cleanup(self, selector):
        try:
            cleanup = self.resources.build_cleanup_service(selector["user_id"], selector["conversation_id"])
            result = cleanup.enroll_run_cleanup(selector["run_id"])
            self.result["cleanup_enrollments"].append({**selector, **result})
            self.result["counts"]["cleanup_runs_enrolled"] += 1
            self.result["counts"]["cleanup_outputs_enrolled"] += result["output_count"]
        except Exception as exc:
            self.failure("cleanup_enrollment", exc, selector)

    def process_outputs(self, selectors, *, cleanup_only=False):
        from content_screening.access import strict_source_authority
        from functions_orchestration_continuation import bind_continuation_result_store, reconcile_run_outputs
        from functions_orchestration_output_store import OutputUnavailableError

        selector = {key: selectors[0][key] for key in ("run_id", "user_id", "conversation_id")}
        lease = None
        handled = False
        try:
            cleanup = self.resources.build_cleanup_service(selector["user_id"], selector["conversation_id"])
            remaining = []
            for selected in selectors:
                try:
                    if not self.cleanup_output(cleanup, selected):
                        if cleanup_only:
                            raise OutputUnavailableError("output_cleanup_denied")
                        remaining.append(selected)
                except Exception as exc:
                    self.failure("output_cleanup", exc, selected)
            if not remaining:
                # Run selectors predate cleanup and may refer to a deleted scope.
                return True
            current_run = self.read_run(selector)
            services = self.services(selector)
            active = []
            for selected in remaining:
                try:
                    output = services.outputs.get(selected["output_id"])
                    if (
                        any(output.get(key) != selected[key] for key in ("run_id", "user_id", "conversation_id"))
                        or selected["output_id"] not in current_run.get("render_output_ids", [])
                    ):
                        raise ValueError("The output does not match its selector.")
                    if output["state"] not in {"completed", "failed", "cancelled"}:
                        active.append((selected, output["state"]))
                except Exception as exc:
                    self.failure("output_read", exc, selected)
            if not active:
                return False
            owned = self.claim(selector, "outputs")
            if owned is None:
                self.result["runs"].append({**selector, "action": "deferred", "state": "owned_or_not_due"})
                return True
            record, lease = owned
            handled = True
            lease.start()
            current = lease.read()
            if self.terminal_condition(current) is None:
                services.results.store = bind_continuation_result_store(
                    current, store=services.results.store, lease=lease,
                )
            for selected, state in active:
                action = "reconcile" if state == "rendering" else "attempt"
                try:
                    with strict_source_authority():
                        lease.read()
                        if state == "rendering":
                            fact = services.rendering.reconcile(selected["output_id"])
                        else:
                            fact = services.rendering.render_attempt(selected["output_id"])
                    self.result["outputs"].append({**selected, "action": action, "state": fact["state"]})
                    self.result["counts"]["outputs_processed"] += 1
                except Exception as exc:
                    self.failure(f"output_{action}", exc, selected)
            record = reconcile_run_outputs(lease.read(), services=services, lease=lease)
            self.refresh(record, lease, services)
            self.published(selector, "outputs")
        except Exception as exc:
            self.failure("output_run", exc, selector)
        finally:
            self.close(lease, selector)
        return handled

    def process_run(self, selector):
        from content_screening.access import strict_source_authority

        with strict_source_authority():
            self._process_run(selector)

    def _process_run(self, selector):
        from functions_orchestration_continuation import (
            ContinuationCheckpoints,
            ContinuationExecutionLease,
            reconcile_run_outputs,
        )
        from functions_orchestration_execution import finalize_harness_failure, prepare_harness_execution

        lease = None
        try:
            record = self.read_run(selector)
            states = {row["step_id"]: row["status"] for row in record.get("execution_steps") or []}
            execution_work = any(
                step.get("enabled", True) and step["role"] != "render"
                and states.get(step["step_id"], "pending") in {"pending", "running", "waiting"}
                for step in record["plan"]["steps"]
            )
            terminal = self.terminal_condition(record)
            if (
                record["status"] == "waiting" and not execution_work and terminal is None
                and record.get("finalization_status") == "saved"
            ):
                self.result["runs"].append({**selector, "action": "deferred", "state": "waiting_outputs"})
                return
            publication_only = record["status"] in {"completed", "failed", "cancelled"}
            mode = "execute" if execution_work and terminal is None and not publication_only else "delivery"
            owned = self.claim(selector, mode)
            if owned is None:
                self.result["runs"].append({**selector, "action": "deferred", "state": "owned_or_not_due"})
                return
            record, lease = owned
            if (
                isinstance(lease, ContinuationExecutionLease)
                and record["continuation"]["mode"] != "execute"
            ):
                mode = "delivery"
            if mode == "execute":
                execution = prepare_harness_execution(
                    record, settings=self.resources.settings, lease=lease,
                    checkpoint_factory=ContinuationCheckpoints,
                )
                self.result["counts"]["runs_executed"] += 1
                execution.execute()
                self.published(selector, "execute")
            else:
                lease.start()
                services = self.services(selector)
                record = lease.read()
                if not publication_only:
                    record = reconcile_run_outputs(record, services=services, lease=lease)
                terminal = self.terminal_condition(record)
                if terminal is not None:
                    finalize_harness_failure(
                        record, failure_code=terminal, services=services,
                        settings=self.resources.settings, lease=lease,
                    )
                else:
                    self.refresh(record, lease, services)
                self.published(selector, "delivery")
        except Exception as exc:
            self.failure("run", exc, selector)
        finally:
            self.close(lease, selector)


def check_due_orchestration_runs_once(*, max_runs=4, max_outputs=8, max_cleanup_runs=4, resources=None):
    """Run independent bounded execution, output and deletion-enrollment scans.

    Enrollment uses the deletion-only service before any live execution factory.
    Completed enrollment retires only its frozen discovery intent, never the
    run/output/lifecycle authority required by deferred cleanup and late writers.
    """
    _limit(max_runs, allow_zero=True)
    _limit(max_outputs, allow_zero=True)
    _limit(max_cleanup_runs, allow_zero=True)
    resources = _initialized_resources() if resources is None else resources
    if not isinstance(resources, OrchestrationSchedulerResources) or type(resources.settings) is not dict:
        raise TypeError("Initialized orchestration scheduler resources are required.")
    tick = _Tick(resources)
    run_selectors, output_selectors, cleanup_selectors = [], [], []
    if max_cleanup_runs:
        try:
            cleanup_selectors = enumerate_cleanup_enrollment_runs(
                resources.runs_container, limit=max_cleanup_runs,
            )
        except Exception as exc:
            tick.failure("cleanup_enrollment_scan", exc)
    cleanup_runs = {_run_key(selector) for selector in cleanup_selectors}
    for selector in cleanup_selectors:
        tick.enroll_cleanup(selector)
    if max_runs:
        try:
            run_selectors = enumerate_due_runs(resources.runs_container, now=tick.now, limit=max_runs)
        except Exception as exc:
            tick.failure("run_scan", exc)
    if max_outputs:
        # The pure output scan does not inspect admission flags or initialize clients.
        from functions_orchestration_output_store import enumerate_due_outputs

        try:
            output_selectors = enumerate_due_outputs(resources.runs_container, now=tick.now, limit=max_outputs)
        except Exception as exc:
            tick.failure("output_scan", exc)
    tick.result["counts"].update(
        run_selectors=len(run_selectors), output_selectors=len(output_selectors),
        cleanup_run_selectors=len(cleanup_selectors),
    )
    groups = OrderedDict()
    seen_outputs = set()
    for selector in output_selectors:
        key = (*_run_key(selector), selector["output_id"])
        if key in seen_outputs:
            continue
        seen_outputs.add(key)
        groups.setdefault(_run_key(selector), []).append(selector)
    handled_runs = set(cleanup_runs)
    for selectors in groups.values():
        if tick.process_outputs(selectors, cleanup_only=_run_key(selectors[0]) in cleanup_runs):
            handled_runs.add(_run_key(selectors[0]))
    for selector in run_selectors:
        if _run_key(selector) not in handled_runs:
            tick.process_run(selector)
    tick.result["counts"]["errors"] = len(tick.result["errors"])
    return tick.result
