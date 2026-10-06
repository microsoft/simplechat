# Search Result Cache Admin Setting Fix

## Issue

V2 Admin Settings showed **Search result caching** as a bare switch under
**Knowledge › Web & Research › Web Search**. It had no description, only the label built
from its key and the raw key `enable_search_result_caching`. Administrators could not tell
what it cached, whether it should be on, or why it sat beside a setting that sends messages
to the public internet. The cache's lifetime, `search_cache_ttl_seconds`, had no control in
either admin interface.

## Root cause

The key had no field in `admin_settings_fields.py`, so the V2 surface found it through its
`enable_*` fallback scan (`buildCapabilityIndex` in `AdminSettingsPage.tsx`). That scan files
a key under the section whose id shares the most word stems with it. "search" scored one
point in both `web-search-section` and `azure-ai-search-section`. Web Search comes first in
navigation order and the first section to reach the top score keeps it, so the cache landed
in Web Search. A switch found that way can only show the key's name.

The setting caches workspace document searches against Azure AI Search, not web search. The
classic Azure AI Search card briefly offered both controls in late 2025, but the classic save
handler never stored them and they were removed, so neither key has had a working control
since.

## Fixed in version: **0.261.263**

The application version is maintained in `application/single_app/config.py`.

## Technical details

### Files modified

| File | Change |
| --- | --- |
| `application/single_app/admin_settings_fields.py` | Declares both settings in a **Search result cache** group of `azure-ai-search-section`, and records them in `V2_ONLY_FIELDS`. |
| `application/single_app/config.py` | Version 0.261.263. |
| `functional_tests/test_v2_admin_capability_placement.py` | Pins the relocation in `RELOCATED_CAPABILITIES_WITHOUT_V1_FIELD`. |
| `functional_tests/test_search_result_cache_admin_setting.py` | New. |
| `ui_tests/test_v2_admin_search_result_cache.py` | New. |
| `docs/admin/knowledge.md`, `docs/admin/scale.md`, `docs/admin/index.md` | Explain the cache with Azure AI Search, and remove the row that described it under Scale. |

### Code changes

- **Cache workspace search results** (`enable_search_result_caching`, switch, default on)
  explains that a repeated identical search reuses the earlier results and skips the query
  embedding and the semantic-ranked Azure AI Search queries. It also says what has to match
  for a cached result to be reused, that cached results are re-checked against the
  requesting user's access, and that the only reason to turn it off is to force fresh
  searches while troubleshooting relevance.
- **Cache lifetime (seconds)** (`search_cache_ttl_seconds`, default 300, 60 to 3,600) is
  shown only while caching is on. Saves are clamped to that range by the existing number
  normalizer.
- The group follows the Connection group, so the section still leads with its endpoint and
  credentials. Its description says the cache covers the searches behind grounded chat,
  agents and workflows, not web search, and that it uses Cosmos DB rather than Redis.
- Declaring the key takes it out of the fallback scan, so the Web Search row is gone.

### Default

No default changed. Caching has defaulted to on since it was introduced, in both
`functions_settings.py` and the fallback in `utils_cache.get_cache_settings()`, and it should
stay on:

- A cache hit saves an embedding call and one semantic-ranked hybrid query per workspace
  index in scope, and the semantic ranker is billed and quota-limited per query.
- A hit returns the same sources for the same question. The semantic ranker alone does not
  guarantee that.
- It is safe to reuse: the cache key includes the documents in scope with their versions and
  content screening state, and every cached result is re-authorized for the requesting user
  before it is returned.

A value an administrator explicitly saved as off is left as is.

## Validation

- `functional_tests/test_search_result_cache_admin_setting.py` checks placement and field
  order, the labels and explanations, the lifetime's bounds and visibility, that the schema
  defaults match `functions_settings.py` and `utils_cache.py`, PATCH clamping, and that no
  classic form submits either key.
- `functional_tests/test_v2_admin_capability_placement.py` fails if the switch is undeclared
  and falls back to the stem-matched guess.
- `ui_tests/test_v2_admin_search_result_cache.py` renders the built V2 page with the real
  schema. It checks that the group explains the cache with the switch on and the lifetime at
  300, that the Web Search card shows nothing of the old row, that turning caching off hides
  the lifetime and saves `false`, and that a lifetime of 5 saves as 60.

Before: a key-named switch under Web Search, and no way to change the lifetime. After: an
explained **Search result cache** group inside Azure AI Search, with the lifetime beside it.

## Known follow-ups

These existed before this change and were not altered by it:

- `invalidate_group_search_cache` and `invalidate_public_workspace_search_cache` filter on
  `CONTAINS(c.doc_scope, <id>)`, but `doc_scope` stores only the scope name. Unless the group
  call passes `document_id`, they delete nothing. Document fingerprints still keep cached
  results correct, so the cache lifetime is what bounds changes that do not alter a
  document's version.
- The `search_cache` container has no Cosmos TTL. Expired entries are deleted only when the
  same search is read again or a personal invalidation runs, so entries for searches that are
  never repeated accumulate.

Related: [Knowledge Settings in the V2 Admin Surface](../features/V2_ADMIN_KNOWLEDGE_SETTINGS.md),
[Search Result Caching](../features/v0.235.001/SEARCH_RESULT_CACHING.md).
