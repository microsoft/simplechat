# File Upload and Document Ingestion Security Audit Fix

Fixed in version: **0.242.054**

## Issue Description

The file upload and document ingestion security audit found several trust-boundary gaps across external public document APIs, citation rendering, and document download headers.

External public document routes accepted `user_id` and `active_workspace_id` directly from request parameters and used them for public workspace upload, metadata update, delete, metadata extraction, and legacy upgrade operations. Citation parsing also constructed inline HTML from document-derived filenames, page/sheet labels, and citation identifiers. Enhanced citation download responses interpolated raw document filenames into `Content-Disposition` headers.

## Root Cause Analysis

The external public routes were designed for the bulk uploader service principal and did not revalidate that the submitted acting user had a manager role in the submitted public workspace before mutating documents. The citation parser produced HTML strings before browser rendering and escaped only some attribute values. Download helpers trusted stored filenames when building response headers.

## Version Implemented

Implemented in version: **0.242.054**

The application version was updated in `application/single_app/config.py` from `0.242.053` to `0.242.054` for this security fix.

## Technical Details

Files modified:

- `application/single_app/route_external_public_documents.py`
- `application/single_app/route_enhanced_citations.py`
- `application/single_app/static/js/chat/chat-citations.js`
- `application/single_app/config.py`
- `functional_tests/test_file_upload_document_ingestion_security_audit.py`

Code changes summary:

- Added a shared external public workspace context validator that requires `user_id` and `active_workspace_id`, confirms the workspace exists, verifies the acting user's public workspace role, and checks workspace status before route operations.
- Required public workspace manager roles for external upload, metadata patch, delete, metadata extraction, and legacy upgrade operations while preserving public reader behavior for list/get routes.
- Built citation anchors with DOM APIs so filenames, location labels, page/sheet labels, and citation IDs are assigned through `textContent`, `dataset`, and normalized URL properties instead of dynamic HTML attributes.
- Sanitized external citation filename URLs with the existing browser URL helper before assigning `href` values.
- Added a common enhanced citation `Content-Disposition` builder using sanitized ASCII fallbacks plus RFC 5987 `filename*` encoding.

## Testing Approach

Regression coverage was added in `functional_tests/test_file_upload_document_ingestion_security_audit.py` to validate:

- External public document route functions call the shared public workspace authorization validator.
- External mutation routes require public workspace manager roles.
- Citation HTML construction uses escaping and URL sanitization for document-derived values.
- Enhanced citation download responses use the safe `Content-Disposition` helper.
- The version bump and fix documentation exist for traceability.

## Impact Analysis

The fix preserves existing personal, group, and public workspace behavior while hardening the external bulk-upload API boundary. Public workspace reads remain available through the existing public reader role model, but document mutations now require the submitted acting user to be an Owner, Admin, or DocumentManager for the target public workspace.

Citation links continue to render and open enhanced citations, but malicious filenames, sheet names, page labels, or crafted citation IDs are assigned through inert DOM text and data properties. Downloaded files retain user-friendly names through encoded filename metadata without exposing raw control characters or header-breaking characters.

## Validation

Expected validation commands:

```powershell
python -m py_compile application/single_app/route_external_public_documents.py application/single_app/route_enhanced_citations.py application/single_app/config.py functional_tests/test_file_upload_document_ingestion_security_audit.py
node --check application/single_app/static/js/chat/chat-citations.js
python functional_tests/test_file_upload_document_ingestion_security_audit.py
python scripts/check_broken_access_control.py --full-file application/single_app/route_external_public_documents.py application/single_app/route_enhanced_citations.py
python scripts/check_xss_sinks.py --full-file application/single_app/static/js/chat/chat-citations.js application/single_app/route_enhanced_citations.py
git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check
```

Before the fix, external public document mutations could proceed from request-supplied workspace/user IDs without route-level role validation, and document-derived citation/header strings crossed into sensitive sinks with incomplete escaping. After the fix, these paths have explicit validation or sanitization at the sensitive operation boundary.