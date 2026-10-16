# route_backend_action_credentials.py
"""Credential-only interaction API. General workspace authoring stays unchanged."""

from functools import wraps
import hmac
import logging
import secrets
import uuid
from datetime import datetime, timezone

from flask import Response, jsonify, request, session, stream_with_context

from action_credential_contracts import ActionCredentialError, ActionCredentialsRequired
from functions_authentication import get_current_user_id, login_required, user_required
from functions_appinsights import log_event, workflow_log_context
from functions_action_credentials import (
    authorize_conversation, authorize_request, credential_continuation, safe_request, submit_credentials,
)
import functions_action_credential_state as state
from swagger_wrapper import swagger_route, get_auth_security


def _csrf_token():
    if not session.get("action_credentials_csrf_token"):
        session["action_credentials_csrf_token"] = secrets.token_urlsafe(32)
    return session["action_credentials_csrf_token"]


def _body(fields):
    expected = session.get("action_credentials_csrf_token") or ""
    supplied = request.headers.get("X-CSRFToken") or ""
    if not expected or not hmac.compare_digest(expected, supplied):
        raise ActionCredentialError("credential_csrf_invalid", 403)
    if request.content_length is not None and request.content_length > 32768:
        raise ActionCredentialError("invalid_request", 400)
    value = request.get_json(silent=True)
    if type(value) is not dict or set(value) != fields:
        raise ActionCredentialError("invalid_request", 400)
    if type(value.get("expected_etag")) is not str or not value["expected_etag"]:
        raise ActionCredentialError("invalid_request", 400)
    return value


