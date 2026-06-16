# background_tasks.py

"""Shared background task runners for web-process and dedicated scheduler use."""

import logging
import os
import socket
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

from azure.core import MatchConditions

from config import cosmos_settings_container, exceptions
from functions_appinsights import log_event
from functions_control_center import (
    calculate_next_control_center_auto_refresh_run,
    execute_control_center_refresh,
    get_control_center_auto_refresh_schedule,
    parse_control_center_auto_refresh_datetime,
)
from functions_cosmos_throughput import (
    COSMOS_THROUGHPUT_AUTOSCALE_DEFAULT_INTERVAL_SECONDS,
    calculate_cosmos_throughput_autoscale_interval_seconds,
    evaluate_and_apply_cosmos_throughput_scaling,
)
from functions_debug import debug_print
from functions_data_management import check_due_data_management_jobs_once
from functions_file_sync import check_due_file_sync_sources_once
from functions_tabular_generated_exports import check_due_tabular_generated_output_runs_once
from functions_personal_workflows import (
    compute_next_run_at,
    get_due_personal_workflows,
    get_personal_workflow,
    update_personal_workflow_runtime_fields,
)
from functions_group_workflows import (
    get_due_group_workflows,
    get_group_workflow,
    update_group_workflow_runtime_fields,
)
from functions_settings import get_settings, is_group_workflows_enabled_for_group, update_settings
from functions_workflow_runner import run_group_workflow, run_personal_workflow


def _get_lock_holder_id():
    """Return a process-unique holder id for distributed background task locks."""
    return f"{socket.gethostname()}:{os.getpid()}:{threading.get_ident()}"


def _is_expired_timestamp(timestamp_value, current_time):
    """Return True when the stored lock expiration timestamp is missing or expired."""
    if not timestamp_value:
        return True

    try:
        expiration_time = datetime.fromisoformat(timestamp_value)
    except Exception:
        return True

    return expiration_time <= current_time


def acquire_distributed_task_lock(task_name, lease_seconds):
    """Acquire a Cosmos-backed lease for a background task across workers and instances."""
    current_time = datetime.now(timezone.utc)
    expires_at = current_time + timedelta(seconds=lease_seconds)
    lock_id = f"background_task_lock_{task_name}"
    lock_body = {
        'id': lock_id,
        'type': 'background_task_lock',
        'task_name': task_name,
        'holder_id': _get_lock_holder_id(),
        'acquired_at': current_time.isoformat(),
        'expires_at': expires_at.isoformat(),
        'lease_seconds': lease_seconds,
        'lock_token': str(uuid.uuid4())
    }

    try:
        cosmos_settings_container.create_item(body=lock_body)
        return lock_body
    except Exception as exc:
        if getattr(exc, 'status_code', None) != 409:
            log_event(
                'background_task_lock_create_error',
                {'task_name': task_name, 'error': str(exc)},
                level=logging.ERROR
            )
            return None

    try:
        existing_lock = cosmos_settings_container.read_item(item=lock_id, partition_key=lock_id)
    except Exception as exc:
        log_event(
            'background_task_lock_read_error',
            {'task_name': task_name, 'error': str(exc)},
            level=logging.ERROR
        )
        return None

    if not _is_expired_timestamp(existing_lock.get('expires_at'), current_time):
        return None

    replacement_lock = dict(existing_lock)
    replacement_lock.update(lock_body)

    try:
        cosmos_settings_container.replace_item(
            item=lock_id,
            body=replacement_lock,
            etag=existing_lock.get('_etag'),
            match_condition=MatchConditions.IfNotModified
        )
        return replacement_lock
    except Exception as exc:
        status_code = getattr(exc, 'status_code', None)
        if status_code not in (409, 412):
            log_event(
                'background_task_lock_replace_error',
                {'task_name': task_name, 'error': str(exc), 'status_code': status_code},
                level=logging.ERROR
            )
        return None


