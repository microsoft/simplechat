# Broken Access Control Full-Repo Audit Guardrails

Implemented in version: **0.241.203**

Fixed/Implemented in version: **0.241.203**

## Overview

This feature adds reusable guardrails for Broken Access Control, IDOR, and BOLA-style reviews beyond a single endpoint fix. It provides a manually runnable GitHub Actions workflow for full-code audits, expands the repository instruction set for future Python development, and adds a workspace prompt that agents can use to perform focused authorization reviews.

## Purpose

The guardrails help prevent new development from trusting caller-supplied object IDs after login. They are especially targeted at reverse-resolution and object-lookup endpoints that turn known user IDs, conversation IDs, document IDs, group IDs, or workspace IDs into protected metadata without proving that the caller can access the exact target object.

## Dependencies

- `.github/workflows/broken-access-control-full-scan.yml`
- `.github/instructions/broken-access-control-prevention.instructions.md`
- `.github/prompts/broken-access-control-audit.prompt.md`
- `scripts/check_broken_access_control.py`
- `functional_tests/test_broken_access_control_guardrails_checker.py`

## Technical Specifications

### Manual Full Scan Workflow

`.github/workflows/broken-access-control-full-scan.yml` defines a `workflow_dispatch` audit workflow with inputs for target paths, strictness, and self-test execution. It collects tracked Python files under the selected paths, runs `scripts/check_broken_access_control.py --full-file`, uploads a report artifact, and defaults to advisory mode so existing legacy findings can be reviewed without immediately failing the run.

### Repository Instruction

The Broken Access Control instruction now explicitly covers caller-controlled user IDs, Entra object IDs, owner IDs, participant IDs, shared user IDs, route path IDs, request body IDs, query-string IDs, plugin IDs, and datastore-sourced IDs. It also documents acceptable cross-user profile display relationships and calls out role-only decorators, GUID opacity, Graph lookup access, and frontend reachability as insufficient object authorization.

### Workspace Prompt

`.github/prompts/broken-access-control-audit.prompt.md` is a reusable Copilot prompt for agent-assisted audits. It guides the reviewer to trace object IDs from source to sink, distinguish role checks from object checks, identify oracle behavior, and produce findings with source, sink, missing check, impact, remediation, and regression-test details.

## Usage Instructions

Run the full-code audit from GitHub Actions:

1. Open Actions.
2. Select `Broken Access Control Full Scan`.
3. Choose target paths, such as `application scripts`.
4. Leave `fail_on_findings` as `false` for baseline/advisory runs.
5. Download the `broken-access-control-full-scan-report` artifact and triage findings.

Run a strict audit after the current baseline is clean:

```text
fail_on_findings=true
```

Run the agent-assisted prompt from VS Code Chat by selecting `Broken Access Control Audit` and providing paths, a feature area, or an incident class.

## Testing and Validation

Test coverage verifies that the BAC checker catches direct user-profile document reads, allows approved helper-based patterns, and that the workflow, instruction, prompt, and feature documentation remain wired into the repository.

Known limitation: the full scan currently reports legacy findings when run across all tracked Python files. The workflow therefore defaults to advisory mode until those findings are triaged, fixed, or marked with reviewed suppressions.