# Bitbucket repository review action

Fixed/Implemented in version: **0.261.450**.
The application version is recorded in `application/single_app/config.py`.

## Overview and dependencies

The `bitbucket` native action retrieves allowlisted repository source and
merge-base-to-target branch comparisons. It supports self-hosted Data Center
and Cloud through REST, without Git execution or repository writes. Users select
repositories and branches conversationally.

Dependencies are the existing requests/guarded HTTP transport, cryptography
Fernet, Cosmos SDK, action catalog/governance, scoped workspace identities and
Semantic Kernel. No new package, external browser asset or Azure test server
is introduced. Provider applications/tokens need repository-read access.

## Architecture and configuration

`functions_bitbucket_operations.py` owns manifest validation, branch policy,
stable repository-ID verification, provider URLs, bounded response parsing and
read-only operations. `semantic_kernel_plugins/bitbucket_plugin.py` exposes
`list_repositories`, `list_branches`, `list_tree`, `read_file` and
`compare_branches`. The current authorized action is rechecked at invocation.

An action names one HTTPS deployment/edition and up to 50 repositories, each
with stable `id`, `project`, `slug`, `name`, `branch_mode` (`fixed`/`any`) and
`default_branch`. An empty allowlist is a setup-only state: save connection
configuration, connect, discover/select repositories, then save again.

Repository access verifies that the current provider ID matches the saved ID.
Both comparison branches satisfy policy and resolve to immutable commits
before source retrieval. Fixed branch mode does not permit a different
baseline. A configured default never falls back if unavailable.

Data Center uses repository REST `/rest/api/1.0`, including context paths;
Cloud uses `https://api.bitbucket.org/2.0`. Cloud diffstat orders source first
and baseline second, unlike `git diff`. Comparisons explicitly obtain the
merge base and retrieve full bounded before/after text to generate local
patches, rather than assuming a provider's truncated patch is complete.

Pagination reconstructs requests to the same API operation. Cloud continuation
URLs must retain the origin, path and relevant filters; only their opaque page
token is carried forward. Credentials are never sent to returned arbitrary
URLs or HTTP redirects. Enterprise private addressing remains supported by
the existing destination guard; loopback/link-local/metadata targets do not.

## Authentication and storage

`functions_bitbucket_connections.py` is bootstrap-free; initialized
`functions_action_credential_runtime.py` supplies storage, current action
authorization, scoped identity hydration and secret resolution.

OAuth connections use `bitbucket_connections`, partitioned by `/user_id`.
Tokens and PKCE verifiers are encrypted with the deployment's
`BITBUCKET_TOKEN_ENCRYPTION_KEY`. That setting must contain a persistent Fernet
key from secret storage. `BITBUCKET_REDIRECT_URI` is the canonical HTTPS callback
ending in `/api/bitbucket/callback`; request Host is not its authority.

OAuth state is single-use, session/actor/action/policy-bound and expires after
600 seconds. Connections retain ETags and generation fencing. Refresh claims
are conditional, preventing concurrent replay of rotating refresh tokens.
Disconnect and newer connect flows fence older callbacks/refresh responses.
The actor/action connection has a stable storage key, so disconnect also clears
the old tokens after an author changes repository or branch policy. Restoring
the old policy cannot resurrect a disconnected connection.
An uncertain refresh is not replayed; reconnect after a failed or interrupted
claim. Local disconnect does not promise provider-side grant revocation.

Data Center uses its incoming application-link authorization-code API with
S256 PKCE and `REPO_READ`. Cloud uses its OAuth consumer confidential-client
flow. Smart-card/SSO participation occurs on Bitbucket's browser sign-in.
SimpleChat/M365 tokens, cookies and SSH keys are never forwarded.

Bearer tokens and Cloud email/API-token pairs reuse existing scoped identities.
Shared action credentials are resolved through the established secret owner;
personal token slots use the existing private credential request/continuation
services. OAuth is not represented as a copied static bearer-token identity.

## APIs and user workflows

`route_backend_bitbucket.py` registers a user-session Blueprint:

