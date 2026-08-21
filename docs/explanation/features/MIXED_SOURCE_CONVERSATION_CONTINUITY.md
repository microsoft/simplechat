# Mixed-Source Conversation Continuity

Implemented in version: **0.250.068**

GitHub issue: [#1060](https://github.com/microsoft/simplechat/issues/1060)

Parent initiative: [#1055](https://github.com/microsoft/simplechat/issues/1055)

Prerequisites: [#1056](https://github.com/microsoft/simplechat/issues/1056), [#1057](https://github.com/microsoft/simplechat/issues/1057), [#1058](https://github.com/microsoft/simplechat/issues/1058), and [#1059](https://github.com/microsoft/simplechat/issues/1059)

## Overview

Phase 5 persists a compact continuity reference for the most recent mixed-source Chat grounding. It is a reauthorization hint, never an authorization decision or evidence cache. A follow-up with no current explicit selection retains the established history fallback, which resolves a new Phase 1 authorized manifest before native narrative retrieval or tabular execution.

## Precedence And Authorization

1. Current explicit selection is authoritative and suppresses previous continuity context.
2. A no-selection follow-up first uses existing history when it is sufficient.
3. When fresh grounding is needed, only the immediately relevant compact references are considered and every source is resolved through `resolve_authorized_source_manifest(...)`.
4. Chat/Search relevance candidates remain available only under their existing bounded Phase 2 rules.

The fresh resolver rechecks personal ownership or exact approved shares, group membership, public visibility, and chat-upload conversation ownership. Missing, revoked, unsupported, or unresolved sources do not become evidence. Changed source versions and partial or failed prior coverage remain terminal state and require native execution rather than treating old evidence as current.

## Metadata Contract

The continuity record contains document ID, canonical scope identity, source role, requested order, source kind, native engine, source version, terminal status, bounded coverage flags, selection origin, action mode, and citation/artifact counts. It never includes document content, filenames, prompts, evidence summaries, blob paths, storage locators, credentials, raw configuration, or authorization snapshots.

## Rollout And Limitations

`enable_mixed_source_conversation_continuity` is default-off and is effective only with `enable_mixed_source_chat_search`. Disabling it preserves existing Phase 2 history grounding and explicit-selection behavior. This phase does not add cross-conversation sharing, many-to-many Compare, target discovery, or persisted raw-evidence reuse.

## Validation

- `functional_tests/test_mixed_source_conversation_continuity.py`
- `functional_tests/test_chat_history_grounded_follow_up_fix.py`
- Python compilation and editor diagnostics for changed modules

Related version update: `application/single_app/config.py` moved from **0.250.067** to **0.250.068**.

## Phase 6 Hardening

Version **0.250.070** preserves source version, terminal status, bounded coverage, role, and order through continuity normalization. A fresh manifest decision is now evaluated before history-only reuse, so revoked, changed, partial, failed, or truncated prior grounding forces native execution even when the history assessor would otherwise reuse an earlier answer. Chat-upload hints are filtered through fresh conversation ownership.