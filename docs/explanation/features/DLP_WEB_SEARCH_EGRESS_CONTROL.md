# DLP Web Search Egress Control

## Overview

Version: 0.242.069

Dependencies: Flask chat routes, configurable regex DLP rules, and Azure AI Foundry web-search agent configuration.

SimpleChat now includes an application-level Data Loss Prevention control before web-search grounding. The app evaluates the current user message after `build_web_search_query_text(...)` and before the configured Azure AI Foundry web-search agent is invoked.

SimpleChat can inspect the `SimpleChat -> Azure AI Foundry` payload. It cannot inspect or intercept the service-side `Azure AI Foundry Agent Service -> Bing` grounding call inside Microsoft's service boundary. Blocking or redaction therefore happens before the app sends the current message to Foundry.

## Technical Specifications

The shared DLP core lives in `application/single_app/functions_dlp.py`. Configurable regex rules live in `application/single_app/functions_dlp_rules.py`.

Implemented behavior:

- Regex DLP is the only implemented engine in this release.
- Regex rules are admin-configurable through the `dlp_regex_rules` settings payload.
- Default rules detect U.S. SSNs and Luhn-valid credit card numbers.
- Rules can target web search, upload, or both.
- Rules can use keyword proximity confidence shaping. A regex match can require nearby terms such as `ssn`, `social security`, `card`, or `billing` before it reaches the configured minimum confidence.
- Generic internal phrase matching is not hardcoded. Administrators can add organization-specific phrases or identifiers as explicit custom rules.
- DLP metadata stores entity types and counts only. Raw matched values are not stored in telemetry or review summaries.
- Structured DLP telemetry uses `log_event(...)` and reaches Application Insights when `APPLICATIONINSIGHTS_CONNECTION_STRING` is configured.
- Scanner errors fail closed by default when `dlp_fail_closed_on_scanner_error` is enabled.
- Text that exceeds the configured scan limit is not partially redacted in `redact` or `block` mode. It is blocked with `scanner_status = truncated`; `monitor` mode records the truncated scanner status while preserving web search.
- The web-search route no longer falls back to the raw current message when the DLP-safe query text is empty.

Admin settings are added in Admin Settings under Data Loss Prevention:

- Shared DLP enablement, regex engine selection, configurable regex rules, maximum scan characters, scanner fail-closed behavior, telemetry, and review destination.
- Web-search DLP enablement and mode: `monitor`, `redact`, or `block`.
- Review destination defaults to `none`. Safety Violations review routing is documented as a future integration unless the review surface is expanded with distinct DLP labeling and access rules.

## Usage

1. Open Admin Settings.
2. Enable Data Loss Prevention.
3. Enable Web Search DLP.
4. Review or edit Custom Regex Rules.
5. Choose a mode:
   - `monitor`: detect and emit safe telemetry while preserving web search. Oversized text records `scanner_status = truncated`.
   - `redact`: replace detected structured identifiers before web search. Oversized text is blocked instead of partially redacted.
   - `block`: skip web search when DLP detects configured sensitive content or when text exceeds the scan limit.

User-visible status messages:

- Blocked: `Web search was blocked because the message appears to contain non-public information.`
- Redacted: `Sensitive details were removed before web search.`

These messages do not include raw values, snippets, recognizer names, scores, or policy identifiers.

## Configurable Regex Rules

The MVP DLP engine uses admin-configurable regex rules. Default rules detect U.S. Social Security numbers and Luhn-valid credit card numbers. Generic internal phrase blocking is not hardcoded; administrators can add organization-specific rules when those phrases are meaningful in their environment.

Each rule can define:

- entity type and replacement label
- allowed surfaces (`web_search`, `upload`)
- optional `luhn` validation
- keyword proximity confidence shaping
- minimum confidence required before redaction or blocking

Confidence shaping lets a regex match become stronger when nearby terms are present. For example, an employee identifier rule can require `EID-123456` plus `employee` within 32 characters before it redacts.

Regex DLP remains deterministic and dependency-light. Richer contextual PII detection for names, addresses, and natural-language identifiers remains future work.

## Telemetry

Telemetry dimensions are bounded and safe:

- `activity_type = dlp_decision`
- `dlp_surface = web_search`
- `dlp_action`
- `dlp_engine`
- `dlp_mode`
- `workspace_scope`
- `scanner_status`
- `dlp_total_replacements`
- `dlp_entity_counts`

Raw prompts, web-search queries, snippets, raw matched values, and filenames are excluded.

Example Azure Monitor alert concepts:

```kusto
customEvents
| where name has "DLP" or tostring(customDimensions.activity_type) == "dlp_decision"
| where tostring(customDimensions.dlp_surface) == "web_search"
| where tostring(customDimensions.dlp_action) == "block"
| summarize blocks=count() by bin(timestamp, 15m)
```

```kusto
customEvents
| where tostring(customDimensions.activity_type) == "dlp_decision"
| where tostring(customDimensions.scanner_status) != "ok"
| summarize scanner_errors=count() by bin(timestamp, 15m), tostring(customDimensions.dlp_engine)
```

## Review And Retention

The implemented default is `dlp_review_destination = none`; DLP findings are not written to the Safety Violations review area by default. Review summary helpers return distinct `policy_type` values such as `dlp_web_search` and counts-only entity metadata for future integration.

Telemetry retention follows the configured Application Insights workspace. This PR does not create a dedicated DLP storage container or store raw DLP matches.

## Limitations

Regex DLP is intentionally lightweight. It is useful for structured identifiers such as SSNs, Luhn-valid credit card numbers, and administrator-defined exact-format identifiers, but it is weaker for names, addresses, contextual PII, international identifiers, secrets, and noisy prose.

The app-level control cannot inspect Bing's internal grounding query after Foundry receives the request. It reduces egress risk by preventing or redacting sensitive text before the app sends the web-search message to the Foundry agent.

## Testing And Validation

Functional coverage:

- `functional_tests/test_dlp_control_plane.py`
- `functional_tests/test_dlp_regex_rules.py`
- `functional_tests/test_dlp_telemetry.py`
- `functional_tests/test_dlp_admin_settings_ui.py`
- `functional_tests/test_dlp_admin_settings_roundtrip.py`
- `functional_tests/test_dlp_review_events.py`
- `functional_tests/test_web_search_dlp_egress.py`
- `functional_tests/test_web_search_dlp_route_integration.py`

Validated with Docker Python 3.12:

- `python -m compileall application/single_app`
- The PR-specific functional tests above.

Additional review-readiness validation:

- `tools/local_dev/run_dlp_local_stack.md` documents a local Cosmos emulator smoke flow for the DLP admin UI.
- `tools/local_dev/render_dlp_admin_preview.py` renders collapsed and expanded DLP admin section previews from the real Jinja template without storing sensitive sample values.
