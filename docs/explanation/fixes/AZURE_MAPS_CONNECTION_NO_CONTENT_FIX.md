# Azure Maps connection no-content diagnostic fix

Fixed in version: **0.261.453**

The application version is tracked in `application/single_app/config.py`.

## Issue and root cause

The Azure Maps action's **Test connection** check reported
`The Azure Maps tile request failed (HTTP 204).` The tester requested only the
world road tile at zoom 0, x 0, y 0. Only HTTP 200 with an image content type
qualified as success; HTTP 204 fell through to a generic failure message.

HTTP 204 means the response has no content. It does not by itself establish
rejected credentials or successful map image retrieval. Microsoft's
[Get Map Tile reference](https://learn.microsoft.com/en-us/rest/api/maps/render/get-map-tile)
documents zoom 0 as supported for `microsoft.base.road`; this fix does not
assume those coordinates are invalid.

The generic diagnostic and lack of an alternate probe were reproduced locally.
The live deployment and Azure account were not accessed, so the reason for the
upstream no-content response remains unconfirmed.

## Technical changes and impact

`application/single_app/functions_action_connection_tests.py` preserves the
initial request. Only an HTTP 204 triggers a second request, at zoom 2, x 1,
y 1. Both use the same endpoint, subscription key, road tileset, and guarded
outbound request helper. The second request uses the remaining portion of the
existing 15-second request timeout budget. An exhausted budget prevents another
request.

Success still requires HTTP 200 with an image content type. Two 204 responses
produce an explicit no-content failure explaining that image retrieval could
not be verified. Other status codes do not trigger retries. Authentication,
destination-policy, non-image, and network failures retain their existing
handling and secret redaction, including when encountered on the second request.

This affects only connection diagnostics. No routes, settings, credentials,
Azure resources, browser assets, or chat tile-proxy behavior change. The shared
request timeout budget is not a hard wall-clock guarantee for DNS, connection,
and read phases of the HTTP client.

User-facing guidance is in `docs/reference/actions/azure-maps-openlayers.md`.

## Validation

`functional_tests/test_azure_maps_connection_no_content.py` exercises the real
tester with mocked outbound responses and a controlled clock. It covers:

- Immediate image success and alternate-tile success after 204.
- Distinct valid fallback coordinates and preservation of request configuration.
- Repeated 204 with explicit failure rather than false success or key rejection.
- Authentication, missing endpoint, unexpected status, and non-image failures.
- Timeout-budget exhaustion, retry timeout, missing credentials, destination
  rejection, and secret-safe messages and telemetry.

Before the fix, a synthetic 204 reproduced the reported generic error with one
probe. After the fix, a 204 followed by an image succeeds; two 204 responses
remain a failure with a specific no-content diagnostic.

Focused validation commands:

```powershell
python -m pytest .\functional_tests\test_azure_maps_connection_no_content.py .\functional_tests\test_action_connection_test_secret_redaction.py .\functional_tests\test_action_test_connection_endpoints.py -q -p no:cacheprovider
python .\functional_tests\test_docs_site_quality.py
```

Results: **18 focused tests passed** and **6/6 documentation quality checks
passed**. The existing connection-test suites emitted nine pytest warnings
because their older test functions return `True`; none failed.

Deployment followed by a live **Test connection** check is still required to
confirm tile availability for the affected Azure Maps resource. The alternate
coordinate is a second opportunity to retrieve a tile, not a guarantee of
upstream availability.
