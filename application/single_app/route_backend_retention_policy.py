# route_backend_retention_policy.py

from config import *
from functions_authentication import *
from functions_settings import *
from functions_retention_policy import execute_retention_policy, get_all_user_settings, get_all_groups, get_all_public_workspaces
from functions_activity_logging import log_retention_policy_force_push
from swagger_wrapper import swagger_route, get_auth_security
from functions_debug import debug_print


def register_route_backend_retention_policy(app):
    
    @app.route('/api/admin/retention-policy/settings', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def get_retention_policy_settings():
        """
        Get current retention policy settings and status.
        """
        try:
            settings = get_settings()
            
            return jsonify({
                'success': True,
                'settings': {
                    'enable_retention_policy_personal': settings.get('enable_retention_policy_personal', False),
                    'enable_retention_policy_group': settings.get('enable_retention_policy_group', False),
                    'enable_retention_policy_public': settings.get('enable_retention_policy_public', False),
                    'retention_policy_execution_hour': settings.get('retention_policy_execution_hour', 2),
                    'retention_policy_last_run': settings.get('retention_policy_last_run'),
                    'retention_policy_next_run': settings.get('retention_policy_next_run'),
                    'retention_conversation_min_days': settings.get('retention_conversation_min_days', 1),
                    'retention_conversation_max_days': settings.get('retention_conversation_max_days', 3650),
                    'retention_document_min_days': settings.get('retention_document_min_days', 1),
                    'retention_document_max_days': settings.get('retention_document_max_days', 3650)
                }
            })
            
        except Exception as e:
            debug_print(f"Error fetching retention policy settings: {e}")
            log_event(f"Fetching retention policy settings failed: {e}", level=logging.ERROR)
            return jsonify({
                'success': False,
                'error': 'Failed to fetch retention policy settings'
            }), 500
    
    
    @app.route('/api/admin/retention-policy/settings', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def update_retention_policy_settings():
        """
        Update retention policy admin settings.
        
        Body:
            enable_retention_policy_personal (bool): Enable for personal workspaces
            enable_retention_policy_group (bool): Enable for group workspaces
            enable_retention_policy_public (bool): Enable for public workspaces
            retention_policy_execution_hour (int): Hour of day to execute (0-23)
        """
        try:
            data = request.get_json()
            settings = get_settings()
            
            # Update settings if provided
            if 'enable_retention_policy_personal' in data:
                settings['enable_retention_policy_personal'] = bool(data['enable_retention_policy_personal'])
            
            if 'enable_retention_policy_group' in data:
                settings['enable_retention_policy_group'] = bool(data['enable_retention_policy_group'])
            
            if 'enable_retention_policy_public' in data:
                settings['enable_retention_policy_public'] = bool(data['enable_retention_policy_public'])
            
            if 'retention_policy_execution_hour' in data:
                hour = int(data['retention_policy_execution_hour'])
                if 0 <= hour <= 23:
                    settings['retention_policy_execution_hour'] = hour
                    
                    # Recalculate next run time
                    next_run = datetime.now(timezone.utc).replace(hour=hour, minute=0, second=0, microsecond=0)
                    if next_run <= datetime.now(timezone.utc):
                        next_run += timedelta(days=1)
                    settings['retention_policy_next_run'] = next_run.isoformat()
                else:
                    return jsonify({
                        'success': False,
                        'error': 'Execution hour must be between 0 and 23'
                    }), 400
            
            update_settings(settings)
            
            return jsonify({
                'success': True,
                'message': 'Retention policy settings updated successfully'
            })
            
        except Exception as e:
            debug_print(f"Error updating retention policy settings: {e}")
            log_event(f"Retention policy settings update failed: {e}", level=logging.ERROR)
            return jsonify({
                'success': False,
                'error': 'Failed to update retention policy settings'
            }), 500
    
    
    @app.route('/api/retention-policy/defaults/<workspace_type>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_retention_policy_defaults(workspace_type):
        """
        Get organization default retention policy settings for a specific workspace type.
        
        Args:
            workspace_type: One of 'personal', 'group', or 'public'
            
        Returns:
            JSON with default_conversation_days and default_document_days for the workspace type
        """
        try:
            # Validate workspace type
            if workspace_type not in ['personal', 'group', 'public']:
                return jsonify({
                    'success': False,
                    'error': f'Invalid workspace type: {workspace_type}'
                }), 400
            
            settings = get_settings()
            
            # Get the default values for the specified workspace type
            default_conversation = settings.get(f'default_retention_conversation_{workspace_type}', 'none')
            default_document = settings.get(f'default_retention_document_{workspace_type}', 'none')
            
            # Get human-readable labels for the values
            def get_retention_label(value):
                if value == 'none' or value is None:
                    return 'No automatic deletion'
                try:
                    days = int(value)
                    if days == 1:
                        return '1 day'
                    elif days == 21:
                        return '21 days (3 weeks)'
                    elif days == 90:
                        return '90 days (3 months)'
                    elif days == 180:
                        return '180 days (6 months)'
                    elif days == 365:
                        return '365 days (1 year)'
                    elif days == 730:
                        return '730 days (2 years)'
                    else:
                        return f'{days} days'
                except (ValueError, TypeError):
                    return 'No automatic deletion'
            
            return jsonify({
                'success': True,
                'workspace_type': workspace_type,
                'default_conversation_days': default_conversation,
                'default_document_days': default_document,
                'default_conversation_label': get_retention_label(default_conversation),
                'default_document_label': get_retention_label(default_document)
            })
            
        except Exception as e:
            debug_print(f"Error fetching retention policy defaults: {e}")
            log_event(f"Fetching retention policy defaults failed: {e}", level=logging.ERROR)
            return jsonify({
                'success': False,
                'error': 'Failed to fetch retention policy defaults'
            }), 500
    
    
    @app.route('/api/admin/retention-policy/execute', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def manual_execute_retention_policy():
        """
        Manually execute retention policy for selected workspace scopes.
        
        Body:
            scopes (list): List of workspace types to process: 'personal', 'group', 'public'
        """
        try:
            data = request.get_json()
            scopes = data.get('scopes', [])
            
            if not scopes:
                return jsonify({
                    'success': False,
                    'error': 'No workspace scopes provided'
                }), 400
            
            # Validate scopes
            valid_scopes = ['personal', 'group', 'public']
            invalid_scopes = [s for s in scopes if s not in valid_scopes]
            if invalid_scopes:
                return jsonify({
                    'success': False,
                    'error': f'Invalid workspace scopes: {", ".join(invalid_scopes)}'
                }), 400
            
            # Execute retention policy for selected scopes
            debug_print(f"Manual execution of retention policy for scopes: {scopes}")
            results = execute_retention_policy(workspace_scopes=scopes, manual_execution=True)
            
            return jsonify({
                'success': results.get('success', False),
                'message': 'Retention policy executed successfully' if results.get('success') else 'Retention policy execution failed',
                'results': results
            })
            
        except Exception as e:
            debug_print(f"Error executing retention policy manually: {e}")
            log_event(f"Manual retention policy execution failed: {e}", level=logging.ERROR)
            return jsonify({
                'success': False,
                'error': f'Failed to execute retention policy: {str(e)}'
            }), 500
    
    
    @app.route('/api/admin/retention-policy/force-push', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def force_push_retention_defaults():
        """
        Force push organization default retention policies to all users/groups/workspaces.
        This resets all custom retention policies to use the organization default ('default' value).
        
        Body:
            scopes (list): List of workspace types to push defaults to: 'personal', 'group', 'public'
        """
        try:
            data = request.get_json()
            scopes = data.get('scopes', [])
            
            if not scopes:
                return jsonify({
                    'success': False,
                    'error': 'No workspace scopes provided'
                }), 400
            
            # Validate scopes
            valid_scopes = ['personal', 'group', 'public']
            invalid_scopes = [s for s in scopes if s not in valid_scopes]
            if invalid_scopes:
                return jsonify({
                    'success': False,
                    'error': f'Invalid workspace scopes: {", ".join(invalid_scopes)}'
                }), 400
            
            details = {}
            total_updated = 0
            
            # Force push to personal workspaces (user settings)
            if 'personal' in scopes:
                debug_print("Force pushing retention defaults to personal workspaces...")
                all_users = get_all_user_settings()
                personal_count = 0
                
                for user in all_users:
                    user_id = user.get('id')
                    if not user_id:
                        continue
                    
                    try:
                        # Update user's retention policy to use 'default'
                        user_settings = user.get('settings', {})
                        user_settings['retention_policy'] = {
                            'conversation_retention_days': 'default',
                            'document_retention_days': 'default'
                        }
                        user['settings'] = user_settings
                        
                        cosmos_user_settings_container.upsert_item(user)
                        personal_count += 1
                    except Exception as e:
                        debug_print(f"Error updating user {user_id}: {e}")
                        log_event(f"Error updating user {user_id} during force push: {e}", level=logging.ERROR)
                        continue
                
                details['personal'] = personal_count
                total_updated += personal_count
                debug_print(f"Updated {personal_count} personal workspaces")
            
            # Force push to group workspaces
            if 'group' in scopes:
                debug_print("Force pushing retention defaults to group workspaces...")
                from functions_group import cosmos_groups_container
                all_groups = get_all_groups()
                group_count = 0
                
                for group in all_groups:
                    group_id = group.get('id')
                    if not group_id:
                        continue
                    
                    try:
                        # Update group's retention policy to use 'default'
                        group['retention_policy'] = {
                            'conversation_retention_days': 'default',
                            'document_retention_days': 'default'
                        }
                        
                        cosmos_groups_container.upsert_item(group)
                        group_count += 1
                    except Exception as e:
                        debug_print(f"Error updating group {group_id}: {e}")
                        log_event(f"Error updating group {group_id} during force push: {e}", level=logging.ERROR)
                        continue
                
                details['group'] = group_count
                total_updated += group_count
                debug_print(f"Updated {group_count} group workspaces")
            
            # Force push to public workspaces
            if 'public' in scopes:
                debug_print("Force pushing retention defaults to public workspaces...")
                from functions_public_workspaces import cosmos_public_workspaces_container
                all_workspaces = get_all_public_workspaces()
                public_count = 0
                
                for workspace in all_workspaces:
                    workspace_id = workspace.get('id')
                    if not workspace_id:
                        continue
                    
                    try:
                        # Update workspace's retention policy to use 'default'
                        workspace['retention_policy'] = {
                            'conversation_retention_days': 'default',
                            'document_retention_days': 'default'
                        }
                        
                        cosmos_public_workspaces_container.upsert_item(workspace)
                        public_count += 1
                    except Exception as e:
                        debug_print(f"Error updating public workspace {workspace_id}: {e}")
                        log_event(f"Error updating public workspace {workspace_id} during force push: {e}", level=logging.ERROR)
                        continue
                
                details['public'] = public_count
                total_updated += public_count
                debug_print(f"Updated {public_count} public workspaces")
            
            # Log to activity logs for audit trail
            admin_user_id = session.get('user', {}).get('oid', 'unknown')
            admin_email = session.get('user', {}).get('preferred_username', session.get('user', {}).get('email', 'unknown'))
            log_retention_policy_force_push(
                admin_user_id=admin_user_id,
                admin_email=admin_email,
                scopes=scopes,
                results=details,
                total_updated=total_updated
            )
            
            log_event("retention_policy_force_push", {
                "scopes": scopes,
                "updated_count": total_updated,
                "details": details
            })
            
            return jsonify({
                'success': True,
                'message': f'Defaults pushed to {total_updated} items',
                'updated_count': total_updated,
                'scopes': scopes,
                'details': details
            })
            
        except Exception as e:
            debug_print(f"Error force pushing retention defaults: {e}")
            log_event(f"Force push retention defaults failed: {e}", level=logging.ERROR)
            return jsonify({
                'success': False,
                'error': f'Failed to push retention defaults: {str(e)}'
            }), 500
    
    
    @app.route('/api/retention-policy/user', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def update_user_retention_settings():
        """
        Update retention policy settings for the current user's personal workspace.
        
        Body:
            conversation_retention_days (str|int): Number of days or 'none'
            document_retention_days (str|int): Number of days or 'none'
        """
        try:
            user_id = get_current_user_id()
            data = request.get_json()
            
            retention_settings = {}
            
            # Validate and parse conversation retention
            if 'conversation_retention_days' in data:
                conv_retention = data['conversation_retention_days']
                if conv_retention == 'none' or conv_retention is None:
                    retention_settings['conversation_retention_days'] = 'none'
                else:
                    try:
                        days = int(conv_retention)
                        settings = get_settings()
                        min_days = settings.get('retention_conversation_min_days', 1)
                        max_days = settings.get('retention_conversation_max_days', 3650)
                        
                        if days < min_days or days > max_days:
                            return jsonify({
                                'success': False,
                                'error': f'Conversation retention must be between {min_days} and {max_days} days'
                            }), 400
                        
                        retention_settings['conversation_retention_days'] = days
                    except ValueError:
                        return jsonify({
                            'success': False,
                            'error': 'Invalid conversation retention value'
                        }), 400
            
            # Validate and parse document retention
            if 'document_retention_days' in data:
                doc_retention = data['document_retention_days']
                if doc_retention == 'none' or doc_retention is None:
                    retention_settings['document_retention_days'] = 'none'
                else:
                    try:
                        days = int(doc_retention)
                        settings = get_settings()
                        min_days = settings.get('retention_document_min_days', 1)
                        max_days = settings.get('retention_document_max_days', 3650)
                        
                        if days < min_days or days > max_days:
                            return jsonify({
                                'success': False,
                                'error': f'Document retention must be between {min_days} and {max_days} days'
                            }), 400
                        
                        retention_settings['document_retention_days'] = days
                    except ValueError:
                        return jsonify({
                            'success': False,
                            'error': 'Invalid document retention value'
                        }), 400
            
            if not retention_settings:
                return jsonify({
                    'success': False,
                    'error': 'No retention settings provided'
                }), 400
            
            # Update user settings
            update_user_settings(user_id, {'retention_policy': retention_settings})
            
            return jsonify({
                'success': True,
                'message': 'Retention settings updated successfully'
            })
            
        except Exception as e:
            debug_print(f"Error updating user retention settings: {e}")
            log_event(f"User retention settings update failed: {e}", level=logging.ERROR)
            return jsonify({
                'success': False,
                'error': 'Failed to update retention settings'
            }), 500
    
    
    @app.route('/api/retention-policy/group/<group_id>', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def update_group_retention_settings(group_id):
        """
        Update retention policy settings for a group workspace.
        User must be owner or admin of the group.
        
        Body:
            conversation_retention_days (str|int): Number of days or 'none'
            document_retention_days (str|int): Number of days or 'none'
        """
        try:
            user_id = get_current_user_id()
            data = request.get_json()
            
            # Get group and verify permissions
            from functions_group import find_group_by_id, get_user_role_in_group
            group = find_group_by_id(group_id)
            
            if not group:
                return jsonify({
                    'success': False,
                    'error': 'Group not found'
                }), 404
            
            user_role = get_user_role_in_group(group, user_id)
            if user_role not in ['Owner', 'Admin']:
                return jsonify({
                    'success': False,
                    'error': 'Insufficient permissions. Must be group owner or admin.'
                }), 403
            
            retention_settings = {}
            
            # Validate and parse conversation retention
            if 'conversation_retention_days' in data:
                conv_retention = data['conversation_retention_days']
                if conv_retention == 'none' or conv_retention is None:
                    retention_settings['conversation_retention_days'] = 'none'
                else:
                    try:
                        days = int(conv_retention)
                        settings = get_settings()
                        min_days = settings.get('retention_conversation_min_days', 1)
                        max_days = settings.get('retention_conversation_max_days', 3650)
                        
                        if days < min_days or days > max_days:
                            return jsonify({
                                'success': False,
                                'error': f'Conversation retention must be between {min_days} and {max_days} days'
                            }), 400
                        
                        retention_settings['conversation_retention_days'] = days
                    except ValueError:
                        return jsonify({
                            'success': False,
                            'error': 'Invalid conversation retention value'
                        }), 400
            
            # Validate and parse document retention
            if 'document_retention_days' in data:
                doc_retention = data['document_retention_days']
                if doc_retention == 'none' or doc_retention is None:
                    retention_settings['document_retention_days'] = 'none'
                else:
                    try:
                        days = int(doc_retention)
                        settings = get_settings()
                        min_days = settings.get('retention_document_min_days', 1)
                        max_days = settings.get('retention_document_max_days', 3650)
                        
                        if days < min_days or days > max_days:
                            return jsonify({
                                'success': False,
                                'error': f'Document retention must be between {min_days} and {max_days} days'
                            }), 400
                        
                        retention_settings['document_retention_days'] = days
                    except ValueError:
                        return jsonify({
                            'success': False,
                            'error': 'Invalid document retention value'
                        }), 400
            
            if not retention_settings:
                return jsonify({
                    'success': False,
                    'error': 'No retention settings provided'
                }), 400
            
            # Update group document
            group['retention_policy'] = retention_settings
            cosmos_groups_container.upsert_item(group)
            
            return jsonify({
                'success': True,
                'message': 'Group retention settings updated successfully'
            })
            
        except Exception as e:
            debug_print(f"Error updating group retention settings: {e}")
            log_event(f"Group retention settings update failed: {e}", level=logging.ERROR)
            return jsonify({
                'success': False,
                'error': 'Failed to update retention settings'
            }), 500
    
    
    @app.route('/api/retention-policy/public/<public_workspace_id>', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def update_public_workspace_retention_settings(public_workspace_id):
        """
        Update retention policy settings for a public workspace.
        User must be owner or admin of the workspace.
        
        Body:
            conversation_retention_days (str|int): Number of days or 'none'
            document_retention_days (str|int): Number of days or 'none'
        """
        try:
            user_id = get_current_user_id()
            data = request.get_json()
            
            # Get workspace and verify permissions
            from functions_public_workspaces import find_public_workspace_by_id, get_user_role_in_public_workspace
            workspace = find_public_workspace_by_id(public_workspace_id)
            
            if not workspace:
                return jsonify({
                    'success': False,
                    'error': 'Public workspace not found'
                }), 404
            
            user_role = get_user_role_in_public_workspace(workspace, user_id)
            if user_role not in ['Owner', 'Admin']:
                return jsonify({
                    'success': False,
                    'error': 'Insufficient permissions. Must be workspace owner or admin.'
                }), 403
            
            retention_settings = {}
            
            # Validate and parse conversation retention
            if 'conversation_retention_days' in data:
                conv_retention = data['conversation_retention_days']
                if conv_retention == 'none' or conv_retention is None:
                    retention_settings['conversation_retention_days'] = 'none'
                else:
                    try:
                        days = int(conv_retention)
                        settings = get_settings()
                        min_days = settings.get('retention_conversation_min_days', 1)
                        max_days = settings.get('retention_conversation_max_days', 3650)
                        
                        if days < min_days or days > max_days:
                            return jsonify({
                                'success': False,
                                'error': f'Conversation retention must be between {min_days} and {max_days} days'
                            }), 400
                        
                        retention_settings['conversation_retention_days'] = days
                    except ValueError:
                        return jsonify({
                            'success': False,
                            'error': 'Invalid conversation retention value'
                        }), 400
            
            # Validate and parse document retention
            if 'document_retention_days' in data:
                doc_retention = data['document_retention_days']
                if doc_retention == 'none' or doc_retention is None:
                    retention_settings['document_retention_days'] = 'none'
                else:
                    try:
                        days = int(doc_retention)
                        settings = get_settings()
                        min_days = settings.get('retention_document_min_days', 1)
                        max_days = settings.get('retention_document_max_days', 3650)
                        
                        if days < min_days or days > max_days:
                            return jsonify({
                                'success': False,
                                'error': f'Document retention must be between {min_days} and {max_days} days'
                            }), 400
                        
                        retention_settings['document_retention_days'] = days
                    except ValueError:
                        return jsonify({
                            'success': False,
                            'error': 'Invalid document retention value'
                        }), 400
            
            if not retention_settings:
                return jsonify({
                    'success': False,
                    'error': 'No retention settings provided'
                }), 400
            
            # Update workspace document
            workspace['retention_policy'] = retention_settings
            cosmos_public_workspaces_container.upsert_item(workspace)
            
            return jsonify({
                'success': True,
                'message': 'Public workspace retention settings updated successfully'
            })
            
        except Exception as e:
            debug_print(f"Error updating public workspace retention settings: {e}")
            log_event(f"Public workspace retention settings update failed: {e}", level=logging.ERROR)
            return jsonify({
                'success': False,
                'error': 'Failed to update retention settings'
            }), 500
