---
applyTo: '**'
---

# GitHub Issue Workflow

## When Starting Work

At the start of meaningful work, determine whether there is an associated GitHub issue for the task.

- If the user mentions an issue number or URL, treat that as the associated issue and keep it in mind for summaries, PR notes, release notes, and later status updates.
- If no issue is mentioned and the work is more than a tiny clarification or one-off command, ask the admin whether they want to create an issue before or alongside the work.
- If the admin wants an issue created, use the existing `Create GitHub Issue` prompt in `.github/prompts/create-github-issue.prompt.md`.
- Do not block urgent fixes, small investigations, or explicitly time-sensitive work just because there is no issue yet. Continue the work and ask at the next natural checkpoint.

## Issue Association

When an issue exists or is created for the work:

- Track it as the working associated issue for the current task.
- Reference the issue in relevant summaries, PR descriptions, fix documentation, feature documentation, and release note entries when appropriate.
- Prefer durable references such as `Fixes #123`, `Closes #123`, or `Refs #123` when the change directly resolves, completes, or relates to the issue.
- Do not create duplicate issues. Use the issue creation prompt's duplicate-search workflow before creating a new issue.

## When To Suggest Updating Issues

Prompt the admin to update the associated issue at natural checkpoints, not on every interaction.

Ask whether to update the associated issue when any of these occur:

- The implementation is complete or materially changes direction.
- Important validation results are available.
- Scope, priority, acceptance criteria, or user impact changes.
- A blocker, dependency, risk, or follow-up task is discovered.
- Release notes are being updated or the admin is asked whether to update release notes.

Use concise wording such as:

> Would you like me to update the associated GitHub issue with the summary, validation, and any follow-ups from this work?

If there is no associated issue at one of these checkpoints, ask whether the admin wants to create one using the `Create GitHub Issue` prompt.

## What To Put In Issue Updates

When the admin approves an issue update, include only useful status information:

- What changed.
- Current validation status and relevant test results.
- Any unresolved risks, blockers, or follow-ups.
- Links or references to related PRs, documentation, or release notes when available.

Do not post noisy progress comments, implementation chatter, or repeated updates that do not change the issue's useful state.