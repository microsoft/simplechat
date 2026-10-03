# Orchestration File Render Permission Fix

**Version: 0.261.233**

Fixed in version: **0.261.233**, recorded in
`application/single_app/config.py`.

Issue: [#1623](https://github.com/microsoft/simplechat/issues/1623). This affects
the React V2 branch (`paullizer-react-v2-ui`) only. The causal commits are not on
`main` or `Development`.

## Issue

Chat orchestration could not create downloadable files. A request such as
"create a csv showing the states and their capitals" planned correctly, and the
compose step that prepared the rows completed. The file step then failed, and
the chat showed:

- `us_states_and_capitals.csv: could not be created.`
- `This operation could not complete.`

Production telemetry recorded the render attempt as `output_access_denied`
after about 260 ms of rendering. At the time, that code meant source access
could not be confirmed, but the source was general knowledge with no documents
involved. Since 0.261.232 the same code means access to the file's
conversation could not be confirmed.

## Root cause

Two changes combined to cause the failure. Neither caused it on its own.

1. **Container image.** The OneNote native extractor work (2026-09-26) made the
   final image stage `FROM onenote-runtime`. That stage copied the extractor
   binary to `/app/native/onenote_extractor/bin/`, which implicitly created
   `/app` owned by `root:root` with mode `0755`. The later
   `COPY --from=builder --chown=${UID}:${GID} /app /app` copies only the
   directory's contents, so `/app` itself stayed root-owned. The application
   runs as UID `65532` with `/app` as its working directory.
2. **Scratch-file location.** The shared structured file renderer
   (`functions_structured_file_renderers.py`) and the verified generated-file
   download stream (`open_generated_chat_artifact_stream` in
   `functions_simplechat_operations.py`) created their scratch files with
   `tempfile.TemporaryFile(dir='.')`, the process working directory.

Creating a scratch file in `/app` therefore raised
`PermissionError: [Errno 13]`. `output_failure()` classifies every
`PermissionError` as `output_access_denied`, and the original exception was not
logged, so the cause was hidden.

Inspection of the deployed image layers confirmed the regression:

| Image | `/app` owner | CSV render |
|---|---|---|
| `20260926-113853` (before the OneNote stage change) | `65532:65532` | Completed |
| `20260930-185829`, `20261002-145750` (after) | `0:0`, mode `0755` | `output_access_denied` |

### Affected behavior

- Every orchestration file in the structured formats (CSV, JSON, XML, YAML,
  TXT, and Markdown) failed to render.
- Office formats (DOCX, XLSX, PPTX, PDF) render in memory, but downloading any
  orchestration-generated file streams it through the same working-directory
  scratch file, so those downloads would fail as well.

## Technical details

### Files modified

| File | Change |
|---|---|
| `application/single_app/functions_temp_files.py` | New import-independent `scratch_file_dir()` helper. |
| `application/single_app/functions_structured_file_renderers.py` | The renderer's scratch file uses `scratch_file_dir()` instead of `dir='.'`. |
| `application/single_app/functions_simplechat_operations.py` | `open_generated_chat_artifact_stream` uses `scratch_file_dir()` instead of `dir="."`. |
| `application/single_app/functions_orchestration_rendering.py` | A failed render attempt records its error class names and OS error number in its diagnostics. |
| `application/single_app/Dockerfile` | The `onenote-runtime` stage is removed. The final stage builds from the pinned distroless image and copies the extractor's notices and source directly. The extractor binary is copied after the app code. |
| `docs/explanation/features/ONENOTE_INGESTION.md` | Build layout updated for the new copy location. |
| `docs/reference/logging-tags.md` | New render-attempt diagnostic fields documented. |
| `functional_tests/test_orchestration_file_render_scratch_dir.py` | New regression tests. |
| `functional_tests/test_generated_file_structured_renderers.py`, `functional_tests/test_orchestration_output_lifecycle.py` | Their stream-tracking doubles required `dir='.'`, which pinned the defect. They now require the `scratch_file_dir()` location. |
| `functional_tests/test_workflow_saved_output_artifacts.py` | Supplies `scratch_file_dir` to the download function it loads from source. |
| `functional_tests/test_v2_onenote_uploads.py` | The image-wiring test required the final stage to inherit `onenote-runtime`. It now requires the distroless base and the extractor binary, notices, licenses, and source in the final stage. |

### Scratch directory

`scratch_file_dir()` returns `/sc-temp-files` when that directory exists and the
process can write to it. The image creates `/sc-temp-files` for the runtime
user, and document uploads already use it. Otherwise the function returns
`None`, which selects the platform temp directory (`/tmp` in the image, `%TEMP%`
on Windows development machines). It never returns the working directory.

### Image layout

The `onenote-runtime` stage is removed. The final stage builds directly from
`mcr.microsoft.com/azurelinux/distroless/python:3.12`, as it did before
2026-09-26. It copies the extractor's notices and corresponding source from
`onenote-builder` to `/usr/share/simplechat/onenote-extractor/`, so the
redistribution notices are unchanged. The chowned copy from the builder stage
then creates `/app` owned by the runtime user. The extractor binary is copied
afterward to the path `functions_onenote.py` expects. The binary remains
root-owned: the application user can run it but cannot replace it.

Removing the stage also clears a false positive in the Malicious PR Security
Review. That check inspects the whole Dockerfile whenever a pull request
changes it. It requires each `FROM` to name an image with a tag or digest, so it
flagged `FROM onenote-runtime`, a build-stage name. The final `FROM` now names
the pinned image, and the check itself is unchanged.

### Render diagnostics

The `[ORCHESTRATION_EXECUTOR] A file render attempt finished.` event now also
includes, for a failed attempt:

- `error_type`: the class name of the exception that failed the attempt.
- `error_cause_type`: the class name at the end of its explicit `__cause__`
  chain, when the error was wrapped.
- `error_errno`: the first OS error number in that chain, when there is one.

Exception messages, file paths, and identifiers are never recorded. A
successful attempt does not include these fields. The user-facing
classification is unchanged. A file-system `PermissionError` still reports
`output_access_denied`, the same code as an access refusal such as losing
access to the file's conversation. Only the file-system error logs
`error_type=PermissionError` and `error_errno=13`, so the two can be told
apart.

## Validation

### Tests

`functional_tests/test_orchestration_file_render_scratch_dir.py`:

- `scratch_file_dir()` returns the dedicated directory only when it exists and
  is writable.
- No application `tempfile` call passes `dir='.'`, `dir=''`, or
  `dir=os.getcwd()`.
- A CSV file renders, commits, and downloads through the real renderer and the
  real download stream while any scratch file aimed at the working directory
  fails with `EACCES`, as it does in the container. This test fails on the
  previous code with `output_access_denied`.
- A failed render logs `PermissionError` and errno `13` without the message or
  path. A wrapped failure logs its outer class, root cause class, and errno.
- The Dockerfile's final stage builds from a pinned image rather than another
  build stage, creates `/app` only through the runtime user's chowned copy, and
  adds the extractor afterward.

Related suites that pass with the change: `test_orchestration_render_check_cadence.py`,
`test_orchestration_output_lifecycle.py`, `test_generated_file_structured_renderers.py`,
`test_workflow_saved_output_artifacts.py`, `test_orchestration_artifact_publication.py`,
`test_document_provenance_publication.py`, and `test_v2_onenote_uploads.py`.

### Deployment

Rebuild and redeploy the image. Each change would fix the failure on its own:
the code no longer writes scratch files to the working directory, and the
rebuilt image gives the runtime user ownership of `/app` again. Both are kept
so a later image-layout change cannot silently break file generation. After
deploying, a failed file render can be diagnosed from the `error_type` and
`error_errno` fields of the render-attempt event.
