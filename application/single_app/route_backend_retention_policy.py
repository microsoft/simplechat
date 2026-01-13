# route_backend_retention_policy.py

from config import *
from functions_authentication import *
from functions_settings import *
from functions_retention_policy import execute_retention_policy
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
