# functions_message_deletion.py
"""Helpers for soft-deleted chat messages.

With conversation archiving enabled, deleting a chat message keeps its document in the
messages container with ``metadata.is_deleted`` set, rather than removing it. The delete
route also masks the message, but only as a fail-safe: masking is a separate, reversible
user action, and a deleted message must not come back as a masked placeholder, be copied
into a fork or shared conversation, be searchable, or reach the model.

Every reader that shows, copies, searches, or sends stored messages to a model therefore
has to drop soft-deleted documents itself. These helpers keep that check in one place.
"""

from collections.abc import Mapping


SOFT_DELETE_METADATA_FIELDS = (
    'is_deleted',
    'deleted_by_user_id',
    'deleted_timestamp',
)

# For Cosmos queries that must exclude soft-deleted messages server-side, such as TOP 1
# lookups where filtering afterwards could leave nothing. The container alias must be `c`.
NOT_SOFT_DELETED_COSMOS_FILTER = (
    '(NOT IS_DEFINED(c.metadata.is_deleted) OR c.metadata.is_deleted != true)'
)


def is_soft_deleted_message(message):
    """Return True when a stored chat message was deleted while archiving was enabled."""
    if not isinstance(message, Mapping):
        return False
    metadata = message.get('metadata')
    return isinstance(metadata, Mapping) and metadata.get('is_deleted') is True


def exclude_soft_deleted_messages(messages):
    """Return the messages that were not soft-deleted, preserving their order."""
    return [message for message in messages or [] if not is_soft_deleted_message(message)]


def strip_soft_delete_metadata(metadata):
    """Remove deletion markers from metadata copied onto a new message, in place."""
    if isinstance(metadata, dict):
        for field_name in SOFT_DELETE_METADATA_FIELDS:
            metadata.pop(field_name, None)
    return metadata
