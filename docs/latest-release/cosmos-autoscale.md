---
layout: latest-release-feature
title: "Cosmos Throughput Autoscale"
description: "How admins can monitor RU pressure, scale throughput, and convert eligible Cosmos resources to native autoscale"
section: "Latest Release"
---

Cosmos Throughput Autoscale brings Cosmos DB request-unit monitoring, guarded scaling controls, policy enforcement, and native autoscale conversion into the Admin Settings Scale experience.

## User Side

This is intentionally an administrator and operator feature. End users benefit from steadier app capacity, but they do not receive Cosmos data-plane access or direct autoscale controls.

## Admin Side

Admins enable and operate this from **Admin Settings > Scale**. The screenshot gallery focuses on access validation, global scale policies, container guardrails, and native autoscale conversion controls that operators need before turning on automation.

## Why It Matters

Administrators can respond to capacity pressure without exposing Cosmos data-plane permissions to agents, actions, or end users.

## How to Try It

1. Open **Admin Settings > Scale** and refresh the Cosmos DB Throughput card.
2. Use **Validate Access** before enabling automation in a new or changed deployment.
3. Review global policy settings and container policies for dedicated-throughput containers.
4. Use native autoscale conversion only for eligible manual throughput resources.

## Notes

- This is primarily an administrator and operator capability.
- Background automation follows configured guardrails, cooldowns, and metrics windows.
- The least-privilege operator role is separate from Cosmos DB data-plane access.
