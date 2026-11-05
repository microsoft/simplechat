# Consolidated dependency updates (v0.261.402)

## Issue and root cause

Nine Dependabot PRs targeted `main`, while these updates need to enter through
`paullizer-react-v2-ui` and subsequently follow its promotion through Development
to main. A replacement PR collects the updates without bypassing that branch flow.
Closing an original PR as superseded does not mean its change has merged into main.

The proposed PyJWT upgrade also conflicts with the feature branch's
`redis-entraid==1.2.1`, which requires `PyJWT~=2.13.0`. Merely copying the Dependabot
pins would leave the combined application requirements uninstallable.

## Fixed in version: **0.261.402**

`application/single_app/config.py` increments the application patch segment from
`0.261.401` to `0.261.402`.

## Technical details

| Original PR | Included update |
| --- | --- |
| #1866 | pypdf 6.16.1 to 6.21.4 |
| #1863 | SHA-pinned setup-python 7.1.0, setup-node 7.1.0, upload-artifact 7.0.2, checkout 7.0.1, and CodeQL 4.39.1 in the eight original workflows |
| #1862 | AnyIO 4.10.0 to 4.14.2 |
| #1829 | Pillow 12.3.0 to 13.0.0 |
| #1792 | snowflake-connector-python[pandas] 3.18.1 to 4.7.3 |
| #1791 | aiohttp 3.14.3 to 3.14.4 |
| #1782 | Development-only MCP SDK 1.28.1 to 1.30.0 |
| #1758 | Werkzeug 3.1.6 to 3.1.9 |
| #1599 | PyJWT 2.13.0 to 2.15.0 |

The Python changes are in `application/single_app/requirements.txt` and
`requirements-dev.txt`. The directly coupled `redis-entraid` patch upgrade to
1.2.2 explicitly permits `PyJWT>=2.15.0,<3`; Redis, MSAL, and Azure Identity pins
remain unchanged. No deployment configuration or user-facing setting is added.

The previous AnyIO pin protected App Service installations where an agent's
`typing_extensions` lacks `sentinel`. AnyIO 4.14.2 no longer imports that symbol.
The regression test removes it from the real module in a fresh process, then
imports the real AnyIO, OpenAI, MCP, and Semantic Kernel MCP integrations and
executes task groups, thread dispatch, and an HTTPX-mocked OpenAI completion.
This is checked with both normal and optimized Python. It does not claim
compatibility with arbitrary incompatible versions of agent-supplied packages.

## Testing and impact

`functional_tests/test_dependency_upgrade_compatibility.py` covers the historical
AnyIO import failure, PyJWT signature/audience validation and Redis token identity
extraction, Redis Entra package constraints, and real PNG/JPEG logo and ICO
conversion. Renamed GIF input must still fail the shared image-decoding allowlist.
The tests use isolated subprocesses rather than leaving mocked modules in the
pytest process.

Local validation passed 54 focused pytest cases and all five standalone
Snowflake action checks on Python 3.12 in a virtual environment without inherited
system packages. The combined application/development requirements installed
successfully, and `python -m pip check` reported no broken requirements.
The three route-policy scripts passed
28 checks, and documentation coverage and site quality passed 13 checks.
All eight changed workflow files parsed successfully; their 21 relevant action
references match the expected immutable SHAs, verified against upstream tags
(including the dereferenced CodeQL release tag). All nine upgraded Python
packages, including the supporting Redis Entra patch, meet the repository's
seven-day release-age requirement.

Existing focused tests cover PDF assembly and extraction, Snowflake action
configuration and read-only query handling, session merging, Redis token
providers, and MCP argument handling. Live Azure App Service, Redis, and
Snowflake authentication require deployment credentials and are not represented
by offline checks. The replacement PR records the exact validation commands,
results, and any environment limitations.

Before this change, the dependency updates were split across main-targeting PRs
and the combined PyJWT/Redis Entra pins conflicted. After this change, all nine
updates are represented together against the feature branch, with the necessary
Redis Entra compatibility patch and regression coverage.
