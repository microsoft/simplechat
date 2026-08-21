# File Processing Log Cleanup

**Implemented in version:** **0.250.075**

## Overview

File Processing Log Cleanup lets administrators permanently remove accumulated file-processing logs from the Cosmos DB `file_processing` container. Admins can delete logs older than a chosen age or explicitly delete every stored log.

**Dependencies:**

- Cosmos DB `file_processing` container
- SimpleChat administrator authentication and authorization
- Bootstrap modal and toast components already included with SimpleChat

## Technical specifications

### Architecture

The feature uses an admin-only API and the existing Admin Settings Logging tab:

1. The browser validates an age and asks for confirmation in a Bootstrap modal.
2. The API validates the request again and computes a UTC cutoff when needed.
3. Cosmos DB is queried across partitions for matching `id` and `document_id` values.
4. Each selected item is deleted with a point delete using its `document_id` partition key.
5. The API returns the exact completed deletion count, and a general admin activity records the operation.

The delete-all mode is explicit. Omitting an age or entering zero never implies delete-all.

### API

`POST /api/admin/settings/file-processing-logs/cleanup`

The route requires an authenticated administrator and includes Swagger authentication metadata.

Delete logs older than an age:

```json
{
    "delete_all": false,
    "age": 30,
    "unit": "days",
    "confirmed": true
}
```

Delete all logs:

```json
{
    "delete_all": true,
    "confirmed": true
}
```

The API rejects requests unless `confirmed` is exactly `true`. Supported units are `days`, `weeks`, and `months`. A month is a fixed 30-day period. Age-based deletion is strict: only timestamps earlier than the calculated cutoff are selected.

A successful response includes `deleted_count`, `delete_all`, and the UTC `cutoff` when applicable. If Cosmos DB fails after some point deletes, the API returns an error and the number already deleted rather than reporting full success.

### Configuration

No new persistent settings are required. Cleanup controls do not alter the enabled state or auto-turnoff configuration for file-processing logging.

### File structure

- `application/single_app/functions_logging.py`: cutoff validation and Cosmos cleanup
- `application/single_app/route_frontend_admin_settings.py`: secured cleanup API and admin activity
- `application/single_app/templates/admin_settings.html`: cleanup controls and confirmation modal
- `application/single_app/static/js/admin/admin_settings.js`: validation, confirmation, API request, and feedback
- `functional_tests/test_file_processing_log_cleanup.py`: backend and authorization regression tests
- `ui_tests/test_admin_file_processing_log_cleanup.py`: static UI contract and authenticated browser workflow

## Usage

1. Open **Admin Settings** and select **Logging**.
2. Find **File Process Logging**, then scroll to **Delete stored logs**.
3. To remove old logs, enter a positive whole number, choose days, weeks, or months, and select **Delete older logs**.
4. To remove every log, select **Delete all logs**.
5. Review the deletion scope in the confirmation modal and confirm. A toast reports the exact number deleted.

Deletion is permanent and cannot be undone.

## Testing and validation

Coverage verifies:

- Days, weeks, and fixed 30-day month cutoff calculations
- Invalid and mixed-scope request rejection
- Cross-partition selection and partition-aware point deletes
- Delete-all behavior and exact counts
- Partial Cosmos failure reporting
- Required admin and Swagger route decorators
- Accessible confirmation, cancellation, payloads, success feedback, and visible errors

## Performance and limitations

- Cleanup runs synchronously and performs one point delete per selected item. Very large containers may take time and consume Cosmos DB request units.
- Age-based cleanup selects only items with a defined ISO timestamp. Delete-all also removes entries without timestamps when they have the required `id` and `document_id`.
- A failure can occur after some items have already been deleted. The response reports that partial count; deleted items are not restored.
