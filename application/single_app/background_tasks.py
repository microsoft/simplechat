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
from functions_debug import debug_print
from functions_settings import get_settings, update_settings


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


def start_background_task_threads():
    """Start all background task loops for the current process."""
    task_specs = [
        ('Logging timer background task started.', run_logging_timer_loop),
        ('Approval expiration background task started.', run_approval_expiration_loop),
        ('Retention policy background task started.', run_retention_policy_loop),
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