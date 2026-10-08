---
layout: page
title: "Control Center"
description: "Reference for the read-only Control Center action that answers usage questions in chat."
section: "Reference"
audience: admin
---

<!-- action-slug: control-center -->

{% include media.html src="reference/actions-control-center-configuration.png" alt="The Control Center action configuration, noting that it needs no connection settings and runs as the signed-in Control Center viewer." title="Control Center action configuration" capture="Capture the Control Center action in the V2 admin action editor with the type selected. Redact user identifiers." %}

## What this action does

Answers questions about how SimpleChat is being used, from the same data as the Control Center dashboard. It reports sign-ins and daily, weekly and monthly active users; conversations created; document uploads by workspace type and processing failures; and token usage by day, model, usage type, user, group or public workspace. It can rank the most active users, groups and public workspaces, show sign-ins by weekday and hour, and look up a person, group or public workspace by name so a question can be narrowed to one of them.

Each answer comes back as rows that orchestration can chart, with the date range it covers and a definition of every figure. Because the action and the dashboard share one aggregation, a figure in chat matches the dashboard for the same dates.

## Why and when to use it

Use it to ask the dashboard questions in plain language, such as "how did sign-ins this month compare with last month?", "which groups used the most tokens last week?" or "chart Jane's token use by model for September". The Control Center's **Chat with this dashboard** button opens an orchestrated chat that uses this action, with a prompt describing the dates and token filters on screen.

It is read-only. It cannot change users, groups, workspaces or settings, and it does not accept query text: every function runs fixed, parameterized reads with bounded results.

## Who can use it

Only people who can view the Control Center dashboard: an **Admin**, or a **ControlCenterAdmin** or **ControlCenterDashboardReader** where the Control Center role settings require those roles. Everyone else never sees the action in chat, and orchestration refuses to run it for them.

The action checks this again on every call, using the signed-in person's own roles. A scheduled workflow run has no signed-in session, so the action refuses it.

## Before you start

- **Enable Agents** must be on in **Admin Settings › Agents & Actions › Agent Runtime**.
- To use it from chat, **Enable Chat Orchestration** and **Enable Action Access** must be on in **Admin Settings › Orchestration**, and the orchestration **Capabilities** list must allow **Use an action** (an empty list allows every capability).
- Create it as a global action. Personal and group workspaces cannot create or use the Control Center type.
- When **Workspace Mode** is on, turn on **Add Global Agents and Actions to Workspaces** so global actions, including this one, are offered in chat.
- If **Govern Global Actions** is on, governance must allow the people who should use it.

## Configuration overview

In **Admin Settings › Agents & Actions › Global Actions**, choose **New action**, then **Control Center**. There is nothing to connect: the action has no endpoint, credentials or extra fields, and always runs as the signed-in person. Give it a description if you want to steer when orchestration chooses it; a blank description is replaced with one that names the questions it answers.

Shared wizard steps: [Common action setup steps](../#common-action-setup-steps).

## Functions

| Function | What it returns |
| --- | --- |
| `get_dashboard_summary` | The headline figures for a date range, each compared with the previous range of the same length, with a definition of each. |
| `get_daily_activity` | Daily sign-ins, conversations created and uploads by workspace type, optionally for one user, workspace type, group or public workspace. Sign-ins are not recorded against a workspace, so workspace filters narrow conversations and uploads only. |
| `get_token_usage` | Tokens totalled by day, model, usage type, user, group or public workspace, with optional filters for user, workspace, model and usage type. |
| `get_top_activity` | The users, groups or public workspaces with the most recorded actions. |
| `get_sign_in_pattern` | Sign-ins totalled by UTC weekday and hour. |
| `find_entities` | The ID of a user found by name or email, or of a group or public workspace found by name, for use as a filter. |

Dates are UTC. A range is either explicit start and end dates or a number of days ending today, up to 366 days. Ranked and grouped results return at most 50 rows.

## Related

- [Use the V2 Control Center]({{ '/guides/v2-control-center/' | relative_url }})
- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents-actions/' | relative_url }})
- [Orchestration]({{ '/admin/orchestration/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
