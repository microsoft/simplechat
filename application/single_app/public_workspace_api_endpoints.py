# public_workspace_api_endpoints.py
# Backend API endpoints for public workspace management
# These should be added to route_backend_control_center.py after the bulk-action endpoint

"""
Add these endpoints after line 3566 in route_backend_control_center.py
(after the api_bulk_public_workspace_action endpoint)
"""

@app.route('/api/admin/control-center/public-workspaces/<workspace_id>', methods=['GET'])
@swagger_route(security=get_auth_security())
@login_required
@admin_required
@control_center_admin_required
def api_get_public_workspace_details(workspace_id):
    """
    Get detailed information about a specific public workspace.
    """
    try:
        # Get the workspace
        workspace = cosmos_public_workspaces_container.read_item(
            item=workspace_id,
            partition_key=workspace_id
        )
        
        # Enhance with activity information
        enhanced_workspace = enhance_public_workspace_with_activity(workspace)
        
        return jsonify(enhanced_workspace), 200
        
    except Exception as e:
        debug_print(f"Error getting public workspace details: {e}")
        return jsonify({'error': 'Failed to retrieve workspace details'}), 500


@app.route('/api/admin/control-center/public-workspaces/<workspace_id>/members', methods=['GET'])
@swagger_route(security=get_auth_security())
@login_required
@admin_required
@control_center_admin_required
def api_get_public_workspace_members(workspace_id):
    """
    Get all members of a specific public workspace with their roles.
    Returns admins, document managers, and owner information.
    """
    try:
        # Get the workspace
        workspace = cosmos_public_workspaces_container.read_item(
            item=workspace_id,
            partition_key=workspace_id
        )
        
        # Collect all member IDs
        owner_id = workspace.get('owner')
        admin_ids = workspace.get('admins', [])
        doc_manager_ids = workspace.get('documentManagers', [])
        
        # Create members list with roles
        members = []
        
        # Add owner
        if owner_id:
            try:
                user = cosmos_user_settings_container.read_item(
                    item=owner_id,
                    partition_key=owner_id
                )
                members.append({
                    'userId': owner_id,
                    'email': user.get('email', ''),
                    'displayName': user.get('display_name', user.get('email', '')),
                    'role': 'owner'
                })
            except:
                pass
        
        # Add admins
        for admin_id in admin_ids:
            try:
                user = cosmos_user_settings_container.read_item(
                    item=admin_id,
                    partition_key=admin_id
                )
                members.append({
                    'userId': admin_id,
                    'email': user.get('email', ''),
                    'displayName': user.get('display_name', user.get('email', '')),
                    'role': 'admin'
                })
            except:
                pass
        
        # Add document managers
        for dm_id in doc_manager_ids:
            try:
                user = cosmos_user_settings_container.read_item(
                    item=dm_id,
                    partition_key=dm_id
                )
                members.append({
                    'userId': dm_id,
                    'email': user.get('email', ''),
                    'displayName': user.get('display_name', user.get('email', '')),
                    'role': 'documentManager'
                })
            except:
                pass
        
        return jsonify({
            'success': True,
            'members': members,
            'workspace_name': workspace.get('name', 'Unknown')
        }), 200
        
    except Exception as e:
        debug_print(f"Error getting workspace members: {e}")
        return jsonify({'error': 'Failed to retrieve workspace members'}), 500


