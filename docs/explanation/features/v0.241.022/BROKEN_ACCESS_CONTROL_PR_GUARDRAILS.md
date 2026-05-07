# Broken Access Control PR Guardrails

Fixed/Implemented in version: **0.241.022**

## Overview

This feature adds a prevention-focused Broken Access Control guardrail for pull requests into Development. It is designed to catch new authorization regressions before they merge, especially when code changes introduce raw active-scope reads and writes, direct personal conversation reads, or plugin tool surfaces that trust caller-supplied scope ids.

## Scope

This change affects:

- the repository instruction set in `.github/instructions/broken-access-control-prevention.instructions.md`
- the changed-file checker in `scripts/check_broken_access_control.py`
- the Development pull-request workflow in `.github/workflows/broken-access-control-check.yml`
- the guardrail regression test in `functional_tests/test_broken_access_control_guardrails_checker.py`

## Technical Details

### GitHub Instruction

The new instruction file documents the repo's preferred authorization-boundary patterns for Python route and plugin code:

- personal conversation ownership helpers such as `_authorize_personal_conversation_read(...)` and `_authorize_personal_conversation_access(...)`
- validated active-scope setters such as `update_active_group_for_user(...)` and `update_active_public_workspace_for_user(...)`
- validated active-scope readers such as `require_active_group(...)` and `require_active_public_workspace(...)`
- request-bound plugin scope normalization such as `_resolve_authorized_scope_arguments(...)`, `_resolve_blob_location_with_fallback(...)`, and `_resolve_authorized_fact_memory_call(...)`

It also explicitly blocks the recurring BAC patterns that caused recent findings:

- direct `update_user_settings(...)` writes for `activeGroupOid` and `activePublicWorkspaceOid` outside the approved validators
- raw backend or plugin reads of `activeGroupOid` or `activePublicWorkspaceOid`
- `@kernel_function` surfaces that expose scope ids without immediately rebinding them to the authorized request context
- direct personal conversation reads from request ids without a helper or explicit ownership check

### Changed-File Checker

`scripts/check_broken_access_control.py` follows the same custom-checker model already used for Swagger route validation and the XSS sink check in this repository.

Key behaviors:

- scans only Python files
- supports pull-request diff mode through `--base-sha` and `--head-sha`
- limits checks to added lines in CI when revision metadata is provided
- emits GitHub Actions error annotations for each blocking issue
- allows a narrow reviewed escape hatch with the suppression token `bac-check: ignore`

### PR Workflow

`.github/workflows/broken-access-control-check.yml` adds a Development pull-request gate with two layers:

- a blocking `broken-access-control-check` job that scans changed application Python files
- a non-blocking guardrail self-test step that runs when the checker, workflow, instruction, or feature doc changes

This keeps the primary PR gate fast while still validating the guardrail itself when the guardrail code changes.

## Local Usage

Run the checker against full files from the repository root:

```powershell
python scripts/check_broken_access_control.py --full-file application/single_app/route_backend_users.py
```

Run the guardrail self-test:

```powershell
python functional_tests/test_broken_access_control_guardrails_checker.py
```

## Reviewed Exceptions

If a reviewed legacy exception is unavoidable, add the suppression token near the specific line and include a justification comment:

```text
bac-check: ignore
```

That token should remain rare. New route and plugin code should use the shared authorization helpers instead.

## Benefits

- prevents common authorization regressions before merge
- gives non-local contributors a CI guardrail instead of relying only on editor instructions
- reinforces the helper patterns already used in the hardened chat, conversation, feedback, and plugin flows
- keeps the first pass lightweight without introducing a full security-lint stack

## Validation

Validation completed with:

- `python functional_tests/test_broken_access_control_guardrails_checker.py`
- targeted diagnostics on `scripts/check_broken_access_control.py`
- review of the Development PR workflow wiring in `.github/workflows/broken-access-control-check.yml`