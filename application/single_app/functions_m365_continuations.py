# functions_m365_continuations.py
"""Conditional delivery of persisted Microsoft 365 workflow continuations."""

from datetime import datetime, timedelta, timezone
import logging

from azure.core import MatchConditions
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError


DECIDED_STATES = frozenset({"approved", "denied", "expired", "invalidated", "revoked"})


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
        if candidate.get("status") == "resuming":
            lease = candidate.get("resume_lease_expires_at")
            if lease and datetime.fromisoformat(lease) > now:
                continue
            # Uncertain execution is not an instruction to repeat external mutations.
            candidate["status"] = "recovery_required"
            candidate["recovery_reason"] = "A continuation worker stopped before acknowledging its result."
            jobs.replace_item(
                candidate["id"], body=candidate, partition_key=candidate["user_id"],
                etag=candidate["_etag"], match_condition=MatchConditions.IfNotModified,
            )
            log_event(
                "[MS_GRAPH_PLUGIN] Workflow continuation requires recovery.",
                level=logging.WARNING,
                extra={"request_id": candidate["id"]},
            )
            continue
        if candidate.get("status") == "awaiting_sign_in":
            if connection_ready is None or not connection_ready(candidate):
                continue
            approval = None
        else:
            try:
                approval = approvals.get_approval(
                    candidate["approval_id"], candidate["user_id"],
                )
            except (CosmosResourceNotFoundError, LookupError):
                log_event(
                    "[MS_GRAPH_PLUGIN] Continuation approval is unavailable.",
                    level=logging.WARNING, extra={"request_id": candidate["id"]},
                )
                continue
            if approval.get("status") not in DECIDED_STATES:
                continue
        if not can_resume(candidate, approval):
            continue
        claimed = {
            **candidate,
            "status": "resuming",
            "resume_lease_expires_at": (now + timedelta(minutes=15)).isoformat(),
        }
        try:
            claimed = jobs.replace_item(
                candidate["id"], body=claimed, partition_key=candidate["user_id"],
                etag=candidate["_etag"], match_condition=MatchConditions.IfNotModified,
            )
        except CosmosHttpResponseError as error:
            if error.status_code == 412:
                continue
            raise
        try:
            result = execute(claimed)
        except Exception:
            log_event(
                "[MS_GRAPH_PLUGIN] Workflow continuation failed.",
                level=logging.ERROR,
                extra={"request_id": claimed["id"]},
                exceptionTraceback=True,
            )
            current = jobs.read_item(claimed["id"], partition_key=claimed["user_id"])
            if current.get("_etag") == claimed["_etag"]:
                current["status"] = "recovery_required"
                jobs.replace_item(
                    current["id"], body=current, partition_key=current["user_id"],
                    etag=current["_etag"], match_condition=MatchConditions.IfNotModified,
                )
            raise
        current = jobs.read_item(claimed["id"], partition_key=claimed["user_id"])
        if current.get("_etag") == claimed["_etag"]:
            current["status"] = "completed" if result.get("success") else "failed"
            current["completed_at"] = now.isoformat()
            jobs.replace_item(
                current["id"], body=current, partition_key=current["user_id"],
                etag=current["_etag"], match_condition=MatchConditions.IfNotModified,
            )
        outcomes.append({"request_id": claimed["id"], "result": result})
    return outcomes
