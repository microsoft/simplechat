# functions_m365_request_resume.py
"""Resume an approved chat using the deciding user's live session, never stored tokens."""

import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from azure.core import MatchConditions
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError
from flask import current_app, request, session

from config import cosmos_conversations_container, cosmos_m365_execution_runs_container
from functions_appinsights import log_event
from functions_m365_approvals import M365PolicyError, get_m365_approval_service


def queue_approved_chat(approval, user_id):
    """Only enqueue the original subject's request once after a recorded decision."""
    context = approval.get("context") or {}
    request_id = context.get("request_id")
    if not request_id or context.get("workflow_id") or request_id.startswith("m365-share-"):
        return {"resume_scheduled": False}
    if user_id != approval.get("subject_user_id") or (session.get("user") or {}).get("oid") != user_id:
        raise PermissionError("Only the data user may resume this Microsoft 365 request.")
    jobs = cosmos_m365_execution_runs_container
    try:
        job = jobs.read_item(request_id, partition_key=user_id)
    except CosmosResourceNotFoundError:
        raise M365PolicyError("m365_request_not_found", "The pending conversation request no longer exists.")
    if (
        job.get("user_id") != user_id or job.get("actor_user_id") != user_id
        or job.get("approval_id") != approval.get("id")
        or job.get("conversation_id") != context.get("conversation_id")
    ):
        raise PermissionError("This approval does not authorize that conversation request.")
    if job.get("status") in {"ready_to_resume", "running", "completed"}:
        return {"resume_scheduled": True, "execution_status": job["status"]}
    if job.get("status") != "awaiting_approval":
        return {"resume_scheduled": False, "execution_status": job.get("status")}
    return _queue_chat_job(job, user_id)


def get_m365_chat_request(request_id, user_id):
    """Read only a subject-owned, resumable interactive request."""
    try:
        job = cosmos_m365_execution_runs_container.read_item(request_id, partition_key=user_id)
    except CosmosResourceNotFoundError as exc:
        raise LookupError("The saved Microsoft 365 chat request no longer exists.") from exc
    if (
        job.get("user_id") != user_id or job.get("actor_user_id") != user_id
        or job.get("workflow_id") or job.get("type") != "m365_execution_request"
    ):
        raise PermissionError("This request cannot be resumed as your chat.")
    if job.get("status") not in {"awaiting_sign_in", "awaiting_approval", "ready_to_resume"}:
        raise M365PolicyError("m365_request_not_waiting", "This request is not waiting for a user decision.")
    return job


def resume_m365_chat_request(request_id, user_id):
    job = get_m365_chat_request(request_id, user_id)
    if job.get("status") == "awaiting_sign_in":
        from functions_m365_connections import get_m365_access_token
        token_result = get_m365_access_token(job.get("required_scopes") or ["User.Read"])
        if not token_result.get("access_token"):
            return {
                "resume_scheduled": False, "auth_required": True,
                "m365_request_id": request_id,
                **{key: token_result[key] for key in ("auth_url", "consent_url", "message") if key in token_result},
            }
    if job.get("status") == "ready_to_resume":
        expires = job.get("resume_queue_expires_at")
        if expires and datetime.fromisoformat(expires) > datetime.now(timezone.utc):
            return {"resume_scheduled": True, "execution_status": "queued"}
    if job.get("status") == "awaiting_approval" and job.get("approval_id"):
        approval = get_m365_approval_service().get_approval(job["approval_id"], user_id)
        if approval["status"] == "pending":
            raise M365PolicyError("m365_approval_pending", "Review and decide the approval before resuming this request.")
    return _queue_chat_job(job, user_id)


