#!/usr/bin/env python3
# test_document_metadata_chunk_sync_batching.py
"""
Functional test for document metadata chunk sync batching.
Version: 0.261.052
Implemented in: 0.261.051
Updated in: 0.261.052

This test ensures that saving metadata on a large document does no per-chunk Search work
inside the request, and that the background sync then covers every chunk with a small number
of batched merges instead of one Search round-trip per chunk or browser-driven continuations.
"""

import os
import sys
import traceback

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_document_search_metadata_sync import Harness  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


DOCUMENT_ID = "doc-large-xml"
CHUNK_COUNT = 5000


def test_large_document_metadata_save_defers_and_batches_chunk_sync():
    """Saving tags on a 5,000-chunk document returns without chunk work and syncs in batches."""
    print("Testing large document metadata chunk sync batching...")
    assert_app_version_at_least("0.261.052")
    harness = Harness()
    harness.add_personal_document(document_id=DOCUMENT_ID, user_id="user-123", chunk_count=CHUNK_COUNT)

    result = harness["update_document"](document_id=DOCUMENT_ID, user_id="user-123", tags=["bills"])

    assert result["search_sync"]["status"] == "pending"
    assert harness.user_search.search_calls == [], "The save request must not list chunks."
    assert harness.user_search.merge_batches == [], "The save request must not write chunks."

    sync_result = harness["run_document_search_metadata_sync"](
        f"document_search_metadata_sync:personal:{DOCUMENT_ID}"
    )

    batch_size = harness["DOCUMENT_SEARCH_SYNC_BATCH_SIZE"]
    expected_batches = -(-CHUNK_COUNT // batch_size)
    # A full final page needs one more key query to confirm there are no more chunks.
    expected_searches = expected_batches + (1 if CHUNK_COUNT % batch_size == 0 else 0)
    assert sync_result["status"] == "complete"
    assert sync_result["chunks_updated"] == CHUNK_COUNT
    assert len(harness.user_search.merge_batches) == expected_batches
    assert len(harness.user_search.search_calls) == expected_searches
    assert all(chunk["document_tags"] == ["bills"] for chunk in harness.user_search.chunks.values())
    assert harness.sync_records() == []

    print("Large document metadata chunk sync batching test passed.")


if __name__ == "__main__":
    try:
        test_large_document_metadata_save_defers_and_batches_chunk_sync()
        success = True
    except Exception as exc:
        print(f"Test failed: {exc}")
        traceback.print_exc()
        success = False
    sys.exit(0 if success else 1)
