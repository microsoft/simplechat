# route_backend_workflows.py

"""
Backend routes for personal workflows.
"""

import json
import logging
import time
from datetime import datetime, timezone

from flask import Response, jsonify, request, stream_with_context

from background_tasks import acquire_distributed_task_lock, release_distributed_task_lock
from config import CosmosResourceNotFoundError, cosmos_conversations_container
from functions_activity_logging import (
    log_workflow_creation,
    log_workflow_deletion,
    log_workflow_update,
)
from functions_appinsights import log_event
from functions_authentication import get_current_user_id, login_required, user_required
from functions_thoughts import get_thoughts_for_message
from functions_workflow_activity import build_workflow_activity_snapshot
from functions_personal_workflows import (
    compute_next_run_at,
    delete_personal_workflow,
    get_latest_personal_workflow_run_for_conversation,
    get_personal_workflow,
    get_personal_workflow_run,
    get_personal_workflows,
    list_personal_workflow_runs,
    save_personal_workflow,
    update_personal_workflow_runtime_fields,
)
from functions_settings import enabled_required
from functions_workflow_runner import run_personal_workflow
from swagger_wrapper import swagger_route, get_auth_security


def _normalize_identifier(value):
    return str(value or '').strip()


def _load_workflow_conversation(user_id, conversation_id):
    if not conversation_id:
        return None

    try:
        conversation = cosmos_conversations_container.read_item(
            item=conversation_id,
            partition_key=conversation_id,
        )
    except CosmosResourceNotFoundError as exc:
        raise ValueError('Workflow conversation not found.') from exc

    if conversation.get('user_id') != user_id:
        raise PermissionError('Forbidden')
    if conversation.get('chat_type') != 'workflow':
        raise ValueError('Workflow activity is only available for workflow conversations.')
    return {key: value for key, value in conversation.items() if not str(key).startswith('_')}


def _resolve_workflow_activity_context(user_id, conversation_id='', workflow_id='', run_id=''):
    workflow_id = _normalize_identifier(workflow_id)
    conversation_id = _normalize_identifier(conversation_id)
    run_id = _normalize_identifier(run_id)

    if not any([conversation_id, workflow_id, run_id]):
        raise ValueError('A workflow activity request needs a conversation, workflow, or run identifier.')

    workflow = get_personal_workflow(user_id, workflow_id) if workflow_id else None
    run_record = get_personal_workflow_run(user_id, run_id) if run_id else None

    if run_id and not run_record:
        raise ValueError('Workflow run not found.')

    if run_record and workflow_id and _normalize_identifier(run_record.get('workflow_id')) != workflow_id:
        raise ValueError('The requested run does not belong to this workflow.')

    if run_record and not workflow:
        workflow = get_personal_workflow(user_id, run_record.get('workflow_id'))

    if not conversation_id:
        conversation_id = _normalize_identifier((run_record or {}).get('conversation_id') or (workflow or {}).get('conversation_id'))

    conversation = _load_workflow_conversation(user_id, conversation_id) if conversation_id else None

    if conversation and workflow_id and _normalize_identifier(conversation.get('workflow_id')) not in {'', workflow_id}:
        raise ValueError('The requested conversation does not belong to this workflow.')

    if not workflow and conversation:
        workflow = get_personal_workflow(user_id, conversation.get('workflow_id'))

    if not run_record and conversation_id:
        run_record = get_latest_personal_workflow_run_for_conversation(
            user_id,
            conversation_id,
            workflow_id=_normalize_identifier((workflow or {}).get('id')) or workflow_id,
        )

    if run_record and conversation_id and _normalize_identifier(run_record.get('conversation_id')) not in {'', conversation_id}:
        raise ValueError('The requested run does not belong to this workflow conversation.')

    thoughts = []
    if run_record and conversation_id and _normalize_identifier(run_record.get('assistant_message_id')):
        thoughts = get_thoughts_for_message(
            conversation_id,
            run_record.get('assistant_message_id'),
            user_id,
        )

    return build_workflow_activity_snapshot(
        run_record=run_record,
        workflow=workflow,
        conversation=conversation,
        thoughts=thoughts,
    )


def _stream_workflow_activity(user_id, conversation_id='', workflow_id='', run_id=''):
    last_payload = None
    terminal_snapshots_seen = 0

    yield 'retry: 750\n\n'

    for _ in range(300):
        snapshot = _resolve_workflow_activity_context(
            user_id,
            conversation_id=conversation_id,
            workflow_id=workflow_id,
            run_id=run_id,
        )
        payload = json.dumps(snapshot, default=str, sort_keys=True)

        if payload != last_payload:
            last_payload = payload
            yield f'data: {payload}\n\n'
        else:
            yield ': keep-alive\n\n'

        run_status = str(((snapshot.get('run') or {}).get('status') or '')).strip().lower()
        if run_status and run_status != 'running':
            terminal_snapshots_seen += 1
            if terminal_snapshots_seen >= 2:
                break
        else:
            terminal_snapshots_seen = 0

        time.sleep(0.5)


