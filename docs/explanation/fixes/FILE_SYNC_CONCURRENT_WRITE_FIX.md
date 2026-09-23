# File Sync Concurrent Write Fix

## Issue

Fixed in version: **0.261.138**

A File Sync run could undo changes a manager made while it was running. Runs
often take minutes, because they list the remote location and ingest every
changed file. While a run was going, the outcomes were:

| What the manager did during the run | What happened when the run finished |
|---|---|
| Edited the source (name, path, filters, schedule, identity, credentials) | The edit was lost; the source reverted to how it was when the run started |
| Turned the source or its schedule off | It was turned back on, with a new next-run time |
| Deleted the source | The source was recreated and kept running on its schedule |
| Ignored a path | The path was un-ignored, so the file kept syncing |

The reverse race was narrower, but real. A manager's save could erase the result
of a run that finished while the save was being prepared. An ignore saved in the
same window as a run's item update could drop that item's new `document_id`, so
the next run would ingest the file again as a duplicate document.

This affects every File Sync interface, including the classic pages. It predates
the V2 group workspace work, which found it while planning native file-source
editing.

## Root cause

A source record and each file's item record have two writers: the manager and
the sync engine. Every write was an unconditional `upsert_item` of a copy read
earlier. Line numbers are in `functions_file_sync.py` at `cf15f048`.

- **The engine wrote the whole source from the copy it read at job start.**
  `process_file_sync_run_by_id` (2261-2271) reads the source once.
  `_update_source_after_run` (3707-3719) sets the run's status fields on that
  copy and upserts the entire document. Because an upsert creates a document
  that no longer exists, a deleted source was recreated.
- **The engine wrote each item from the copy loaded when the run started.**
  `_load_existing_items` runs before the remote listing.
  - `_touch_item` (3571-3579), `_upsert_failed_item` (3624-3658) and
    `_handle_remote_deletes` (3661-3691) upsert those copies.
  - `_upsert_synced_item` (3582-3621) also writes `"ignored": False` explicitly.
- **The manager's writes did the same.** `update_file_sync_source` (1683-1691)
  and `set_file_sync_path_ignored` (2136-2163) read the record, change it, and
  upsert it.

`next_run_at` is shared. The editor keeps it, sets it or clears it
(`_normalize_schedule`), and the engine advances it after every run. So the
engine also restored a stale schedule, and the editor restored a stale next-run
time.

## Fix

Every write now goes through `_write_with_etag_guard`:

1. It reads the stored record.
2. It applies the writer's changes to that copy.
3. It writes with `MatchConditions.IfNotModified` against the etag just read.
4. When another writer lands in between (412), it reads again and re-applies,
   up to `FILE_SYNC_WRITE_ATTEMPTS` (3) times.
5. A record that no longer exists is only created when the caller supplies a
   new record (a newly synced file). A source is never recreated.

Each writer now changes only the fields it owns:

- **The engine** writes only the run's fields onto the stored source:
  - `last_run_at`, `last_run_id`, `last_run_status`, `last_run_counts` and
    `updated_at`;
  - `schedule.next_run_at`, computed from the schedule as it is **now**: an
    interval saved mid-run applies to the next run, and a schedule turned off
    mid-run stays off.
- **The engine's item writes** record the run's results but read `ignored` from
  the stored item. An item ignored mid-run stays ignored, with status `ignored`,
  and still records the document the run produced.
- **The editor** applies its normalized fields to the stored source, so a run's
  status recorded meanwhile survives. When the schedule stays on, it keeps the
  engine's `next_run_at`.
- **Ignoring a path** changes only `ignored`, `status`, `updated_by` and
  `updated_at`, and keeps an engine update made meanwhile.

### Failure handling

| Situation | Result |
|---|---|
| A source deleted while a run was going | The run finishes as `completed`, the source stays deleted, and an info event is logged |
| A run's status write loses three attempts in a row | A warning is logged and the run keeps its real outcome. The next scheduled run starts sooner, because `next_run_at` was not advanced. Other errors writing status, such as throttling, still mark the run `failed`, as before |
| An edit to a source deleted while the edit was prepared | `LookupError`, which the File Sync routes return as **404** |
| An edit that loses three attempts in a row | `FileSyncWriteConflict`, which the routes return as **409** with "This File Sync item changed while it was being saved. Reload it and try again." |

Concurrent **edits** by two managers are still last-writer-wins, as before. This
fix only guarantees that the engine and the editor never overwrite each other's
fields. Detecting conflicting manager edits needs a revision the client sends
back, which the V2 group file-source editor adds as `config_revision`.

### Files modified

- `application/single_app/functions_file_sync.py`:
  - `_write_with_etag_guard`, `_record_item_run_result`, `FileSyncWriteConflict`
    and `FILE_SYNC_WRITE_ATTEMPTS`;
  - rewrites of `update_file_sync_source`, `set_file_sync_path_ignored`,
    `_update_source_after_run`, `_touch_item`, `_upsert_synced_item`,
    `_upsert_failed_item` and `_handle_remote_deletes`.
- `application/single_app/route_backend_file_sync.py`: `_map_exception` returns
  409 for `FileSyncWriteConflict`.

## Known limitations

- A run whose source is deleted while it is going still finishes processing
  its remaining files. It stops only when it would write the source. Any items
  and documents it creates after the delete are left behind. When the delete
  asked to remove associated files, documents created after that point are not
  removed.
- A run decides which files to process, including whether to hard-delete a
  document whose remote file is gone, from the state it loaded at the start. An
  ignore saved mid-run takes effect on the item, and from the next run on.

## Validation

`functional_tests/test_file_sync_concurrent_write_safety.py` loads the real
module against in-memory containers that enforce etag preconditions the way
Cosmos DB does: 412 on a stale etag, 404 on a missing record, and replace
never creates. It interleaves the writers deterministically:

- Runs go through `process_file_sync_run_by_id`, with the manager acting during
  the remote listing.
- Edits go through `update_file_sync_source` and its real normalizer.
- A race between a read and a write is landed exactly between them.
- The group PATCH route is exercised through Flask for 200, 409 and 404.

| Case | Before the fix |
|---|---|
| A run records its status without rewriting the source | Fails: the whole source was upserted |
| An edit made mid-run survives, and the next run uses the new interval | Fails: the edit was reverted |
| A source disabled mid-run stays disabled | Fails: it was re-enabled |
| A source deleted mid-run stays deleted, and the run is `completed` | Fails: it was recreated |
| Changed, unchanged and missing files keep an ignore saved mid-run | Fails: `ignored` became `False` |
| An ignore keeps a document the run recorded meanwhile | Fails: `document_id` was lost |
| A save keeps a run result recorded while it was prepared | Fails: `last_run_id` was erased |
| The engine retries after an edit lands between its read and write | Fails: the edit was overwritten |
| Losing every status write attempt does not fail the run | New behaviour |
| An edit racing a delete is refused and does not recreate the source | Fails: the source was recreated |
| The group route returns 200, 409 on a lasting conflict, and 404 on a raced delete | New behaviour |

All 12 cases pass on the fix. Against the original module, 11 fail, each at the
assertion naming its bug. The remaining case is the version check.

Related: [File Sync Source Delete Options](../features/FILE_SYNC_SOURCE_DELETE_OPTIONS.md).