def _credential_boundary(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            response = function(*args, **kwargs)
        except (PermissionError, LookupError):
            response = jsonify({"error": "Credential request not found.", "code": "not_found"}), 404
        except ActionCredentialError as error:
            response = jsonify({"error": "Refresh the credential request and try again.", "code": error.code}), error.status_code
        except Exception as error:
            # No payloads, provider text, or exception tracebacks at this secret-bearing boundary.
            log_event("[PLUGINS] Credential interaction failed.", extra={"error_type": type(error).__name__})
            response = jsonify({"error": "Action credentials could not be saved or resumed.", "code": "credentials_unavailable"}), 503
        from flask import make_response

        result = make_response(response)
        result.headers["Cache-Control"] = "no-store"
        result.headers["Pragma"] = "no-cache"
        return result
    return guarded


def _finish_request(user_id, request_id, claim, status):
    current = state.read(user_id, request_id, record_type="credential_request")
    if current["status"] == "continuing" and current.get("continuation_claim") == claim:
        state.replace(user_id, current, {"status": status}, current["_etag"])


class _CredentialExecution:
    """Complete interaction state on the durable worker, not the browser socket."""

    def __init__(self, execution, item, user_id):
        self.execution, self.item, self.user_id = execution, item, user_id

    def execute(self, **kwargs):
        try:
            yield from self.execution.execute(**kwargs)
        finally:
            try:
                status = self.execution.credential_continuation_status(self.item)
                _finish_request(self.user_id, self.item["id"], self.item["continuation_claim"], status)
            except Exception as error:
                log_event("[PLUGINS] Credential continuation outcome could not be confirmed.", level=logging.WARNING, extra={
                    **workflow_log_context(
                        run_id=self.item["continuation"]["run_id"], conversation_id=self.item["conversation_id"],
                        step_id=self.item["continuation"]["step_id"],
                    ),
                    "stage": "credential_continuation_finalization", "error_type": type(error).__name__,
                })
                raise

    def close(self):
        return self.execution.close()


def _orchestration_continue(item, user_id):
    from agent_execution_context import capture_execution_identity
    from config import cosmos_messages_container
    from functions_settings import get_settings
    from functions_orchestration_continuation import ContinuationCheckpoints, claim_run_continuation
    from functions_orchestration_execution import prepare_harness_execution
    from route_backend_orchestration import (
        _conversation_context_for_run, _request_identity, _stream_execution,
    )

    conversation_id, run_id = item["conversation_id"], item["continuation"]["run_id"]
    owned = claim_run_continuation(
        run_id, user_id, conversation_id,
        authorize=lambda: authorize_conversation(user_id, conversation_id),
        message_container=cosmos_messages_container, credential_request_id=item["id"],
    )
    if owned is None:
        raise ActionCredentialError("credential_execution_busy")
    record, lease = owned
    try:
        settings = get_settings()
        snapshot = _conversation_context_for_run(record, user_id, settings)
        record = {**record, "conversation_context": snapshot}
        # Harness initialization reacquires current capability/source permissions.
        execution = prepare_harness_execution(
            record, settings=settings, identity_context=_request_identity(user_id),
            execution_identity=capture_execution_identity(user_id, conversation_id),
            lease=lease, checkpoint_factory=ContinuationCheckpoints,
        )
    except BaseException:
        lease.close()
        raise
    return _stream_execution(
        _CredentialExecution(execution, item, user_id),
        run_id=run_id, conversation_id=conversation_id, settings=settings,
    )


def _chat_continue(item, user_id):
    from agent_execution_context import AgentExecutionFrame, DelegationBudget, agent_execution, capture_execution_identity
    from agent_delegation_runtime import _build_local_agent, close_agent_resources
    from functions_agent_delegation import resolve_delegation_agent
    from functions_settings import get_settings
    from functions_action_credential_continuation import invoke_credential_agent
    from route_backend_chats import _persist_screened_assistant
    from functions_orchestration_events import serialize_sse
    import asyncio

    descriptor = {**item["continuation"], "resume": True}
    checkpoint = state.read(user_id, descriptor["checkpoint_id"], record_type="credential_checkpoint")
    if checkpoint["conversation_id"] != item["conversation_id"] or "root" not in checkpoint["value"]:
        raise ActionCredentialError("credential_checkpoint_changed")
    identity = capture_execution_identity(user_id, item["conversation_id"])
    settings = get_settings()
    target = resolve_delegation_agent(descriptor["agent_reference"], user_id=user_id, settings=settings)
    frame = AgentExecutionFrame(identity, target, DelegationBudget())
    # Reconstruct a new invocation-local kernel under the current actor's bridge.
    with identity.bridge(target), agent_execution(frame):
        kernel, agent = _build_local_agent(target, settings)

    async def execute():
        with identity.bridge(target), agent_execution(frame), credential_continuation(descriptor):
            try:
                return await invoke_credential_agent(agent, None)
            finally:
                await close_agent_resources(kernel)

    @stream_with_context
    def frames():
        try:
            result = asyncio.run(execute())
            authorize_conversation(user_id, item["conversation_id"])
            message = {
                "id": uuid.uuid4().hex, "conversation_id": item["conversation_id"], "user_id": user_id,
                "role": "assistant", "content": str(result),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "metadata": {"action_credential_continuation": True},
            }
            saved = _persist_screened_assistant(message, user_id, settings=settings)
            _finish_request(user_id, item["id"], item["continuation_claim"], "completed")
            yield serialize_sse({"content": saved["content"]})
            yield serialize_sse({
                "done": True, "conversation_id": item["conversation_id"], "message_id": saved["id"],
                "reload_messages": True,
            })
        except ActionCredentialsRequired as error:
            _finish_request(user_id, item["id"], item["continuation_claim"], "superseded")
            yield serialize_sse(error.event)
        except Exception as error:
            _finish_request(user_id, item["id"], item["continuation_claim"], "failed")
            log_event("[PLUGINS] Credential continuation stopped.", extra={"error_type": type(error).__name__})
            yield serialize_sse({"error": "Saved work could not be continued. Refresh this conversation."})

    return Response(frames(), mimetype="text/event-stream", headers={"Cache-Control": "no-store"})


def register_route_backend_action_credentials(bp):
    @bp.route("/api/action-credentials/pending", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @_credential_boundary
    def action_credentials_pending():
        user_id = get_current_user_id()
        conversation_id = request.args.get("conversation_id")
        authorize_conversation(user_id, conversation_id)
        requests = []
        for row in state.pending(user_id, conversation_id):
            try:
                item, manifest = authorize_request(user_id, row["id"])
                requests.append(safe_request(item, manifest))
            except (PermissionError, LookupError, ActionCredentialError):
                continue
        return jsonify({"requests": requests, "csrf_token": _csrf_token()})

    @bp.route("/api/action-credentials/<request_id>", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @_credential_boundary
    def action_credentials_request(request_id):
        item, manifest = authorize_request(get_current_user_id(), request_id)
        return jsonify({"credential_request": safe_request(item, manifest), "csrf_token": _csrf_token()})

    @bp.route("/api/action-credentials/<request_id>/submit", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @_credential_boundary
    def action_credentials_submit(request_id):
        body = _body({"expected_etag", "slots"})
        dto = submit_credentials(get_current_user_id(), request_id, body["expected_etag"], body["slots"])
        return jsonify({"credential_request": dto})

    @bp.route("/api/action-credentials/<request_id>/continue", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @_credential_boundary
    def action_credentials_continue(request_id):
        body = _body({"expected_etag"})
        user_id = get_current_user_id()
        item, _manifest = authorize_request(user_id, request_id)
        descriptor = item.get("continuation") or {}
        if descriptor.get("mode") not in {"chat", "orchestration"}:
            raise ActionCredentialError("credential_continuation_unavailable")
        claimed = state.claim_request(user_id, item, body["expected_etag"])
        try:
            return _orchestration_continue(claimed, user_id) if descriptor["mode"] == "orchestration" else _chat_continue(claimed, user_id)
        except Exception:
            # Neither response generator has started: an admission/preparation
            # failure cannot have executed the blocked operation.
            _finish_request(user_id, claimed["id"], claimed["continuation_claim"], "ready")
            raise

    @bp.route("/api/action-credentials/<request_id>/cancel", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @_credential_boundary
    def action_credentials_cancel(request_id):
        body = _body({"expected_etag"})
        user_id = get_current_user_id()
        item, manifest = authorize_request(user_id, request_id)
        if item["status"] not in {"pending", "ready"}:
            raise ActionCredentialError("credential_request_closed")
        item = state.replace(user_id, item, {"status": "cancelled"}, body["expected_etag"])
        if item["continuation"].get("run_id"):
            from functions_orchestration_recovery import request_cancellation

            request_cancellation(
                item["continuation"]["run_id"], user_id, item["conversation_id"],
                lambda: authorize_conversation(user_id, item["conversation_id"]),
            )
        return jsonify({"credential_request": safe_request(item, manifest)})
