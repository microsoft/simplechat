# V2 Agents Catalogue

Implemented in version: **0.261.305**, recorded in
`application/single_app/config.py`.

Refs [#1722](https://github.com/microsoft/simplechat/issues/1722), row 1.

## Overview

The **Agents** navigation entry now opens a native V2 catalogue instead of handing
users off to the classic interface. It brings together personal agents, agents
from groups the user belongs to, and enterprise agents. Users can discover an
agent, review its details, and start a new chat without leaving V2.

Agents blocked by governance are absent, including promoted agents. The catalogue
uses the same agent-usage policy as the chat picker; it does not advertise
restricted agents or offer a request-access workflow.

### Dependencies

The page reuses the existing accessible-agent catalogue, governance checks, usage
counts, and administrator promotion settings. React Router, the shared modal,
agent icons, and the human-authored Markdown renderer come from the existing V2
application. No packages, settings keys, or third-party browser assets were added.

## Technical specifications

### API and authorization

`GET /api/v2/agents/catalog` returns `page` display configuration and an `agents`
array. It requires an authenticated application user and **Enable Agents**
(`enable_semantic_kernel`).

The server first builds the user's accessible catalogue, then checks each agent
against agent governance. Only permitted records receive usage counts and
promotion annotations. An unexpected governance or catalogue failure returns a
generic error, not unchecked agents or exception text.

An explicit field allowlist exposes identity, scope, descriptions, tags, icons,
model display labels, action labels, usage counts, and promotion metadata. It
does not expose assigned knowledge or model endpoint/provider configuration.
Instructions are included only when **Show Agent Instructions in Details** is on.
The page configuration is built from sanitized settings.

The classic `/api/agents/catalog` and `/api/agents/popular` contracts are unchanged.
The administrator's promotion picker still uses the classic catalogue, so this
user-facing governance filter does not remove promotion candidates from that
editor.

### Routes and launching

The SPA route is basename-relative `/agents`, currently served at `/v2/agents`.
Latest Features shortcuts to classic `/agents` are translated to that native
route.

**Chat** starts a new conversation with the selected agent's ID and scope. Group
links also carry that agent's own group ID, not the account's active group. The
chat page refreshes its authorized catalogue before resolving the launch. An
agent removed or revoked since browsing produces a visible error rather than a
name-based fallback. Records missing an ID or a group ID remain inspectable but
cannot be launched.

### Configuration and file structure

Both interfaces use the existing [Agents Page settings](../../admin/agents-actions.md#agents-page-customization-card):
hero title/subtitle, single or two-tone background, Markdown guidance, instruction
visibility, and Popular promotions. V2 validates the configured hexadecimal
colors and adds a dark scrim to keep hero text readable on bright backgrounds.

| File | Responsibility |
| --- | --- |
| `functions_v2_agents_catalog.py` | Governance-first payload builder and allowlist |
| `route_backend_v2.py` | Authenticated catalogue endpoint and error logging |
| `src/lib/agentCatalog.ts` | Payload parsing, Popular ranking, filtering, and launch scopes |
| `src/pages/AgentsCatalogPage.tsx` | Native browsing and load states |
| `src/components/agentsCatalog/` | Shared badges/Chat links and details modal |
| `src/components/ui/Modal.tsx` | Shared dialog header wrapping for long names |
| `src/lib/latestFeatureShortcuts.ts` | Native Agents shortcut translation |

Frontend paths in this table are relative to `application/v2_ui`.

## Usage

Open **Agents** from the navigation rail. **Popular** starts with all-time usage;
switch to **Last 30 days** to see recent usage. Promotions appear in their
configured windows and placement. They are additional to the twelve
usage-ranked, nonpromoted agents.

Choose **Personal**, **Group**, or **Enterprise** to browse a scope. Search spans
all scopes, including names, descriptions, group names, model labels, and tags.
Clearing the search restores the previous category. Selecting multiple tags
requires every selected tag; **Clear filters** removes search and tag filters.

Switch between list and card views. The browser remembers the choice using
`simplechat-agents-catalog-view`, shared with the classic catalogue. Browsing
still works when browser storage is unavailable.

Use **Details** to review the generated name, scope, type, description, model,
usage, actions, tags, and permitted instructions. Use **Chat** from a result or
its details to start a new conversation. Long names, group labels, and tags wrap
in results and details rather than widening the page on mobile.
**New agent** opens the native personal
editor when available; on Group it opens the active visible group's Agents
section, or the group workspace entry when no active group is available.

## Testing and validation

| Coverage | Test |
| --- | --- |
| Governance filtering, annotation order, allowlist, instructions, route guards/error contract | `functional_tests/test_v2_agents_catalog_endpoint.py` |
| Payload parsing, Popular windows/placement, search/tags, safe display, view mode, exact launch scope | `functional_tests/test_v2_agents_catalog.py` and `test_v2_agents_catalog_logic.ts` |
| Latest Features native Agents destination | `functional_tests/test_v2_support_menu.py` and `ui_tests/test_v2_support_menu.py` |
| Real production SPA, keyboard/modal behavior, storage, unavailable/error/retry/loading states, chat refresh, light/dark desktop/mobile overflow | `ui_tests/test_v2_agents_catalog.py` |

The UI suite reuses the Azure-capable Playwright connection fixture and falls
back to local Playwright when no Azure workspace is configured. It serves the
real, freshly built SPA with synthetic API responses and rejects unexpected
requests, including legacy page hand-offs.

### Performance and limitations

Filtering and ranking run locally over one loaded catalogue; changing categories,
tags, or the usage window does not fetch the catalogue again. This preserves the
classic aggregate-usage ranking, not a per-user recommendation system.

This change implements only row 1 of the V2 parity issue. The companion legacy
routing and **New UI only** policy in
[#1723](https://github.com/microsoft/simplechat/issues/1723) are separate work.
Restricted-agent discovery and request access remain deferred. Instruction
redaction applies to this catalogue response; the existing bootstrap contract is
not changed by this feature.