@app.route('/api/admin/control-center/public-workspaces/<workspace_id>/activity', methods=['GET'])
@swagger_route(security=get_auth_security())
@login_required
@admin_required
@control_center_admin_required
def api_get_public_workspace_activity(workspace_id):
    """
    Get activity timeline for a specific public workspace.
    Query parameters: days (7, 30, 90, or 'all')
    """
    try:
        days = request.args.get('days', '30')
        export = request.args.get('export', 'false').lower() == 'true'
        
        # Calculate date range
        if days == 'all':
            # Query all activity
            start_date = datetime(2000, 1, 1)
        else:
            days_int = int(days)
            start_date = datetime.utcnow() - timedelta(days=days_int)
        
        # Query activity logs
        query = """
            SELECT * FROM c 
            WHERE c.workspace_context.public_workspace_id = @workspace_id 
            AND c.timestamp >= @start_date
            ORDER BY c.timestamp DESC
        """
        parameters = [
            {"name": "@workspace_id", "value": workspace_id},
            {"name": "@start_date", "value": start_date.isoformat()}
        ]
        
        activities = list(cosmos_activity_logs_container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        ))
        
        # Format activities for display
        formatted_activities = []
        for activity in activities:
            formatted_activities.append({
                'timestamp': activity.get('timestamp'),
                'action': activity.get('activity_type', 'Unknown'),
                'user_id': activity.get('user_id'),
                'details': f"{activity.get('activity_type', 'Activity')} in workspace"
            })
        
        if export:
            # Return CSV for export
            import io
            import csv
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(['Timestamp', 'Action', 'User ID', 'Details'])
            for activity in formatted_activities:
                writer.writerow([
                    activity['timestamp'],
                    activity['action'],
                    activity['user_id'],
                    activity['details']
                ])
            
            csv_content = output.getvalue()
            output.close()
            
            from flask import make_response
            response = make_response(csv_content)
            response.headers['Content-Type'] = 'text/csv'
            response.headers['Content-Disposition'] = f'attachment; filename="workspace_{workspace_id}_activity.csv"'
            return response
        
        return jsonify({
            'success': True,
            'activities': formatted_activities
        }), 200
        
    except Exception as e:
        debug_print(f"Error getting workspace activity: {e}")
        return jsonify({'error': 'Failed to retrieve workspace activity'}), 500