def release_distributed_task_lock(lock_document):
    """Release a previously acquired distributed background task lock."""
    if not lock_document:
        return

    lock_id = lock_document.get('id')
    holder_id = lock_document.get('holder_id')
    if not lock_id or not holder_id:
        return

    try:
        current_lock = cosmos_settings_container.read_item(item=lock_id, partition_key=lock_id)
    except Exception:
        return

    if current_lock.get('holder_id') != holder_id:
        return

    try:
        cosmos_settings_container.delete_item(
            item=lock_id,
            partition_key=lock_id,
            etag=current_lock.get('_etag'),
            match_condition=MatchConditions.IfNotModified
        )
    except Exception:
        return


def _should_run_retention_policy(settings, current_time):
    """Return True when retention policy work should run for the current schedule state."""
    personal_enabled = settings.get('enable_retention_policy_personal', False)
    group_enabled = settings.get('enable_retention_policy_group', False)
    public_enabled = settings.get('enable_retention_policy_public', False)

    if not (personal_enabled or group_enabled or public_enabled):
        return False

    next_run = settings.get('retention_policy_next_run')
    if next_run:
        try:
            next_run_dt = datetime.fromisoformat(next_run)
            return current_time >= next_run_dt
        except Exception as parse_error:
            print(f"Error parsing next_run timestamp: {parse_error}")

    last_run = settings.get('retention_policy_last_run')
    if last_run:
        try:
            last_run_dt = datetime.fromisoformat(last_run)
            return (current_time - last_run_dt).total_seconds() > (23 * 3600)
        except Exception:
            return True

    return True


def check_logging_timers_once():
    """Disable temporary logging settings after their timer expires."""
    settings = get_settings()
    current_time = datetime.now()
    settings_changed = False

    if (
        settings.get('enable_debug_logging', False)
        and settings.get('debug_logging_timer_enabled', False)
        and settings.get('debug_logging_turnoff_time')
    ):
        turnoff_time = settings.get('debug_logging_turnoff_time')
        if isinstance(turnoff_time, str):
            try:
                turnoff_time = datetime.fromisoformat(turnoff_time)
            except Exception:
                turnoff_time = None

        if turnoff_time and current_time >= turnoff_time:
            debug_print(f"logging timer expired at {turnoff_time}. Disabling debug logging.")
            settings['enable_debug_logging'] = False
            settings['debug_logging_timer_enabled'] = False
            settings['debug_logging_turnoff_time'] = None
            settings_changed = True

    if (
        settings.get('enable_file_processing_logs', False)
        and settings.get('file_processing_logs_timer_enabled', False)
        and settings.get('file_processing_logs_turnoff_time')
    ):
        turnoff_time = settings.get('file_processing_logs_turnoff_time')
        if isinstance(turnoff_time, str):
            try:
                turnoff_time = datetime.fromisoformat(turnoff_time)
            except Exception:
                turnoff_time = None

        if turnoff_time and current_time >= turnoff_time:
            print(f"File processing logs timer expired at {turnoff_time}. Disabling file processing logs.")
            settings['enable_file_processing_logs'] = False
            settings['file_processing_logs_timer_enabled'] = False
            settings['file_processing_logs_turnoff_time'] = None
            settings_changed = True

    if settings_changed:
        update_settings(settings)
        print("Logging settings updated due to timer expiration.")


def check_expired_approvals_once():
    """Auto-deny expired approval requests and return the affected count."""
    from functions_approvals import auto_deny_expired_approvals

    lock_document = acquire_distributed_task_lock('approval_expiry', lease_seconds=1800)
    if not lock_document:
        debug_print('Skipping approval expiration check because another worker holds the lease.')
        return None

    try:
        denied_count = auto_deny_expired_approvals()
        if denied_count > 0:
            print(f"Auto-denied {denied_count} expired approval request(s).")
    finally:
        release_distributed_task_lock(lock_document)

    return denied_count


