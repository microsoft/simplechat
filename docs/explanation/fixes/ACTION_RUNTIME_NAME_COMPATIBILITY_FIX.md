# Assigned action runtime-name compatibility fix

Fixed/Implemented in version: **0.261.347**.

Related version update: `application/single_app/config.py`.

Issue: [#1781](https://github.com/microsoft/simplechat/issues/1781).

## Issue and root cause

SimpleChat accepts hyphens in saved action names. Semantic Kernel does not
accept them in plugin identifiers. Registration used the saved name directly
in both the logged loader and its legacy fallbacks. An agent could therefore
resolve its assigned action correctly, fail to register it, and answer with no
access to that capability.

A long, hyphenated calendar action created by a test harness reproduced the
failure. An underscore-only calendar action worked. The same mismatch affects
other connectors; it is not special treatment for a particular Microsoft 365
agent. This diagnosis does not establish that a downstream service will accept
the action's credentials or that a calendar invitation was delivered.

## Implementation

`application/single_app/action_runtime_contracts.py` separates canonical saved
identity from the runtime plugin identifier. A trusted scoped action identity
provides a deterministic alias when a name is invalid, conflicts with another
action or core plugin, or exceeds the qualified tool-name budget.

The shared registration boundary handles ordinary decorated plugins and
factory-provided plugin facades. It retains operation names and verifies that
the resulting plugin exposes functions. SQL schema companions have a separate
internal runtime role without losing their query action's trusted origin.

`semantic_kernel_plugins/logged_plugin_loader.py` and both registration
fallbacks in `semantic_kernel_loader.py` use this boundary. Captured execution
checks compare the actual runtime bindings rather than assuming that a saved
name is a kernel key. Saved names, IDs, assignments, capability restrictions,
secret references, and workspace permissions are unchanged.

Ordinary chat now stops before model execution when assigned actions cannot
load. See [Agent action recovery](../features/AGENT_ACTION_RECOVERY.md) for
explicit continuation and permission-aware remediation. Later failures do not
produce a whole-request replay opportunity. Selected global agents use fresh
request-local kernels so one user's exclusions cannot modify a shared kernel.

## Validation

`functional_tests/test_action_runtime_names.py` covers the reported name,
dash/underscore and scoped collisions, core names, dynamic facades, SQL
companions, qualified-name lengths, and cold imports in both orders under
normal and optimized Python.

`functional_tests/test_m365_loader_preflight.py` exercises the actual shared
loader, legacy registration, captured failures, and propagation of Microsoft
365 policy decisions. `functional_tests/test_m365_provider_core.py` registers
all four typed Microsoft 365 action classes with FED-style names while
authentication and source access are forbidden.

Local validation with the repository-pinned Semantic Kernel **1.39.4** and
Azure Cosmos SDK **4.9.0** passed 256 focused naming, recovery, Microsoft 365,
and orchestration tests. These include ordinary-versus-nested execution checks:
a delegated or captured agent never inherits the parent chat's exclusions
merely because it runs inside the same Flask request. The
actual nonstreaming and streaming chat routes both stopped before kernel
initialization or user-message persistence when admission found an unavailable
action, with network access blocked.

Browser coverage passed 23 new recovery cases across classic and V2 chat.
Existing credential-flow browser checks also passed: 28 classic and 22 V2
cases. V2 type checking and production build, classic JavaScript syntax checks,
route-policy checks, and documentation coverage/quality checks passed.

The final Cosmos boundary gate passed **1,082 tests and 244 subtests** with
network access blocked, reviewing 1,066 storage owners and 410 test doubles
with no inventory review gaps.

A broader, unchanged workflow-actor AST-extraction test fails because its
namespace omits `_prepare_workflow_xsd_generation`. The same failure was
reproduced against untouched HEAD source; this fix does not change that
workflow owner or its test harness.

These are registration and recovery checks, not live Graph delivery tests.
No saved production agent needs renaming, and this fix does not resend
previously failed or uncertain calendar/email operations.
