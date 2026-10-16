# functions_m365_continuations.py
"""Conditional delivery of persisted Microsoft 365 workflow continuations."""

from datetime import datetime, timedelta, timezone
import hashlib
import logging

from azure.core import MatchConditions
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError

from functions_m365_context import M365PolicyError


DECIDED_STATES = frozenset({"approved", "denied", "expired", "invalidated", "revoked"})


class M365ContinuationNotStarted(M365PolicyError):
    """The executor verified deletion before entering any workflow execution."""

    def __init__(self):
        super().__init__("m365_workflow_missing", "The workflow no longer exists.")


def _log_continuation(log_event, candidate, *, code, stage, level, error=None):
    properties = {
        "request_id_hash": hashlib.sha256(str(candidate.get("id") or "").encode("utf-8")).hexdigest(),
        "failure_code": code,
        "stage": stage,
    }
    if error is not None:
        properties["error_type"] = type(error).__name__
    log_event(
        "[MS_GRAPH_PLUGIN] Workflow continuation outcome.",
        level=level, extra=properties,
    )


def _fail_deleted_workflow(jobs, candidate, now):
    stopped = {
        **candidate, "status": "failed", "failure_code": "workflow_deleted",
        "completed_at": now.isoformat(),
    }
    stopped.pop("resume_lease_expires_at", None)
    jobs.replace_item(
        candidate["id"], body=stopped,
        etag=candidate["_etag"], match_condition=MatchConditions.IfNotModified,
    )


def resume_pending_workflows(
    jobs, approvals, *, execute, can_resume, log_event, connection_ready=None, limit=25, clock=None,
):
    """Deliver pending work once per lease; the executor owns workflow checkpoints."""
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    candidates = jobs.query_items(
        query=(
            "SELECT TOP @limit * FROM c WHERE c.type = 'm365_execution_request' "
            "AND IS_STRING(c.workflow_id) AND c.workflow_id != '' "
            "AND c.status IN ('awaiting_approval', 'awaiting_sign_in', 'ready_to_resume', 'resuming')"
        ),
        parameters=[{"name": "@limit", "value": limit}],
        enable_cross_partition_query=True,
    )
    outcomes = []
    for candidate in candidates:
        stage = "preflight"
        try:
            if candidate.get("status") == "resuming":
                lease = candidate.get("resume_lease_expires_at")
                if lease and datetime.fromisoformat(lease) > now:
                    continue
                # An expired claim is uncertain even if its workflow was later deleted.
                recovering = {
                    **candidate, "status": "recovery_required",
                    "recovery_reason": "A continuation worker stopped before acknowledging its result.",
                }
                stage = "recover_expired_claim"
                jobs.replace_item(
                    candidate["id"], body=recovering,
                    etag=candidate["_etag"], match_condition=MatchConditions.IfNotModified,
                )
                _log_continuation(
                    log_event, candidate, code="continuation_recovery_required",
                    stage=stage, level=logging.WARNING,
                )
                continue

            try:
                # Check the workflow even when approval/sign-in is still pending.
                eligible = can_resume(candidate, None)
            except M365PolicyError as error:
                if error.code != "m365_workflow_missing":
                    raise
                stage = "terminalize_deleted_workflow"
                _fail_deleted_workflow(jobs, candidate, now)
                _log_continuation(
                    log_event, candidate, code="workflow_deleted",
                    stage=stage, level=logging.INFO,
                )
                continue
            if not eligible:
                continue
            if candidate.get("status") == "awaiting_sign_in":
                if connection_ready is None or not connection_ready(candidate):
                    continue
            else:
                try:
                    approval = approvals.get_approval(
                        candidate["approval_id"], candidate["user_id"],
                    )
                except (CosmosResourceNotFoundError, LookupError) as error:
                    _log_continuation(
                        log_event, candidate, code="continuation_approval_unavailable",
                        stage=stage, level=logging.WARNING, error=error,
                    )
                    continue
                if approval.get("status") not in DECIDED_STATES:
                    continue
                try:
                    eligible = can_resume(candidate, approval)
                except M365PolicyError as error:
                    if error.code != "m365_workflow_missing":
                        raise
                    stage = "terminalize_deleted_workflow"
                    _fail_deleted_workflow(jobs, candidate, now)
                    _log_continuation(
                        log_event, candidate, code="workflow_deleted",
                        stage=stage, level=logging.INFO,
                    )
                    continue
                if not eligible:
                    continue
            claimed = {
                **candidate,
                "status": "resuming",
                "resume_lease_expires_at": (now + timedelta(minutes=15)).isoformat(),
            }
            stage = "claim"
            claimed = jobs.replace_item(
                candidate["id"], body=claimed,
                etag=candidate["_etag"], match_condition=MatchConditions.IfNotModified,
            )
            stage = "execute"
            try:
                result = execute(claimed)
            except M365ContinuationNotStarted:
                stage = "terminalize_deleted_workflow"
                _fail_deleted_workflow(jobs, claimed, now)
                _log_continuation(
                    log_event, claimed, code="workflow_deleted",
                    stage=stage, level=logging.INFO,
                )
                continue
            except Exception as error:
                _log_continuation(
                    log_event, claimed, code="continuation_execution_failed",
                    stage=stage, level=logging.ERROR, error=error,
                )
                stage = "recover_failed_execution"
                recovering = {
                    **claimed, "status": "recovery_required",
                    "recovery_reason": "The continuation failed after execution may have started.",
                }
                jobs.replace_item(
                    claimed["id"], body=recovering,
                    etag=claimed["_etag"], match_condition=MatchConditions.IfNotModified,
                )
                continue
            stage = "acknowledge"
            current = dict(claimed)
            if result.get("durable_execution") is True and result.get("pending") is True:
                current["status"] = "running"
                current.pop("resume_lease_expires_at", None)
            else:
                current["status"] = "completed" if result.get("success") else "failed"
                current["completed_at"] = now.isoformat()
            try:
                jobs.replace_item(
                    current["id"], body=current,
                    etag=claimed["_etag"], match_condition=MatchConditions.IfNotModified,
                )
            except CosmosHttpResponseError as error:
                if error.status_code != 412:
                    raise
                # The executor may have saved a new approval or its own checkpoint.
                _log_continuation(
                    log_event, candidate, code="continuation_conflict",
                    stage=stage, level=logging.INFO, error=error,
                )
            outcomes.append({"request_id": claimed["id"], "result": result})
        except Exception as error:
            conflict = isinstance(error, CosmosHttpResponseError) and error.status_code in {404, 412}
            _log_continuation(
                log_event, candidate,
                code="continuation_conflict" if conflict else "continuation_processing_failed",
                stage=stage, level=logging.INFO if conflict else logging.ERROR, error=error,
            )
    return outcomes
