# Group Document Projection Coordination

## Overview

Implemented in version: **0.261.130**, tracked in
`application/single_app/config.py`.

Group sharing changes and existing document writers must not race so that an
old approved access projection arrives after a revocation. A source ETag check
alone is insufficient once a remote Search or access-index write is in flight.

The coordination helper uses the existing group source record and Cosmos
conditional writes. There is no new container, global application lock, setting,
or deployment requirement.

## Source and projection boundary

`functions_group_document_projection_fence.py` accepts its storage handle from
the caller and does not import application configuration, settings, or clients.
The internal `group_document_projection_writer` marker binds document, owner
group, revision, and a unique execution token.

An ordinary group publisher can claim the source only when no other writer or
unfinished collaboration checkpoint owns it. A new collaboration claim checks
the same source record before its conditional write. Both claims use ETags, so
an overlapping loser does not publish or overwrite the winner's checkpoint.

Only the exact executing collaboration ID/token can enter its internal
projection context. It does not grant a caller read/write authorization and is
not accepted from a browser. The caller still validates its actor and operation.

Group source persistence uses conditional creation/replacement rather than an
unconditional upsert that could erase a concurrent claim. Group deletion
checks active claims and uses the source ETag. Existing personal/public source
behavior is unchanged.

## Search and access index

Group chunk, batch, video, metadata/visibility and reviewed-content publication
passes explicit source group/document/revision identity to the shared Search
writer. Under its claim, stale requested sharing entries are intersected with
the current source relationships. An archived source cannot be published as
active by an old payload. The existing Data Management migration fence still
runs before embedding preparation and Search execution.

Group access-index synchronization claims the source and builds its projection
from the fresh stored document, not an earlier caller snapshot. A missing or
changed source is not recreated by a stale publisher.

The source claim remains held through remote writes. Confirmed completion
releases it conditionally. Ambiguous transport/process outcomes retain an
uncertain claim: time passing does not prove the old publisher cannot finish.
Those outcomes require explicit reconciliation; there is no automatic timeout
that permits a competing access grant or revocation.

The marker is internal and excluded from ordinary browser document payloads.

## Files and validation

The helper is wired into `functions_documents.py`,
`functions_document_access_index.py`, and
`content_screening/publication.py`. Public projection strips the marker in
`content_screening/access.py`.

`functional_tests/test_group_document_projection_fence.py` exercises real
conditional coordination, overlapping threads/claims, stale group source CAS,
Search ACL refresh, access-index refresh, missing/revision-mismatched sources,
unknown remote outcomes, and the existing migration fence ordering. Cold
imports run in normal and optimized Python with sockets blocked.

Management/read/index tests and the affected screening intake/publication
tests protect existing behavior. Store fixtures model the actual persisted
group source and ETag condition instead of allowing an index-only phantom
source.

## Limitations

This is not a distributed transaction across Cosmos, Search, cache, and Blob
Storage. Partial and unknown outcomes remain explicit. Claims serialize
publication for one document, not unrelated documents or workspaces. No live
Azure mutation or production-scale latency benchmark is claimed.
