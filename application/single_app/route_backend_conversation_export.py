# route_backend_conversation_export.py

import io
import json
import zipfile
from datetime import datetime

from config import *
from functions_authentication import *
from functions_settings import *
from flask import Response, jsonify, request, make_response
from functions_debug import debug_print
from swagger_wrapper import swagger_route, get_auth_security


def register_route_backend_conversation_export(app):
    """Register conversation export API routes."""

    @app.route('/api/conversations/export', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_export_conversations():
        """
        Export one or more conversations in JSON or Markdown format.
        Supports single-file or ZIP packaging.

        Request body:
            conversation_ids (list): List of conversation IDs to export.
            format (str): Export format — "json" or "markdown".
            packaging (str): Output packaging — "single" or "zip".
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        data = request.get_json()
        if not data:
            return jsonify({'error': 'Request body is required'}), 400

        conversation_ids = data.get('conversation_ids', [])
        export_format = data.get('format', 'json').lower()
        packaging = data.get('packaging', 'single').lower()

        if not conversation_ids or not isinstance(conversation_ids, list):
            return jsonify({'error': 'At least one conversation_id is required'}), 400

        if export_format not in ('json', 'markdown'):
            return jsonify({'error': 'Format must be "json" or "markdown"'}), 400

        if packaging not in ('single', 'zip'):
            return jsonify({'error': 'Packaging must be "single" or "zip"'}), 400

        try:
            exported = []
            for conv_id in conversation_ids:
                # Verify ownership and fetch conversation
                try:
                    conversation = cosmos_conversations_container.read_item(
                        item=conv_id,
                        partition_key=conv_id
                    )
                except Exception:
                    debug_print(f"Export: conversation {conv_id} not found or access denied")
                    continue

                # Verify user owns this conversation
                if conversation.get('user_id') != user_id:
                    debug_print(f"Export: user {user_id} does not own conversation {conv_id}")
                    continue

                # Fetch messages ordered by timestamp
                message_query = f"""
                    SELECT * FROM c
                    WHERE c.conversation_id = '{conv_id}'
                    ORDER BY c.timestamp ASC
                """
                messages = list(cosmos_messages_container.query_items(
                    query=message_query,
                    partition_key=conv_id
                ))

                # Filter for active thread messages only
                filtered_messages = []
                for msg in messages:
                    thread_info = msg.get('metadata', {}).get('thread_info', {})
                    active = thread_info.get('active_thread')
                    if active is True or active is None or 'active_thread' not in thread_info:
                        filtered_messages.append(msg)

                exported.append({
                    'conversation': _sanitize_conversation(conversation),
                    'messages': [_sanitize_message(m) for m in filtered_messages]
                })

            if not exported:
                return jsonify({'error': 'No accessible conversations found'}), 404

            # Generate export content
            timestamp_str = datetime.utcnow().strftime('%Y%m%d_%H%M%S')

            if packaging == 'zip':
                return _build_zip_response(exported, export_format, timestamp_str)
            else:
                return _build_single_file_response(exported, export_format, timestamp_str)

        except Exception as e:
            debug_print(f"Export error: {str(e)}")
            return jsonify({'error': f'Export failed: {str(e)}'}), 500

    def _sanitize_conversation(conv):
        """Return only user-facing conversation fields."""
        return {
            'id': conv.get('id'),
            'title': conv.get('title', 'Untitled'),
            'last_updated': conv.get('last_updated', ''),
            'chat_type': conv.get('chat_type', 'personal'),
            'tags': conv.get('tags', []),
            'is_pinned': conv.get('is_pinned', False),
            'context': conv.get('context', [])
        }

    def _sanitize_message(msg):
        """Return only user-facing message fields."""
        result = {
            'role': msg.get('role', ''),
            'content': msg.get('content', ''),
            'timestamp': msg.get('timestamp', ''),
        }
        # Include citations if present
        if msg.get('citations'):
            result['citations'] = msg['citations']
        # Include context/tool info if present
        if msg.get('context'):
            result['context'] = msg['context']
        return result

    def _build_single_file_response(exported, export_format, timestamp_str):
        """Build a single-file download response."""
        if export_format == 'json':
            content = json.dumps(exported, indent=2, ensure_ascii=False, default=str)
            filename = f"conversations_export_{timestamp_str}.json"
            content_type = 'application/json; charset=utf-8'
        else:
            parts = []
            for entry in exported:
                parts.append(_conversation_to_markdown(entry))
            content = '\n\n---\n\n'.join(parts)
            filename = f"conversations_export_{timestamp_str}.md"
            content_type = 'text/markdown; charset=utf-8'

        response = make_response(content)
        response.headers['Content-Type'] = content_type
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    def _build_zip_response(exported, export_format, timestamp_str):
        """Build a ZIP archive containing one file per conversation."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for entry in exported:
                conv = entry['conversation']
                safe_title = _safe_filename(conv.get('title', 'Untitled'))
                conv_id_short = conv.get('id', 'unknown')[:8]

                if export_format == 'json':
                    file_content = json.dumps(entry, indent=2, ensure_ascii=False, default=str)
                    ext = 'json'
                else:
                    file_content = _conversation_to_markdown(entry)
                    ext = 'md'

                file_name = f"{safe_title}_{conv_id_short}.{ext}"
                zf.writestr(file_name, file_content)

        buffer.seek(0)
        filename = f"conversations_export_{timestamp_str}.zip"

        response = make_response(buffer.read())
        response.headers['Content-Type'] = 'application/zip'
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    def _conversation_to_markdown(entry):
        """Convert a conversation + messages entry to Markdown format."""
        conv = entry['conversation']
        messages = entry['messages']

        lines = []
        title = conv.get('title', 'Untitled')
        lines.append(f"# {title}")
        lines.append('')

        # Metadata
        last_updated = conv.get('last_updated', '')
        chat_type = conv.get('chat_type', 'personal')
        tags = conv.get('tags', [])

        lines.append(f"**Last Updated:** {last_updated}  ")
        lines.append(f"**Chat Type:** {chat_type}  ")
        if tags:
            tag_strs = [str(t) for t in tags]
            lines.append(f"**Tags:** {', '.join(tag_strs)}  ")
        lines.append(f"**Messages:** {len(messages)}  ")
        lines.append('')
        lines.append('---')
        lines.append('')

        # Messages
        for msg in messages:
            role = msg.get('role', 'unknown')
            timestamp = msg.get('timestamp', '')
            raw_content = msg.get('content', '')
            content = _normalize_content(raw_content)

            role_label = role.capitalize()
            if role == 'assistant':
                role_label = 'Assistant'
            elif role == 'user':
                role_label = 'User'
            elif role == 'system':
                role_label = 'System'
            elif role == 'tool':
                role_label = 'Tool'

            lines.append(f"### {role_label}")
            if timestamp:
                lines.append(f"*{timestamp}*")
            lines.append('')
            lines.append(content)
            lines.append('')

            # Citations
            citations = msg.get('citations')
            if citations:
                lines.append('**Citations:**')
                if isinstance(citations, list):
                    for cit in citations:
                        if isinstance(cit, dict):
                            source = cit.get('title') or cit.get('filepath') or cit.get('url', 'Unknown')
                            lines.append(f"- {source}")
                        else:
                            lines.append(f"- {cit}")
                lines.append('')

            lines.append('---')
            lines.append('')

        return '\n'.join(lines)

    def _normalize_content(content):
        """Normalize message content to a plain string.
        
        Content may be a string, a list of content-part dicts
        (e.g. [{"type": "text", "text": "..."}, ...]), or a dict.
        """
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    if item.get('type') == 'text':
                        parts.append(item.get('text', ''))
                    elif item.get('type') == 'image_url':
                        parts.append('[Image]')
                    else:
                        parts.append(str(item))
                else:
                    parts.append(str(item))
            return '\n'.join(parts)
        if isinstance(content, dict):
            if content.get('type') == 'text':
                return content.get('text', '')
            return str(content)
        return str(content) if content else ''

    def _safe_filename(title):
        """Create a filesystem-safe filename from a conversation title."""
        import re
        # Remove or replace unsafe characters
        safe = re.sub(r'[<>:"/\\|?*]', '_', title)
        safe = re.sub(r'\s+', '_', safe)
        safe = safe.strip('_. ')
        # Truncate to reasonable length
        if len(safe) > 50:
            safe = safe[:50]
        return safe or 'Untitled'
