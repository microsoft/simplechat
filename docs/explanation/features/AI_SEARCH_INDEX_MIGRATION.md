# AI Search Index Migration

## Overview

The AI Search migration script copies every index definition and every
retrievable document from one Azure AI Search service to another. Source
indexes are discovered at runtime, so the script covers the personal, group,
public, and any additional indexes present in the source service.

Implemented in version: **0.250.079**

Console progress reporting added in version: **0.250.080**

Editable source and destination parameter defaults added in version:
**0.250.061**

Streaming document transfer, request timeouts, and paging diagnostics added in
version: **0.250.063**

Resumable JSON checkpointing added in version: **0.250.064**

Acknowledged-batch resume within active indexes added in version:
**0.250.065**

Parallel indexing batches added in version: **0.250.073**

The application version was updated in `application/single_app/config.py` for
this feature.

### Dependencies

- PowerShell 7
- The `Az.Accounts` PowerShell module when admin keys are resolved automatically
- Source and destination Azure AI Search services reachable from the machine
- Permission to list admin keys for both services, or both admin keys supplied
- Sufficient destination Search capacity for all source indexes and documents

## Technical Specifications

### Architecture

The script uses the Azure AI Search data-plane REST API to:

1. Discover all source and destination synonym maps.
2. Copy missing synonym maps in differential mode or update them in full mode.
3. Discover every source and destination index definition.
4. Create missing index definitions in differential mode or update all source
   index definitions in full mode.
5. Read documents using server-side paging and keyset paging where supported,
   streaming documents into a bounded destination batch window.
6. Upload up to eight indexing batches concurrently by default, with every
   batch bounded by document count and serialized size.

Admin keys are resolved with the stable Azure Resource Manager
`listAdminKeys` operation through `Invoke-AzRestMethod`. Keys can instead be
provided as script parameters when ARM key access is unavailable.

### Migration Modes

Differential mode is enabled by default with
`-DifferentialMigration $true`.

- Existing destination index definitions are retained.
- Documents whose key already exists in the destination are skipped.
- Missing source indexes and document keys are copied.
- Destination-only indexes and documents are never deleted.

Azure AI Search has no universal document timestamp or file-size property.
Differential comparison therefore uses each index's declared key field and does
not overwrite an existing destination document whose source content changed.

Full mode is selected with `-DifferentialMigration $false`.

- Every source index definition is created or updated in the destination.
- Every source document is uploaded, replacing a destination document with the
  same key.
- Destination-only indexes and documents are still not deleted.

### APIs

- Search data plane: `2026-04-01` by default
- Search management plane: `2025-05-01` by default
- Index list and create/update APIs
- Document search and indexing APIs
- Synonym map list and create/update APIs

### Configuration

The six source and destination identity parameters have editable placeholder
defaults at the top of the script. Replace those defaults to run the script
without arguments, or supply any of them as named parameters at invocation;
supplied values override the corresponding defaults.

The main parameters are:

- Source service name, resource group, and subscription ID
- Destination service name, resource group, and subscription ID
- `DifferentialMigration`, defaulting to `$true`
- `ShowProgress`, defaulting to `$true`
- `ProgressUpdateInterval`, defaulting to every 100 processed documents
- `BatchSize`, defaulting to 100 documents
- `MaxConcurrentBatches`, defaulting to 8 indexing requests and accepting 1-64
- `MaxBatchBytes`, defaulting to 15,000,000 bytes
- `PageSize`, defaulting to 100 documents to bound vector-heavy responses
- `MaxRetryCount`, defaulting to 5
- `RequestTimeoutSeconds`, defaulting to 300 seconds
- `SearchDnsSuffix`, configurable for sovereign Azure clouds
- `StateFilePath`, defaulting to `scripts/Migration-AISearch.state.json`
- `ResetState`, which discards an existing checkpoint after explicit operator
  selection

Leading and trailing whitespace is removed from endpoint, identity, API
version, and key parameters before validation and request construction.

### Resume State

The script checkpoints synonym maps as one resource and each index as a
separate resource. Rerunning the same command skips resources marked
`completed`. For indexes whose key field is filterable and sortable, every
fully acknowledged destination batch window records the last committed key
and cumulative counters. An index left `in_progress` by termination, or marked
`failed` after a handled error, resumes after that key in both full and
differential modes. If one parallel batch fails, the entire uncommitted window
remains behind the checkpoint. Full mode idempotently reuploads that window;
differential mode refreshes destination keys and skips batches that succeeded
before the failure.

If an index cannot support keyset paging, or its source document count changed
after checkpointing, that active index is conservatively replayed from its
beginning. Existing version 1 state files remain valid; a file created before
batch checkpointing starts gaining a `progress` object after its next
successful destination batch.

State is written atomically as JSON and bound to the source, destination, mode,
and API configuration. A mismatch requires a different `-StateFilePath` or an
explicit `-ResetState`. The file stores names, timestamps, status, attempts,
counts, the key-field name, the last committed document key, and error text,
but never Search admin keys or document content. The default state and
temporary files are ignored by Git; custom repository-local paths should be
ignored separately.

