# Analyze Scope Select Fix

## Header Information

Version: 0.241.023

Fixed/Implemented in version: **0.241.070**

Updated in version: **0.241.023**

Issue description:
Document analysis failed when ordered chunk retrieval queried Azure Search with scope fields that do not exist on the active index. A personal-workspace analysis could request `group_id`, which caused Azure Search to reject the `$select` clause before any chunks were returned.

Root cause analysis:
`get_ordered_document_chunks()` used one static select list for personal, group, and public search clients. Each index only exposes its own scope identifier, so cross-scope fields in `$select` caused runtime failures.

## Technical Details

Files modified:
- `application/single_app/functions_documents.py`
- `application/single_app/config.py`
- `functional_tests/test_document_analysis_feature.py`
- `functional_tests/test_document_analysis_scope_select_fix.py`

Code changes summary:
Ordered chunk retrieval now picks the scope-specific field that exists on the active Azure Search index and fills the other scope identifiers from the resolved document record.

Impact analysis:
This fix applies to both chat and workflow analysis execution because both routes share the same ordered retrieval helper through the common analysis backend path.

## Validation

Test results:
`functional_tests/test_document_analysis_scope_select_fix.py` verifies that scope-aware select logic is present and that chat and workflow analysis still share one executor.

Before/after comparison:
Before the fix, personal analysis could fail with `Could not find a property named 'group_id' on type 'search.document'`. After the fix, the retrieval helper only selects the scope field supported by the active index.

User experience improvements:
Users can now run analysis against personal documents from chat without hitting the Azure Search `$select` error, and scheduled or manual workflows benefit from the same fix.