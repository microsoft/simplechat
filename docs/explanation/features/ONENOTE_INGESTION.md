# Native OneNote Ingestion

Implemented in version: **0.261.142** (React v2 integration)

The application version is tracked in `application/single_app/config.py`.
This branch ports the native ingestion from [#1525](https://github.com/microsoft/simplechat/pull/1525),
source commit `1db88bce120c0b59141e4aafd5e52116ef146c45` (original version
0.261.045), without merging that pull request.

## Overview

Upload a OneNote section (`.one`) or exported notebook (`.onepkg`) directly to a
personal, group, or public workspace to search its typed notes and table contents.
A notebook package remains one workspace document, with its existing sharing,
classification, revision, and deletion rules. Section paths, page titles, and
subpage context remain in the searchable chunks.

This is file ingestion, not a connection to a live OneNote notebook. Changes made
in OneNote after export require another upload. Direct chat attachments are not
part of this feature; select the destination workspace, upload there, and then
use that workspace in chat.

## Dependencies and architecture

OneNote uses a binary revision store. Notebook packages are CAB archives, not ZIP
files, and are not supported directly by Azure Document Intelligence.

SimpleChat builds a local Rust executable using `onenote_parser` and a pinned
compatibility fix at
[`d0d3330f9674f07903664329f50434d997eced8c`](https://github.com/msiemens/onenote.rs/tree/d0d3330f9674f07903664329f50434d997eced8c).
The fix handles valid revision metadata associated with copying outlines between
sections. It is not part of the published `2.0.0` release.

The Python adapter invokes this executable without a shell or inherited Azure
credentials. The extractor uses validated, in-memory package files rather than
following notebook references on the host filesystem. It does not fetch links,
run attachments, or use a conversion service. Normal embedding, indexing, and
optional metadata generation still use the application's configured Azure
services.

The complete extraction and all chunks are checked before searchable writes
begin. Missing sections, malformed input, unsupported content, unsafe package
paths, and processing-limit violations fail the upload instead of silently
publishing an incomplete notebook.

### Content and citations

Typed paragraphs and table values are extracted as text. Hidden rich-text runs
are not indexed. The processor uses the current page graph and excludes package
recycle-bin sections rather than indexing the raw revision store.

Chunks stay within a page, carry their section/page context, and use globally
unique chunk numbers within the upload. Large pages are split using the existing
TXT word target and the embedding character budget, including the context
headers. Tables are text evidence, not spreadsheet inputs to tabular tools.

The existing `number_of_pages` field continues to represent saved chunks.
`onenote_source_page_count`, `onenote_section_count`, and
`onenote_excluded_content` record the extraction's page/section counts and
excluded-content counts separately.

Citations use the existing text viewer. There is no browser-native notebook
viewer or pixel-exact OneNote layout rendering. Original-file retention and
download availability continue to follow the workspace's existing storage and
download policies; enhanced citations preserve the original upload.

### Unsupported content

Handwriting recognition, image OCR, embedded files, and embedded audio/video
ingestion are not included. Pages without typed body content retain a visible
typed title when one exists; the image, ink, or attachment itself remains
unsearchable. Pages with neither typed body text nor a visible title contribute
no chunks. A document with no searchable typed content fails with an explanatory
message rather than being marked ready.

Encrypted/password-protected files and unsupported legacy structures are
rejected. Do not remove sensitivity labels or bypass organizational export
controls to prepare an upload; use an export permitted by your organization.

## Configuration and usage

No new feature toggle, Graph permission, paid SDK, or Office installation is
required on the server. Use a current application container, or build the native
component when running from source.

1. Export the desired section as `.one`, or the notebook as `.onepkg`, using a
   format permitted by your OneNote client and organizational policy.
2. Choose the personal, group, or public workspace whose members should access
   the notes. Existing upload permissions still apply.
3. Check the configured maximum upload size. For example, a 41.7 MiB notebook
   needs a larger limit than 16 MiB; a 64 MiB setting permits that file while
   staying below the extractor's input ceiling.
4. Upload and wait for **Processing complete**. The status identifies the
   typed-text-only scope.
5. Search or ask a grounded question in the same workspace. Use the section and
   page names in the citation text to locate the original note.

### React v2 workspace uploads

Open **My workspace > Documents** (`/v2/workspace/documents`) and use **Upload**
or drop the exported file onto the document list. **Supported file types**
expands the same categorized format catalog used by the classic workspaces,
including the OneNote typed-text limitation. The picker and drop validation use
that catalog from `/api/v2/bootstrap`; they do not reuse or expand the chat
attachment allowlist. Existing upload-size limits still apply.

Group and public document management remain on the existing
`/group_workspaces` and `/public_workspaces` pages on this branch. Both use the
same native ingestion and existing authorization checks. This port does not add
new React group/public editors.

### Processing limits

The normal application upload limit is enforced in addition to these native
safety limits. Increasing the upload setting does not remove the native limits.

| Resource | Limit |
|---|---|
| Input file | 128 MiB |
| Individual expanded CAB member | 128 MiB |
| Total expanded CAB members | 256 MiB |
| CAB members | 1,024 |
| CAB compression folders / data blocks | 1,024 / 65,536 |
| Section-path/content nesting | 16 levels |
| Source pages | 10,000 |
| Saved chunks | 10,000 |
| Extracted body and title text combined | 16 MiB of UTF-8 |
| Native JSON output | 32 MiB |
| Worker memory | 1 GiB |
| Worker CPU time | 120 seconds |
| Python execution deadline | 150 seconds |

One extractor runs at a time per application worker process. Size the deployment
for its configured number of worker processes; the memory limit is not a
whole-application memory reservation. A queued extraction that cannot obtain a
slot within the deadline reports a retryable busy error.

For limit or timeout errors, export smaller sections instead of increasing
limits indiscriminately. For an incomplete notebook, re-export the source and
check for missing or unsupported sections. An unavailable-extractor error
requires correcting the native installation, not re-uploading the same file.

## Build and file layout

The Dockerfile has an `onenote-builder` stage with a pinned Rust 1.85.1 image.
The application inherits the `onenote-runtime` stage, containing the native
executable on the same Azure Linux distroless Python 3.12 base.
The React branch retains its independent `v2uibuilder` stage and copies its
fresh bundle into that final application image. Publishing the branch is not
a deployment; an existing test app needs a rebuild from this branch before it
can run the feature.

The compiler and build-time downloads are not needed during extraction.
Third-party notices and dependency sources are included under
`/usr/share/simplechat/onenote-extractor/` in the container. The parser is
MPL-2.0 licensed; retain the notices and corresponding source when redistributing
the image or native component.

For local development, install Rust and the platform's linker/build tools, then
run from the repository root:

```powershell
cargo build --release --locked --manifest-path .\application\single_app\native\onenote_extractor\Cargo.toml
```

The adapter checks the native component's `bin` and `target/release` directories.
For a different build location, set `SIMPLECHAT_ONENOTE_EXTRACTOR` to the absolute
executable path. This is trusted deployment configuration, not a browser setting.
The original upload filename is passed separately as a display-only fallback
for sections without a stored name; temporary upload filenames never become
section context. Windows builds use job-object resource limits; Linux uses a
resource-limited supervisor and worker. Other operating systems fail closed.

| File | Responsibility |
|---|---|
| `config.py` | Shared OneNote extensions and supported-type display |
| `functions_onenote.py` | Bounded child process, strict result validation, safe errors |
| `native/onenote_extractor/` | Native parsing, CAB boundary, limits, pinned dependencies |
| `functions_documents.py` | Workspace dispatch, page-aware chunks, embeddings, metadata |
| `functions_mixed_source_orchestration.py` | Narrative-source classification for analysis |
| `Dockerfile` | Native build and runtime packaging |

Existing personal, group, public, and authorized external workspace upload
endpoints use the shared processor. No new route or search-index migration is
required.

## Testing and validation

Native tests cover parsing and package safety. Python regression coverage lives
in `functional_tests/test_onenote_extractor_runtime.py` and
`functional_tests/test_onenote_workspace_ingestion.py`, including process limits,
strict output validation, page/section context, scope propagation, chunk bounds,
and safe failure behavior. Workspace supported-type rendering is covered in
`ui_tests/test_workspace_supported_file_types_modal.py`.

`functional_tests/test_onenote_native_integration.py` runs the real Python
adapter against the installed executable when
`SIMPLECHAT_ONENOTE_NATIVE_TESTS=1`. Optional private fixture paths are read from
`SIMPLECHAT_ONENOTE_SECTION_FIXTURE` and `SIMPLECHAT_ONENOTE_PACKAGE_FIXTURE`.
Expected section, page, and nonempty-page counts can be supplied through the
corresponding `SIMPLECHAT_ONENOTE_EXPECTED_*` environment variables. The packaged
Azure Linux runtime has been exercised with networking disabled. Windows has
cross-target checks, not a native runtime acceptance run.

`ui_tests/test_onenote_workspace_upload_workflow.py` covers actual modal
interaction on desktop/mobile using local assets. Its configured-application
upload/status cases require the existing UI base URL and authenticated state;
uploads are mocked and never send private notebooks to a browser service.

`functional_tests/test_v2_onenote_uploads.py` checks the shared format catalog,
existing audio/video/schema gates, adapter cold imports, and combined container
stage wiring. `ui_tests/test_v2_onenote_workspace_uploads.py` loads the real built
React SPA with synthetic API responses and files. It covers desktop/mobile and
light/dark supported-type disclosure, picker/drop validation, size limits,
missing-runtime status, older-bootstrap compatibility, and the unchanged chat
attachment boundary. These closed-API browser tests do not validate live Azure
embedding or Search services.

Real-file acceptance inputs must remain local unless explicitly approved for
redistribution. User-provided notebooks are not committed to this repository or
included in container build contexts. Constructed CAB tests supplement, rather
than replace, compatibility checks on actual OneNote exports.
