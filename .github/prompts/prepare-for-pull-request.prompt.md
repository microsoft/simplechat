---
name: "Prepare for Pull Request"
description: "Use when the user says: Prepare for a pull request, PR prep, ready this branch for PR, validate before PR, or create a PR to Development. Runs SimpleChat branch sync and validation workflow before optionally pushing or creating a GitHub pull request."
argument-hint: "Optional: include merge Development, rebase Development, push, create draft PR, or create PR"
agent: "agent"
---

# Prepare SimpleChat for a Pull Request

You are preparing the current SimpleChat branch for a GitHub pull request into `Development`.

The default outcome is a verified PR-readiness report. You may push the branch or create the pull request only after explicitly asking the user to proceed and receiving confirmation. If the user already asked to push or create the PR, still pause at the final confirmation gate before doing it.

## Repository Policy

- Work in the SimpleChat repository.
- Target contributor PRs to `Development`, not `main` or `Staging`.
- Treat `Development` and `Staging` as case-sensitive branch names.
- Prefer the remote named `upstream` when it exists and has `Development`; otherwise use `origin/Development`.
- Never use destructive Git commands such as `git reset --hard`, `git checkout -- <path>`, or force push unless the user explicitly asks and understands the consequence.
- Do not revert unrelated user changes.
- Do not commit, push, or create a PR without a user confirmation step.
- If secrets, `.env` files, session tokens, storage keys, connection strings, or generated local artifacts appear in the changed file set, stop and ask before proceeding.

## Initial Discovery

Run read-only checks first and summarize what you find:

1. Confirm the repo root and current branch.
2. Show concise working tree status, including untracked files.
3. Show remotes and identify the remote target branch for `Development`.
4. Fetch the target branch: `git fetch <remote> Development`.
5. Determine whether the current branch contains the latest target branch:
   - Up to date when `<remote>/Development` is an ancestor of `HEAD`.
   - Behind or diverged when it is not.
6. Determine changed files relative to `<remote>/Development` and include both committed and uncommitted local changes.

If the current branch is `Development`, `Staging`, or `main`, stop and ask whether to create or switch to a feature branch before continuing.

## Development Sync Gate

Before reporting PR readiness or creating a PR, ensure the current branch includes the latest `Development` changes.

Default behavior:

- Fetch `Development` and report whether the branch is up to date.
- If the branch is behind or diverged, stop and ask how to integrate the changes.
- Do not merge or rebase automatically.

Supported opt-in behaviors:

- If the user asks to `merge Development`, run a normal merge from `<remote>/Development` after confirming.
- If the user asks to `rebase Development` or `rebase onto Development`, rebase onto `<remote>/Development` after confirming.
- If the user asks only to check readiness, do not integrate. Explain that PR readiness is blocked until the branch includes the latest target branch.

After any merge or rebase, recompute changed files and rerun all applicable validation.

## Conflict Handling

If a merge or rebase produces conflicts, do not ask the user to manually resolve files. Resolve conflicts interactively with the user while you do the editing.

For each conflict:

1. Identify the conflicted file and the affected feature or behavior.
2. Explain the two sides clearly:
   - `ours`: what the user's current branch changed.
   - `theirs`: what `Development` changed.
3. Explain the likely impact of choosing either side or combining them.
4. Recommend a resolution when there is enough context, but ask the user how to proceed.
5. Apply the selected resolution yourself.
6. Continue until there are no conflict markers and `git status` shows no unmerged paths.
7. Continue the merge or rebase with non-interactive Git commands.

If the user cancels conflict resolution, report the current Git state and the safest next step. Do not abandon a merge or rebase unless the user explicitly asks.

## Local Validation

Use the repo's existing workflow files, scripts, and instructions as the source of truth. Run the smallest reliable set that matches the changed files, then broaden only when risk calls for it.

Always run:

- `git diff --check` for changed files.
- A Python syntax compile check for changed Python files, and at minimum the Python files under `application/single_app` that GitHub compiles.
- Any new or changed test files directly.

When Python route files changed:

- Run `python scripts/check_swagger_routes.py <changed-python-files>`.
- Verify every Flask route has `@swagger_route(security=get_auth_security())` immediately after `@app.route(...)`.

When JavaScript, HTML, or Python browser-rendering surfaces changed:

- Run `python scripts/check_xss_sinks.py` against changed `application/**/*.js`, `application/**/*.html`, and `application/**/*.py` files.
- If validating only committed changes, prefer changed-line mode:
  `python scripts/check_xss_sinks.py --base-sha <remote>/Development --head-sha HEAD <files>`.
- If the working tree has uncommitted changes, use `--full-file` for those files because they are not represented by `HEAD`.

When Python authorization-sensitive surfaces changed:

- Run `python scripts/check_broken_access_control.py` against changed `application/**/*.py` files.
- If validating only committed changes, prefer changed-line mode:
  `python scripts/check_broken_access_control.py --base-sha <remote>/Development --head-sha HEAD <files>`.
- If the working tree has uncommitted changes, use `--full-file` for those files.

When HTML, CSS, or JavaScript changes affect UI behavior:

- Run relevant `ui_tests/` tests when the local app and authentication state are available.
- If UI tests cannot be run locally, say why and include the gap in the final PR-readiness report.

When bug fixes, new features, route changes, API changes, security changes, or UI workflow changes are present:

- Check for matching functional tests under `functional_tests/`.
- Run relevant functional tests with pytest or directly with Python, matching existing test style.
- If no relevant test exists, call this out and recommend the missing coverage.

When application code changed:

- Verify `application/single_app/config.py` has an appropriate patch version bump unless the change is docs-only.
- Verify fix or feature documentation exists when required by the repo instructions.
- Check whether `docs/explanation/release_notes.md` should be updated. If release notes are needed and missing, update them under the current `config.py` version as part of PR readiness unless the user explicitly requested report-only behavior.
- If the current `config.py` version does not have a release notes section yet, create a new section at the top of the release notes before adding the entry.

## PR Readiness Review

Before asking to push or create a PR, provide a concise report with:

- Current branch and target branch.
- Whether the branch includes the latest `Development`.
- Changed-file summary grouped by area.
- Validation commands run and pass/fail status.
- Tests run and any skipped tests with reasons.
- Version, documentation, and release notes status.
- Security review notes for secrets, XSS, broken access control, settings sanitization, and route decorators.
- Remaining risks or manual follow-up.

If validation fails, fix issues that are clearly in scope and rerun the affected checks. If a failure is unrelated or needs a product decision, stop and explain the blocker.

## Optional Push and PR Creation

Only after the readiness report is clean or the user accepts the noted risks, ask whether to proceed with push and PR creation.

If uncommitted changes remain:

- Do not push or create a PR yet.
- Ask whether the user wants you to stage and commit the PR-ready changes.
- Propose a concise commit message based on the change summary.

If the user confirms push:

- Push the current branch to the appropriate remote.
- Do not force push unless the user explicitly asks after seeing the risk.

If the user confirms PR creation:

- Use GitHub CLI when available.
- Create the PR against `Development`.
- Default to a draft PR unless the user asks for a ready-for-review PR.
- Include a PR body with summary, validation, tests, release notes status, and known risks.
- Return the PR URL.

If GitHub CLI is unavailable or unauthenticated, report the exact blocker and provide the PR title/body text for manual creation.