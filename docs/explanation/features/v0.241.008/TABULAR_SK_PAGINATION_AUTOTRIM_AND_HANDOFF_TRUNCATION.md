# Tabular SK — Pagination, Auto-Trim, Timing, and Handoff Truncation

> Branch: `feature/tabular-sk-enhancements-ui`
> Version: `0.241.008`
This document covers four related improvements to the tabular SK analysis pipeline that together allow large datasets (1 000+ rows) to be retrieved, paginated, and delivered to the outer model correctly.

---

## Overview of Changes

| # | Change | File | What it fixes |
|---|---|---|---|
| 1 | `return_columns` + `start_row` pagination params | `tabular_processing_plugin.py` | No way to page through large results or project specific columns |
| 2 | `_auto_trim_df_for_output` method | `tabular_processing_plugin.py` | Plugin returning huge payloads with no column/row budget guard |
| 3 | Elapsed time logging + 100K inner-analysis guard | `route_backend_chats.py` | No visibility into slow attempts; 20K char cap silently dropped data |
| 4 | Handoff truncation raised 24K → 100K | `route_backend_chats.py` | Outer LLM only saw first ~24K chars of inner LLM analysis text |

---

## Change 1 — Pagination and Column Projection (`return_columns`, `start_row`)

### Issue Without This Change

`filter_rows` and `query_tabular_data` had a hard `max_rows` cap with no way to:

- **Page through results** — if 1 000 rows matched a query and `max_rows=100`, rows 101–1 000 were silently discarded with no indication that more rows existed.
- **Project a subset of columns** — the plugin always returned every column in the DataFrame, which produced very wide JSON payloads and made it harder for the LLM to focus on the columns that matter.

The LLM had no `has_more` signal and no `next_start_row` hint, so it could not issue a follow-up call to retrieve the rest of the dataset.

### What Changed

Two new parameters were added to `filter_rows` and `query_tabular_data` (both the single-sheet path and the cross-sheet helper functions `_filter_rows_across_sheets` / `_query_tabular_data_across_sheets`):

| Parameter | Default | Purpose |
|---|---|---|
| `return_columns` | `None` | Comma-separated list of columns to include in each result row. When omitted, all columns are returned (subject to auto-trim). |
| `start_row` | `0` | Zero-based offset into the matched result set. Combined with `max_rows` to implement pagination. |

The result JSON now includes:

```json
{
  "total_matches": 1189,
  "returned_rows": 100,
  "has_more": true,
  "next_start_row": 100,
  "note": "Showing rows 0–99 of 1189 total matches. Use start_row=100 with the same query to retrieve the next page."
}
```

The inner SK system prompt was also updated with instruction **#20** telling the LLM to rerun with a higher `max_rows` or to paginate when `total_matches > returned_rows` for a full-list request.

### Files Modified

- `application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py`
  - `filter_rows` (public kernel function)
  - `query_tabular_data` (public kernel function)
  - `_filter_rows_across_sheets` (private cross-sheet helper)
  - `_query_tabular_data_across_sheets` (private cross-sheet helper)

---

## Change 2 — Auto-Trim Output (`_auto_trim_df_for_output`)

### Issue Without This Change

When `return_columns` was not specified and the matched DataFrame was wide and/or deep, the plugin could produce JSON payloads in the tens-of-megabytes range. This caused:

- Token budget exhaustion in the SK kernel context window mid-analysis.
- Very slow serialisation (noticeable in tool call latency).
- No feedback to the LLM about which columns were dropped.

### What Changed

A new private method `_auto_trim_df_for_output(df, max_chars=50_000)` was added. It is called **only when `return_columns` was not specified** (i.e., the LLM did not explicitly request particular columns).

**Phase 1 — drop heavy columns**: The method estimates the serialised length of each column (average cell length × row count). It iteratively removes the heaviest column until the estimated total output fits within `max_chars`.

**Phase 2 — truncate rows**: If the output is still over budget after all candidate columns have been considered (minimum 10 rows are always kept), rows are trimmed from the tail.

The result JSON includes the list of any auto-excluded columns so the LLM knows what was dropped:

```json
{
  "auto_excluded_columns": ["discussion", "supplemental_guidance"],
  "note": "Columns auto-excluded to stay within output budget. Use return_columns to retrieve them explicitly."
}
```

The LLM can then re-call with `return_columns=<heavy_column>` if that column is needed.

