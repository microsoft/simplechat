# React V2 Static Security Fix (v0.261.421)

Fixed in version: **0.261.421**, recorded in
`application/single_app/config.py`.

Tracking item: [PR #1903](https://github.com/microsoft/simplechat/pull/1903).

## Issue and root cause

The integration introduced a frontend manifest with 22 floating dependency
ranges and a screening fixture containing three literal zero-width joiners.
The existing malicious-PR security check correctly reported these as 25
blockers. A lockfile alone did not satisfy the manifest's exact-pin requirement.
The joiners were intentional emoji test data, but were invisible during source
review.

## Technical changes

- `application/v2_ui/package.json` pins dependencies to their previously
  resolved lockfile versions, not to different library releases.
- `application/v2_ui/package-lock.json` changes only the root manifest pins.
  All 288 resolved package records, URLs, integrity values, dependency
  relationships, and peer/optional metadata remain unchanged.
- `functional_tests/test_v2_content_screening_logic.mjs` represents each joiner
  with a visible `\u200d` source escape. JavaScript still constructs the same
  runtime strings, including the joined emoji and codepoint boundaries.
- `functional_tests/test_v2_static_security_fix.py` runs the unchanged checker
  against the actual manifest and fixture, verifies manifest/lockfile
  consistency, and prevents literal hidden controls from returning.

No browser runtime assets, application behavior, CI workflows, checker rules,
or alert dismissals are changed by this fix.

## Validation

The focused validations cover exact dependency pins, unchanged resolved
packages, visible source controls, and the existing Unicode selection behavior.

```powershell
python -m pytest -q .\functional_tests\test_v2_static_security_fix.py
node --check .\functional_tests\test_v2_content_screening_logic.mjs
node .\functional_tests\test_v2_content_screening_logic.mjs
.\application\v2_ui\node_modules\.bin\tsc.cmd --noEmit --project .\application\v2_ui\tsconfig.json
```

| Local verification | Result |
| --- | --- |
| New static-security regression selection | 2 passed |
| Screening fixture syntax and existing runtime selection | Passed; 30 checks passed |
| Frontend no-emit TypeScript check | Passed |
| Python compilation of the changed config and new test | Passed |
| Unchanged static-security CLI on the three-file fix scope | Zero blockers; release-age verification not included |
| Dependency and fixture before/after comparison | All 288 package records and fixture runtime values preserved |
| Documentation coverage, site quality, and release-note integrity selection | 14 passed; 14 existing return-value warnings |
| Regenerated release pages and `build_release_notes_pages.py --check` | In sync |
| Git whitespace check | Passed |

The before/after checker comparison is 25 blockers before the fix and zero in
the three-file scope afterward. All 30 existing screening checks retain their
runtime coverage. Local typechecking does not restore dependencies or prove a
live Azure deployment; committed-head CI must verify the complete PR range and
dependency release ages.

## Scope and remaining review

CodeQL's original failed summary combines Development-baseline findings with
PR-introduced findings. Comparing the exact PR merge analysis to the actual
Development base confirms that all six critical partial-SSRF sinks already
exist on Development. Broader new test, utility, and exception-response
findings still require human review; this fix does not dismiss them or claim
that the entire integration is security-cleared.

The existing broader V2 creation/CSRF empty-draft recovery failures also remain
unresolved. Their evidence and the review-comment batch's validation results
are preserved in
[the integration fix documentation](REACT_V2_DEVELOPMENT_INTEGRATION_FIX.md).
Neither those failures nor the broader CodeQL work is neutralized to obtain a
passing check. No merge is performed.
