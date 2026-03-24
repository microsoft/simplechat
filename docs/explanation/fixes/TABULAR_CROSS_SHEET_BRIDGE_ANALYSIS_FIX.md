# Tabular Cross-Sheet Bridge Analysis Fix

Fixed in version: **0.239.140**

## Issue Description

Grouped workbook questions could fail when the answer required combining a small reference worksheet with a larger fact worksheet.

Example pattern:
- one worksheet lists canonical entities such as solution engineers
- another worksheet contains the fact rows such as milestones
- the user asks for grouped results per entity

The prior orchestration sometimes stayed on a single worksheet, grouped a boolean or membership-style column, or fell back to schema-only language after an incomplete analytical pass.

## Root Cause

Analysis mode had strong single-sheet guidance but no generalized prompt for a reference-sheet plus fact-sheet bridge.

Two specific gaps caused the failure:
- multi-sheet analysis still established a default worksheet even when the workbook structure suggested the answer needed more than one sheet
- the prompt did not tell the model to prefer canonical entity names from a small reference sheet over boolean or membership-flag columns in a larger fact sheet

## Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_tabular_cross_sheet_bridge_analysis.py`

## Code Changes Summary

- added generalized detection for grouped cross-sheet analytical questions
- added a lightweight bridge-plan helper that infers a smaller reference worksheet and a larger fact worksheet from workbook metadata
- prevented analysis mode from setting a default sheet when that bridge plan is active
- added prompt guidance to query both sheets explicitly and avoid answering “each X” by grouping yes/no or membership-flag columns
- added regression coverage for intent detection, bridge-plan inference, and prompt guardrails

## Testing Approach

The new functional regression test validates:
- grouped cross-sheet questions remain in analysis mode rather than entity-lookup mode
- workbook metadata produces the expected reference-sheet and fact-sheet bridge plan
- the analysis prompt includes the new bridge-plan and flag-column guardrails

## Impact Analysis

This change is intentionally narrow:
- schema-summary routing is unchanged
- entity-lookup routing is unchanged
- normal single-sheet analysis still keeps the existing default-sheet behavior

The new behavior only activates when the question looks like a grouped analytical request and the workbook structure strongly suggests a small reference sheet plus a larger fact sheet.

## Validation

Expected improvement:
- grouped cross-sheet workbook questions can iterate across the relevant tabs without overfitting to a workbook-specific scenario
- the model is less likely to mistake flag columns for the requested entity dimension

Related functional test:
- `functional_tests/test_tabular_cross_sheet_bridge_analysis.py`