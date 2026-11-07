# Group Settings Error Text Fix (v0.261.154)

## Issue

When a classic group settings save failed, the error sent to the browser was the
raw exception text:
- renaming the group, changing its download setting, or saving its logo
  returned the Cosmos DB error message when storage failed;
- an unreadable logo returned the Pillow message, which can include the
  uploaded file name and internal object details;
- a logo that decompresses to an enormous image (a decompression bomb) wasn't
  handled at all, and gave a server error.

Internal service messages don't belong in a browser, and the page showed them
to the user as they were.

Fixed in version: **0.261.154**, tracked in `application/single_app/config.py`.

## Root cause

The routes answered failures with `jsonify({"error": str(ex)})`, and the logo
route caught only `ValueError` and `OSError`. Pillow raises its decompression
bomb error as neither.

## Technical details

### The change

Each failure now gets reviewed text, with the same status as before:

| Route | Failure | Answer |
|---|---|---|
| `PATCH` and `PUT /api/groups/<group_id>` | storage | 400 "The group could not be saved. Try again." |
| `PATCH /api/groups/<group_id>/download-settings` | storage | 400 "The download settings could not be saved. Try again." |
| `POST /api/groups/<group_id>/logo` | storage | 400 "The logo could not be saved. Try again." |
| `POST /api/groups/<group_id>/logo` | any image that can't be read, including a decompression bomb | 400 "The logo image could not be read. Upload a PNG or JPEG image." |

A storage failure is logged under `[GROUP_SETTINGS]` with the error type and the
status code only. The native group settings routes use the same image text.

### Files modified

- `route_backend_groups.py`: `api_update_group`,
  `api_update_group_download_settings` and `api_upload_group_logo`.
- `docs/reference/logging-tags.md`: `[GROUP_SETTINGS]`.

### Tests

`functional_tests/test_group_settings_legacy_fixes.py`: a storage failure on each
route answers the reviewed text and logs no detail, and unreadable images (text,
a truncated PNG, a GIF and a decompression bomb) answer the reviewed image text
with no decoder or file name detail.

## Validation

- Before: a failed save showed the user a Cosmos DB or Pillow message, and a
  decompression bomb gave a server error.
- After: the user sees what went wrong in plain terms, and the detail stays out
  of the response and the logs.

## Related

- [Group Settings APIs](../features/GROUP_SETTINGS_APIS.md)
- [Group Settings Write Safety Fix](GROUP_SETTINGS_WRITE_SAFETY_FIX.md)
