    # The public directory is where the user can see all public workspaces and enables which ones
    # they want to use with chat. There are two sections one for selected workspaces and another
    # for unselected workspaces. each row is a workspace with columns for workspace name,
    # workspace description, document count, and prompt count, a toggle to select or unselect the workspace
    # and a button to view the workspace. 
    # there is an expand button to show the owner of the workspace and the date it was created
    # The user can also search for workspaces by name or description.
    # The user can minimize the selected or unselected workspaces section to save space.
    # If the user has permissions to create workspaces, there is a button to create a new workspace.
    # We will save the selected workspaces in the user's settings to show in the directory page and in chat
    # We start with creating two pages 
    # 1. my public workspaces page, this is where people who have the role
    # "CreatePublicWorkspaces" can view their public workspaces and create new ones.
    # This page will look similar to the my_groups.html page
    # 2. manage public workspaces page, this is 
    # Roles in Public Workspaces
    # Owner: Full control over the workspace, transfer ownership, can delete it, create and manage documents and prompts, add or remove members, and their roles.
    # Admin: Can manage workspac, create and manage documents and prompts, add or remove members, and their roles.
    # Document Manager: Can upload and manage documents and prompts
    # Unlike Group Workspaces, there is no "User" role - all documents and prompts are visible to everyone in the organization.
    # This page will look similar to the manage_group.html page and manage_group.js 

from config import *
from functions_authentication import *
from functions_settings import *

def register_route_frontend_public_workspaces(app):
    @app.route("/my_public_workspaces", methods=["GET"])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @create_public_workspace_role_required
    def my_public_workspaces():
        settings = get_settings()
        public_settings = sanitize_settings_for_user(settings)
        return render_template(
            "my_public_workspaces.html", 
            settings=public_settings
        )

    @app.route("/public_workspaces/<workspace_id>", methods=["GET"])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @create_public_workspace_role_required
    def manage_public_workspace(workspace_id):
        settings = get_settings()
        public_settings = sanitize_settings_for_user(settings)
        return render_template(
            "manage_public_workspace.html",
            settings=public_settings,
            workspace_id=workspace_id
        )