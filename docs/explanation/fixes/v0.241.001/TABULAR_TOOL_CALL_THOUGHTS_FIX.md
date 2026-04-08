# Tabular Tool Call Thoughts Fix

## Issue Description
Tabular analysis thoughts were summarized as generic wrapper messages such as `Running tabular analysis on 1 workspace file(s)` and `Tabular analysis completed using 1 tool call(s)`. That hid which specific tabular tools actually ran, making it harder to understand whether the system queried, filtered, grouped, or only inspected the file.

**Version implemented:** 0.239.035

Fixed/Implemented in version: **0.239.035**

Related `config.py` update: `VERSION` was bumped to `0.239.035`.

## Root Cause Analysis
1. **Thoughts were recorded at the workflow level instead of the tool level**
   - The workspace and chat tabular paths emitted only start/completion wrapper thoughts.
   - Individual plugin invocations were collected for citations but not surfaced as separate tabular thoughts.
2. **Users could not see what analysis actually happened**
   - A completion message with a tool count did not reveal whether the mini-agent used `query_tabular_data`, `group_by_datetime_component`, `aggregate_column`, or other functions.
3. **The agent tool-call pattern already existed elsewhere**
   - Agent execution paths already emitted one thought per plugin invocation, but the tabular pre-analysis flow had not adopted the same level of detail.

## Technical Details
### Files Modified
- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_workspace_tabular_trigger_and_thoughts.py`

### Code Changes Summary
- Added helpers in `route_backend_chats.py` to:
  - format concise tabular tool thought content,
  - sanitize thought detail fields,
  - convert tabular plugin invocations into per-tool thought payloads.
- Replaced generic workspace and chat tabular wrapper thoughts with one `tabular_analysis` thought per tabular plugin invocation.
- Preserved failure thoughts when tabular analysis cannot compute results.
- Kept enhanced citations behavior unchanged while making the thoughts feed more transparent.

### Testing Approach
- Updated `functional_tests/test_workspace_tabular_trigger_and_thoughts.py` to verify:
  - per-tool tabular thought helpers exist,
  - workspace and streaming paths emit tool-level thought payload loops,
  - generic completion wrapper thoughts are no longer used,
  - formatted thought payloads contain useful parameters while excluding user and conversation identifiers.

## Impact Analysis
- Processing Thoughts now shows which tabular tool functions actually ran.
- Users can distinguish schema inspection, filtering, grouping, and datetime analysis directly from the thoughts timeline.
- Debugging tabular behavior is easier because the thought feed reflects the real analysis steps instead of only wrapper status messages.

## Validation
### Before
- Thoughts showed only generic tabular wrapper messages.
- Users could not tell which tabular function actually answered the question.

### After
- Thoughts include individual entries such as the exact tabular function invoked and its key parameters.
- Generic wrapper completion thoughts are replaced by specific tabular tool-call thoughts.
- Failure thoughts still appear when tabular analysis cannot compute results.

## Related Validation Assets
- Functional test: `functional_tests/test_workspace_tabular_trigger_and_thoughts.py`
- Related fix: `docs/explanation/fixes/v0.239.034/TABULAR_COMPUTED_ANALYSIS_ENFORCEMENT_FIX.md`
- Related fix: `docs/explanation/fixes/v0.239.033/TABULAR_DATETIME_COMPONENT_ANALYSIS_FIX.md`