### Console Progress

Progress reporting uses two nested PowerShell progress bars:

- The overall bar reports completed indexes, total indexes, indexes remaining,
  percentage complete, and cumulative copied/skipped document counts.
- The active-index bar first reports destination-key comparison in
  differential mode, then reports source documents processed, documents
  remaining, percentage complete, copied/skipped counts, completed batches,
  and buffered documents.

The index bar refreshes after the first document, at the configured
`ProgressUpdateInterval`, at batch-window boundaries, and at completion. This
keeps large migrations visible without writing one console record for every
Search document. Azure AI Search migrates documents or chunks rather than
files, so a third per-file progress bar is not used.

Before every Search page request, the active-index bar displays the page
number, maximum page size, and request timeout. The script logs timing for the
first page, every tenth page, and the final page so a slow service response is
distinguishable from a stalled process.

Progress can be disabled for noninteractive automation:

```powershell
-ShowProgress $false
```

### Files

- `scripts/Migration-AISearch.ps1`
- `scripts/Migration-State.ps1`
- `functional_tests/test_ai_search_all_indexes_migration.py`
- `functional_tests/test_ai_search_parallel_batch_writes.py`
- `application/single_app/config.py`

## Usage

After replacing the six source and destination placeholders in the parameter
block, run a differential migration with the configured defaults:

```powershell
.\scripts\Migration-AISearch.ps1
```

Run differential migration:

```powershell
.\scripts\Migration-AISearch.ps1 `
    -SourceSearchService "source-search" `
    -SourceResourceGroup "source-rg" `
    -SourceSubscriptionId "00000000-0000-0000-0000-000000000001" `
    -DestinationSearchService "destination-search" `
    -DestinationResourceGroup "destination-rg" `
    -DestinationSubscriptionId "00000000-0000-0000-0000-000000000002"
```

Run full overwrite migration:

```powershell
.\scripts\Migration-AISearch.ps1 `
    -SourceSearchService "source-search" `
    -SourceResourceGroup "source-rg" `
    -SourceSubscriptionId "00000000-0000-0000-0000-000000000001" `
    -DestinationSearchService "destination-search" `
    -DestinationResourceGroup "destination-rg" `
    -DestinationSubscriptionId "00000000-0000-0000-0000-000000000002" `
    -DifferentialMigration $false
```

For Azure Government, set the Search DNS suffix explicitly:

```powershell
-SearchDnsSuffix "search.azure.us"
```

Tune destination indexing concurrency independently from batch size, or use a
single request for sequential troubleshooting:

```powershell
-MaxConcurrentBatches 4
-MaxConcurrentBatches 1
```

If a migration is interrupted, stop the old process and rerun the same command.
Completed indexes are skipped from JSON state, and a keyset-capable active
index resumes after its last acknowledged batch. Add `-ResetState` only when
every source index should be processed again.

## Testing and Validation

The functional test executes both modes against mocked source and destination
REST APIs. It validates multi-index discovery, missing-schema creation,
differential key skipping, full replacement uploads, and the no-delete
contract. It also validates whitespace normalization, page-by-page streaming,
request timeout propagation, and pre-request progress reporting.
It also verifies atomic, secret-free state creation and a resumed run that does
not repeat completed index writes. Dedicated parallel coverage proves that
batch requests overlap, source paging remains backpressured, transient batch
results are retried, and a partially failed window is replayed from its last
fully acknowledged checkpoint.

Run the test with:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  functional_tests\test_ai_search_all_indexes_migration.py `
  functional_tests\test_ai_search_parallel_batch_writes.py
```

### Performance Considerations

- Search indexing requests support at most 1,000 documents and 16 MB per batch.
  The script enforces both limits with configurable lower defaults. Source
  pages default to 100 documents to keep vector payloads bounded.
- Up to `MaxConcurrentBatches` serialized requests are held in one bounded
  window. Reduce concurrency when Search throttling dominates or memory is
  constrained; set it to 1 to use the sequential request path.
- Transient request and per-document failures use exponential-backoff retries.
- Requests time out after five minutes by default and timeout failures are
  retried within the configured retry limit.
- Differential mode first reads destination keys into memory for efficient
  source-key checks.
- Source indexes should not be modified during migration because Search paging
  does not provide a snapshot.

### Known Limitations

- Non-retrievable fields cannot be exported by the Search query API and are
  reported as warnings.
- Redacted secrets in source index or synonym map definitions cannot be
  recreated automatically.
- Indexes over 100,000 documents require a key field marked both `filterable`
  and `sortable`. The standard SimpleChat indexes meet this requirement.
- Data sources, indexers, skillsets, knowledge stores, and index aliases are not
  copied because they are separate Search service resources.
- The destination Search tier must support the source schema features,
  including semantic and vector search configuration.