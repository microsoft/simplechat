# React V2 Development Integration (v0.261.420)

Integration implemented in version: **0.261.419**.
Fixed/Implemented in version: **0.261.420** (review follow-ups), tracked in
`application/single_app/config.py`.

Tracking item: [PR #1903](https://github.com/microsoft/simplechat/pull/1903).

## Issue and root cause

The React V2 and Development histories diverged while fixes were ported and
extended independently. Combining them produced overlapping implementations,
historical release entries with the same version numbers, and regression
fixtures written for different revisions of the application.

A clean textual merge alone was insufficient: automatic merging duplicated
default-model helpers and appended unreachable metadata-sync work. Browser
coverage also exposed a restored waiting run incorrectly claiming the composer's
Stop button, even though no reply stream was active.

## Technical changes

The integration preserves both Git histories and the newer implementations of
Development's existing fixes, including durable metadata synchronization,
fail-closed sharing projections, content-safety thresholds, model governance,
upload system prompts, image processing, and deployment identity permissions.
It does not replace Development with an unrelated tree or change interface
rollout settings.

- `Composer.tsx` distinguishes a tracked durable wait from work that owns the
  composer. Waiting executions remain discoverable and cancellable through the
  plan; they are not rerun or forgotten.
- `navigationGroups.ts` and `NavExtras.tsx` reject executable, protocol-relative,
  backslash, and control-character destinations before assigning an anchor URL.
  Valid local paths and HTTP(S) links retain their existing behavior.
- `python-syntax-check.yml` retains Development's recursive package discovery.
  The staging smoke workflow keeps its existing temporary branch trigger, with
  the comment required by the guardrail contract.
- `check_xss_sinks.py` treats the pinned classic Mermaid distribution as vendor
  code, matching the existing vendor boundary. First-party wrappers remain
  scanned. Narrow annotations document verified sanitizer, generated-blob,
  fixed-route, and intentionally hostile fixture boundaries; they do not
  disable the first-party checks.
- `ui_tests/requirements.txt` uses the application's `azure-identity==1.24.0`
  pin so application and browser-test requirements can be restored together.
  Validation uses the application's pinned OpenAI SDK, not another SDK
  installed on the host.
- Both release histories retain their distinct entries. Generated release pages
  come from the combined authoring source, with source-relative links replaced
  by verified repository permalinks where required by the generator.

Deployer files retain the React branch's implementation and version `1.0.37`.
This integration does not introduce another deployer or cloud-permission change.

## Regression coverage

`functional_tests/test_react_v2_development_integration.py` guards against
duplicate shared helpers and unreachable projection work. Runtime metadata,
sharing, startup, retry, and SDK suites continue to exercise the real owners.
The older retry regression now uses the current catalog-authorized replay owner
instead of restoring an unused legacy helper.

Browser coverage retains real components, production CSS, and closed HTTP
fixtures. Updated fixtures answer the pending-question endpoint, return the
requested plan revision after clarification, and inspect the visible quiet
activity row rather than a button inside collapsed details. Manual
clarification still requires approval and does not start a run.

OneNote's earlier Development-only rollback is historical. Its rejection-only
test is retired in favor of the current native-format acceptance, dispatch,
extraction, and V2 upload contracts. Packaging checks accept equivalent
directory-exclusion syntax and trace the bootstrap's sanitized upload catalog
through its local binding.

## Validation and limitations

Relevant checks include the React production build, Python/JavaScript syntax,
route policy suites, documentation coverage and generated-page freshness, the
full changed-code guardrails, local browser scenarios, and the offline Cosmos
response-boundary bank.

| Local verification | Result |
| --- | --- |
| Production React/TypeScript build and browser-harness build | Passed; the existing large-bundle advisory remains |
| Integrated browser regression selection | 184 passed |
| New orchestration functional selection | 262 passed |
| Promotion, retry, provenance, navigation, and checker selection | 175 passed; 57 subtests passed |
| Preserved Development/startup/retry selection with the pinned SDK | 77 passed; 33 subtests passed |
| Offline Cosmos response-boundary bank | 2,005 passed; 431 subtests passed; 1,094 owners and 425 doubles with zero review gaps |
| Classic inline diagrams and browser export rasterization | 5/5 and 3/3 passed |
| Navigation URL runtime checks | 12/12 passed |
| Route policy, documentation coverage/quality, generated notes, and changed-code guardrails | Passed |

These are local results. Committed-head checks must still run before
publication, and PR checks must pass before merge.

Local browser fixtures and SDK contracts do not prove a live Azure deployment.
Native OneNote executable/container checks require their documented build and
fixtures. No deployment, resource provisioning, GitHub default-branch change,
or promotion to Staging/main is performed by these tests.

## Review follow-ups in 0.261.420

The four supplied review comments were evaluated together rather than removing
guards or rewriting already-safe diagnostic rendering.

- `admin_settings.js` captures the initial checks' explicit success/conflict
  result before resubmitting. Late group/public conflicts still block saves;
  duplicate queued submissions save once, and form drafts remain intact.
- `chat-action-recovery.js` rebuilds permitted personal, group, and global
  editor routes with encoded identifiers. Malformed encodings, dot segments,
  nonlocal destinations, and controls cannot become links. Unexpected decoder
  errors propagate rather than being silently treated as invalid input.
  Diagnostics already used `textContent`; that behavior and report/recheck
  controls remain unchanged.
- The unused image-test wrapper and reasoning import are removed. Regression
  coverage now clicks the actual image and embedding buttons, retaining the
  saved-binding and unsaved-edit checks.

| Review follow-up verification | Result |
| --- | --- |
| Four changed classic JavaScript assets: `node --check` | Passed |
| Admin editor integration and recovery URL Node selection | 16 tests passed, including 40 URL/failure-propagation contracts |
| Admin consistency and recovery rendering browser selection | 24 passed; one authenticated-environment test skipped |
| Reasoning runtime and initial-sync selection in its own process | 9 passed; existing return-value warnings remain |
| Expanded admin and both-interface recovery selection | 65 passed, one skipped, two V2 empty-draft recovery checks failed |

The first all-in-one browser selection encountered a Playwright fixture
lifecycle collision when two independent synchronous browser owners shared one
process. The focused selections above pass in their respective processes; no
fixture or assertion was weakened.

The expanded V2 failures occur in creation/CSRF recovery with no newer draft.
An isolated DOM probe also confirmed an empty textarea value after the send
settled, so the failure is not merely a text-versus-value assertion mismatch.
V2 production sources and those recovery tests/fixtures are unchanged from the
published integration head; these failures remain a broader validation gap,
not a passing result or a reason to disable coverage. PR checks and these
unresolved gaps must be reviewed before the integration is merged.
