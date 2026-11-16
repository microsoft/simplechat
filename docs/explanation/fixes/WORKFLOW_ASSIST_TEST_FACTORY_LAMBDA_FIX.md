# Workflow Assist Test Factory Lambda Fix

Fixed in version: **0.261.344**

Related review: [PR #1775, CodeQL comment](https://github.com/microsoft/simplechat/pull/1775#discussion_r4299480714).

## Issue and Root Cause

CodeQL's `py/unnecessary-lambda` rule identified a workflow assistant test factory
that wrapped `SimpleNamespace()` in a zero-argument lambda. The wrapper did not
change arguments or the returned object.

## Technical Details

`functional_tests/test_workflow_assist_cosmos_response_contract.py` now supplies
`SimpleNamespace` directly as the mocked `get_m365_connection_service` factory.
Calling the factory still creates a fresh empty namespace. Application behavior,
authorization checks, Cosmos storage boundaries and SDK transport doubles are
unchanged.

`application/single_app/config.py` records version `0.261.344`, and the affected
functional test's version header matches it.

## Validation

The existing workflow assistant Cosmos response suite exercises real SDK point
responses, personal and group partition isolation, editor projection, and group
adapter authorization. Run it with `application\single_app` and
`functional_tests` on `PYTHONPATH`:

```powershell
python -m pytest -q -p test_support.cosmos_network_guard functional_tests\test_workflow_assist_cosmos_response_contract.py
python scripts\check_cosmos_response_boundaries.py
```

The network guard prevents these regressions from contacting external services.
The inventory check verifies that the existing reviewed storage owners and doubles
remain current; the factory cleanup does not require a new Cosmos classification.

Both commands passed: **11 tests passed** with two existing `jsonschema.RefResolver`
deprecation warnings, and the inventory reported **1,066 owners, 409 doubles and
zero review gaps**. The same 11 tests passed before the change.
