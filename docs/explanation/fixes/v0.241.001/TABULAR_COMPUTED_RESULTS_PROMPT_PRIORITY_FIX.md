# Tabular Computed Results Prompt Priority Fix

## Fix Title
Successful tabular tool analysis now has prompt priority over excerpt-only retrieval instructions in the final GPT response.

## Issue Description
The tabular SK pass could recover, find the correct worksheet, and compute the needed row-level values, but the outer GPT response could still answer as if those results were unavailable. In practice, the final response sometimes fell back to the search-excerpt framing and said it did not have direct access to the requested record even after the tool pass succeeded.

## Root Cause Analysis
- The retrieval augmentation prompt told the outer GPT response to answer only from retrieved excerpts and to say so when the answer was not present in those excerpts.
- The tabular-computed-results handoff was added as a separate system message later in the prompt assembly.
- That created a prompt conflict: search excerpts often contained only workbook schema context, while the successful tabular pass contained the actual computed row-level values.
- The final model could anchor on the excerpt-only instruction and ignore the later tool-backed analysis, producing a cautious but incorrect fallback-style answer.

## Version Implemented
Fixed in version: **0.239.118**

## Files Modified
| File | Change |
|------|--------|
| `application/single_app/route_backend_chats.py` | Added shared prompt helpers so retrieval augmentation explicitly allows later tool-backed results and successful tabular analysis is marked authoritative |
| `functional_tests/test_tabular_computed_results_prompt_priority.py` | Added regression coverage for the search-prompt contract and authoritative tabular handoff |
| `application/single_app/config.py` | Version bump to 0.239.118 |

## Code Changes Summary
- Replaced the repeated search augmentation prompt text with a shared helper.
- Updated the retrieval prompt so it permits and respects computed tool-backed results that appear in later system messages.
- Replaced repeated successful-tabular-analysis handoff text with a shared helper that explicitly marks those results as authoritative for calculations and row-level facts.
- Added a regression test to block reintroduction of the older excerpt-only wording.

## Testing Approach
- Added `functional_tests/test_tabular_computed_results_prompt_priority.py`.
- Planned focused validation against the prompt helpers plus existing tabular orchestration coverage.

## Impact Analysis
- Successful tabular recovery should now survive the final answer synthesis step instead of being overwritten by schema-only search guidance.
- The final GPT response should stop claiming it lacks direct access when tool-backed values are already present in the prompt.
- This fix is general for workspace and chat-upload tabular analysis paths because it updates the shared prompt handoff contract rather than a workbook-specific rule.

## Validation
- Before: a recovered tabular pass could still lead to an excerpt-only final answer.
- After: the final answer prompt treats successful tabular results as authoritative and no longer frames the answer as limited to excerpts alone.