@app.route('/api/admin/control-center/public-workspaces/<workspace_id>/ownership', methods=['PUT'])
@swagger_route(security=get_auth_security())
@login_required
@admin_required
@control_center_admin_required
def api_update_public_workspace_ownership(workspace_id):
    """
    Transfer ownership of a public workspace.
    Body: { "action": "admin" | "transfer", "reason": "...", "new_owner_id": "..." }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        action = data.get('action')
        reason = data.get('reason')
        new_owner_id = data.get('new_owner_id')
        
        if not action or not reason:
            return jsonify({'error': 'Action and reason are required'}), 400
        
        if action not in ['admin', 'transfer']:
            return jsonify({'error': 'Invalid action. Must be "admin" or "transfer"'}), 400
        
        if action == 'transfer' and not new_owner_id:
            return jsonify({'error': 'new_owner_id is required for transfer action'}), 400
        
        # Get admin user info
        admin_user = session.get('user', {})
        admin_user_id = admin_user.get('oid', 'unknown')
        admin_email = admin_user.get('preferred_username', 'unknown')
        
        # Get the workspace
        workspace = cosmos_public_workspaces_container.read_item(
            item=workspace_id,
            partition_key=workspace_id
        )
        
        old_owner_id = workspace.get('owner')
        
        if action == 'admin':
            # Admin takes ownership
            new_owner = admin_user_id
            new_owner_email = admin_email
        else:
            # Transfer to another user
            new_owner = new_owner_id
            # Get new owner email
            try:
                new_owner_user = cosmos_user_settings_container.read_item(
                    item=new_owner_id,
                    partition_key=new_owner_id
                )
                new_owner_email = new_owner_user.get('email', 'unknown')
            except:
                new_owner_email = 'unknown'
        
        # Update ownership
        workspace['owner'] = new_owner
        workspace['modifiedDate'] = datetime.utcnow().isoformat()
        
        # Remove new owner from admins/documentManagers if present
        if new_owner in workspace.get('admins', []):
            workspace['admins'].remove(new_owner)
        if new_owner in workspace.get('documentManagers', []):
            workspace['documentManagers'].remove(new_owner)
        
        # Add old owner to members if not already there
        if old_owner_id and old_owner_id != new_owner:
            if old_owner_id not in workspace.get('admins', []) and \
               old_owner_id not in workspace.get('documentManagers', []):
                # Demote to regular member (just in members list, handled by frontend)
                pass
        
        cosmos_public_workspaces_container.upsert_item(workspace)
        
        # Log the ownership change
        log_event("[ControlCenter] Public Workspace Ownership Changed", {
            "admin_user": admin_email,
            "admin_user_id": admin_user_id,
            "workspace_id": workspace_id,
            "workspace_name": workspace.get('name'),
            "old_owner": old_owner_id,
            "new_owner": new_owner,
            "action": action,
            "reason": reason
        })
        
        return jsonify({
            'message': 'Ownership transferred successfully',
            'old_owner': old_owner_id,
            'new_owner': new_owner
        }), 200
        
    except Exception as e:
        debug_print(f"Error updating workspace ownership: {e}")
        return jsonify({'error': 'Failed to update workspace ownership'}), 500


@app.route('/api/admin/control-center/public-workspaces/<workspace_id>/documents', methods=['DELETE'])
@swagger_route(security=get_auth_security())
@login_required
@admin_required
@control_center_admin_required
def api_delete_public_workspace_documents(workspace_id):
    """
    Delete all documents in a public workspace.
    """
    try:
        # Get admin user info
        admin_user = session.get('user', {})
        admin_user_id = admin_user.get('oid', 'unknown')
        admin_email = admin_user.get('preferred_username', 'unknown')
        
        # Query all documents for this workspace
        doc_query = "SELECT c.id FROM c WHERE c.public_workspace_id = @workspace_id"
        doc_params = [{"name": "@workspace_id", "value": workspace_id}]
        
        docs_to_delete = list(cosmos_public_documents_container.query_items(
            query=doc_query,
            parameters=doc_params,
            enable_cross_partition_query=True
        ))
        
        deleted_count = 0
        for doc in docs_to_delete:
            try:
                delete_document_chunks(doc['id'])
                delete_document(doc['id'])
                deleted_count += 1
            except Exception as del_e:
                debug_print(f"Error deleting document {doc['id']}: {del_e}")
        
        # Log the action
        log_event("[ControlCenter] Public Workspace Documents Deleted", {
            "admin_user": admin_email,
            "admin_user_id": admin_user_id,
            "workspace_id": workspace_id,
            "documents_deleted": deleted_count
        })
        
        return jsonify({
            'message': 'All documents deleted successfully',
            'deleted_count': deleted_count
        }), 200
        
    except Exception as e:
        debug_print(f"Error deleting workspace documents: {e}")
        return jsonify({'error': 'Failed to delete workspace documents'}), 500


@app.route('/api/admin/control-center/public-workspaces/<workspace_id>', methods=['DELETE'])
@swagger_route(security=get_auth_security())
@login_required
@admin_required
@control_center_admin_required
def api_delete_public_workspace(workspace_id):
    """
    Delete an entire public workspace including all documents and members.
    """
    try:
        # Get admin user info
        admin_user = session.get('user', {})
        admin_user_id = admin_user.get('oid', 'unknown')
        admin_email = admin_user.get('preferred_username', 'unknown')
        
        # Get workspace name for logging
        try:
            workspace = cosmos_public_workspaces_container.read_item(
                item=workspace_id,
                partition_key=workspace_id
            )
            workspace_name = workspace.get('name', 'Unknown')
        except:
            workspace_name = 'Unknown'
        
        # First delete all documents
        doc_query = "SELECT c.id FROM c WHERE c.public_workspace_id = @workspace_id"
        doc_params = [{"name": "@workspace_id", "value": workspace_id}]
        
        docs_to_delete = list(cosmos_public_documents_container.query_items(
            query=doc_query,
            parameters=doc_params,
            enable_cross_partition_query=True
        ))
        
        for doc in docs_to_delete:
            try:
                delete_document_chunks(doc['id'])
                delete_document(doc['id'])
            except Exception as del_e:
                debug_print(f"Error deleting document {doc['id']}: {del_e}")
        
        # Delete the workspace itself
        cosmos_public_workspaces_container.delete_item(
            item=workspace_id,
            partition_key=workspace_id
        )
        
        # Log the action
        log_event("[ControlCenter] Public Workspace Deleted", {
            "admin_user": admin_email,
            "admin_user_id": admin_user_id,
            "workspace_id": workspace_id,
            "workspace_name": workspace_name,
            "documents_deleted": len(docs_to_delete)
        })
        
        return jsonify({
            'message': 'Workspace deleted successfully'
        }), 200
        
    except Exception as e:
        debug_print(f"Error deleting workspace: {e}")
        return jsonify({'error': 'Failed to delete workspace'}), 500
