# functions_workflow_file_sync_sources.py

"""
The File Sync sources a personal workflow can use, listed without Flask.

A personal workflow can sync the user's own sources while File Sync is on for their personal
workspace. It can also sync the sources of the active group and the active public workspace,
when the user manages that workspace and File Sync is on for it. The personal workflow sources
route lists these for the classic and V2 editors, and chat orchestration lists them for its
planner, so both offer the same sources.

Nothing here writes. The active group and public workspace are read through
``user_settings_reader``. The route keeps ``get_user_settings``, and a caller without a request,
such as the planner on an executor thread, passes a write-free settings snapshot.
"""

import functions_settings
from functions_file_sync import (
    FILE_SYNC_MANAGER_ROLES,
    FILE_SYNC_SCOPE_GROUP,
    FILE_SYNC_SCOPE_PERSONAL,
    FILE_SYNC_SCOPE_PUBLIC,
    assert_public_workspace_role,
    is_file_sync_enabled_for_group,
    is_file_sync_enabled_for_public_workspace,
    is_file_sync_enabled_for_user,
    list_file_sync_sources,
)
from functions_group import assert_group_role


def project_workflow_file_sync_source(scope_type, scope_id, source):
    """Return a source's scope, id, name, type and state, without the full sanitizer.

    ``sanitize_file_sync_source`` also resolves the source's workspace identity, which can read
    Key Vault. The fields kept here pass through it unchanged, so a caller that needs only these
    fields, such as the planner, skips that lookup.
    """
    source = source if isinstance(source, dict) else {}
    return {
        'scope_type': scope_type,
        'scope_id': scope_id,
        'source_id': str(source.get('id') or '').strip(),
        'name': str(source.get('name') or source.get('id') or '').strip(),
        'source_type': str(source.get('source_type') or '').strip(),
        'enabled': source.get('enabled') is not False,
    }


def _user_settings_block(user_settings):
    block = user_settings.get('settings') if isinstance(user_settings, dict) else None
    return block if isinstance(block, dict) else {}


def collect_personal_workflow_file_sync_sources(user_id, settings, user_info, *, serialize,
                                                user_settings_reader=None):
    """Return ``(personal_file_sync_enabled, sources)`` for a personal workflow's File Sync.

    ``personal_file_sync_enabled`` says whether File Sync is on for the user's personal workspace,
    and so whether ``sources`` includes every personal source. ``serialize(scope_type, scope_id,
    source)`` shapes each source. The active group and public workspace are included by the same
    rules as before this helper existed: the user must hold a File Sync manager role there, and
    File Sync must be on for it. A missing, unknown or unmanaged workspace is skipped. Sources
    without an id are dropped.
    """
    user_info = user_info if isinstance(user_info, dict) else {}
    read_user_settings = user_settings_reader or functions_settings.get_user_settings
    user_settings = {}

    def active_workspace_id(key):
        if 'value' not in user_settings:
            user_settings['value'] = read_user_settings(user_id)
        return _user_settings_block(user_settings['value']).get(key)

    sources = []
    personal_enabled = is_file_sync_enabled_for_user(settings, user_id, user_info.get('email'), user_info=user_info)
    if personal_enabled:
        sources.extend(
            serialize(FILE_SYNC_SCOPE_PERSONAL, user_id, source)
            for source in list_file_sync_sources(FILE_SYNC_SCOPE_PERSONAL, user_id)
        )

    try:
        group_id = active_workspace_id('activeGroupOid')
        if not group_id:
            raise ValueError('No active group selected')
        assert_group_role(user_id, group_id, allowed_roles=FILE_SYNC_MANAGER_ROLES)
        if is_file_sync_enabled_for_group(settings, group_id, user_info=user_info):
            sources.extend(
                serialize(FILE_SYNC_SCOPE_GROUP, group_id, source)
                for source in list_file_sync_sources(FILE_SYNC_SCOPE_GROUP, group_id)
            )
    except (LookupError, PermissionError, ValueError):
        # No active group, a group that no longer exists, or one the user can't manage: its
        # sources aren't offered, and the personal and public sources still are.
        pass

    try:
        public_workspace_id = str(active_workspace_id('activePublicWorkspaceOid') or '').strip()
        if not public_workspace_id:
            raise ValueError('No active public workspace selected')
        assert_public_workspace_role(user_id, public_workspace_id, allowed_roles=FILE_SYNC_MANAGER_ROLES)
        if is_file_sync_enabled_for_public_workspace(settings, public_workspace_id, user_info=user_info):
            sources.extend(
                serialize(FILE_SYNC_SCOPE_PUBLIC, public_workspace_id, source)
                for source in list_file_sync_sources(FILE_SYNC_SCOPE_PUBLIC, public_workspace_id)
            )
    except (LookupError, PermissionError, ValueError):
        # The same rule for the active public workspace: skip it and keep the other sources.
        pass

    return personal_enabled, [source for source in sources if source.get('source_id')]
