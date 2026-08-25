---
layout: latest-release-feature
title: Model Endpoint User Identity Header for APIM
description: Admins can send stable hashed user identity headers with model endpoint calls for APIM routing, quota, and attribution scenarios.
section: Latest Release
generated_from_catalog: true
---

Current release version for Model Endpoint User Identity Header for APIM: **0.261.001**

The model endpoint path can include an HMAC-hashed user identity key without exposing raw UPN, object ID, or tenant ID. Configuration supports global enablement, custom header names, selectable identity inputs, and per-endpoint overrides.

## Why It Matters

This matters because APIM policies can enforce per-user quotas and cost attribution without leaking direct user identifiers.

## How to Try It

1. Open Admin Settings > AI Models and identify the endpoints routed through APIM.
2. Enable the identity header globally only when downstream APIM policies are ready to consume it.
3. Choose the header name and identity input that match the tenant quota or attribution design.
4. Use per-endpoint overrides for providers that should not receive the hashed identity header.

## Where to Find It

- **Open AI Models** &mdash; Configure model endpoint identity header behavior.
