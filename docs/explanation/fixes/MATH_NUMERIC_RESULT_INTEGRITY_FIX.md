# Math numeric-result integrity fix

Fixed/Implemented in version: **0.261.380**

Related version update: `application/single_app/config.py`.

## Issue and root cause

A request to add `1e308` and `1e308` could receive an answer claiming infinity,
even though the mathematical sum is the finite number `2e308`.

SimpleChat inherited Semantic Kernel's binary-float Add and Subtract
implementations. Its other Math operations used the same float parser. Addition,
subtraction, multiplication and division could silently return non-finite
machine values; large integer inputs could lose digits before arithmetic.
Power could instead throw overflow or return a complex value despite the
real-number tool contract.

The invocation wrapper treated any normal return as success, including infinity.
The model received that result, but the existing JSON serializer converted it to
`null` when building saved tool evidence. The invocation still reported success
with no error, so the model and the stored citation disagreed.

## Product changes

`application/single_app/semantic_kernel_plugins/math_plugin.py` now implements all
seven operations with a shared, isolated decimal context. Inputs have bounded
length, precision and exponents; powers also have a bounded exponent. Results
are finite decimal/scientific-notation text. Rounded results explicitly identify
their approximation and 64-digit half-even precision. No result is converted
back to binary float.

Malformed, non-finite and unsupported inputs fail with stable safe errors.
Real-domain and calculation-limit errors remain failures, not invented answers.
Negative-operand modulus retains the previous divisor-sign semantics. The
calculator does not provide unbounded precision or evaluate arbitrary code.

`application/single_app/semantic_kernel_plugins/plugin_invocation_logger.py`
validates raw float and Decimal results, including values nested in standard
dictionaries, lists, tuples, sets and frozen sets, before emitting success.
Synchronous functions, async functions and sync functions returning awaitables
use the same check. An invalid result raises a safe numeric-result error and
records a failed invocation with no successful result.

This validation does not parse strings or interpret business fields called
`success`, `error` or `status_code`. Existing connector-declared failures and
cancellation behavior remain intact. The check does not retry tools or change
which connector an agent chooses.

The existing citation builder and JSON serializer are unchanged. Valid decimal
text survives them intact; invalid raw numeric output reaches the existing
failure path before a success can be recorded.

## Compatibility and impact

Math tool names and parameter names are unchanged. **Math result values changed
from floats to strings.** Direct consumers must handle the textual result
contract, including the explicit qualifier on approximate answers, rather than
assuming numeric JSON. Unrelated tools retain their result shapes.

The shared guard intentionally turns a logged tool's raw non-finite numeric
output into failure. A textual reference to `"Infinity"` or `"NaN"` remains
ordinary data. This is a numeric-integrity check, not general validation of every
possible custom object a plugin might return.

The initial failure report was a UI-driven end-to-end test whose intended MCP
operation differed from the built-in Math call actually observed. Harness
findings are tracked separately, outside this product fix. This change neither
forces MCP selection nor relies on an overflowing calculation as a synthetic
connector-failure mechanism.

## Testing and validation

`functional_tests/test_math_numeric_integrity.py` exercises real Math and logging
modules in fresh offline processes, in normal and optimized Python. It covers:

- All seven operations, finite large results and large integer precision.
- Numeric text, integer and float inputs; input, precision, exponent and power
  limits; invalid input and real-domain errors.
- Explicit rounding, half-even ties, negative modulus and decimal-context
  isolation across concurrent tasks.
- Scalar and nested non-finite output for sync, async and awaitable functions;
  one start/completion identity pair and preservation of valid business data.
- Real Semantic Kernel tool registration and function-result history, followed
  by successful execution after a domain error and an invalid tool result.
- Agreement between model-visible outcomes, reasoning, citations and saved
  citation artifacts, including strict JSON encoding.

`functional_tests/test_logged_core_plugins.py` checks the updated Math result
contract and reasoning using a portable fresh-process offline bootstrap.
`functional_tests/test_plugin_invocation_outcomes.py` covers connector-declared
outcomes, concurrent/nested calls, deferred errors and cancellation.

The focused validation uses the repository-pinned Semantic Kernel 1.39.4 and
OpenAI 1.109.1 in an isolated test environment, not the older globally installed
SDK. No external model or cloud data mutation is needed for these regressions.

Validation completed with the pinned-dependency Python environment:

| Command | Result |
|---|---|
| `python -B -m pytest .\functional_tests\test_math_numeric_integrity.py .\functional_tests\test_plugin_invocation_outcomes.py .\functional_tests\test_logged_core_plugins.py -q --tb=short` | 11 passed |
| `python -B .\functional_tests\test_docs_app_surface_coverage.py` | 7/7 checks passed |
| `python -B .\functional_tests\test_docs_site_quality.py` | 6/6 checks passed |
| `git diff --check` | Passed |

`docs/_data/app_surface.yml` was regenerated; its only change is the Math action's
description. No new capability toggle or UI control was introduced.

## Before and after

| Case | Before | After |
|---|---|---|
| `1e308 + 1e308` | `inf`, reported as success | `"2E+308"`, finite successful result |
| `9007199254740992 + 1` from strings | Rounded to `9007199254740992.0` | `"9007199254740993"` |
| `1 / 3` | Binary float approximation | Decimal text with an explicit approximation qualifier |
| Raw non-finite result from a logged tool | Model saw success; citation could contain `null` | Safe failed invocation; no successful numeric result |
| Valid call after a genuine failure | Not established by the supplied UI run | Exercised in the same real Semantic Kernel instance |

This fix does not deploy itself. Local regression results do not establish that
an existing Azure deployment has been updated.
