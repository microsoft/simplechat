---
name: multi-model-plan
description: Opt-in multi-model planning for difficult troubleshooting or substantial features. Use when the user explicitly requests /multi-model-plan, a planning council, or three independent model plans followed by synthesis and implementation. Do not trigger automatically for ordinary feature or troubleshooting requests. Creates three independent plan-mode child conversations (MAI-Code-2, Claude Sonnet 5, GPT-6.1 Sol), then a GPT-6.1 Sol synthesis conversation, then, only after user approval, a MAI-Code-2 autopilot implementation conversation.
---

# Multi-model planning

## Purpose and activation

Coordinate independent analysis before committing to an implementation. Seek the
smallest reliable solution, better diagnosis, and a precise implementation handoff.
Model diversity is a source of competing hypotheses, not a guarantee of correctness.
More planning costs money; do not promise lower total cost or better results.

Run only on explicit user opt-in. Good candidates include elusive or recurring
bugs, unclear root causes, substantial features, and consequential design tradeoffs.
Use normal single-session work for obvious fixes, mechanical edits, and small,
well-understood features unless the user specifically requests this process.

This skill defines a reusable conversation procedure. It does not install a
background service, schedule work, or run itself automatically.

## Fixed roles

Create five coordinated child conversations in three stages, all nested directly
under the invoking coordinator. Do not create a chain of children under children.
The three planners work in parallel; the remaining stages are sequential.

| Stage | Conversation | Model ID | Mode |
| --- | --- | --- | --- |
| 1 | Independent MAI plan | `mai-code-2` | `plan` |
| 1 | Independent Sonnet plan | `claude-sonnet-5` | `plan` |
| 1 | Independent Sol plan | `gpt-6.1-sol` | `plan` |
| 2 | Consolidated plan | `gpt-6.1-sol` | `plan` |
| 3 | Implementation | `mai-code-2` | `autopilot` |

These are app-native conversations, not temporary task agents. Use
`create_session` and the available session inspection/messaging tools. Do not
replace them with `task`, a dynamic workflow, or an automation.
Do not silently substitute models or modes if unavailable; explain the blocker
and ask the user before changing the lineup.

## 1. Establish one shared brief

Resolve the repository with `list_repositories`. Check existing sessions for an
already-running council for the same task before creating another.
If the repository or requested outcome is unclear, ask one focused question.
Do not expand a single-repository request into a cross-repository project.

Capture a shared brief containing:

- The user's actual feature request or troubleshooting symptoms and desired outcome.
- Acceptance criteria, explicit constraints, non-goals, and compatibility needs.
- Reproduction details, errors, and evidence already available.
- The relevant repository and baseline ref/commit, when observable.
- Any relevant existing work that must be preserved.

All planners must analyze the same baseline. Normally omit `base_branch`, allowing
the app's normal base selection, and have each planner report its actual baseline.
If the task explicitly depends on an in-progress branch, use that existing branch
consistently as permitted by the session tools. Do not invent a branch requirement.
Do not copy uncommitted changes or switch a shared checkout without authorization.
If the required work exists only in another worktree, resolve access or baseline
differences before drawing conclusions from divergent source.

Announce the three planning conversations, the later synthesis conversation, and
the user-approval gate before implementation. This opt-in authorizes this bounded
pipeline, not unlimited rounds, agents, or retries.

## 2. Run three independent planning conversations

Create the three stage-1 conversations together with:

- The resolved `project_id` and an isolated `workspace_type: "worktree"`.
- `coordinate_with_creator: true` and `notify_on_idle: "once"`.
- The role's exact `kickoff.model` and `kickoff.mode: "plan"`.
- A complete standalone kickoff with the same shared brief and planner assignment.

Follow the app's user-message provenance requirements. Include the relevant
verbatim user task in each kickoff, separately from coordinator-authored guidance.
Do not pass one planner's findings to another before all three finish. Do not give
different planners different subsystems: each independently analyzes the whole
task. They must not invoke this skill recursively or spawn additional reviewers.

Planner assignment:

> Independently investigate this task and propose a minimal, evidence-backed plan.
> This is planning only: do not implement, change repository source, approve an
> implementation, or open a pull request. Inspect applicable repository instructions,
> existing architecture, helpers, call sites, and relevant tests. Distinguish observed
> facts from assumptions and cite file paths and symbols/lines where useful.
> For troubleshooting, identify reproduction steps, rank plausible causes, and
> specify discriminating checks rather than guessing a fix. For a feature, map
> acceptance criteria to existing behavior and identify the smallest coherent
> extension. Prefer reuse; justify every proposed dependency, abstraction, or
> architectural change. Include ordered file-level steps, focused validation,
> compatibility/rollback considerations, risks, and unresolved questions. State
> your baseline ref/commit and confidence. Return a self-contained plan through
> the native plan mechanism, then stop in plan mode. Do not consult the other
> planners or create additional sessions.

Wait using session notifications, not shell sleep loops or repeated status polls.
On notification inspect each known session ID with `get_session`, including
`pending_plan` and any blocked input. Idle alone does not mean a plan is complete.
Do not approve the independent plans: none of these conversations implements.

