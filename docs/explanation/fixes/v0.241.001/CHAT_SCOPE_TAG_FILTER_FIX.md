# CHAT SCOPE TAG FILTER FIX

Fixed/Implemented in version: **0.240.029**

## Header Information

- Issue description: Chat retrieval could return chunks from documents outside the selected tag scope when the chat scope was limited to personal, group, or public workspaces.
- Root cause analysis: `hybrid_search()` only appended the tag OData clause in the `all` scope branch, while the dedicated `personal`, `group`, and `public` branches ignored `tags_filter` entirely.
- Version implemented: 0.240.029

## Technical Details

- Files modified: `application/single_app/functions_search.py`, `application/single_app/config.py`, `functional_tests/test_chat_scope_tag_filter_fix.py`
- Code changes summary: Added tag-clause composition to the personal, group, and public `hybrid_search()` branches and aligned their selected Azure AI Search fields to include `document_tags` consistently.
- Testing approach: Added a focused functional regression test that inspects the scoped `hybrid_search()` branches and verifies the version bump.
- Impact analysis: Chat requests that rely on tag selection now constrain retrieval consistently across personal, group, public, and all-scope searches.

## Validation

- Test results: Targeted functional regression test verifies the tag filter clause is present in every scoped search branch.
- Before/after comparison: Before the fix, tag selection only constrained `all`-scope hybrid search; after the fix, every chat document scope applies the same tag enforcement.
- User experience improvements: Asking for document summaries while a tag is selected now stays within the tagged subset instead of pulling unrelated documents from the same workspace.