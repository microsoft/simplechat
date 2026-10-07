# functions_control_center.py
"""
Functions for Control Center operations including scheduled auto-refresh.
Version: 0.250.102
"""

from datetime import datetime, timezone

from config import cosmos_user_settings_container, cosmos_groups_container
from functions_debug import debug_print
from functions_settings import get_settings, update_settings
from functions_appinsights import log_event
# The schedule rules are pure and live in functions_control_center_schedule, so the
# admin settings normalizer can share them without importing config.
from functions_control_center_schedule import calculate_next_control_center_auto_refresh_run


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
                settings_updates = {
                    'control_center_last_refresh': current_time.isoformat(),
                }

                # Calculate next scheduled auto-refresh time if enabled
                if settings.get('control_center_auto_refresh_enabled', True):
                    next_run = calculate_next_control_center_auto_refresh_run(settings, current_time=current_time)
                    settings_updates['control_center_auto_refresh_next_run'] = next_run.isoformat()
                else:
                    settings_updates['control_center_auto_refresh_next_run'] = None
                
                update_success = update_settings(settings_updates)
                
                if update_success:
                    debug_print("✅ [AUTO-REFRESH] Admin settings updated with refresh timestamp")
                else:
                    results['success'] = False
                    results['error'] = 'Unable to save Control Center refresh settings.'
                    debug_print("⚠️ [AUTO-REFRESH] Failed to update admin settings")
            else:
                results['success'] = False
                results['error'] = 'Unable to load Control Center refresh settings.'

        except Exception as settings_error:
            results['success'] = False
            results['error'] = 'Unable to save Control Center refresh settings.'
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