def _queue_chat_job(job, user_id):
    request_id = job["id"]
    jobs = cosmos_m365_execution_runs_container
    if (session.get("user") or {}).get("oid") != user_id:
        raise PermissionError("The live session does not match the waiting request.")
    executor = current_app.extensions.get("executor")
    if executor is None:
        raise M365PolicyError("m365_executor_unavailable", "Background execution is unavailable. Your decision is saved.")
    cookie_name = current_app.config["SESSION_COOKIE_NAME"]
    cookie_value = request.cookies.get(cookie_name)
    if not cookie_value:
        raise M365PolicyError("m365_session_required", "Sign in again before resuming this conversation.")
    cookie_header = f"{cookie_name}={cookie_value}"
    queue_id = uuid4().hex
    queued = {
        **job, "status": "ready_to_resume", "resume_queue_id": queue_id,
        "resume_queue_expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
    }
    try:
        jobs.replace_item(
            request_id, body=queued,
            etag=job["_etag"], match_condition=MatchConditions.IfNotModified,
        )
    except CosmosHttpResponseError as error:
        if error.status_code != 412:
            raise
        return {"resume_scheduled": True, "execution_status": "queued"}
    app = current_app._get_current_object()
    try:
        executor.submit(_execute_chat_continuation, app, cookie_header, queued)
    except Exception:
        latest = jobs.read_item(request_id, partition_key=user_id)
        if latest.get("status") == "ready_to_resume" and latest.get("resume_queue_id") == queue_id:
            latest["status"] = job["status"]
            jobs.replace_item(
                request_id, body=latest,
                etag=latest["_etag"], match_condition=MatchConditions.IfNotModified,
            )
        raise
    return {"resume_scheduled": True, "execution_status": "queued"}


def _execute_chat_continuation(app, cookie_header, job):
    """Consume the ordinary route so persistence, collaboration, and notifications match chat."""
    jobs = cosmos_m365_execution_runs_container
    try:
        current = jobs.read_item(job["id"], partition_key=job["user_id"])
        if current.get("status") != "ready_to_resume" or current.get("resume_queue_id") != job["resume_queue_id"]:
            return
        payload = dict(job.get("payload") or {})
        payload.update(m365_request_id=job["id"], conversation_id=job["conversation_id"])
        if job.get("user_message_id"):
            payload["retry_user_message_id"] = job["user_message_id"]
        conversation = cosmos_conversations_container.read_item(
            item=job["conversation_id"], partition_key=job["conversation_id"],
        )
        shared_id = conversation.get("collaboration_conversation_id")
        endpoint = f"/api/collaboration/conversations/{shared_id}/stream" if shared_id else "/api/chat/stream"
        if shared_id:
            payload["content"] = payload.pop("message", payload.get("content", ""))
        with app.test_request_context(endpoint, method="POST", json=payload, headers={"Cookie": cookie_header}):
            if (session.get("user") or {}).get("oid") != job["user_id"]:
                raise M365PolicyError("m365_session_expired", "Sign in again to resume this conversation.")
            response = app.full_dispatch_request()
            try:
                for _chunk in response.response:
                    pass
            finally:
                response.close()
            if response.status_code >= 400:
                raise M365PolicyError("m365_resume_failed", "The saved request could not be resumed.")
            latest = jobs.read_item(job["id"], partition_key=job["user_id"])
            if latest.get("status") in {"ready_to_resume", "running"}:
                raise M365PolicyError("m365_resume_unfinished", "The continuation ended without a committed completion.")
    except Exception as error:
        log_event(
            "[MS_GRAPH_PLUGIN] Microsoft 365 chat continuation did not complete.",
            extra={"request_id": job["id"], "conversation_id": job["conversation_id"]},
            level=logging.ERROR, exceptionTraceback=True,
        )
        latest = jobs.read_item(job["id"], partition_key=job["user_id"])
        if latest.get("status") in {"ready_to_resume", "running"}:
            latest["status"] = (
                "awaiting_sign_in" if isinstance(error, M365PolicyError) and error.code == "m365_session_expired"
                else "recovery_required"
            )
            jobs.replace_item(
                latest["id"], body=latest,
                etag=latest["_etag"], match_condition=MatchConditions.IfNotModified,
            )
            if latest.get("approval_id"):
                get_m365_approval_service().record_execution_status(
                    latest["approval_id"], latest["user_id"], latest["id"], latest["status"],
                )
