---
layout: latest-release-feature
title: "Reference Actions and Knowledge Directly in Agent Instructions"
description: "Agent instructions can now name the exact actions and documents an agent holds using autocompleted hash-action and hash-knowledge tokens, and the agent builder reorders its steps so instructions come last."
section: "Latest Release"
---

Current release version for Reference Actions and Knowledge Directly in Agent Instructions: **0.261.001**

While writing agent instructions you can type a hash character to open an autocomplete listing the actions, capabilities, and documents that agent actually has, then insert a precise reference instead of describing the tool in prose. The agent modal now runs Actions, then Knowledge, then Instructions, so you choose capabilities before you write about them, and a collapsible summary panel shows your selections while you write.

## User Side

Agent instructions can now name the exact actions and documents an agent holds using autocompleted hash-action and hash-knowledge tokens, and the agent builder reorders its steps so instructions come last.

## Admin Side

Admins decide whether Reference Actions and Knowledge Directly in Agent Instructions is available in your environment. If you cannot find Open Agents and Open Chat, ask whether the related settings, governance policy, or workspace access has been enabled for your account.

## Why It Matters

This matters because vague instructions are the most common reason an agent ignores a tool you gave it, and naming the capability directly removes that guesswork.

## How to Try It

1. Open Agents and create a new agent or edit an existing one.
2. Work through the Actions step first and attach the actions this agent should be able to call.
3. Move to the Knowledge step and select the workspaces or documents it should ground on.
4. Continue to the Instructions step and expand the summary panel to review what you selected.
5. Start typing a hash character in the instruction editor to open the reference autocomplete.
6. Insert an action or knowledge reference so the instruction names the capability exactly.
7. Use Draft Instructions if you want a starting point, then save and test the agent in Chat.

## Notes

- The Reference Actions and Knowledge Directly in Agent Instructions guide belongs to the SimpleChat 0.261.001 latest-feature set.
- The gallery for this page uses `release_260_agent_instruction_references_1.png`, `release_260_agent_instruction_references_2.png`, `release_260_agent_instruction_references_3.png` from the app Latest Features catalog.