def check_retention_policy_once():
    """Run scheduled retention processing when the next execution window is due."""
    settings = get_settings()

    current_time = datetime.now(timezone.utc)

    if not _should_run_retention_policy(settings, current_time):
        return None

    lock_document = acquire_distributed_task_lock('retention_policy', lease_seconds=3600)
    if not lock_document:
        debug_print('Skipping retention policy check because another worker holds the lease.')
        return None

    settings = get_settings()
    current_time = datetime.now(timezone.utc)
    if not _should_run_retention_policy(settings, current_time):
        release_distributed_task_lock(lock_document)
        return None

    print(f"Executing scheduled retention policy at {current_time.isoformat()}")
    from functions_retention_policy import execute_retention_policy

    try:
        results = execute_retention_policy(manual_execution=False)
        if results.get('success'):
            print(
                "Retention policy execution completed: "
                f"{results['personal']['conversations']} personal conversations, "
                f"{results['personal']['documents']} personal documents, "
                f"{results['group']['conversations']} group conversations, "
                f"{results['group']['documents']} group documents, "
                f"{results['public']['conversations']} public conversations, "
                f"{results['public']['documents']} public documents deleted."
            )
        else:
            print(f"Retention policy execution failed: {results.get('errors')}")
    finally:
        release_distributed_task_lock(lock_document)

    return results


def _seed_control_center_auto_refresh_next_run(settings, current_time):
    """Persist the next Control Center auto-refresh run when schedule fields are missing."""
    schedule = get_control_center_auto_refresh_schedule(settings)
    next_run = calculate_next_control_center_auto_refresh_run(settings, current_time=current_time)
    update_settings({
        'control_center_auto_refresh_enabled': settings.get('control_center_auto_refresh_enabled', True),
        'control_center_auto_refresh_time': schedule['time'],
        'control_center_auto_refresh_hour': schedule['hour'],
        'control_center_auto_refresh_minute': schedule['minute'],
        'control_center_auto_refresh_next_run': next_run.isoformat(),
    })
    return next_run


def check_control_center_auto_refresh_once():
    """Run the scheduled Control Center refresh when its daily UTC schedule is due."""
    settings = get_settings()
    if not settings.get('control_center_auto_refresh_enabled', True):
        return None

    current_time = datetime.now(timezone.utc)
    next_run = parse_control_center_auto_refresh_datetime(settings.get('control_center_auto_refresh_next_run'))
    if not next_run:
        _seed_control_center_auto_refresh_next_run(settings, current_time)
        return None

    if current_time < next_run:
        return None

    lock_document = acquire_distributed_task_lock('control_center_auto_refresh', lease_seconds=7200)
    if not lock_document:
        debug_print('Skipping Control Center auto-refresh because another worker holds the lease.')
        return None

    try:
        settings = get_settings()
        if not settings.get('control_center_auto_refresh_enabled', True):
            return None

        current_time = datetime.now(timezone.utc)
        next_run = parse_control_center_auto_refresh_datetime(settings.get('control_center_auto_refresh_next_run'))
        if not next_run:
            _seed_control_center_auto_refresh_next_run(settings, current_time)
            return None
        if current_time < next_run:
            return None

        print(f"Executing scheduled Control Center auto-refresh at {current_time.isoformat()}")
        return execute_control_center_refresh(manual_execution=False)
    finally:
        release_distributed_task_lock(lock_document)


def run_logging_timer_loop():
    """Run the logging timer monitor forever."""
    while True:
        try:
            check_logging_timers_once()
        except Exception as exc:
            print(f"Error in logging timer check: {exc}")
            log_event(f"Error in logging timer check: {exc}", level=logging.ERROR)

        time.sleep(60)


def run_approval_expiration_loop():
    """Run approval expiration checks forever."""
    while True:
        try:
            check_expired_approvals_once()
        except Exception as exc:
            print(f"Error in approval expiration check: {exc}")
            log_event(f"Error in approval expiration check: {exc}", level=logging.ERROR)

        time.sleep(21600)


def run_retention_policy_loop():
    """Run retention policy scheduling checks forever."""
    while True:
        try:
            check_retention_policy_once()
        except Exception as exc:
            print(f"Error in retention policy check: {exc}")
            log_event(f"Error in retention policy check: {exc}", level=logging.ERROR)

        time.sleep(300)


def run_control_center_auto_refresh_loop():
    """Run Control Center auto-refresh scheduling checks forever."""
    while True:
        try:
            check_control_center_auto_refresh_once()
        except Exception as exc:
            print(f"Error in Control Center auto-refresh check: {exc}")
            log_event(f"Error in Control Center auto-refresh check: {exc}", level=logging.ERROR)

        time.sleep(300)


