# File Sync SSRF Endpoint Validation Fix

Fixed in version: **0.261.314**

Related code-scanning alerts: [1090](https://github.com/microsoft/simplechat/security/code-scanning/1090)
and [2098](https://github.com/microsoft/simplechat/security/code-scanning/2098), both
`py/partial-ssrf`.

## Issue description and root cause

Azure Files connection normalization previously required only an HTTPS scheme
and a nonempty authority. Arbitrary hosts could consequently reach the
`ShareServiceClient` constructor with the application's managed identity or a
service-principal credential. Validating a URL's syntax alone does not establish
that its destination is an approved Azure service.

The pinned `azure-storage-file-share==12.25.0` SDK currently rejects the affected
token-credential construction because it does not supply `token_intent`.
Investigation did not establish a network request or token disclosure through
that call. This incidental SDK failure is not a durable endpoint security
boundary: fixing authentication separately must not enable arbitrary destinations.
This change does not repair that authentication failure.

The OneDrive flow reported by alert 1090 already normalizes selected paths,
rejects traversal segments, and percent-encodes each segment beneath a user's
Graph drive path. The reported browse-path input cannot change the Graph origin.
No OneDrive runtime change or alert suppression is included.

## Technical details

### Files modified

- `application/single_app/functions_azure_endpoint_validation.py`
- `application/single_app/functions_file_sync.py`
- `application/single_app/config.py`
- `functional_tests/test_file_sync_ssrf_validation.py`
- [Azure Files feature documentation](../features/v0.241.127/AZURE_FILES_FILE_SYNC.md)
- [File Sync guide](../../guides/create-a-file-sync.md)

### Endpoint policy

The shared `validate_azure_file_endpoint()` validator requires the `file` service
label, a valid 3-24 character alphanumeric storage account name, and a supported
Azure Storage suffix:

| Cloud | File service hostname |
| --- | --- |
| Public | `account.file.core.windows.net` |
| US Government | `account.file.core.usgovcloudapi.net` |
| China | `account.file.core.chinacloudapi.cn` |
| Germany | `account.file.core.cloudapi.de` |

The validator rejects arbitrary hosts, IP literals, localhost, embedded
credentials, explicit ports (including 443), query strings, fragments,
parameters, unsupported suffixes, and suffix lookalikes. It reconstructs the
HTTPS origin from the validated account name and suffix rather than passing
through the submitted authority.

Service URLs, share URLs, and bare canonical hostnames remain accepted during
configuration. Share and directory components are decoded and normalized as
before. Stored account URLs are revalidated before token-credential and SDK
construction and must not contain a share or directory path.

### Impact and limitations

Existing sources using canonical Azure File service hostnames remain valid.
Private endpoints should use those same hostnames with private DNS resolution.
Custom domains, Azure Stack/custom suffixes, direct private-link hostnames, and
emulator URLs are rejected for the URL field.

Connection-string authentication remains unchanged: it uses the supplied
storage credentials, not the alerted token-credential account URL path. This
fix is not a review of all connection-string endpoints or all File Sync
providers.

OneDrive's absolute Graph pagination links and file-download redirects are not
redesigned by this fix. The regression tests address the reported browse-path
flow, not every possible Graph network interaction.

## Testing and validation

`functional_tests/test_file_sync_ssrf_validation.py` executes the production
normalization, SDK-boundary, Graph-path, and browse-dispatch functions using the
existing isolated function loader. External credentials, SDK construction,
source authorization setup, and HTTP are mocked; no Azure or Cosmos bootstrap
or live network access is required.

Coverage includes accepted endpoints for each supported cloud, decoded
share/directory paths, retained selections, hostile submitted and persisted
URLs, rejection before credential/client construction, canonical SDK inputs,
and unchanged connection-string dispatch. OneDrive tests prepare the outgoing
HTTP URL and verify the configured public/Government Graph origin and user path
are preserved for delimiter-bearing, encoded, and attacker-like browse paths;
invalid segments fail before HTTP.

The application version in `config.py` is incremented to `0.261.314`. The new
test uses a minimum-version assertion so subsequent version bumps do not break
this regression coverage.

Before the change, arbitrary HTTPS Azure Files origins passed normalization.
After the change, they fail at configuration and token-client boundaries.
OneDrive's already-protected browse behavior is unchanged.

Passing local regression tests does not establish CodeQL alert closure. A fresh
GitHub analysis must determine whether either alert remains; neither alert is
automatically dismissed.

### Local results

| Command | Result |
| --- | --- |
| `python -m pytest functional_tests\test_file_sync_ssrf_validation.py functional_tests\test_file_sync_azure_files_identity.py functional_tests\test_file_sync_azure_blob_storage.py functional_tests\test_file_sync_onedrive_personal.py -q` | 166 passed, 1 pre-existing failure |
| Same provider command with `-k "not test_file_sync_routes_do_not_disclose_exception_details"` | 166 passed, 1 deselected |
| `python -m pytest functional_tests\test_action_app_identity_endpoint_hardening.py -q -k "endpoint_allowlist or file_sync_reuses_the_shared_allowlist"` | 3 passed, 7 deselected |
| `python functional_tests\test_docs_app_surface_coverage.py` | 7 checks passed; inventory current |
| `python functional_tests\test_docs_site_quality.py` | 6 checks passed |

The pre-existing failure is
`test_file_sync_routes_do_not_disclose_exception_details`: it expects the old
`[FileSync] Request failed.` tag, while the unchanged route uses
`[FILE_SYNC] Request failed.`. The same failure occurred before the fix
(31 passed, 1 failed). No unrelated logging or test assertion was changed.
The new security regression cases all passed.
