---
layout: latest-release-feature
title: "Governance and Access Controls"
description: "How governance policies control endpoints, agents, actions, delegated review, and action-type availability"
section: "Latest Release"
---

Current release version: **0.250.001**

Governance policies now cover endpoints, agents, actions, feature access, delegated item review, and action-type availability across personal, group, and global scopes.

## User Side

Users see only the governed endpoints, agents, actions, and action types their account or group is allowed to use. Delegated personal or group items can follow review workflows before broader use.

## Admin Side

Admins manage feature policies, delegated item policies, review workflows, allowlists, and action-type controls from Admin Settings governance surfaces.

## Screenshot Placeholder

Replace `/images/latest-release/release_250_governance.png` with a screenshot of feature policies, endpoint/agent/action policy controls, delegated review, and action-type governance.

## Why It Matters

Broader AI capabilities need a reviewable access model that scales beyond one global on/off switch.

## How to Try It

1. Open **Admin Settings > Governance**.
2. Review feature policies for endpoints, agents, actions, and action types.
3. Confirm the user-facing picker only shows allowed items.

## Notes

- Governance cache versioning reduces stale reads after admin policy changes across Redis-enabled and no-Redis deployments.
