# Deep Research Temporal Context Fix

Fixed/Implemented in version: **0.241.116**

## Issue Description

Deep Research could plan and review strong source evidence, but time-sensitive requests such as upcoming events, speaking opportunities, interviews, deadlines, or current security topics did not receive an explicit current date. As a result, search planning and final reasoning could treat stale March or prior-year December results as still relevant to a request made on May 28, 2026.

## Root Cause Analysis

The standard Semantic Kernel chat path already loads the Time plugin when enabled, but Deep Research performs server-side query planning, Foundry web search calls, and Source Review evidence packaging outside that normal tool-call loop. Those orchestration steps sent the user request and reviewed evidence without a server-provided temporal context.

## Version Implemented

- Application version updated in `application/single_app/config.py` to `0.241.116`.

## Technical Details

### Files Modified

- `application/single_app/functions_source_review.py`
- `application/single_app/route_backend_chats.py`
- `functional_tests/test_deep_research_query_planning_and_ledger.py`
- `application/single_app/config.py`

### Code Changes Summary

- Added reusable research temporal context helpers that expose the current UTC date, time, year, and display date.
- Added current-date guidance to Deep Research query planning, deterministic fallback query variants, Source Review child-link planning, Source Review evidence system messages, Deep Research ledger metadata, and Deep Research ledger Markdown.
- Added current-date guidance to the request sent to the external Foundry web-search agent so normal Web Search and Deep Research search calls can interpret relative terms consistently.

### Testing Approach

- Updated the Deep Research functional test to validate current-date query bias for event/speaking opportunities.
- Added coverage for the web-search prompt temporal context and ledger temporal metadata.

## Impact Analysis

Deep Research and Web Search now have an explicit current-date anchor for time-sensitive requests. Current, recent, upcoming, future, deadline, event, speaking, and participation language is interpreted relative to the server date, reducing stale results being presented as actionable future opportunities.

## Validation

Run:

```bash
python -m py_compile application/single_app/functions_source_review.py application/single_app/route_backend_chats.py application/single_app/config.py functional_tests/test_deep_research_query_planning_and_ledger.py
python functional_tests/test_deep_research_query_planning_and_ledger.py
```

## Related Version Updates

- `application/single_app/config.py` was updated to version **0.241.116**.