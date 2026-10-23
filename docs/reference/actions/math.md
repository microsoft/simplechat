---
layout: page
title: "Math"
description: "Reference for the Math SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: math -->

{% include media.html src="reference/actions-math-configuration.png" alt="Math action setup or assignment UI." title="Math action" capture="Capture the Math action setup or assignment UI with relevant fields visible. Redact secrets and user identifiers." %}

## What this action does

Performs deterministic real-number addition, subtraction, multiplication, division,
powers, square roots, and modulus. Use it to ground an answer in a calculation
rather than asking the model to approximate arithmetic.

Implemented numeric-integrity improvements in version: **0.261.380**.

## Why and when to use it

Use it when an agent should calculate instead of approximating arithmetic. Use Tabular or SQL for dataset aggregations.

## Before you start

- No credentials; controlled by `enable_math_plugin`.
- Users also need access to the action through workspace or governance policy where applicable.

## Configuration overview

No service-specific configuration beyond enabling/assigning the action.

Shared wizard steps: [Common action setup steps](../#common-action-setup-steps).

## Numbers and precision

The calculator uses bounded decimal arithmetic with 64 significant digits and
half-even rounding. It can calculate finite values outside binary floating-point
range: for example, `1e308 + 1e308` returns `2E+308`, not infinity. Decimal inputs
such as `0.1` and `0.2` sum to `0.3`.

Pass numbers as strings when preserving their digits matters. An integer such as
`"9007199254740992"` plus `"1"` returns `"9007199254740993"`. If a caller has
already rounded a number by converting it to a floating-point value, the
calculator cannot recover the missing digits.

The limits are:

- At most 1,024 characters per numeric input, after trimming outer whitespace.
- At most 64 significant coefficient digits, excluding trailing zeros.
- Both the written decimal exponent and the most significant digit's decimal
  exponent must be between -10,000 and 10,000.
- The absolute value of a power's exponent must not exceed 10,000.
- Calculated results must remain in the supported normal decimal range.

Use plain decimal or scientific notation, without commas or digit separators.
NaN, infinity, booleans, complex numbers and malformed numeric text are not
accepted. Inputs that exceed these limits fail explicitly instead of being
silently truncated.

## Tool results and errors

Since version **0.261.380**, Math tool results are **text**, not floating-point
numbers. Exact results are decimal or scientific-notation strings; for example,
`"200000"` or `"2E+308"`. Tool names and argument names have not changed.
Integrations that consume Math tool results directly must not assume a numeric
JSON type or convert large result strings back to binary float.

When an operation needs rounding, its result text explicitly includes
`(approximate; rounded half-even to 64 significant digits)`. This applies to
nonterminating division, irrational roots, and other calculations whose answers
do not fit the precision. Bounded precision is not an arbitrary-precision or
symbolic-mathematics guarantee.

Division or modulus by zero, a negative square root, and a fractional power of
a negative base produce explicit real-domain errors. Modulus keeps the divisor's
sign, so `-5 % 3` is `1` and `5 % -3` is `-1`. Zero raised to zero retains the
calculator's programming convention of `1`.

A calculation limit is not a claim that the mathematical answer is infinity.
The failed invocation remains visible in tool evidence; a later valid
calculation can still run. SimpleChat also rejects raw non-finite numeric results
from logged tools before reporting them as successful, preventing a successful
model result from becoming an unexplained `null` in the saved citation.

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents-actions/' | relative_url }})
- [Workspace identities]({{ '/admin/workspaces/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
