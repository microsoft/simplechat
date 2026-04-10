# MSGRAPH_INCREMENTAL_CONSENT_FLOW_FIX.md

## Microsoft Graph Incremental Consent Flow Fix (v0.239.175)

Fixed/Implemented in version: **0.239.175**

### Issue Description

Microsoft Graph plugin calls could incorrectly tell users to grant permissions again even when the
authentication app registration already had the delegated permissions granted. The plugin auth flow
also lost the plugin-requested scopes during the `/getAToken` callback and redeemed only the base
login scope set.

### Root Cause Analysis

The shared plugin token helper treated any silent-token miss as a consent problem and always built
an interactive URL with `prompt=consent`. At the same time, the OAuth callback always redeemed
`SCOPE` from `config.py` instead of the scopes originally requested by the plugin operation.

### Technical Details

Files modified:
- `application/single_app/functions_authentication.py`
- `application/single_app/route_frontend_authentication.py`
- `application/single_app/config.py`
- `functional_tests/test_msgraph_auth_consent_flow.py`

Code changes summary:
- Added session-backed tracking for plugin-requested OAuth scopes.
- Stopped forcing `prompt=consent` for generic interactive reauthentication.
- Preserved explicit consent prompting only when Microsoft Entra returns a consent-specific error.
- Updated the `/getAToken` callback to redeem the stored plugin scopes instead of always using the
  base login scope list.

Testing approach:
- Added `functional_tests/test_msgraph_auth_consent_flow.py` to verify:
  - silent token misses return interactive auth without forced consent,
  - explicit consent errors still force `prompt=consent`,
  - the OAuth callback redeems the originally requested plugin scopes.

Impact analysis:
- Users should no longer be told to re-consent for already granted delegated Graph permissions.
- Incremental Graph plugin scopes now survive the OAuth round-trip correctly.
- The authentication app registration remains the expected delegated-auth client for Graph plugin
  operations, while managed identity continues to be unrelated to `/me` Graph calls.

### Validation

Before:
- Silent token misses were surfaced as consent requests.
- Interactive URLs always forced `prompt=consent`.
- The callback redeemed only the base login scopes and could miss plugin-specific Graph scopes.

After:
- Generic interactive sign-in requests no longer force a consent prompt.
- Consent is only forced when Microsoft Entra explicitly reports missing consent.
- The callback redeems the exact plugin-requested scopes and clears the temporary scope state.