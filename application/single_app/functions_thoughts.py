# functions_thoughts.py

import uuid
import time
from datetime import datetime, timedelta, timezone
from config import cosmos_thoughts_container, cosmos_archived_thoughts_container
from functions_appinsights import log_event
from functions_settings import get_settings


class ThoughtTracker:
    """Stateful per-request tracker that writes processing step records to Cosmos DB.

    Each add_thought() call immediately upserts a document so that polling
    clients can see partial progress before the final response is sent.

    All Cosmos writes are wrapped in try/except so thought errors never
    interrupt the chat processing flow.
    """

    def __init__(self, conversation_id, message_id, thread_id, user_id):
        self.conversation_id = conversation_id
        self.message_id = message_id
        self.thread_id = thread_id
        self.user_id = user_id
        self.current_index = 0
        settings = get_settings()
        self.enabled = settings.get('enable_thoughts', False)

    def add_thought(self, step_type, content, detail=None):
        """Write a thought step to Cosmos immediately.

        Args:
            step_type: One of search, tabular_analysis, web_search,
                       agent_tool_call, generation, content_safety.
            content: Short human-readable description of the step.
            detail: Optional technical detail (function names, params, etc.).

        Returns:
            The thought document id, or None if disabled/failed.
        """
        if not self.enabled:
            return None

        thought_id = str(uuid.uuid4())
        thought_doc = {
            'id': thought_id,
            'conversation_id': self.conversation_id,
            'message_id': self.message_id,
            'thread_id': self.thread_id,
            'user_id': self.user_id,
            'step_index': self.current_index,
            'step_type': step_type,
            'content': content,
            'detail': detail,
            'duration_ms': None,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        self.current_index += 1

        try:
            cosmos_thoughts_container.upsert_item(thought_doc)
        except Exception as e:
            log_event(f"ThoughtTracker.add_thought failed: {e}", level="WARNING")
            return None

        return thought_id

    def complete_thought(self, thought_id, duration_ms):
        """Patch an existing thought with its duration after the step finishes."""
        if not self.enabled or not thought_id:
            return

        try:
            thought_doc = cosmos_thoughts_container.read_item(
                item=thought_id,
                partition_key=self.user_id
            )
            thought_doc['duration_ms'] = duration_ms
            cosmos_thoughts_container.upsert_item(thought_doc)
        except Exception as e:
            log_event(f"ThoughtTracker.complete_thought failed: {e}", level="WARNING")

    def timed_thought(self, step_type, content, detail=None):
        """Convenience: add a thought and return a timer helper.

        Usage:
            timer = tracker.timed_thought('search', 'Searching documents...')
            # ... do work ...
            timer.stop()
        """
        start = time.time()
        thought_id = self.add_thought(step_type, content, detail)
        return _ThoughtTimer(self, thought_id, start)


class _ThoughtTimer:
    """Helper returned by ThoughtTracker.timed_thought() for auto-duration capture."""

    def __init__(self, tracker, thought_id, start_time):
        self._tracker = tracker
        self._thought_id = thought_id
        self._start = start_time

    def stop(self):
        elapsed_ms = int((time.time() - self._start) * 1000)
        self._tracker.complete_thought(self._thought_id, elapsed_ms)
        return elapsed_ms


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

def get_thoughts_for_message(conversation_id, message_id, user_id):
    """Return all thoughts for a specific assistant message, ordered by step_index."""
    try:
        query = (
            "SELECT * FROM c "
            "WHERE c.conversation_id = @conv_id "
            "AND c.message_id = @msg_id "
            "ORDER BY c.step_index ASC"
        )
        params = [
            {"name": "@conv_id", "value": conversation_id},
            {"name": "@msg_id", "value": message_id},
        ]
        results = list(cosmos_thoughts_container.query_items(
            query=query,
            parameters=params,
            partition_key=user_id
        ))
        return results
    except Exception as e:
        log_event(f"get_thoughts_for_message failed: {e}", level="WARNING")
        return []


def get_pending_thoughts(conversation_id, user_id, message_id=None):
    """Return the latest thoughts for a conversation that are still in-progress.

    Used by the polling endpoint.  Retrieves thoughts created within the last
    5 minutes for the conversation. When a message_id is provided, only
    thoughts for that assistant message are returned.
    """
    try:
        five_minutes_ago = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()

        query_parts = [
            "SELECT * FROM c ",
            "WHERE c.conversation_id = @conv_id ",
            "AND c.timestamp >= @since ",
        ]
        params = [
            {"name": "@conv_id", "value": conversation_id},
            {"name": "@since", "value": five_minutes_ago},
        ]

        if message_id:
            query_parts.append("AND c.message_id = @msg_id ")
            params.append({"name": "@msg_id", "value": message_id})

        query_parts.append("ORDER BY c.timestamp DESC")
        query = ''.join(query_parts)

        results = list(cosmos_thoughts_container.query_items(
            query=query,
            parameters=params,
            partition_key=user_id
        ))

        if not results:
            return []

        if message_id:
            pending_thoughts = results
        else:
            latest_message_id = results[0].get('message_id')
            pending_thoughts = [
                t for t in results if t.get('message_id') == latest_message_id
            ]

        pending_thoughts.sort(key=lambda t: t.get('step_index', 0))
        return pending_thoughts
    except Exception as e:
        log_event(f"get_pending_thoughts failed: {e}", level="WARNING")
        return []


def get_thoughts_for_conversation(conversation_id, user_id):
    """Return all thoughts for a conversation."""
    try:
        query = (
            "SELECT * FROM c "
            "WHERE c.conversation_id = @conv_id "
            "ORDER BY c.timestamp ASC"
        )
        params = [
            {"name": "@conv_id", "value": conversation_id},
        ]
        results = list(cosmos_thoughts_container.query_items(
            query=query,
            parameters=params,
            partition_key=user_id
        ))
        return results
    except Exception as e:
        log_event(f"get_thoughts_for_conversation failed: {e}", level="WARNING")
        return []


def archive_thoughts_for_conversation(conversation_id, user_id):
    """Copy all thoughts for a conversation to the archive container, then delete originals."""
    try:
        thoughts = get_thoughts_for_conversation(conversation_id, user_id)
        for thought in thoughts:
            archived = dict(thought)
            archived['archived_at'] = datetime.now(timezone.utc).isoformat()
            cosmos_archived_thoughts_container.upsert_item(archived)

        for thought in thoughts:
            cosmos_thoughts_container.delete_item(
                item=thought['id'],
                partition_key=user_id
            )
    except Exception as e:
        log_event(f"archive_thoughts_for_conversation failed: {e}", level="WARNING")


def delete_thoughts_for_conversation(conversation_id, user_id):
    """Delete all thoughts for a conversation."""
    try:
        thoughts = get_thoughts_for_conversation(conversation_id, user_id)
        for thought in thoughts:
            cosmos_thoughts_container.delete_item(
                item=thought['id'],
                partition_key=user_id
            )
    except Exception as e:
        log_event(f"delete_thoughts_for_conversation failed: {e}", level="WARNING")


def delete_thoughts_for_message(message_id, user_id):
    """Delete all thoughts associated with a specific assistant message."""
    try:
        query = (
            "SELECT * FROM c "
            "WHERE c.message_id = @msg_id"
        )
        params = [
            {"name": "@msg_id", "value": message_id},
        ]
        results = list(cosmos_thoughts_container.query_items(
            query=query,
            parameters=params,
            partition_key=user_id
        ))
        for thought in results:
            cosmos_thoughts_container.delete_item(
                item=thought['id'],
                partition_key=user_id
            )
    except Exception as e:
        log_event(f"delete_thoughts_for_message failed: {e}", level="WARNING")