def check_cosmos_throughput_autoscale_once():
    """Run the Cosmos DB throughput autoscale check when enabled."""
    settings = get_settings()
    if not settings.get('cosmos_throughput_autoscale_enabled', False):
        return None

    lock_document = acquire_distributed_task_lock('cosmos_throughput_autoscale', lease_seconds=240)
    if not lock_document:
        debug_print('Skipping Cosmos throughput autoscale because another worker holds the lease.')
        return None

    try:
        settings = get_settings()
        if not settings.get('cosmos_throughput_autoscale_enabled', False):
            return None

        refresh_id = f"background-{uuid.uuid4()}"
        log_event(
            '[CosmosThroughput] Background autoscale check starting.',
            extra={'refresh_id': refresh_id},
        )
        result = evaluate_and_apply_cosmos_throughput_scaling(settings, refresh_id=refresh_id)
        settings_update = result.get('settings_update') or {}
        if settings_update:
            update_settings(settings_update)
        decision = result.get('decision') or {}
        scale_result = result.get('scale_result') or {}
        log_event(
            '[CosmosThroughput] Background autoscale check completed.',
            extra={
                'refresh_id': refresh_id,
                'decision_reason': decision.get('reason'),
                'should_scale': decision.get('should_scale', False),
                'scale_scope': scale_result.get('scope', ''),
                'container_name': scale_result.get('container_name', ''),
            },
        )
        return result
    finally:
        release_distributed_task_lock(lock_document)


def get_cosmos_throughput_autoscale_sleep_seconds():
    """Return the next Cosmos throughput autoscale sleep interval."""
    try:
        return calculate_cosmos_throughput_autoscale_interval_seconds(get_settings())
    except Exception as exc:
        log_event(
            '[CosmosThroughput] Failed to calculate autoscale check interval; using default.',
            extra={
                'error': str(exc),
                'sleep_seconds': COSMOS_THROUGHPUT_AUTOSCALE_DEFAULT_INTERVAL_SECONDS,
            },
            level=logging.WARNING,
        )
        return COSMOS_THROUGHPUT_AUTOSCALE_DEFAULT_INTERVAL_SECONDS


def run_cosmos_throughput_autoscale_loop():
    """Run Cosmos DB throughput autoscale checks forever."""
    while True:
        try:
            check_cosmos_throughput_autoscale_once()
        except Exception as exc:
            print(f"Error in Cosmos throughput autoscale check: {exc}")
            log_event(f"[CosmosThroughput] Error in autoscale check: {exc}", level=logging.ERROR)

        sleep_seconds = get_cosmos_throughput_autoscale_sleep_seconds()
        log_event(
            '[CosmosThroughput] Background autoscale check sleeping.',
            extra={
                'sleep_seconds': sleep_seconds,
                'metrics_window_minutes': int(sleep_seconds / 60),
            },
        )
        time.sleep(sleep_seconds)


