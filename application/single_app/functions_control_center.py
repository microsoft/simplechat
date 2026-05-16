# functions_control_center.py
"""
Functions for Control Center operations including scheduled auto-refresh.
Version: 0.241.029
"""

from datetime import datetime, timezone, timedelta
from config import cosmos_user_settings_container, cosmos_groups_container
from functions_debug import debug_print
from functions_settings import get_settings, update_settings
from functions_appinsights import log_event


CONTROL_CENTER_DEFAULT_AUTO_REFRESH_HOUR = 6
CONTROL_CENTER_DEFAULT_AUTO_REFRESH_MINUTE = 0
CONTROL_CENTER_DEFAULT_AUTO_REFRESH_TIME = '06:00'


def normalize_control_center_auto_refresh_time(schedule_time=None, schedule_hour=None, schedule_minute=None):
    """Return a normalized UTC daily refresh schedule."""
    normalized_hour = CONTROL_CENTER_DEFAULT_AUTO_REFRESH_HOUR
    normalized_minute = CONTROL_CENTER_DEFAULT_AUTO_REFRESH_MINUTE

    if isinstance(schedule_time, str) and schedule_time.strip():
        time_parts = schedule_time.strip().split(':')
        if len(time_parts) >= 2:
            try:
                parsed_hour = int(time_parts[0])
                parsed_minute = int(time_parts[1])
                if 0 <= parsed_hour <= 23 and 0 <= parsed_minute <= 59:
                    normalized_hour = parsed_hour
                    normalized_minute = parsed_minute
            except (TypeError, ValueError):
                pass
    else:
        try:
            parsed_hour = int(schedule_hour)
            if 0 <= parsed_hour <= 23:
                normalized_hour = parsed_hour
        except (TypeError, ValueError):
            pass

        try:
            parsed_minute = int(schedule_minute)
            if 0 <= parsed_minute <= 59:
                normalized_minute = parsed_minute
        except (TypeError, ValueError):
            pass

    return {
        'hour': normalized_hour,
        'minute': normalized_minute,
        'time': f"{normalized_hour:02d}:{normalized_minute:02d}",
    }


def get_control_center_auto_refresh_schedule(settings=None):
    """Normalize schedule fields from app settings."""
    settings = settings or {}
    return normalize_control_center_auto_refresh_time(
        settings.get('control_center_auto_refresh_time'),
        settings.get('control_center_auto_refresh_hour'),
        settings.get('control_center_auto_refresh_minute'),
    )


def calculate_next_control_center_auto_refresh_run(settings=None, current_time=None):
    """Calculate the next UTC daily Control Center auto-refresh run time."""
    current_time = current_time or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    else:
        current_time = current_time.astimezone(timezone.utc)

    schedule = get_control_center_auto_refresh_schedule(settings)
    next_run = current_time.replace(
        hour=schedule['hour'],
        minute=schedule['minute'],
        second=0,
        microsecond=0,
    )
    if next_run <= current_time:
        next_run += timedelta(days=1)

    return next_run


