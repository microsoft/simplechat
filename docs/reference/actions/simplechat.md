---
layout: page
title: "SimpleChat"
description: "Reference for the SimpleChat SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: simplechat -->

{% include media.html src="reference/actions-simplechat-configuration.png" alt="The SimpleChat configuration pane noting the action needs no URL or external credentials, above capability toggles for creating groups, adding users, creating conversations and workflows, and uploading Markdown documents." title="SimpleChat action configuration" capture="Capture the SimpleChat action setup or assignment UI with relevant fields visible. Redact secrets and user identifiers." %}

## What this action does

Lets agents create groups, conversations, workflows, alerts, messages, and generated documents using SimpleChat APIs.

## Why and when to use it

Use it for in-app automation. Do not enable capabilities beyond what the agent should do for users.

## Before you start

- Uses signed-in user permissions; no external credentials.
- Users also need access to the action through workspace or governance policy where applicable.

## In scheduled workflows

A scheduled workflow run acts as the workflow's owner, with the name and email stored in their SimpleChat profile, but it has no signed-in session to look people up in the directory. Two things follow:

- To add a group member from a scheduled run, give the person's object ID together with their email or display name. An email alone needs a directory lookup, which a scheduled run cannot make.
- Inviting people to a group conversation works by email, object ID or display name for anyone who is already a member of the group.

A manual run uses the signed-in session, so neither limit applies to it.

## Configuration overview

Choose the default SimpleChat capabilities exposed to agents.

Shared wizard steps: [Common action setup steps](../#common-action-setup-steps).

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents-actions/' | relative_url }})
- [Workspace identities]({{ '/admin/workspaces/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
