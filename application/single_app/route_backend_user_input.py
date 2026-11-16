# route_backend_user_input.py
"""V2 interactive local-agent questions; answers never grant action permissions."""

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from functools import wraps
import hmac
import time
import uuid

from flask import Response, jsonify, make_response, request, session, stream_with_context

from action_credential_contracts import ActionCredentialError
from agent_interaction_contracts import AgentInteractionRequired
from functions_appinsights import log_event
from functions_interaction_csrf import get_interaction_csrf_token as _csrf_token
from functions_authentication import get_current_user_id, login_required, user_required
from functions_action_credentials import (
    authorize_conversation, credential_continuation, credential_services,
    pending_execution_ids, request_conversation,
)
import functions_action_credential_state as state
from functions_user_input import (
    UserInputError, answer_request, finish_request, pending_requests, read_request, safe_request, stop_request,
)
from route_backend_action_credentials import _orchestration_continue
from swagger_wrapper import swagger_route, get_auth_security


def _input_boundary(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            response = function(*args, **kwargs)
        except (PermissionError, LookupError):
            response = jsonify({"error": "This question is unavailable.", "code": "not_found"}), 404
        except (UserInputError, ActionCredentialError) as error:
            response = jsonify({"error": "This question changed or could not continue. Refresh the conversation.", "code": error.code}), error.status_code
        except Exception as error:
            log_event("[PLUGINS] User input could not be processed.", extra={"error_type": type(error).__name__})
            response = jsonify({"error": "Your answers could not be processed. Refresh and retry.", "code": "input_unavailable"}), 503
        result = make_response(response)
        result.headers["Cache-Control"] = "no-store"
        return result
    return guarded


def _body():
    token = session.get("action_credentials_csrf_token") or ""
    supplied = request.headers.get("X-CSRFToken") or ""
    if not token or not hmac.compare_digest(token, supplied):
        raise UserInputError("input_csrf_invalid", 403)
    if request.content_length is None or request.content_length > 131072:
        raise UserInputError("input_invalid", 400)
    body = request.get_json(silent=True)
    if type(body) is not dict:
        raise UserInputError("input_invalid", 400)
    return body


def _chat_continue(item, user_id):
    # Reconstruction belongs to the initialized route, not a lower-level contract/tool.
    from agent_execution_context import AgentExecutionFrame, AgentExecutionCancelled, DelegationBudget, agent_execution, capture_execution_identity
    from agent_delegation_runtime import _build_local_agent, await_agent_operation, close_agent_resources
    from functions_agent_delegation import resolve_delegation_agent
    from functions_action_credential_continuation import invoke_credential_agent
    from functions_settings import get_settings
    from functions_orchestration_events import serialize_sse
    from route_backend_chats import _persist_screened_assistant
    from semantic_kernel.contents import ChatHistory
    from agent_delegation_runtime import _observed_usage, delegation_citations, delegation_usage
    from functions_user_input import services

    accepted_answers = {
        **item["continuation"].get("user_input_answers", {}),
        **{item["question"]["requested_schema"]["properties"][name].get("title", name): value
           for name, value in item["response"]["content"].items()},
    }
    descriptor = {
        **item["continuation"], "resume": True, "user_input_enabled": True,
        "user_input_answers": accepted_answers,
        "retained_agent_citations": item.get("retained_agent_citations", []),
    }
    checkpoint = state.read(user_id, descriptor["checkpoint_id"], record_type="credential_checkpoint")
    if checkpoint["conversation_id"] != item["conversation_id"] or "root" not in checkpoint["value"]:
        raise UserInputError("input_checkpoint_changed")
    original_payload = {key: value for key, value in descriptor.get("interaction_payload", {}).items()
                        if key != "m365_request_id"}
    identity = replace(capture_execution_identity(
        user_id, item["conversation_id"], request_payload=original_payload,
    ), supports_user_input=True)
    settings = get_settings()
    target = resolve_delegation_agent(descriptor["agent_reference"], user_id=user_id, settings=settings)
    budget = DelegationBudget(**item["budget"])
    checked_at, stopped = 0.0, False

    def cancelled():
        nonlocal checked_at, stopped
        now = time.monotonic()
        if now - checked_at >= 1:
            current = state.read(user_id, item["id"], record_type="user_input_request")
            stopped = (
                current.get("cancel_requested") is True or current["status"] != "continuing"
                or current.get("continuation_claim") != item["continuation_claim"]
            )
            checked_at = now
        return stopped

    frame = AgentExecutionFrame(identity, target, budget, cancel_requested=cancelled)

    async def execute():
        from functions_m365_approvals import M365ApprovalRequired
        from m365_interaction import M365SignInRequired
        from functions_m365_runtime import initialize_m365_chat_context, record_m365_pending, record_m365_auth_wait

        with identity.bridge(target), agent_execution(frame), credential_continuation(descriptor):
            kernel = None
            try:
                request_conversation(item)
                initialize_m365_chat_context(user_id, item["conversation_id"])
                kernel, agent = _build_local_agent(
                    target, settings, construction_profile=descriptor.get("construction_profile", "agent-core"),
                )
                return await await_agent_operation(invoke_credential_agent(agent, None), frame)
            except M365ApprovalRequired as error:
                raise _RecordedInteraction(record_m365_pending(error)) from error
            except M365SignInRequired as error:
                raise _RecordedInteraction(record_m365_auth_wait(error)) from error
            finally:
                if kernel is not None:
                    await close_agent_resources(kernel)

    @stream_with_context
    def frames():
        try:
            result = asyncio.run(execute())
            if result is None:
                raise UserInputError("input_result_unavailable", 503)
            request_conversation(item)
            completed = state.read(user_id, descriptor["checkpoint_id"], record_type="credential_checkpoint")
            history = ChatHistory.restore_chat_history(completed["value"]["root"]["history"])
            usage = {}
            for entry in history.messages:
                for key, value in (_observed_usage(entry) or {}).items():
                    usage[key] = usage.get(key, 0) + value
            delegated_usage = delegation_usage(budget) or {}
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                if key in delegated_usage:
                    usage[key] = usage.get(key, 0) + delegated_usage[key]
            citations = [
                *item.get("retained_agent_citations", []),
                *(services().capture_citations(frame) if services().capture_citations else []),
                *delegation_citations(budget),
            ]
            message = {
                "id": f"input_answer_{state.key_for(descriptor['checkpoint_id'])}",
                "conversation_id": item["conversation_id"], "user_id": user_id,
                "role": "assistant", "content": str(result),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "metadata": {"user_input_answers": accepted_answers, "token_usage": usage},
                "agent_citations": citations,
                "agent_name": target.get("name"),
                "agent_display_name": target.get("display_name") or target.get("name"),
            }
            saved = _persist_screened_assistant(message, user_id, settings=settings)
            publish = credential_services().publish_chat_result
            if publish:
                saved = publish(user_id, item, saved)
            outcome = {
                "done": True, "full_content": saved["content"], "message_id": saved["id"],
                "conversation_id": safe_request(item)["conversation_id"], "reload_messages": True,
            }
            finish_request(user_id, item["id"], item["continuation_claim"], "completed", outcome)
            yield serialize_sse(outcome)
        except AgentExecutionCancelled:
            finish_request(user_id, item["id"], item["continuation_claim"], "cancelled")
            yield serialize_sse({"done": True, "cancelled": True, "full_content": ""})
        except AgentInteractionRequired as error:
            finish_request(user_id, item["id"], item["continuation_claim"], "superseded")
            yield serialize_sse(error.event)
        except Exception as error:
            # A post-resume failure may follow a real effect. Never restart this execution.
            finish_request(user_id, item["id"], item["continuation_claim"], "failed")
            log_event("[PLUGINS] Agent answer continuation stopped.", extra={"error_type": type(error).__name__})
            yield serialize_sse({"error": "The saved work could not finish. It was not automatically replayed.", "done": True})

    return Response(frames(), mimetype="text/event-stream", headers={"Cache-Control": "no-store"})


class _RecordedInteraction(AgentInteractionRequired):
    def __init__(self, event):
        super().__init__("An existing authorization interaction is required.")
        self.event = event


def register_route_backend_user_input(bp):
    @bp.route("/api/v2/user-input/pending", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @_input_boundary
    def user_input_pending():
        user_id = get_current_user_id()
        conversation_id = request.args.get("conversation_id")
        if not isinstance(conversation_id, str) or not conversation_id or len(conversation_id) > 200:
            raise UserInputError("input_invalid", 400)
        context = authorize_conversation(user_id, conversation_id)
        return jsonify({
            "requests": pending_requests(user_id, pending_execution_ids(context, conversation_id)),
            "csrf_token": _csrf_token(),
        })

    @bp.route("/api/v2/user-input/<request_id>/answer", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @_input_boundary
    def user_input_answer(request_id):
        user_id = get_current_user_id()
        item = answer_request(user_id, request_id, _body())
        if item["status"] == "cancelled" and item["continuation"].get("run_id"):
            from functions_orchestration_recovery import request_cancellation

            request_cancellation(
                item["continuation"]["run_id"], user_id, item["conversation_id"],
                lambda: request_conversation(item),
            )
        return jsonify({"input_request": safe_request(item)})

    @bp.route("/api/v2/user-input/<request_id>/continue", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @_input_boundary
    def user_input_continue(request_id):
        body = _body()
        if set(body) != {"submission_id"}:
            raise UserInputError("input_invalid", 400)
        user_id = get_current_user_id()
        item = read_request(user_id, request_id)
        if item["continuation"].get("mode") not in {"chat", "orchestration"}:
            raise UserInputError("input_invalid", 400)
        if item.get("submission_id") != body["submission_id"]:
            raise UserInputError("input_changed")
        if item["status"] == "completed":
            from functions_orchestration_events import serialize_sse

            return Response(serialize_sse(item.get("outcome") or {"done": True, "reload_messages": True}),
                            mimetype="text/event-stream", headers={"Cache-Control": "no-store"})
        if item["status"] != "answered":
            raise UserInputError("input_resume_unconfirmed")
        claimed = state.replace(user_id, item, {
            "status": "continuing", "continuation_claim": uuid.uuid4().hex,
        }, item["_etag"])
        try:
            return _orchestration_continue(claimed, user_id) if item["continuation"]["mode"] == "orchestration" else _chat_continue(claimed, user_id)
        except Exception:
            # Admission failed before either execution generator started.
            finish_request(user_id, request_id, claimed["continuation_claim"], "answered")
            raise

    @bp.route("/api/v2/user-input/<request_id>/stop", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @_input_boundary
    def user_input_stop(request_id):
        body = _body()
        if set(body) != {"submission_id"}:
            raise UserInputError("input_invalid", 400)
        item = stop_request(get_current_user_id(), request_id, body["submission_id"])
        return jsonify({"cancel_requested": bool(item.get("cancel_requested")), "status": item["status"]})