def check_due_workflows_once():
    """Execute scheduled personal and group workflows that are due."""
    settings = get_settings()
    results = []

    if settings.get('allow_user_workflows', False):
        due_workflows = get_due_personal_workflows(limit=20)
        for workflow in due_workflows:
            workflow_id = str(workflow.get('id') or '').strip()
            user_id = str(workflow.get('user_id') or '').strip()
            if not workflow_id or not user_id:
                continue

            lock_document = acquire_distributed_task_lock(f'workflow_run_{workflow_id}', lease_seconds=900)
            if not lock_document:
                continue

            refreshed_workflow = None
            try:
                refreshed_workflow = get_personal_workflow(user_id, workflow_id)
                if not refreshed_workflow:
                    continue
                trigger_type = str(refreshed_workflow.get('trigger_type') or '').strip().lower()
                if trigger_type not in {'interval', 'file_sync'} or not refreshed_workflow.get('is_enabled', False):
                    continue
                trigger_source = 'file_sync_monitor' if trigger_type == 'file_sync' else 'scheduled'

                next_run_at = refreshed_workflow.get('next_run_at')
                if next_run_at:
                    try:
                        if datetime.fromisoformat(next_run_at) > datetime.now(timezone.utc):
                            continue
                    except Exception:
                        pass

                started_at = datetime.now(timezone.utc).isoformat()
                update_personal_workflow_runtime_fields(
                    user_id,
                    workflow_id,
                    {
                        'status': 'running',
                        'last_run_started_at': started_at,
                        'last_run_trigger_source': trigger_source,
                        'last_run_error': '',
                    },
                )

                result = run_personal_workflow(refreshed_workflow, trigger_source=trigger_source)
                update_fields = dict(result.get('workflow_updates') or {})
                update_fields['status'] = 'idle'
                update_fields['next_run_at'] = compute_next_run_at(refreshed_workflow, from_time=datetime.now(timezone.utc))
                update_personal_workflow_runtime_fields(user_id, workflow_id, update_fields)
                results.append({'scope': 'personal', 'workflow_id': workflow_id, 'success': bool(result.get('success'))})
            except Exception as exc:
                log_event(
                    f"[WorkflowScheduler] Error executing workflow {workflow_id}: {exc}",
                    extra={
                        'workflow_id': workflow_id,
                        'user_id': user_id,
                    },
                    level=logging.ERROR,
                    exceptionTraceback=True,
                )
                if refreshed_workflow:
                    update_personal_workflow_runtime_fields(
                        user_id,
                        workflow_id,
                        {
                            'status': 'idle',
                            'last_run_status': 'failed',
                            'last_run_error': str(exc),
                            'last_run_at': datetime.now(timezone.utc).isoformat(),
                            'last_run_trigger_source': 'file_sync_monitor' if refreshed_workflow.get('trigger_type') == 'file_sync' else 'scheduled',
                            'next_run_at': compute_next_run_at(refreshed_workflow, from_time=datetime.now(timezone.utc)),
                        },
                    )
            finally:
                release_distributed_task_lock(lock_document)

    if settings.get('allow_group_workflows', False):
        due_group_workflows = get_due_group_workflows(limit=20)
        for workflow in due_group_workflows:
            workflow_id = str(workflow.get('id') or '').strip()
            group_id = str(workflow.get('group_id') or '').strip()
            if not workflow_id or not group_id:
                continue
            if not is_group_workflows_enabled_for_group(settings, group_id):
                continue

            lock_document = acquire_distributed_task_lock(f'group_workflow_run_{group_id}_{workflow_id}', lease_seconds=900)
            if not lock_document:
                continue

            refreshed_workflow = None
            try:
                refreshed_workflow = get_group_workflow(group_id, workflow_id)
                if not refreshed_workflow:
                    continue
                trigger_type = str(refreshed_workflow.get('trigger_type') or '').strip().lower()
                if trigger_type not in {'interval', 'file_sync'} or not refreshed_workflow.get('is_enabled', False):
                    continue
                trigger_source = 'file_sync_monitor' if trigger_type == 'file_sync' else 'scheduled'

                next_run_at = refreshed_workflow.get('next_run_at')
                if next_run_at:
                    try:
                        if datetime.fromisoformat(next_run_at) > datetime.now(timezone.utc):
                            continue
                    except Exception:
                        pass

                started_at = datetime.now(timezone.utc).isoformat()
                update_group_workflow_runtime_fields(
                    group_id,
                    workflow_id,
                    {
                        'status': 'running',
                        'last_run_started_at': started_at,
                        'last_run_trigger_source': trigger_source,
                        'last_run_error': '',
                    },
                )

                result = run_group_workflow(refreshed_workflow, trigger_source=trigger_source)
                update_fields = dict(result.get('workflow_updates') or {})
                update_fields['status'] = 'idle'
                update_fields['next_run_at'] = compute_next_run_at(refreshed_workflow, from_time=datetime.now(timezone.utc))
                update_group_workflow_runtime_fields(group_id, workflow_id, update_fields)
                results.append({'scope': 'group', 'group_id': group_id, 'workflow_id': workflow_id, 'success': bool(result.get('success'))})
            except Exception as exc:
                log_event(
                    f"[WorkflowScheduler] Error executing group workflow {workflow_id}: {exc}",
                    extra={
                        'workflow_id': workflow_id,
                        'group_id': group_id,
                    },
                    level=logging.ERROR,
                    exceptionTraceback=True,
                )
                if refreshed_workflow:
                    update_group_workflow_runtime_fields(
                        group_id,
                        workflow_id,
                        {
                            'status': 'idle',
                            'last_run_status': 'failed',
                            'last_run_error': str(exc),
                            'last_run_at': datetime.now(timezone.utc).isoformat(),
                            'last_run_trigger_source': 'file_sync_monitor' if refreshed_workflow.get('trigger_type') == 'file_sync' else 'scheduled',
                            'next_run_at': compute_next_run_at(refreshed_workflow, from_time=datetime.now(timezone.utc)),
                        },
                    )
            finally:
                release_distributed_task_lock(lock_document)

    return results


