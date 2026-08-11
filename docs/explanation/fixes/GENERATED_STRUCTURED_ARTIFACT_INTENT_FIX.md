# Generated Structured Artifact Intent Fix

Fixed in version: **0.250.154**

Related issue: **microsoft/simplechat#1031**

## Issue Description

Prompts such as `Take the content for the PDF and put it into the XML` did not follow the generated XML artifact path unless the user also used recognized terms such as `create`, `download`, `populate`, or `XML file`. The model therefore rendered XML inline even though a semantically equivalent prompt using explicit file terminology produced the expected downloadable artifact.

## Root Cause

Chat, document analysis, and workflow artifact creation each maintained separate marker lists and regular expressions. Those predicates recognized conventional export verbs but did not treat destination language such as `put into`, `place in`, or `write as` as structured output intent.

## Technical Details

### Files Modified

- `application/single_app/functions_generated_file_exports.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/functions_document_analysis.py`
- `application/single_app/functions_workflow_runner.py`
- `application/single_app/config.py`
- `functional_tests/test_generated_json_xml_exports.py`
- `docs/explanation/features/GENERATED_FILE_EXPORT_FRAMEWORK.md`

### Code Changes

- Added one shared CSV/JSON/XML artifact-format detector.
- Preserved existing explicit export phrases and CSV table intent.
- Added destination transformations including put, place, write, map, load, insert, transfer, copy, move, transform, and translate when directed into/in/to/as JSON or XML.
- Destination syntax takes precedence, so `Convert JSON to XML` selects XML and `Put the XML into JSON` selects JSON.
- Directly negated output requests and source-only XML/JSON mentions do not select artifact generation.
- Chat, Analyze, and workflow JSON/XML predicates now delegate to the shared detector.

## Scope

This change only normalizes output-format intent. It does not change source selection, document extraction, model orchestration, comparison behavior, or artifact publication mechanics.

## Validation

The regression matrix verifies legacy phrases, the reported PDF-to-XML phrase, JSON and XML destination disambiguation, negation, and source-only mentions. It executes the shared detector and the Chat, Analyze, and workflow wrappers to ensure every supported execution path makes the same decision.

## Related Version Update

`application/single_app/config.py` was incremented from **0.250.153** to **0.250.154** for this terminology normalization fix.