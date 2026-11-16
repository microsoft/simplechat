# functions_orchestration_source_access.py
"""Strict current-authority source services for orchestration input reads.

Version: 0.261.232

Owners bind these runtime callbacks, not a browser-selectable policy. They are used
only when a step reads uploaded documents as inputs. Retained orchestration results
take their access from the conversation and run that produced them and never call
back into these services. Legacy screening/search callers outside the explicit scope
retain their old behavior.
"""

from content_screening.access import (
    assert_document_available,
    assert_evidence_available,
    raise_source_authority_error,
    strict_source_authority,
)
from functions_analysis_access import authorize_analysis_sources
from functions_mixed_source_orchestration import (
    MixedSourceCancellationError,
    resolve_authorized_source_manifest,
)


def resolve_orchestration_source_manifest(
    requested_sources, user_id, selection_mode="selected", conversation_id=None,
    active_group_ids=None, active_public_workspace_ids=None, doc_scope="all",
    context_resolver=None, cancel_requested=None, request_correlation_id=None,
):
    """Resolve current sources without disguising authority failures as absence."""
    with strict_source_authority():
        try:
            return resolve_authorized_source_manifest(
                requested_sources, user_id, selection_mode=selection_mode, conversation_id=conversation_id,
                active_group_ids=active_group_ids, active_public_workspace_ids=active_public_workspace_ids,
                doc_scope=doc_scope, context_resolver=context_resolver, cancel_requested=cancel_requested,
                request_correlation_id=request_correlation_id,
            )
        except MixedSourceCancellationError:
            raise
        except Exception as error:
            raise_source_authority_error(error)


def read_orchestration_source_metadata(document_id, user_id, group_id=None, public_workspace_id=None):
    """Read fresh authorized metadata and preserve its strict, typed failure state."""
    return assert_document_available(
        document_id, user_id, group_id, public_workspace_id,
        purpose="orchestration_result", strict_errors=True,
    )


def verify_orchestration_input_sources(
    user_id, sources, *, require_snapshot, resolver, metadata_reader,
):
    """Input reads only: confirm a step may still read the uploaded documents it selected.

    The reader must still have access, no document may be held, and with
    ``require_snapshot`` each document must still be the version the step started from.
    Never call this for a retained result: those take their access from their container.
    """
    def resolve(document_ids, **scope):
        try:
            return resolver(document_ids, **scope)
        except MixedSourceCancellationError:
            raise
        except Exception as error:
            raise_source_authority_error(error)

    with strict_source_authority():
        checked = authorize_analysis_sources(
            user_id, sources, require_snapshot=require_snapshot, resolver=resolve,
        )
        assert_evidence_available(sources, user_id=user_id, metadata_reader=metadata_reader)
        return checked
