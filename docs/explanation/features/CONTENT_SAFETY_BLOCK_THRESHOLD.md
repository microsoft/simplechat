# Content Safety Block Threshold

Implemented in version: **0.261.059**

## Overview

The Content Safety block thresholds let administrators choose per-category Azure AI Content Safety prompt severities that block a chat request and record a safety violation. The setting is useful when deployments need different safety postures: a youth-focused chatbot can block lower-severity prompts for one or more harm categories, while investigative or operational teams can allow higher-severity prompts that are expected in their work.

## Dependencies

- Azure AI Content Safety must be enabled in Admin Settings.
- The Content Safety endpoint must be configured directly or through Azure API Management.
- Safety violation logging uses the existing Cosmos DB settings and safety containers.

## Technical specifications

### Architecture

- The admin setting is stored in the Cosmos DB settings document as `content_safety_category_thresholds`.
- The default threshold is `4` (Medium) for each category, preserving the previous block behavior.
- Supported categories are Violence, Hate, Sexual, and Self-harm.
- Accepted threshold values are `2` (Low), `4` (Medium), and `6` (High).
- Chat requests are blocked and recorded when any returned Content Safety category severity is greater than or equal to that category's configured threshold.
- Blocklist matches continue to block independently of category thresholds.
- Higher threshold levels do not override model deployment guardrails.

### Files

- `application/single_app/functions_content_safety.py`
- `application/single_app/functions_settings.py`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/templates/admin/_panes/content-safety.html`
- `application/single_app/static/js/admin/admin_settings.js`

## Usage instructions

1. Open Admin Settings and select the Content Safety tab.
2. Enable Content Safety and configure the endpoint or APIM route.
3. Set the **Prompt Category Block Thresholds** for Violence, Hate, Sexual, and Self-harm.
4. Save settings.

Threshold meanings:

| Label | Value | Behavior |
| --- | --- | --- |
| Low | `2` | Block Low, Medium and High |
| Medium | `4` | Allow Low / Block Medium and High |
| High | `6` | Allow Low and Medium / Block High |

A lower value blocks more prompts. A higher value blocks only more severe prompts for that category.

## Testing and validation

- `functional_tests/test_content_safety_violation_message.py` validates threshold normalization and admin-template coverage.
- `ui_tests/test_admin_content_safety_threshold_ui.py` validates the category sliders and live label/help-text wiring.

## Known limitations

The threshold applies to prompt checks in the existing chat Content Safety flow. It does not change blocklist behavior, which always blocks when Azure Content Safety reports a configured blocklist match.
