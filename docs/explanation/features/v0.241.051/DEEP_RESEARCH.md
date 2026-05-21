# Deep Research

Implemented in version: **0.241.051**

## Overview

Deep Research is the user-facing research mode for chat requests that need stronger web evidence. It combines bounded web-search query planning, direct URL inspection, guarded source-page review, link traversal, optional JavaScript rendering, and a persisted research ledger.

Source Review remains the internal source-inspection component. Users see Deep Research in chat; admins still keep safety and budget controls for the underlying page review engine.

## Dependencies

- Web Search / Grounding with Bing Search through the existing Foundry web-search agent for query discovery.
- Source Review for SSRF-safe page fetching, parsing, prompt-injection isolation, and evidence packets.
- Generated analysis artifacts for optional Markdown research ledger storage.
- Optional Playwright runtime support when JavaScript rendering and Load More handling are enabled.

## Technical Specifications

### Architecture

Deep Research runs in the chat backend before the final model response:

1. The current user message is used as the only outbound web-search input boundary.
2. If Web Search is active, Deep Research plans a bounded set of query variants from the current message only.
3. Each planned query is sent through the existing Foundry web-search agent within the configured query limit.
4. Search result URLs and direct user-provided URLs are collected as Source Review seeds.
5. Source Review validates every URL before fetch, blocks unsafe hosts, applies page/time/size/redirect limits, extracts evidence packets, and records skipped URLs.
6. A Deep Research ledger summarizes queries, discovered citations, reviewed pages, skipped pages, direct URL caps, Load More behavior, and coverage.
7. When enabled, the ledger is saved as a Markdown generated analysis artifact in the chat.

### API Behavior

The chat request accepts both fields for compatibility:

- `deep_research_enabled`: user-facing Deep Research toggle.
- `source_review_enabled`: existing internal compatibility flag.

The response and assistant-message metadata include:

- `source_review`: compact internal review metadata.
- `deep_research`: user-facing ledger metadata with query plan, web-search runs, coverage, and optional ledger artifact reference.

### Configuration

Admin settings include:

- Enable Deep Research for chat.
- Activation mode: user toggle only. Web Search by itself does not start Deep Research or Source Review.
- Max pages per turn.
- Max seed pages per turn.
- Max user URLs per turn.
- Max search queries per turn.
- Source traversal depth.
- Timeout, redirect, and page-size limits.
- Query planning toggle.
- Ledger artifact toggle.
- Source link planning toggle.
- JavaScript rendering and Load More click cap.
- robots.txt, domain allow/block, and user allow/block controls.

Hard limits remain server-side and cannot be exceeded by admin settings.

## Usage Instructions

In chat, the Deep Research button appears only when:

- Web Search is active, or
- The prompt contains at least one direct `http://` or `https://` URL.

When selected, the chat request runs Deep Research before the final answer. If direct URLs exceed the configured cap, the first configured number of URLs are reviewed and the omitted count is recorded in the ledger.

## Testing and Validation

Coverage added in this version:

- Functional test for Deep Research config clamping, direct URL caps, query planning, and ledger Markdown generation.
- Admin UI test updates for Deep Research controls and new budgets.
- Chat UI test for Deep Research button visibility when Web Search is active or prompt URLs are present.

Validation should include Python compilation, JavaScript syntax checks, focused functional tests, and focused UI tests when a runnable authenticated environment is available.

## Known Limitations

- Web-search query planning is bounded and current-message-only; it does not use conversation history.
- JavaScript rendering depends on Playwright availability in the app host.
- Ledger artifact creation is inline with the chat turn so the final answer can use the same reviewed evidence; the artifact uses the existing generated analysis artifact pipeline rather than a separate long-running queue.
