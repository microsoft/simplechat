# Foundry Upload Context User Scope Fix

Fixed in version: **0.241.130**

## Issue Description

Foundry workflow requests received attached image/file bytes and SimpleChat OCR/vision context, but the USPTO prior art workflow still routed to its unusable-upload branch. Azure CLI inspection of `wfresp_7ee365ebb342287100BhgOThogMbUJTVGCOV68PwP6xml1bBlr` confirmed the request contained both `input_text` and `input_file` content, while the workflow output executed `send_unusable_intake_output`.

## Root Cause Analysis

The uploaded-file OCR and vision context was present in SimpleChat's system-context portion of the prompt. Controlled Foundry probes showed that putting the same compact file description directly in user-scoped text caused the workflow to proceed past the unusable-upload branch, indicating the workflow or invoked Foundry agents were using only the user request text for intake.

## Technical Details

- Files modified: `application/single_app/foundry_agent_runtime.py`, `functional_tests/test_foundry_workflow_agent_payload.py`, `application/single_app/config.py`
- When Foundry REST file parts are attached, SimpleChat now extracts existing upload context blocks from chat history and creates a compact `Attached file searchable summary`.
- Foundry workflow payloads use a clean one-shot user message containing the compact summary and the latest user request, instead of sending the full SimpleChat role-packed `SYSTEM:`/`USER:` history text.
- Common phrases such as `file ive uploaded` are rewritten to reference the attached file summary so workflow intake agents do not branch into upload-placeholder handling.
- Normal new-Foundry Responses agents keep their multi-message payload shape, with the compact summary prepended to the latest user message when file parts are attached.

## Validation

- Azure CLI inspection confirmed the original workflow response received `input_file` with `data:image/png;base64,...` and routed to `send_unusable_intake_output`.
- Controlled Azure CLI-token REST probes showed exact SimpleChat text plus file repeated the unusable branch. A direct compact summary plus cleaned request completed the prior-art workflow and reached `send_prior_art_report`.
- A post-fix builder smoke probe confirmed the workflow payload no longer includes `SYSTEM:` role-packed text or literal `file ive uploaded` wording; the non-streaming Foundry request advanced into the longer prior-art path and returned service timeout instead of the unusable-upload branch.
- Added regression tests that verify uploaded image/file context is compacted into user-scoped Foundry workflow and new-Foundry payload text when file inputs are attached.
- Related config.py version update: `VERSION = "0.241.130"`.