Gather the full plans, not just short summaries. Retain their session IDs and
available plan artifact references for auditability and resumption. A blocked or
failed planner is not a completed plan. Surface missing evidence and resolve the
blocker rather than silently presenting two plans as three.

## 3. Synthesize only after all three plans are ready

Create a fresh stage-2 child with `model: "gpt-6.1-sol"`, `mode: "plan"`,
coordination enabled, and `notify_on_idle: "once"`. Supply the original shared brief,
all three complete plans, baseline information, and their source session IDs.
Do not assume the new conversation can see sibling conversations.

Synthesis assignment:

> Critically evaluate the three independent plans against the original request
> and repository evidence. Produce one cohesive, implementation-ready plan.
> Agreement is not proof; do not majority-vote or concatenate the plans. Verify
> consequential claims in the repository. Identify shared assumptions, conflicts,
> unsupported claims, and valuable minority insights. Choose the simplest approach
> that meets the acceptance criteria. Explicitly reject unnecessary abstractions,
> dependencies, speculative changes, and scope expansion, explaining important
> exclusions briefly. Resolve conflicts through evidence; if they cannot be
> resolved, mark the precise decision or diagnostic check still needed.
> The final plan must include the objective and non-goals, diagnosis or design
> rationale, concrete ordered file/symbol-level changes, acceptance criteria,
> focused validation and regression checks, compatibility/rollback concerns,
> and remaining risks or blockers. Add a short decision record explaining what
> was adopted or rejected from each source plan. Preserve useful differences
> rather than inventing consensus. Do not implement, approve execution, open a
> pull request, or spawn other sessions. Return the consolidated plan through
> the native plan mechanism and stop in plan mode.

Read the complete consolidated plan using its exact session ID. If it has
unresolved prerequisites, resolve or present those before seeking implementation
approval. Do not launch another review round automatically.

## 4. Require the user's approval

Show the consolidated plan or its accessible artifact/session link, the key
decisions, and material risks. Ask the user whether to implement that specific
version of the plan. Use `ask_user` when asking a question; suitable choices are
`Approve implementation`, `Revise the plan`, and `Stop after planning`.

Never infer approval from the original invocation, a planner's recommendation,
an idle notification, or agreement between models. Do not create or start the
implementation conversation before explicit approval. Honor any additional
permission dialogs enforced by the app.

The synthesizer is not the implementer. Do not approve its pending plan with an
action that makes it code, and do not approve any of the three independent
planners for execution. Leave the planning conversations available for reference.
If the user requests changes, revise the synthesis in its existing conversation
using the native plan rejection/feedback mechanism when it is paused, then obtain
approval of the revised plan. Do not blindly queue messages behind a plan gate.

## 5. Implement in a new MAI-Code-2 conversation

After approval create the stage-3 child with `model: "mai-code-2"`,
`mode: "autopilot"`, an isolated worktree in the same repository,
`coordinate_with_creator: true`, and `notify_on_idle: "once"`.

Provide a standalone handoff containing the original task, the complete approved
plan, acceptance criteria, constraints, relevant baseline, and source plan
references. Follow current user-message provenance rules; do not claim that a
coordinator-authored summary is the user's verbatim approval.

Implementation assignment:

> Implement the approved consolidated plan in this conversation's isolated
> worktree. Follow repository instructions and reuse existing patterns. Recheck
> the actual baseline and relevant source before editing; plans can be stale.
> Make the smallest coherent change and run the focused validation needed to
> establish the acceptance criteria and preserve existing behavior. The plan
> guides implementation but does not override source evidence or repository
> instructions. Make routine implementation decisions locally. If evidence
> requires a material design change, new dependency, scope expansion, or risky
> behavior change, stop and report the evidence and proposed deviation to the
> coordinator for user decision. Report the resulting change, relevant
> validation outcomes, deviations, and unresolved issues. Do not create a pull
> request unless the user requested one. Do not rerun the planning council or
> spawn more reviewers.

Inspect completion and any blockers through the existing child session. Do not
claim implementation is finished merely because the child became idle. Deliver
the actual outcome and required handoff, keeping work in its owning session.

## Cost, safety, and lifecycle

- At most three independent planners, one synthesizer, and one implementer per
  run. Use existing sessions for revisions; do not grow an unbounded council.
- Keep evidence relevant. Pass complete plans, not enormous raw investigation
  transcripts. Do not force paid model reasoning tiers or promise a price ratio.
- Keep plans inspectable and source-attributed. Preserve session IDs so interrupted
  coordination can resume without duplicating paid work.
- Planning sessions remain planning-only. Implementation starts in the fifth
  conversation only after approval.
- Do not merge, publish, deploy, delete user work, change shared repository state,
  or add unrelated deliverables under this skill's authority.
- Do not auto-archive planning conversations or implementation work. Follow
  normal preservation rules and any explicit user cleanup request.
- This personal skill applies wherever the app loads personal skills, while
  repository instructions, available models/tools, trust gates, and organizational
  policies still apply. If the required session tools are absent, explain that
  limitation rather than approximating the workflow silently.
