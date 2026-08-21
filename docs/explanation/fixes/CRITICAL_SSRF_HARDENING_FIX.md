# Critical SSRF Hardening Fix - Version 0.260.029

Fixed in version: **0.260.029**

Related pull request: [#1335](https://github.com/microsoft/simplechat/pull/1335)

## Issue Description

The Development-to-Staging promotion check reported 15 critical CodeQL server-side request forgery
results. Several credentialed clients accepted an endpoint, redirect, or pagination URL derived from
settings or an authenticated request without enforcing the destination again at the network boundary.
An authenticated user or administrator with configuration access could direct some connection tests,
action calls, or discovery requests toward an unintended server.

## Root Cause Analysis

Endpoint handling was implemented independently by each integration. Some paths trimmed strings or
checked only for HTTPS, while others trusted redirects or server-returned pagination URLs. Save-time
validation did not protect older stored records, and automatic redirects could move a credentialed
request away from its original host. CodeQL also reported two fixed-origin URL builders because it did
not infer their path constraints.

## Technical Details

### Files Modified

- `application/single_app/functions_azure_endpoint_validation.py`
- `application/single_app/functions_outbound_http.py`
- Content Understanding, File Sync, action connection test, model endpoint, Key Vault, Cosmos
  throughput, public workspace, user, and document route helpers
- Focused functional tests under `functional_tests/`

### Code Changes

- Added canonical Azure service validators for Blob Storage, Azure Files, Foundry, Content
  Understanding, Azure Maps, and Key Vault.
- Revalidated destinations immediately before SDK client construction or credentialed HTTP calls so
  legacy stored settings cannot bypass current save validation.
- Added a public HTTPS policy for OpenAPI actions that rejects local, private, metadata, reserved, and
  mixed public/private DNS results; disables environment proxies; and revalidates every redirect.
- Required OpenAPI redirects to remain on the original origin before forwarding configured headers or
  authentication.
- Restricted OneDrive pagination to the configured Microsoft Graph origin. Graph download redirects
  are validated as public HTTPS and receive no Graph authorization header.
- Fully encoded directory object IDs before adding them to Microsoft Graph paths.
- Required Cosmos management paths to remain relative `/subscriptions/...` resource IDs under the
  deployment-controlled Azure Resource Manager origin.
- Centralized Key Vault URL construction around a validated vault name and trusted cloud suffix.

## Testing Approach

`functional_tests/test_outbound_http_ssrf_policy.py` covers hostile schemes, URL credentials, IP
literals, private and metadata addresses, mixed DNS answers, traversal segments, same-origin
redirects, and blocked cross-origin credential forwarding. Existing endpoint, Content Understanding,
File Sync, Enhanced Citations, Cosmos throughput, action connection, model endpoint, and route tests
cover integration behavior.

## Impact Analysis

Canonical Azure service endpoints continue to work across supported public, US Government, China,
and Germany suffixes where the integration supports those clouds. OpenAPI actions now require public
HTTPS port 443 and same-origin redirects; private-network APIs and custom ports are intentionally
rejected. Content Understanding and Foundry discovery require canonical Azure AI Foundry hosts.

The Cosmos throughput and authorized user-profile Graph results are controlled paths rather than
exploitable SSRF: both use deployment-owned service origins, percent-encoded identifiers, and explicit
relative-path or object-authorization checks. Narrow CodeQL suppressions document those reviewed
boundaries.

## Validation

- Before: configurable or server-returned destinations could reach credentialed clients without a
  shared last-boundary policy.
- After: every reported destination is canonicalized, origin-constrained, public-network validated,
  or proven to be a fixed-origin encoded path before the network call.
- The application version was updated from `0.260.028` to `0.260.029`.
