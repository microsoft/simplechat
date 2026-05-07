# XSS PR Guardrails

Fixed/Implemented in version: **0.241.021**

## Overview

This feature adds a prevention-focused XSS guardrail for pull requests into Development. It is designed to catch new browser-side sink regressions before they merge, especially when code arrives from contributors who are not using the local Copilot or CLAUDE instruction set.

## Scope

This change affects:

- the repository instruction set in `.github/instructions/xss-prevention.instructions.md`
- the changed-file checker in `scripts/check_xss_sinks.py`
- the Development pull-request workflow in `.github/workflows/xss-sink-check.yml`
- the guardrail regression test in `functional_tests/test_xss_guardrails_checker.py`

## Technical Details

### GitHub Instruction

The new instruction file documents the repo's preferred safe browser-rendering patterns:

- `createElement(...)`
- `textContent`
- `setAttribute(...)`
- `dataset`
- `addEventListener(...)`
- `DOMPurify.sanitize(marked.parse(...))`

It also explicitly blocks the sink patterns that caused the recurring XSS findings:

- dynamic `innerHTML`, `outerHTML`, `insertAdjacentHTML`, and jQuery `.html(...)`
- inline event handlers such as `onclick`, `onerror`, and `onload`
- dynamic interpolation into `href`, `src`, `title`, `style`, and `data-*`
- `javascript:` URLs
- `Markup(...)` in Python on untrusted content
- Jinja `|safe` on untrusted content
- `marked.parse(...)` rendered without DOMPurify

### Changed-File Checker

`scripts/check_xss_sinks.py` follows the same custom-checker model already used for Swagger route validation in this repository.

Key behaviors:

- Scans only supported source files: `.js`, `.html`, and `.py`
- Supports pull-request diff mode through `--base-sha` and `--head-sha`
- Limits checks to added lines in CI when revision metadata is provided
- Emits GitHub Actions error annotations for each blocking issue
- Allows a narrow reviewed escape hatch with the suppression token `xss-check: ignore`

### PR Workflow

`.github/workflows/xss-sink-check.yml` adds a Development pull-request gate with two layers:

- a blocking `xss-sink-check` job that scans changed application files
- a non-blocking guardrail self-test step that runs when the checker, workflow, instruction, or feature doc changes

This keeps the primary PR gate fast while still validating the guardrail itself when the guardrail code changes.

## Local Usage

Run the checker against full files from the repository root:

```powershell
python scripts/check_xss_sinks.py --full-file application/single_app/static/js/chat/chat-messages.js
```

Run the guardrail self-test:

```powershell
python functional_tests/test_xss_guardrails_checker.py
```

## Reviewed Exceptions

If a reviewed legacy exception is unavoidable, add the suppression token near the specific line and include a justification comment:

```text
xss-check: ignore
```

That token should remain rare. New rendering code should use the safe DOM patterns instead.

## Benefits

- Prevents common XSS sink regressions before merge
- Gives non-local contributors a CI guardrail instead of relying only on editor instructions
- Reinforces the safe rendering patterns already used in the hardened chat, workspace, and Control Center flows
- Keeps the first pass lightweight without introducing a full frontend lint stack

## Validation

Validation completed with:

- `python functional_tests/test_xss_guardrails_checker.py`
- targeted diagnostics on `scripts/check_xss_sinks.py`
- review of the Development PR workflow wiring in `.github/workflows/xss-sink-check.yml`