### Files Modified

- `application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py`
  - New method: `_auto_trim_df_for_output`

---

## Change 3 — Elapsed Time Logging and 100K Inner-Analysis Guard

### Issue Without This Change

**Timing**: There was no way to tell from logs how long individual analysis attempts were taking or where time was being spent across retries.

**20K truncation guard**: Inside `run_tabular_sk_analysis`, the inner LLM's response text was hard-capped at 20 000 characters before being returned as `tabular_analysis`:

```python
if len(analysis) > 20000:
    analysis = analysis[:20000] + "\n[Analysis truncated]"
```

With large result sets the inner LLM frequently produced more than 20K chars of content (e.g., a Markdown table of 1 000+ rows). The truncated text was then passed to the handoff message, compounding the data loss.

### What Changed

- **`import time`** added at the top of the tabular analysis section.
- **`_analysis_start_time = time.monotonic()`** recorded before the retry loop.
- **`_attempt_start_time`** recorded at the start of each attempt; `attempt_elapsed_seconds` logged on both success and exception paths.
- **`total_elapsed_seconds`** logged at every major exit point (success, max retries, exception).
- **20K → 100K**: The inner-analysis truncation guard was raised from `20_000` to `100_000` characters to avoid silently dropping large-result analysis text.

### Files Modified

- `application/single_app/route_backend_chats.py`
  - `run_tabular_sk_analysis`

---

## Change 4 — Handoff Truncation Raised 24K → 100K

### Issue Without This Change

This was the primary cause of the "can't display the full 1K+ rows" symptom reported in testing.

The `build_tabular_computed_results_system_message` function is responsible for packaging the inner SK agent's analysis text and injecting it into the outer LLM's context as a system message. It had a hard cap:

```python
max_handoff_chars = 24000
if len(rendered_analysis) > max_handoff_chars:
    rendered_analysis = (
        rendered_analysis[:max_handoff_chars]
        + "\n[Computed results handoff truncated for prompt budget.]"
    )
```

**Concrete example from `test_output.log`**:

- The inner SK agent called `query_tabular_data` with `return_columns=identifier,name`, `max_rows=2000`.
- The plugin returned all **1 189 rows** (`total_matches: 1189`, `returned_rows: 1189`).
- The inner LLM spent 81.5 seconds generating a Markdown table from those 1 189 rows (~65K chars).
- The 24K cap silently discarded roughly the last **63%** of those rows before they reached the outer LLM.
- The outer LLM therefore could not enumerate the full list, even though the data had been correctly retrieved.

**Why the 24K cap existed**: It was an early conservative guard to avoid blowing up the outer model's context window. In practice, modern GPT-4o / GPT-4.1 models have 128K–1M token windows, and 100K chars of analysis text (~75K tokens) is well within budget for a typical deployment.

### What Changed

```python
max_handoff_chars = 100000
if len(rendered_analysis) > max_handoff_chars:
    log_event(
        f"[Tabular SK Analysis] Handoff truncated: analysis length {len(rendered_analysis)} chars exceeds max_handoff_chars {max_handoff_chars}",
        level=logging.WARNING,
    )
    rendered_analysis = (
        rendered_analysis[:max_handoff_chars]
        + "\n[Computed results handoff truncated for prompt budget.]"
    )
```

- Cap raised from **24 000 → 100 000** characters.
- A `log_event(WARNING)` is now emitted whenever truncation does occur, so it will be visible in Application Insights.

### Files Modified

- `application/single_app/route_backend_chats.py`
  - `build_tabular_computed_results_system_message`

---

## End-to-End Impact

Without these four changes a user asking "list all NIST SP-800-53 controls" would experience:

1. The plugin returns 1 189 rows ✅
2. The inner LLM generates a full Markdown table (~65K chars) ✅
3. **The 24K handoff cap silently drops rows 300–1 189** ❌
4. The outer LLM sees only ~300 rows and tells the user the list is incomplete ❌

With these changes:

1. The plugin returns all 1 189 rows ✅
2. The inner LLM generates a full Markdown table ✅
3. The 100K handoff cap passes the full table to the outer LLM ✅
4. The outer LLM enumerates all 1 189 controls ✅

Additionally, if a user asks for only specific columns (`return_columns=identifier,name`), the payload is smaller from the start and neither the auto-trim nor the handoff cap ever triggers for typical NIST-sized files.