def parse_control_center_auto_refresh_datetime(timestamp_value):
    """Parse an ISO timestamp as a timezone-aware UTC datetime."""
    if not timestamp_value:
        return None

    try:
        if isinstance(timestamp_value, datetime):
            parsed_datetime = timestamp_value
        else:
            normalized_value = timestamp_value.replace('Z', '+00:00') if isinstance(timestamp_value, str) else timestamp_value
            parsed_datetime = datetime.fromisoformat(normalized_value)
        if parsed_datetime.tzinfo is None:
            parsed_datetime = parsed_datetime.replace(tzinfo=timezone.utc)
        return parsed_datetime.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def execute_control_center_refresh(manual_execution=False):
    """
    Execute Control Center data refresh operation.
    Refreshes user and group metrics data.
    
    Args:
        manual_execution: True if triggered manually, False if scheduled
        
    Returns:
        dict: Results containing success status and refresh counts
    """
    results = {
        'success': True,
        'refreshed_users': 0,
        'failed_users': 0,
        'refreshed_groups': 0,
        'failed_groups': 0,
        'error': None,
        'manual_execution': manual_execution
    }
    
    try:
        debug_print(f"🔄 [AUTO-REFRESH] Starting Control Center {'manual' if manual_execution else 'scheduled'} refresh...")
        
        # Import enhance functions from route module
        from route_backend_control_center import enhance_user_with_activity, enhance_group_with_activity
        
        # Get all users to refresh their metrics
        debug_print("🔄 [AUTO-REFRESH] Querying all users...")
        users_query = "SELECT c.id, c.email, c.display_name, c.lastUpdated, c.settings FROM c"
        all_users = list(cosmos_user_settings_container.query_items(
            query=users_query,
            enable_cross_partition_query=True
        ))
        debug_print(f"🔄 [AUTO-REFRESH] Found {len(all_users)} users to process")
        
        # Refresh metrics for each user
        for user in all_users:
            try:
                user_id = user.get('id')
                debug_print(f"🔄 [AUTO-REFRESH] Processing user {user_id}")
                
                # Force refresh of metrics for this user
                enhanced_user = enhance_user_with_activity(user, force_refresh=True)
                results['refreshed_users'] += 1
                
            except Exception as user_error:
                results['failed_users'] += 1
                debug_print(f"❌ [AUTO-REFRESH] Failed to refresh user {user.get('id')}: {user_error}")
        
        debug_print(f"🔄 [AUTO-REFRESH] User refresh completed. Refreshed: {results['refreshed_users']}, Failed: {results['failed_users']}")
        
        # Refresh metrics for all groups
        debug_print("🔄 [AUTO-REFRESH] Starting group refresh...")
        
        try:
            groups_query = "SELECT * FROM c"
            all_groups = list(cosmos_groups_container.query_items(
                query=groups_query,
                enable_cross_partition_query=True
            ))
            debug_print(f"🔄 [AUTO-REFRESH] Found {len(all_groups)} groups to process")
            
            # Refresh metrics for each group
            for group in all_groups:
                try:
                    group_id = group.get('id')
                    debug_print(f"🔄 [AUTO-REFRESH] Processing group {group_id}")
                    
                    # Force refresh of metrics for this group
                    enhanced_group = enhance_group_with_activity(group, force_refresh=True)
                    results['refreshed_groups'] += 1
                    
                except Exception as group_error:
                    results['failed_groups'] += 1
                    debug_print(f"❌ [AUTO-REFRESH] Failed to refresh group {group.get('id')}: {group_error}")
                    
        except Exception as groups_error:
            debug_print(f"❌ [AUTO-REFRESH] Error querying groups: {groups_error}")
        
        debug_print(f"🔄 [AUTO-REFRESH] Group refresh completed. Refreshed: {results['refreshed_groups']}, Failed: {results['failed_groups']}")
        
        # Update admin settings with refresh timestamp and calculate next run time
        try:
            settings = get_settings()
            if settings:
                current_time = datetime.now(timezone.utc)
                settings['control_center_last_refresh'] = current_time.isoformat()
                
                schedule = get_control_center_auto_refresh_schedule(settings)
                settings['control_center_auto_refresh_time'] = schedule['time']
                settings['control_center_auto_refresh_hour'] = schedule['hour']
                settings['control_center_auto_refresh_minute'] = schedule['minute']

                # Calculate next scheduled auto-refresh time if enabled
                if settings.get('control_center_auto_refresh_enabled', True):
                    next_run = calculate_next_control_center_auto_refresh_run(settings, current_time=current_time)
                    settings['control_center_auto_refresh_next_run'] = next_run.isoformat()
                else:
                    settings['control_center_auto_refresh_next_run'] = None
                
                update_success = update_settings(settings)
                
                if update_success:
                    debug_print("✅ [AUTO-REFRESH] Admin settings updated with refresh timestamp")
                else:
                    debug_print("⚠️ [AUTO-REFRESH] Failed to update admin settings")
                    
        except Exception as settings_error:
            debug_print(f"❌ [AUTO-REFRESH] Admin settings update failed: {settings_error}")
        
        # Log the activity
        log_event("control_center_refresh", {
            "manual_execution": manual_execution,
            "refreshed_users": results['refreshed_users'],
            "failed_users": results['failed_users'],
            "refreshed_groups": results['refreshed_groups'],
            "failed_groups": results['failed_groups']
        })
        
        debug_print(f"🎉 [AUTO-REFRESH] Refresh completed! Users: {results['refreshed_users']} refreshed, {results['failed_users']} failed. "
                   f"Groups: {results['refreshed_groups']} refreshed, {results['failed_groups']} failed")
        
        return results
        
    except Exception as e:
        debug_print(f"💥 [AUTO-REFRESH] Error executing Control Center refresh: {e}")
        results['success'] = False
        results['error'] = str(e)
        return results