def run_workflow_scheduler_loop():
    """Run personal workflow scheduling checks forever."""
    while True:
        try:
            check_due_workflows_once()
        except Exception as exc:
            print(f"Error in workflow scheduler check: {exc}")
            log_event(f"[WorkflowScheduler] Error in workflow scheduler check: {exc}", level=logging.ERROR)

        time.sleep(5)


def run_file_sync_scheduler_loop():
    """Run File Sync scheduling checks forever."""
    while True:
        lock_document = None
        try:
            lock_document = acquire_distributed_task_lock('file_sync_scheduler_scan', lease_seconds=300)
            if lock_document:
                check_due_file_sync_sources_once()
        except Exception as exc:
            print(f"Error in File Sync scheduler check: {exc}")
            log_event(f"[FileSync] Error in scheduler check: {exc}", level=logging.ERROR)
        finally:
            if lock_document:
                release_distributed_task_lock(lock_document)

        time.sleep(60)


def run_tabular_generated_output_scheduler_loop():
    """Resume queued or stale tabular generated-output runs."""
    while True:
        lock_document = None
        try:
            lock_document = acquire_distributed_task_lock('tabular_generated_output_scheduler_scan', lease_seconds=120)
            if lock_document:
                check_due_tabular_generated_output_runs_once()
        except Exception as exc:
            print(f"Error in tabular generated-output scheduler check: {exc}")
            log_event(f"[Tabular Generated Output] Error in scheduler check: {exc}", level=logging.ERROR)
        finally:
            if lock_document:
                release_distributed_task_lock(lock_document)

        time.sleep(30)


def run_data_management_scheduler_loop():
    """Queue due Data Management backup jobs across scaled-out workers."""
    while True:
        lock_document = None
        try:
            lock_document = acquire_distributed_task_lock('data_management_scheduler_scan', lease_seconds=300)
            if lock_document:
                check_due_data_management_jobs_once()
        except Exception as exc:
            print(f"Error in Data Management scheduler check: {exc}")
            log_event(f"[DataManagement] Error in scheduler check: {exc}", level=logging.ERROR)
        finally:
            if lock_document:
                release_distributed_task_lock(lock_document)

        time.sleep(60)


def start_background_task_threads():
    """Start all background task loops for the current process."""
    task_specs = [
        ('Logging timer background task started.', run_logging_timer_loop),
        ('Approval expiration background task started.', run_approval_expiration_loop),
        ('Retention policy background task started.', run_retention_policy_loop),
        ('Control Center auto-refresh background task started.', run_control_center_auto_refresh_loop),
        ('Cosmos throughput autoscale background task started.', run_cosmos_throughput_autoscale_loop),
        ('Workflow scheduler background task started.', run_workflow_scheduler_loop),
        ('File Sync scheduler background task started.', run_file_sync_scheduler_loop),
        ('Tabular generated-output scheduler background task started.', run_tabular_generated_output_scheduler_loop),
        ('Data Management scheduler background task started.', run_data_management_scheduler_loop),
    ]

    started_threads = []
    for startup_message, task_target in task_specs:
        worker_thread = threading.Thread(target=task_target, daemon=True)
        worker_thread.start()
        print(startup_message)
        started_threads.append(worker_thread)

    return started_threads


def run_scheduler_forever():
    """Start all scheduler loops and keep the process alive."""
    start_background_task_threads()
    print('SimpleChat scheduler is running.')

    while True:
        time.sleep(3600)