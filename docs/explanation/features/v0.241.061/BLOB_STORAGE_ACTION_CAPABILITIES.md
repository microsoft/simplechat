# Blob Storage Action Capabilities

Implemented in version: **0.241.061**

Related config update:
- `application/single_app/config.py` now reports version `0.241.061`.

## Overview

This enhancement upgrades the existing `blob_storage` action type from a hidden, mostly listing-oriented plugin into a container-scoped Blob Storage action that is usable from the workspace action modal. The action now supports capability defaults for listing container contents, reading file content, and uploading files, with Markdown as the first supported file type for read and upload operations.

## Dependencies

- `application/single_app/functions_blob_storage_operations.py`
- `application/single_app/semantic_kernel_plugins/blob_storage_plugin.py`
- `application/single_app/semantic_kernel_loader.py`
- `application/single_app/route_backend_plugins.py`
- `application/single_app/json_schema_validation.py`
- `application/single_app/semantic_kernel_plugins/plugin_health_checker.py`
- `application/single_app/static/js/plugin_modal_stepper.js`
- `application/single_app/templates/_plugin_modal.html`

## Technical Specifications

Architecture overview:
- The action remains `blob_storage`, but it is now configured as a single-container action instead of a broad account-level listing tool.
- Saved defaults live in `additionalFields` using three maps:
  - `blob_storage_capabilities`
  - `blob_storage_read_file_types`
  - `blob_storage_upload_file_types`
- The runtime plugin derives the Blob endpoint from the stored connection string when possible so the shared validation and loader flows continue to work with the existing manifest format.

Capability model:
- `list_container_contents`
- `read_file_content`
- `upload_file_to_container`

Configuration model:
- Required connection string
- Required container name
- Optional blob prefix
- Markdown-only read/upload file type toggles in this first version

Runtime behavior:
- The plugin exposes only the enabled functions in metadata and loader overlays.
- Listing returns blob names, relative paths, file types, and whether each blob is supported for read or upload.
- Read operations are limited to supported UTF-8 text files and currently expect Markdown extensions.
- Upload operations are limited to supported file types and currently write Markdown with a text/markdown content type.

## Usage Instructions

1. Create a new workspace action and choose `Blob Storage`.
2. Enter an Azure Storage connection string with access to the target container.
3. Set the container name and, if needed, a blob prefix such as `docs/markdown`.
4. Enable the default capabilities the action should expose.
5. Leave Markdown enabled for any read or upload capability you turn on.
6. Save the action and assign it to agents as needed.

## Testing And Validation

Functional coverage:
- `functional_tests/test_blob_storage_action_capabilities.py`

UI coverage:
- `ui_tests/test_workspace_blob_storage_action_modal.py`

Validation focus:
- connection-string endpoint derivation
- capability-gated plugin metadata
- modal visibility and validation rules for Blob Storage
- workspace save payload shape for container name, prefix, and file-type defaults