# route_frontend_my_public_workspaces.py

from config import *
from functions_authentication import *
from functions_public_workspace import *


@app.route('/my_public_workspaces', methods=['GET'])
@login_required
@create_public_workspace_role_required
def my_public_workspaces():
    """Render the My Public Workspaces page (visible only to users with CreatePublicWorkspaces role)."""
    try:
        user_id = get_current_user_id()
        workspaces = get_user_public_workspaces(user_id)
        
        return render_template('my_public_workspaces.html', 
            workspaces=workspaces,
            page_title="My Public Workspaces"
        )
        
    except Exception as e:
        print(f"Error in my_public_workspaces: {str(e)}")
        flash(f"An error occurred: {str(e)}", "danger")
        return redirect(url_for('index'))


@app.route('/my_public_workspaces/create', methods=['GET', 'POST'])
@login_required
@create_public_workspace_role_required
def create_new_public_workspace():
    """Handle creation of a new public workspace."""
    if request.method == 'POST':
        try:
            name = request.form.get('name')
            description = request.form.get('description', '')
            
            if not name:
                flash("Workspace name is required", "danger")
                return redirect(url_for('create_new_public_workspace'))
                
            # Create the new public workspace
            workspace = create_public_workspace(name, description)
            
            flash("Public workspace created successfully", "success")
            return redirect(url_for('manage_public_workspace', workspace_id=workspace["id"]))
            
        except Exception as e:
            print(f"Error creating public workspace: {str(e)}")
            flash(f"Failed to create public workspace: {str(e)}", "danger")
            return redirect(url_for('my_public_workspaces'))
    
    # GET request - render the creation form
    return render_template('create_public_workspace.html',
        page_title="Create Public Workspace"
    )


@app.route('/my_public_workspaces/<workspace_id>/manage', methods=['GET'])
@login_required
def manage_public_workspace(workspace_id):
    """Render the page to manage a public workspace's documents and prompts."""
    try:
        # Get the workspace
        workspace = find_public_workspace_by_id(workspace_id)
        if not workspace:
            flash("Public workspace not found", "danger")
            return redirect(url_for('my_public_workspaces'))
            
        # Check if user has permissions to manage this workspace
        user_id = get_current_user_id()
        role = get_user_role_in_public_workspace(workspace, user_id)
        
        if not role:
            flash("You do not have permission to manage this workspace", "danger")
            return redirect(url_for('my_public_workspaces'))
            
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
        
        return render_template('manage_public_workspace.html',
            workspace=workspace,
            documents=documents,
            prompts=prompts,
            user_role=role,
            page_title=f"Manage: {workspace.get('name', 'Public Workspace')}"
        )
        
    except Exception as e:
        print(f"Error in manage_public_workspace: {str(e)}")
        flash(f"An error occurred: {str(e)}", "danger")
        return redirect(url_for('my_public_workspaces'))


@app.route('/my_public_workspaces/<workspace_id>/admin', methods=['GET', 'POST'])
@login_required
def administrate_public_workspace(workspace_id):
    """Render the page to administrate a public workspace's settings and members."""
    try:
        # Get the workspace
        workspace = find_public_workspace_by_id(workspace_id)
        if not workspace:
            flash("Public workspace not found", "danger")
            return redirect(url_for('my_public_workspaces'))
            
        # Check if user has permissions to administrate this workspace (Owner or Admin)
        user_id = get_current_user_id()
        role = get_user_role_in_public_workspace(workspace, user_id)
        
        if not role or role not in ["Owner", "Admin"]:
            flash("You do not have permission to administrate this workspace", "danger")
            return redirect(url_for('my_public_workspaces'))
            
        # Handle POST requests (update workspace settings)
        if request.method == 'POST':
            action = request.form.get('action')
            
            if action == 'update_info':
                # Update workspace info
                name = request.form.get('name')
                description = request.form.get('description', '')
                
                if not name:
                    flash("Workspace name is required", "danger")
                    return redirect(url_for('administrate_public_workspace', workspace_id=workspace_id))
                    
                workspace['name'] = name
                workspace['description'] = description
                workspace['modifiedDate'] = datetime.utcnow().isoformat()
                
                cosmos_public_workspaces_container.replace_item(item=workspace_id, body=workspace)
                flash("Workspace information updated successfully", "success")
                
            elif action == 'add_member':
                # Add a member with a role
                member_id = request.form.get('member_id')
                member_role = request.form.get('role')
                
                if not member_id or not member_role:
                    flash("Member ID and role are required", "danger")
                    return redirect(url_for('administrate_public_workspace', workspace_id=workspace_id))
                    
                if member_role == 'Admin':
                    if member_id not in workspace.get('admins', []):
                        workspace.setdefault('admins', []).append(member_id)
                elif member_role == 'DocumentManager':
                    if member_id not in workspace.get('documentManagers', []):
                        workspace.setdefault('documentManagers', []).append(member_id)
                
                workspace['modifiedDate'] = datetime.utcnow().isoformat()
                cosmos_public_workspaces_container.replace_item(item=workspace_id, body=workspace)
                flash(f"Member added as {member_role} successfully", "success")
                
            elif action == 'delete_workspace':
                # Only the owner can delete the workspace
                if role != "Owner":
                    flash("Only the workspace owner can delete the workspace", "danger")
                    return redirect(url_for('administrate_public_workspace', workspace_id=workspace_id))
                    
                delete_public_workspace(workspace_id)
                flash("Workspace deleted successfully", "success")
                return redirect(url_for('my_public_workspaces'))
                
            return redirect(url_for('administrate_public_workspace', workspace_id=workspace_id))
        
        # GET request - render the administration page
        return render_template('administrate_public_workspace.html',
            workspace=workspace,
            user_role=role,
            page_title=f"Administrate: {workspace.get('name', 'Public Workspace')}"
        )
        
    except Exception as e:
        print(f"Error in administrate_public_workspace: {str(e)}")
        flash(f"An error occurred: {str(e)}", "danger")
        return redirect(url_for('my_public_workspaces'))