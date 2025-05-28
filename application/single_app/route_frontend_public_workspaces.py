# route_frontend_public_workspaces.py

from config import *
from functions_authentication import *
from functions_public_workspace import *


def register_route_frontend_public_workspaces(app):
    @app.route('/public_workspaces_directory', methods=['GET'])
    @login_required
    def public_workspaces_directory():
        """Render the public workspaces directory page."""
        try:
            # Get all public workspaces
            workspaces = get_all_public_workspaces()
            
            # Get the current user ID to determine roles
            user_id = get_current_user_id()
            
            # For each workspace, determine if the user has any role
            for workspace in workspaces:
                workspace["userRole"] = get_user_role_in_public_workspace(workspace, user_id)
                
                # Count documents and prompts for this workspace
                # Documents count
                documents_query = "SELECT VALUE COUNT(1) FROM c WHERE c.public_workspace_id = @workspace_id AND c.type = 'document_metadata'"
                documents_params = [{"name": "@workspace_id", "value": workspace["id"]}]
                documents_count = list(cosmos_public_documents_container.query_items(
                    query=documents_query,
                    parameters=documents_params,
                    enable_cross_partition_query=True
                ))[0]
                
                # Prompts count
                prompts_query = "SELECT VALUE COUNT(1) FROM c WHERE c.public_workspace_id = @workspace_id AND c.type = 'public_prompt'"
                prompts_params = [{"name": "@workspace_id", "value": workspace["id"]}]
                prompts_count = list(cosmos_public_prompts_container.query_items(
                    query=prompts_query,
                    parameters=prompts_params,
                    enable_cross_partition_query=True
                ))[0]
                
                workspace["documentsCount"] = documents_count
                workspace["promptsCount"] = prompts_count
                
                # Get the owner, admins, and document managers
                workspace["ownerInfo"] = workspace.get("owner", {})
                
                # Get admin info
                admin_info = []
                for admin_id in workspace.get("admins", []):
                    # In a real app, you'd look up each user's info from your user database
                    # For now, we'll just include the ID
                    admin_info.append({"id": admin_id})
                workspace["adminInfo"] = admin_info
                
                # Get document manager info
                doc_manager_info = []
                for manager_id in workspace.get("documentManagers", []):
                    # In a real app, you'd look up each user's info from your user database
                    # For now, we'll just include the ID
                    doc_manager_info.append({"id": manager_id})
                workspace["documentManagerInfo"] = doc_manager_info
                
            return render_template('public_workspaces_directory.html', 
                workspaces=workspaces,
                page_title="Public Workspaces"
            )
                
        except Exception as e:
            print(f"Error in public_workspaces_directory: {str(e)}")
            flash(f"An error occurred: {str(e)}", "danger")
            return redirect(url_for('index'))


    @app.route('/public_workspaces/<workspace_id>', methods=['GET'])
    @login_required
    def public_workspace(workspace_id):
    """Render a specific public workspace page."""
    try:
        # Get the workspace
        workspace = find_public_workspace_by_id(workspace_id)
        if not workspace:
            flash("Public workspace not found", "danger")
            return redirect(url_for('public_workspaces_directory'))
            
        # Anyone can view a public workspace
        user_id = get_current_user_id()
        role = get_user_role_in_public_workspace(workspace, user_id)
        can_edit = bool(role and role in ["Owner", "Admin", "DocumentManager"])
        
        # Get workspace documents
        query = "SELECT * FROM c WHERE c.public_workspace_id = @workspace_id AND c.type = 'document_metadata'"
        params = [{"name": "@workspace_id", "value": workspace_id}]
        
        documents = list(cosmos_public_documents_container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True
        ))
        
        # Get workspace prompts
        prompts_query = "SELECT * FROM c WHERE c.public_workspace_id = @workspace_id AND c.type = 'public_prompt'"
        prompts = list(cosmos_public_prompts_container.query_items(
            query=prompts_query,
            parameters=params,
            enable_cross_partition_query=True
        ))
        
        # Save this as the active public workspace in the session
        session["active_public_workspace"] = workspace_id
        
        # Update the user's settings to reflect this choice
        update_active_public_workspace_for_user(workspace_id)
        
        return render_template('public_workspace.html',
            workspace=workspace,
            documents=documents,
            prompts=prompts,
            user_role=role,
            can_edit=can_edit,
            page_title=workspace.get("name", "Public Workspace")
        )
        
    except Exception as e:
        print(f"Error in public_workspace: {str(e)}")
        flash(f"An error occurred: {str(e)}", "danger")
        return redirect(url_for('public_workspaces_directory'))


    @app.route('/my_public_workspaces')
    @login_required
    def my_public_workspaces():
    """Show public workspaces where the current user has a management role."""
    try:
        current_user_id = get_current_user_id()
        workspaces = get_user_public_workspaces(current_user_id)
        
        return render_template('my_public_workspaces.html', 
                              workspaces=workspaces,
                              page_title="My Public Workspaces")
        
    except Exception as e:
        flash(f"Error retrieving your public workspaces: {str(e)}", "danger")
        return redirect(url_for('index'))


    @app.route('/create_public_workspace', methods=['GET', 'POST'])
    @login_required
    @create_public_workspace_role_required
    def create_new_public_workspace():
    """Create a new public workspace."""
    if request.method == 'GET':
        return render_template('create_public_workspace.html', 
                              page_title="Create Public Workspace")
        
    elif request.method == 'POST':
        try:
            name = request.form.get('name')
            description = request.form.get('description', '')
            
            if not name:
                flash("Workspace name is required", "danger")
                return render_template('create_public_workspace.html')
                
            workspace = create_public_workspace(name, description)
            
            flash("Public workspace created successfully", "success")
            return redirect(url_for('manage_public_workspace', workspace_id=workspace['id']))
            
        except Exception as e:
            flash(f"Error creating workspace: {str(e)}", "danger")
            return render_template('create_public_workspace.html')


    @app.route('/manage_public_workspace/<workspace_id>')
    @login_required
    def manage_public_workspace(workspace_id):
    """Manage content (documents and prompts) in a public workspace."""
    try:
        workspace = find_public_workspace_by_id(workspace_id)
        if not workspace:
            flash("Workspace not found", "danger")
            return redirect(url_for('my_public_workspaces'))
            
        current_user_id = get_current_user_id()
        user_role = get_user_role_in_public_workspace(workspace, current_user_id)
        
        # Check if user has management role
        if not user_role:
            flash("You don't have permission to manage this workspace", "danger")
            return redirect(url_for('public_workspaces_directory'))
            
        # Get documents
        doc_query = """
            SELECT * FROM c WHERE c.public_workspace_id = @workspace_id AND c.type = 'document_metadata'
        """
        doc_params = [{"name": "@workspace_id", "value": workspace_id}]
        documents = list(cosmos_public_documents_container.query_items(
            query=doc_query,
            parameters=doc_params,
            enable_cross_partition_query=True
        ))
        
        # Get prompts
        prompt_query = """
            SELECT * FROM c WHERE c.public_workspace_id = @workspace_id AND c.type = 'public_prompt'
        """
        prompt_params = [{"name": "@workspace_id", "value": workspace_id}]
        prompts = list(cosmos_public_prompts_container.query_items(
            query=prompt_query,
            parameters=prompt_params,
            enable_cross_partition_query=True
        ))
        
        return render_template(
            'manage_public_workspace.html',
            workspace=workspace,
            documents=documents,
            prompts=prompts,
            user_role=user_role,
            page_title=f"Manage {workspace.get('name', 'Public Workspace')}"
        )
        
    except Exception as e:
        flash(f"Error managing workspace: {str(e)}", "danger")
        return redirect(url_for('my_public_workspaces'))


    @app.route('/administrate_public_workspace/<workspace_id>', methods=['GET', 'POST'])
    @login_required
    def administrate_public_workspace(workspace_id):
    """Administrate a public workspace (settings, members, etc.)."""
    try:
        workspace = find_public_workspace_by_id(workspace_id)
        if not workspace:
            flash("Workspace not found", "danger")
            return redirect(url_for('my_public_workspaces'))
            
        current_user_id = get_current_user_id()
        user_role = get_user_role_in_public_workspace(workspace, current_user_id)
        
        # Check if user has admin or owner role
        if user_role not in ["Owner", "Admin"]:
            flash("You don't have administrative permissions for this workspace", "danger")
            return redirect(url_for('public_workspaces_directory'))
            
        if request.method == 'POST':
            action = request.form.get('action')
            
            # Update workspace info
            if action == 'update_info':
                # Verify user is Owner or Admin
                if user_role not in ["Owner", "Admin"]:
                    flash("You don't have permission to update workspace settings", "danger")
                    return redirect(url_for('administrate_public_workspace', workspace_id=workspace_id))
                    
                name = request.form.get('name')
                description = request.form.get('description', '')
                
                if not name:
                    flash("Workspace name is required", "danger")
                    return redirect(url_for('administrate_public_workspace', workspace_id=workspace_id))
                
                workspace['name'] = name
                workspace['description'] = description
                workspace['modifiedDate'] = datetime.utcnow().isoformat()
                
                cosmos_public_workspaces_container.upsert_item(workspace)
                flash("Workspace information updated successfully", "success")
                
            # Add member
            elif action == 'add_member':
                # Only Owner can add Admins, but both Owner and Admins can add DocumentManagers
                member_id = request.form.get('member_id')
                role = request.form.get('role')
                
                if not member_id or not role:
                    flash("Member ID and role are required", "danger")
                    return redirect(url_for('administrate_public_workspace', workspace_id=workspace_id))
                    
                if role == "Admin" and user_role != "Owner":
                    flash("Only workspace owners can add admins", "danger")
                    return redirect(url_for('administrate_public_workspace', workspace_id=workspace_id))
                
                # Check if user already has a role
                if workspace.get('owner', {}).get('id') == member_id:
                    flash("This user is already the workspace owner", "warning")
                elif member_id in workspace.get('admins', []) and role == "Admin":
                    flash("This user is already an admin", "warning")
                elif member_id in workspace.get('documentManagers', []) and role == "DocumentManager":
                    flash("This user is already a document manager", "warning")
                else:
                    # Remove from other role if present (role switch)
                    if member_id in workspace.get('admins', []) and role != "Admin":
                        workspace['admins'].remove(member_id)
                    if member_id in workspace.get('documentManagers', []) and role != "DocumentManager":
                        workspace['documentManagers'].remove(member_id)
                    
                    # Add to new role
                    if role == "Admin":
                        if 'admins' not in workspace:
                            workspace['admins'] = []
                        workspace['admins'].append(member_id)
                        flash(f"User added as Admin", "success")
                    elif role == "DocumentManager":
                        if 'documentManagers' not in workspace:
                            workspace['documentManagers'] = []
                        workspace['documentManagers'].append(member_id)
                        flash(f"User added as Document Manager", "success")
                    
                    workspace['modifiedDate'] = datetime.utcnow().isoformat()
                    cosmos_public_workspaces_container.upsert_item(workspace)
                    
            # Remove member
            elif action == 'remove_member':
                member_id = request.form.get('member_id')
                member_role = request.form.get('member_role')
                
                if not member_id or not member_role:
                    flash("Member information is missing", "danger")
                    return redirect(url_for('administrate_public_workspace', workspace_id=workspace_id))
                
                # Only owners can remove admins
                if member_role == "Admin" and user_role != "Owner":
                    flash("Only workspace owners can remove admins", "danger")
                    return redirect(url_for('administrate_public_workspace', workspace_id=workspace_id))
                
                if member_role == "Admin" and member_id in workspace.get('admins', []):
                    workspace['admins'].remove(member_id)
                    flash("Admin removed successfully", "success")
                elif member_role == "DocumentManager" and member_id in workspace.get('documentManagers', []):
                    workspace['documentManagers'].remove(member_id)
                    flash("Document Manager removed successfully", "success")
                else:
                    flash("Member not found with the specified role", "warning")
                    
                workspace['modifiedDate'] = datetime.utcnow().isoformat()
                cosmos_public_workspaces_container.upsert_item(workspace)
                
            # Delete workspace
            elif action == 'delete_workspace':
                # Only owner can delete workspace
                if user_role != "Owner":
                    flash("Only workspace owners can delete workspaces", "danger")
                    return redirect(url_for('administrate_public_workspace', workspace_id=workspace_id))
                
                try:
                    delete_public_workspace(workspace_id)
                    flash("Workspace deleted successfully", "success")
                    return redirect(url_for('my_public_workspaces'))
                except Exception as e:
                    flash(f"Error deleting workspace: {str(e)}", "danger")
            
            # Redirect back to administration page after actions
            return redirect(url_for('administrate_public_workspace', workspace_id=workspace_id))
            
        # For GET requests, render the administration page
        return render_template(
            'administrate_public_workspace.html',
            workspace=workspace,
            user_role=user_role,
            page_title=f"Administrate {workspace.get('name', 'Public Workspace')}"
        )
        
    except Exception as e:
        flash(f"Error administering workspace: {str(e)}", "danger")
        return redirect(url_for('my_public_workspaces'))
