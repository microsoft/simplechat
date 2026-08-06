# functions_logging.py

from datetime import datetime, timedelta, timezone
import logging
import uuid

from config import cosmos_file_processing_container
from functions_appinsights import log_event
import functions_settings


FILE_PROCESSING_LOG_AGE_UNITS = {
    'days': 1,
    'weeks': 7,
    'months': 30,
}


class FileProcessingLogDeletionError(RuntimeError):
    """Report a cleanup failure without losing the number of completed deletes."""

    def __init__(self, deleted_count):
        super().__init__('File processing log cleanup did not complete.')
        self.deleted_count = deleted_count


def calculate_file_processing_log_cutoff(age, unit, now=None):
    """Return the UTC cutoff for a validated age and unit."""
    if isinstance(age, bool) or not isinstance(age, int) or age < 1:
        raise ValueError('Age must be a positive integer.')

    normalized_unit = str(unit or '').strip().lower()
    if normalized_unit not in FILE_PROCESSING_LOG_AGE_UNITS:
        raise ValueError('Unit must be days, weeks, or months.')

    reference_time = now or datetime.now(timezone.utc)
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)
    else:
        reference_time = reference_time.astimezone(timezone.utc)

    days = age * FILE_PROCESSING_LOG_AGE_UNITS[normalized_unit]
    try:
        return reference_time - timedelta(days=days)
    except OverflowError as exc:
        raise ValueError('Age is too large.') from exc


def delete_file_processing_logs(
    *,
    delete_all=False,
    age=None,
    unit=None,
    now=None,
    container=None,
):
    """Delete all file processing logs or only logs older than a cutoff."""
    if not isinstance(delete_all, bool):
        raise ValueError('delete_all must be a boolean.')
    if delete_all and (age is not None or unit is not None):
        raise ValueError('Delete-all requests cannot include an age or unit.')

    target_container = (
        container
        if container is not None
        else cosmos_file_processing_container
    )
    cutoff = None
    query = (
        'SELECT c.id, c.document_id FROM c '
        'WHERE IS_DEFINED(c.id) AND IS_DEFINED(c.document_id)'
    )
    parameters = None

    if not delete_all:
        cutoff = calculate_file_processing_log_cutoff(age, unit, now=now)
        cutoff_value = cutoff.replace(tzinfo=None).isoformat()
        query += ' AND IS_DEFINED(c.timestamp) AND c.timestamp < @cutoff'
        parameters = [{'name': '@cutoff', 'value': cutoff_value}]

    deleted_count = 0
    try:
        items = list(
            target_container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True,
            )
        )
        for item in items:
            item_id = item.get('id')
            document_id = item.get('document_id')
            if item_id is None or document_id is None:
                raise ValueError('A selected log item is missing its id or document_id.')
            target_container.delete_item(item=item_id, partition_key=document_id)
            deleted_count += 1
    except Exception as exc:
        log_event(
            '[FILE_PROCESSING_LOGS] Cleanup failed.',
            extra={
                'delete_all': delete_all,
                'deleted_count': deleted_count,
                'cutoff': cutoff.isoformat() if cutoff else None,
                'error_type': type(exc).__name__,
            },
            level=logging.ERROR,
        )
        raise FileProcessingLogDeletionError(deleted_count) from exc

    log_event(
        '[FILE_PROCESSING_LOGS] Cleanup completed.',
        extra={
            'delete_all': delete_all,
            'deleted_count': deleted_count,
            'cutoff': cutoff.isoformat() if cutoff else None,
        },
        level=logging.INFO,
    )
    return {
        'deleted_count': deleted_count,
        'delete_all': delete_all,
        'cutoff': cutoff.isoformat() if cutoff else None,
    }


def add_file_task_to_file_processing_log(document_id, user_id, content):
    settings = functions_settings.get_settings()
    enable_file_processing_log = settings.get('enable_file_processing_logs', True)

    if enable_file_processing_log:
        try:
            id_value = str(uuid.uuid4())
            log_item = {
                "id": id_value,
                "document_id": document_id,
                "user_id": user_id,
                "log": content,
                "timestamp": datetime.utcnow().isoformat()
            }
            cosmos_file_processing_container.create_item(log_item)
        except Exception as e:
            raise e
        
