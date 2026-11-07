# Group Agent API Assertion Execution Fix (v0.261.422)

Fixed in version: **0.261.422**, recorded in
`application/single_app/config.py`.

Tracking item: [PR #1903](https://github.com/microsoft/simplechat/pull/1903).

## Issue and root cause

[CodeQL run 128260505956](https://github.com/microsoft/simplechat/runs/128260505956),
which analyzed head `9ee327ea0d0e9cd196dff79245d3028abd525039`, reports six
`py/side-effect-in-assert` findings in `test_group_agent_apis.py`.
The test file does not exist on the actual Development base
`f4e186401b58e284ee9b626aa84c903f69ea100b`, so this cluster is PR-caused,
not an infrastructure failure or a Development-baseline finding.

Python's `-O` mode removes an entire `assert` expression, including HTTP
requests inside it. A real-harness reproduction passed normally but failed in
optimized Python because the DELETE request never executed and its activity
callback was never called. The same test module contained 37 HTTP requests in
assertions, including reads and denied writes.

## Technical changes

- `functional_tests/test_group_agent_apis.py` executes each request before
  checking its captured response. All 153 assertions, expected comparisons,
  HTTP methods, and request arguments are retained.
- `functional_tests/test_group_agent_assertion_execution.py` checks the whole
  module for requests embedded in assertions. It also runs the real contract
  module and its existing isolated backend harness in fresh normal and
  optimized Python processes.
- Each subprocess exercises 12 scenarios and explicitly checks 49
  request-method/status pairs. These checks use explicit failures rather than
  assertions, so optimization cannot remove the regression's own validation.

The probe covers unavailable group statuses, global-agent write refusal,
availability flags, governance denial, successful deletion and activity
logging, refused writes, stale revisions, missing records, and invalid options
requests. The existing harness prohibits live network calls and restores its
module patches between scenarios.

No production route, authorization rule, storage owner, Cosmos double, CI
configuration, or CodeQL query is changed. The earlier dependency pins, Unicode
fixture fix, and published review-comment batch are preserved.

## Validation

Before the fix, the new regression selection reported two failures and one
pass: the static check found all 37 embedded requests, and the optimized probe
observed only PATCH where POST, PATCH, and DELETE were required. After the fix,
the targeted group-agent, optimization, and preserved static-security selection
passes all 97 tests.

```powershell
python -m pytest -q .\functional_tests\test_group_agent_apis.py .\functional_tests\test_group_agent_assertion_execution.py .\functional_tests\test_v2_static_security_fix.py --tb=short
python .\functional_tests\test_group_agent_assertion_execution.py --probe
python -O .\functional_tests\test_group_agent_assertion_execution.py --probe
node .\functional_tests\test_v2_content_screening_logic.mjs
```

The unchanged screening fixture still passes all 30 Node checks. An AST
before/after comparison confirms that every HTTP request and all 153 original
assertions and expected comparisons remain present. Changed Python sources
compile without importing application configuration.

| Local verification | Result |
| --- | --- |
| Group API, fresh-process optimization, and preserved static-security selection | 97 passed |
| Direct normal and optimized probes | 12 scenarios and 49 request/status checks passed in each mode |
| Screening runtime selection | 30 checks passed |
| Unchanged static-security checker on the two changed test files | Zero blockers |
| Cosmos boundary inventory guard | 1,094 owners, 425 doubles, zero review gaps |
| Documentation coverage, quality, and release integrity selection | 14 passed; 14 existing return-value warnings |
| Generated release pages | In sync |
| Changed-source Python compilation and Git whitespace check | Passed |

## Remaining review

The supplied run remains a historical failed check on its original head.
A newer pushed head must receive its own analysis; resolving this cluster does
not imply that CodeQL's broader mixed findings have been cleared.

Development-baseline critical alerts, other PR-introduced findings, and
unproven modelling findings remain separately classified for human review.
The broader V2 empty-draft recovery failures documented in
[the integration fix](REACT_V2_DEVELOPMENT_INTEGRATION_FIX.md) also remain
unresolved. No alerts are dismissed or suppressed, and no merge is performed.