| Method and route | Purpose |
| --- | --- |
| GET `/bitbucket/connect` | Private connect/reconnect/disconnect page for authorized action users, including non-editors |
| GET `/api/bitbucket/connection` | Safe actor-local connection status and interaction CSRF token |
| POST `/api/bitbucket/connect` | Begin provider sign-in with a trusted callback |
| GET `/api/bitbucket/callback` | Consume bound state and exchange the authorization code server-side |
| POST `/api/bitbucket/disconnect` | Remove local token usability |
| POST `/api/bitbucket/discover` | Editor-only repository discovery or permitted-branch discovery |

Mutations require the shared interaction CSRF token. User IDs and ownership are
derived from the signed-in actor/current action origin, not request bodies.
Discovery requires personal ownership, current active-group management rights,
or global admin rights; it cannot expose the shared credential's wider
repository access to ordinary action users.

Classic uses `_plugin_modal.html`, the shared stepper and the local
`bitbucket-action-editor.js` module. V2 uses
`BitbucketActionConfiguration.tsx` with existing field/secret/editor components.
Both preserve selected repositories when discovery fails.

OAuth's private page uses the local `bitbucket-connection.js` asset. After
connecting, users retry the chat request. Personal token credentials instead use
the existing private Save and continue flow. No chat toolbar picker is added.

See the [Bitbucket action reference](../../reference/actions/bitbucket.md) for
setup steps, authentication choices and usage examples.

## Testing, performance and limitations

Focused coverage is in `functional_tests/test_bitbucket_action_plugin.py`,
`test_bitbucket_connections.py`, `test_bitbucket_routes.py`, and
`ui_tests/test_bitbucket_action_configuration.py`. Tests use real Fernet,
SDK-default Cosmos response doubles and production Classic/V2 components;
fresh normal/optimized processes verify real application imports without
network access. Route policy tests cover the registered authentication boundary.

Implementation validation passed 30 focused backend cases, 33 route/policy
cases, 134 dependent action/outbound regressions, and 32 Classic/Bitbucket plus
27 V2 credential UI cases. The V2 typecheck and production build passed.
Classic and V2 layouts were checked at 390- and 1440-pixel widths with local
production styles. Private token tests exercise both supported token identity
types through real SDK identity storage and rejected-token continuation.

The network-blocked SDK/core selection passed 107 cases; its inventory check
failed on 18 pre-existing module-fingerprint mismatches belonging only to
unchanged `route_backend_orchestration.py`. The full
`check_cosmos_response_boundaries.py --run-contracts` gate stops on that same
baseline drift. This change reviews its three new OAuth storage owners and
renews the seven affected identity-owner contracts without approving unrelated
orchestration entries.

Requests have connect/read timeouts of 10/30 seconds. Directory/branch pages
contain at most 50 entries; comparison pages at most 10 files. Files are bounded
to 250,000 bytes, returned line windows to 500, and provider JSON/combined patch
text to 1,000,000 bytes. Serialized comparison results also stay within that byte
budget. Comparison inputs are limited to 10,000 lines per file.
Comparison omissions and further pages remain explicit.
Exact Data Center branch matching examines at most 10 filtered pages, then
fails explicitly instead of choosing a similar branch.

Offline fixtures are not a live-provider or smart-card acceptance claim.
Validate the customer's Data Center version, SSO/proxy configuration and Cloud
consumer/scopes against authorized test repositories before rollout.
No Azure lab was deployed. SSH transport, cookie replay, forward proxy
authentication, repository indexing, pull-request operations, code execution
and posted review feedback are outside this version.

## Provider references

- [Data Center HTTP access tokens](https://confluence.atlassian.com/bitbucketserver/http-access-tokens-939515499.html)
- [Incoming application links](https://confluence.atlassian.com/bitbucketserver/configure-an-incoming-link-1108483657.html)
- [Data Center OAuth provider API](https://confluence.atlassian.com/bitbucketserver/bitbucket-oauth-2-0-provider-api-1108483661.html)
- [Cloud REST authentication](https://developer.atlassian.com/cloud/bitbucket/rest/intro/)
- [Cloud commit/diff APIs](https://developer.atlassian.com/cloud/bitbucket/rest/api-group-commits/)
