---
description: "Use when: creating a GitHub issue for microsoft/simplechat, triaging labels, assigning an owner, setting priority and size, and adding it to the Simple Chat Roadmap prioritized backlog."
name: "Create GitHub Issue"
argument-hint: "Issue request, optional title/body, optional labels, optional assignee, optional priority P0/P1/P2, optional size"
agent: "agent"
---

# Create a SimpleChat GitHub Issue

Create a well-triaged GitHub issue in `microsoft/simplechat` and add it to the `Prioritized backlog` view in the `Simple Chat Roadmap` project: <https://github.com/orgs/microsoft/projects/2171>.

Use this prompt when the user describes a bug, feature request, enhancement, security finding, documentation task, deployment task, or maintenance work that should become a GitHub issue.

## Defaults

- Repository: `microsoft/simplechat`
- Project owner: `microsoft`
- Project number: `2171`
- Project: `Simple Chat Roadmap`
- Target project view: `Prioritized backlog`
- Do not create duplicate issues. Search first.
- Do not invent missing business priority. Ask the user to choose `P0`, `P1`, or `P2` unless they already provided it.
- Always ask whether to assign the issue to the user, to someone else, or to leave it unassigned.
- Infer size from the request and nearby code context when useful. Ask only when the size is ambiguous or would affect planning materially.

## Initial Inputs

If the user did not provide enough detail to create a useful issue, ask the smallest set of questions needed. Prefer collecting these in one short turn:

- What is the request, bug, or desired outcome?
- What priority should be used: `P0`, `P1`, or `P2`?
- Should this be assigned to you, assigned to someone else, or left unassigned?

If assigning to someone else, ask for their GitHub username. If assigning to the current user, resolve the login with:

```powershell
gh api user --jq .login
```

## Discovery

Before creating the issue, gather focused context:

1. Search for likely duplicate issues:

```powershell
gh issue list --repo microsoft/simplechat --state all --search "<keywords>" --limit 20
```

2. Load available labels and use only labels that exist in the repository:

```powershell
gh label list --repo microsoft/simplechat --limit 200 --json name,description
```

3. If sizing depends on implementation complexity, inspect only the most relevant code or docs paths needed to estimate scope. Do not do broad exploration unless the request is vague.

4. Load project fields and options:

```powershell
gh project view 2171 --owner microsoft --format json
gh project field-list 2171 --owner microsoft --format json
```

## Triage Rules

### Labels

Choose labels based on the request content and available repository labels.

Use this decision logic where matching labels exist:

- Bug, regression, broken behavior, errors, crashes: `bug`
- New user-facing capability: `enhancement` or feature-related label
- Documentation-only request: `documentation`
- Security, access control, secrets, auth, XSS, CSRF: security-related label
- Deployment, infrastructure, azd, Bicep, Terraform, CI/CD: deployment, infrastructure, or DevOps-related label
- Tests, validation, automation, quality gates: testing or automation-related label
- Question, investigation, or uncertain behavior: question, investigation, or needs-triage-related label

If more than one label fits, apply the smallest useful set. If no existing label clearly fits, continue without that label and mention the gap in the final summary.

### Priority

Ask the user to choose priority unless already supplied.

- `P0`: outage, active data loss, critical security issue, deployment-blocking production incident, or no acceptable workaround.
- `P1`: important user-facing bug, high-value roadmap feature, security hardening with meaningful risk, or work blocking near-term release goals.
- `P2`: normal backlog item, minor bug, quality improvement, documentation update, cleanup, or enhancement with a workaround.

Use the user's priority selection when populating the project. If the project uses different option names, map to the closest exact project option and call out the mapping.

### Size

Infer size from the request and code context. Use the project's exact size field options when available.

- `XS`: wording, small docs, labels, or a tiny config-only change.
- `S`: localized single-file or narrow UI/API change with straightforward tests.
- `M`: a feature or fix spanning a few files, one integration boundary, or moderate test coverage.
- `L`: cross-cutting change across multiple subsystems, migrations, auth/security-sensitive flows, or significant UI and backend work.
- `XL`: project-sized effort requiring design, staged delivery, data migration, or multiple owners.

If the roadmap uses numeric sizes or another scale, map `XS/S/M/L/XL` to the closest available option and include that mapping in the issue or final summary.

## Issue Drafting

Write the issue with clear, actionable structure. Choose the template that best fits the request.

### Bug

```markdown
## Issue
<What is broken and who is affected.>

## Steps to Reproduce
1. <Step>
2. <Step>
3. <Step>

## Expected Behavior
<What should happen.>

## Actual Behavior
<What happens instead.>

## Impact
<User, admin, deployment, security, or operational impact.>

## Notes
<Relevant context, suspected area, links, logs, or screenshots.>
```

### Feature or Enhancement

```markdown
## Summary
<What should be added or improved.>

## User Value
<Why this matters and who benefits.>

## Proposed Behavior
<How the capability should work.>

## Acceptance Criteria
- [ ] <Observable outcome>
- [ ] <Observable outcome>
- [ ] <Validation, docs, or tests as appropriate>

## Notes
<Relevant implementation context, dependencies, or open questions.>
```

### Task, Documentation, or Maintenance

```markdown
## Summary
<What work should be completed.>

## Scope
- <Included work>
- <Included work>

## Acceptance Criteria
- [ ] <Observable completion condition>
- [ ] <Validation or review condition>

## Notes
<Relevant context, links, or constraints.>
```

## Creation Workflow

1. Summarize the proposed title, labels, priority, size, and assignee.
2. Ask for confirmation before creating the issue if any field is uncertain or if the user has not explicitly asked to create it now.
3. Create the issue:

```powershell
gh issue create --repo microsoft/simplechat --title "<title>" --body-file "<temp-body-file>" --label "<label1>" --label "<label2>" --assignee "<assignee>"
```

Omit `--label` or `--assignee` arguments when there are no labels or no assignee.

4. Add the created issue to the roadmap project:

```powershell
gh project item-add 2171 --owner microsoft --url "<issue-url>"
```

5. Populate project metadata using project field IDs and option IDs from discovery:

```powershell
gh project item-edit --project-id "<project-id>" --id "<item-id>" --field-id "<priority-field-id>" --single-select-option-id "<priority-option-id>"
gh project item-edit --project-id "<project-id>" --id "<item-id>" --field-id "<size-field-id>" --single-select-option-id "<size-option-id>"
```

If the roadmap has a status, view, or backlog field that controls whether an item appears in `Prioritized backlog`, set it to the matching backlog option. If views are computed from fields and no editable view field exists, adding the item to the project and setting priority/size is sufficient.

## Final Response

Return a concise summary with:

- Issue URL.
- Labels applied.
- Assignee choice.
- Priority and size values set in the roadmap.
- Any project field that could not be populated and why.
- Any duplicate issue that was found and how it was handled.

If GitHub CLI is unavailable, unauthenticated, or lacks project permissions, stop and report the exact blocker plus the issue title/body and project field values so the user can create or finish it manually.
