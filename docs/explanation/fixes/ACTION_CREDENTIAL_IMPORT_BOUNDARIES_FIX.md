# Personal action credential import boundaries

Fixed/Implemented in version: **0.261.336**, recorded in
`application/single_app/config.py`.

Related pull request: [#1766](https://github.com/microsoft/simplechat/pull/1766).

## Issue and root cause

The credential resolver imported authentication, settings, the action catalog,
workspace identities, and the chat owner. Those owners reached the resolver
again through action discovery or agent execution. The continuation journal
also imported settings and content-screening owners that reached the journal
again. Function-local imports delayed these dependencies but did not remove
the cycles identified by CodeQL's `py/cyclic-import` rule.

## Technical changes

`functions_action_credential_runtime.py` composes callbacks from the initialized
web or scheduler owners. `functions_action_credentials.py` receives existing
conversation/action authorization and identity operations;
`functions_action_credential_continuation.py` receives canonical agent resolution
and retained-source authorization. Neither lower-level module imports those
owners, and neither silently initializes cloud services if the callbacks have
not been configured.

`app.py` and `simplechat_scheduler.py` configure both services alongside private
storage. The callbacks preserve fresh action settings, current user roles,
conditional identity updates, and document access checks before retained work
is reused. Identity storage failures remain failures, not new credential prompts.

The same change removes unused imports, makes the invocation filter's
successful return explicit, and documents why concurrent `404` deletion is
an idempotent success. Other deletion errors still propagate.

## Validation

`functional_tests/test_action_credentials_bootstrap.py` checks the transitive
import graph, including function-local imports. Fresh normal and optimized
processes exercise both early credential import orders, web initialization,
dedicated scheduler initialization, unconfigured failures, and real-module
conversation ownership with network access blocked.

The existing identity, orchestration, and Semantic Kernel continuation suites
exercise the injected owners. Completed tool results and nested agent work stay
retained rather than replayed. Added tests cover concurrent private-state
deletion and identity-service outages; the classic credential UI suite covers
removal of its unused import.

At **0.261.336**, the four credential suites passed **49 tests** and the complete
network-blocked Cosmos contract gate passed **837 tests and 231 subtests**.
The classic UI suite passed **28 cases**. A broader delegation compatibility run
had 72 passes and nine failures in existing AST-extracted entrypoint fixtures
with missing globals; their loader, workflow, and chat source files were not
changed by this fix.

Before this fix, runtime owners could import themselves indirectly through
credential execution. After it, initialized owners supply their operations
without reverse imports. The private credential card and storage policy are
unchanged.
