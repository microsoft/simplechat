# Image Proposal Inline Placement Guidance Fix

Fixed/Implemented in version: **0.241.138**

## Issue Description

Image proposal cards could appear at the end of a generated response instead of staying near the slide, paragraph, or visual suggestion they supported. The guidance also encouraged a single proposal, even when several distinct visuals would be valuable.

## Root Cause Analysis

The chat renderer preserves `simpleimage` blocks wherever the model emits them, but the system guidance was too soft about placement and still told the model to prefer one proposal with a low upper bound. That made end-of-response image cards more likely for slide-deck style answers.

## Technical Details

### Files Modified

- `application/single_app/functions_image_generation.py`
- `application/single_app/config.py`
- `functional_tests/test_image_proposal_pipeline.py`

### Code Changes Summary

- Strengthened image proposal guidance so each `simpleimage` block should be emitted inline immediately after the paragraph, bullet, slide section, or visual suggestion it supports.
- Added slide-deck-specific placement guidance to keep proposal cards inside the relevant slide section.
- Replaced the previous preference for one proposal with value-based guidance that allows zero, one, or multiple distinct image proposals.
- Bumped `config.py` version to `0.241.138`.

### Testing Approach

- Updated the image proposal pipeline functional test to verify the guidance includes inline placement and flexible count instructions.
- Verified the old “prefer one/up to four” wording is absent.

## Impact Analysis

The proposal approval workflow is unchanged. Future model responses should keep image generation cards inline with the content they support and can include as many useful proposals as the response warrants, including just one when that is enough.

## Validation

- `python -m py_compile application/single_app/functions_image_generation.py functional_tests/test_image_proposal_pipeline.py`
- `python functional_tests/test_image_proposal_pipeline.py`
- `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check`