def register_route_backend_workflows(app):
    @app.route('/api/user/workflows', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_workflows')
    def get_user_workflows():
        user_id = get_current_user_id()
        return jsonify({'workflows': get_personal_workflows(user_id)})


    @app.route('/api/user/workflows', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_workflows')
    def save_user_workflow():
        user_id = get_current_user_id()
        payload = request.get_json(silent=True) or {}
        is_create = not str(payload.get('id') or '').strip()

        try:
            workflow = save_personal_workflow(user_id, payload, actor_user_id=user_id)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except Exception as exc:
            log_event(
                f'[WorkflowRoutes] Failed to save workflow: {exc}',
                extra={'user_id': user_id},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Unable to save workflow right now.'}), 500

        if is_create:
            log_workflow_creation(
                user_id=user_id,
                workflow_id=workflow.get('id', ''),
                workflow_name=workflow.get('name', ''),
                runner_type=workflow.get('runner_type'),
                trigger_type=workflow.get('trigger_type'),
            )
        else:
            log_workflow_update(
                user_id=user_id,
                workflow_id=workflow.get('id', ''),
                workflow_name=workflow.get('name', ''),
                runner_type=workflow.get('runner_type'),
                trigger_type=workflow.get('trigger_type'),
            )

        return jsonify({'success': True, 'workflow': workflow}), 201 if is_create else 200


    @app.route('/api/user/workflows/<workflow_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_workflows')
    def delete_user_workflow(workflow_id):
        user_id = get_current_user_id()
        workflow = get_personal_workflow(user_id, workflow_id)
        if not workflow:
            return jsonify({'error': 'Workflow not found.'}), 404

        deleted = delete_personal_workflow(user_id, workflow_id)
        if not deleted:
            return jsonify({'error': 'Workflow not found.'}), 404

        log_workflow_deletion(
            user_id=user_id,
            workflow_id=workflow_id,
            workflow_name=workflow.get('name', ''),
        )
        return jsonify({'success': True})


    @app.route('/api/user/workflows/<workflow_id>/runs', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_workflows')
    def get_user_workflow_runs(workflow_id):
        user_id = get_current_user_id()
        workflow = get_personal_workflow(user_id, workflow_id)
        if not workflow:
            return jsonify({'error': 'Workflow not found.'}), 404

        return jsonify({
            'workflow_id': workflow_id,
            'runs': list_personal_workflow_runs(user_id, workflow_id, limit=50),
        })


    @app.route('/api/user/workflows/activity', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_workflows')
    def get_user_workflow_activity_snapshot():
        user_id = get_current_user_id()
        conversation_id = request.args.get('conversation_id', '')
        workflow_id = request.args.get('workflow_id', '')
        run_id = request.args.get('run_id', '')

        try:
            snapshot = _resolve_workflow_activity_context(
                user_id,
                conversation_id=conversation_id,
                workflow_id=workflow_id,
                run_id=run_id,
            )
            return jsonify(snapshot)
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except Exception as exc:
            log_event(
                f'[WorkflowRoutes] Failed to load workflow activity snapshot: {exc}',
                extra={
                    'user_id': user_id,
                    'conversation_id': conversation_id,
                    'workflow_id': workflow_id,
                    'run_id': run_id,
                },
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Unable to load workflow activity right now.'}), 500


    @app.route('/api/user/workflows/activity/stream', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_workflows')
    def stream_user_workflow_activity():
        user_id = get_current_user_id()
        conversation_id = request.args.get('conversation_id', '')
        workflow_id = request.args.get('workflow_id', '')
        run_id = request.args.get('run_id', '')

        try:
            _resolve_workflow_activity_context(
                user_id,
                conversation_id=conversation_id,
                workflow_id=workflow_id,
                run_id=run_id,
            )
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except Exception as exc:
            log_event(
                f'[WorkflowRoutes] Failed to initialize workflow activity stream: {exc}',
                extra={
                    'user_id': user_id,
                    'conversation_id': conversation_id,
                    'workflow_id': workflow_id,
                    'run_id': run_id,
                },
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Unable to open workflow activity stream right now.'}), 500

        return Response(
            stream_with_context(
                _stream_workflow_activity(
                    user_id,
                    conversation_id=conversation_id,
                    workflow_id=workflow_id,
                    run_id=run_id,
                )
            ),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
            },
        )


    @app.route('/api/user/workflows/<workflow_id>/run', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('allow_user_workflows')
    def run_user_workflow(workflow_id):
        user_id = get_current_user_id()
        workflow = get_personal_workflow(user_id, workflow_id)
        if not workflow:
            return jsonify({'error': 'Workflow not found.'}), 404

        lock_document = acquire_distributed_task_lock(f'workflow_run_{workflow_id}', lease_seconds=900)
        if not lock_document:
            return jsonify({'error': 'This workflow is already running.'}), 409

        try:
            started_at = datetime.now(timezone.utc).isoformat()
            update_personal_workflow_runtime_fields(
                user_id,
                workflow_id,
                {
                    'status': 'running',
                    'last_run_started_at': started_at,
                    'last_run_trigger_source': 'manual',
                    'last_run_error': '',
                },
            )

            result = run_personal_workflow(workflow, trigger_source='manual')
            update_fields = dict(result.get('workflow_updates') or {})
            update_fields['status'] = 'idle'
            if workflow.get('trigger_type') == 'interval' and workflow.get('is_enabled', False) and not workflow.get('next_run_at'):
                update_fields['next_run_at'] = compute_next_run_at(workflow, from_time=datetime.now(timezone.utc))

            updated_workflow = update_personal_workflow_runtime_fields(user_id, workflow_id, update_fields)
            response_body = {
                'success': bool(result.get('success')),
                'workflow': updated_workflow,
                'run': result.get('run'),
            }
            if result.get('success'):
                return jsonify(response_body)
            return jsonify(response_body), 500
        finally:
            release_distributed_task_lock(lock_document)