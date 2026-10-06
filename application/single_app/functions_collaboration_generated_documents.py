# functions_collaboration_generated_documents.py
"""Documents that agents generated in a shared conversation, and who may download them.

An agent creates a document with the SimpleChat action's upload functions. Each stores the file
in the requester's personal workspace or in a group workspace and returns its id, which stays on
the message in the agent citation. That is what lets a shared conversation list what was produced
in it. Listing reveals only file names; downloading follows the workspace's own download rules,
whichever group the reader currently has active.
"""

import json
import os
import re

from functions_documents import get_document_record
from functions_group import assert_group_role, find_group_by_id
from functions_settings import (
    get_settings,
    is_group_workspace_file_download_enabled,
    is_personal_workspace_file_download_enabled,
)

GENERATED_DOCUMENT_FUNCTIONS = frozenset({
    'upload_markdown_document',
    'upload_word_document',
    'upload_powerpoint_document',
})
# The roles the group workspace's own download route requires
# (GROUP_DOCUMENT_DOWNLOAD_MANAGER_ROLES in route_backend_group_documents.py).
GROUP_DOWNLOAD_ROLES = ('Owner', 'Admin', 'DocumentManager')
DOCUMENT_ID_PATTERN = re.compile(r'^[A-Za-z0-9-]{8,64}$')
MARKDOWN_EXTENSIONS = frozenset({'.md', '.markdown'})
FILE_NAME_MAX_LENGTH = 255


def _parse_result(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value if isinstance(value, dict) else None


def read_generated_document(citation):
    """Return the document an upload citation created, or None for any other citation."""
    if not isinstance(citation, dict):
        return None
    if str(citation.get('function_name') or '').strip() not in GENERATED_DOCUMENT_FUNCTIONS:
        return None
    result = _parse_result(citation.get('function_result'))
    if not result or result.get('success') is False:
        return None
    document = result.get('document')
    if not isinstance(document, dict):
        return None

    document_id = str(document.get('id') or '').strip()
    if not DOCUMENT_ID_PATTERN.match(document_id):
        return None
    scope = str(result.get('workspace_scope') or '').strip().lower()
    group_id = str(result.get('group_id') or '').strip()
    if scope == 'group':
        if not group_id:
            return None
    elif scope == 'personal':
        group_id = ''
    else:
        return None

    raw_name = str(document.get('file_name') or '').replace('\\', '/')
    file_name = os.path.basename(raw_name).strip()[:FILE_NAME_MAX_LENGTH] or 'document'
    extension = os.path.splitext(file_name)[1].lower()
    return {
        'document_id': document_id,
        'file_name': file_name,
        'workspace_scope': scope,
        'group_id': group_id or None,
        'preview': 'markdown' if extension in MARKDOWN_EXTENSIONS else None,
    }


def collect_generated_documents(messages):
    """List every document generated in a conversation's messages, oldest first, once each.

    A fully masked message is skipped: masking it hid what it said, including what it produced.
    """
    found = {}
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        metadata = message.get('metadata')
        if isinstance(metadata, dict) and metadata.get('masked') is True:
            continue
        citations = message.get('agent_citations')
        if not isinstance(citations, list):
            continue
        for citation in citations:
            document = read_generated_document(citation)
            if not document or document['document_id'] in found:
                continue
            document['message_id'] = str(message.get('id') or '')
            document['created_at'] = str(
                (citation.get('timestamp') if isinstance(citation, dict) else '')
                or message.get('timestamp')
                or ''
            )
            found[document['document_id']] = document
    return list(found.values())


def authorize_generated_document_download(user_id, document, settings=None):
    """Return ``(document_record, group_id)`` when ``user_id`` may download ``document``.

    Raises ``PermissionError`` when the workspace's download rules refuse it and ``LookupError``
    when the document cannot be read by this user, which includes another person's personal
    document. A group document needs a document-managing role in that group and downloads
    allowed for it; a personal one needs to be the reader's own with personal downloads allowed.
    """
    settings = settings if settings is not None else get_settings()
    document_id = document['document_id']
    if document['workspace_scope'] == 'group':
        if not settings.get('enable_group_workspaces', False):
            raise PermissionError('Group workspaces are disabled')
        group_id = document['group_id']
        group_doc = find_group_by_id(group_id)
        if not group_doc:
            raise LookupError('Document not found')
        assert_group_role(user_id, group_id, allowed_roles=GROUP_DOWNLOAD_ROLES)
        if not is_group_workspace_file_download_enabled(settings, group_doc):
            raise PermissionError('File downloads are disabled for this group workspace')
        record = get_document_record(user_id=user_id, document_id=document_id, group_id=group_id)
        if not record:
            raise LookupError('Document not found')
        return record, group_id

    if not settings.get('enable_user_workspace', False):
        raise PermissionError('Personal workspaces are disabled')
    if not is_personal_workspace_file_download_enabled(settings):
        raise PermissionError('File downloads are disabled for personal workspaces')
    record = get_document_record(user_id=user_id, document_id=document_id)
    if not record:
        raise LookupError('Document not found')
    return record, None


def can_download_generated_document(user_id, document, settings=None):
    """Whether the download would be allowed, for the list's Download control."""
    try:
        authorize_generated_document_download(user_id, document, settings=settings)
    except (LookupError, PermissionError):
        return False
    return True
