---
layout: latest-release-feature
title: Auto-Login on Home Page (Entra SSO)
description: Admins can opt in to redirect unauthenticated home-page visits directly into Microsoft Entra sign-in.
section: Latest Release
generated_from_catalog: true
---

Current release version for Auto-Login on Home Page (Entra SSO): **0.261.001**

The ENABLE_AUTO_LOGIN_ON_INDEX setting sends unauthenticated visits to the home page into the Microsoft Entra sign-in flow. It supports government tenant SSO scenarios where users commonly already have a browser session.

## Why It Matters

This matters because SSO-first tenants can reduce landing-page friction while keeping the behavior explicit and opt-in.

## How to Try It

1. Open Admin Settings > Security and confirm Microsoft Entra authentication is the intended sign-in path.
2. Enable home-page auto-login only for tenants where browser SSO is expected for most users.
3. Validate the unauthenticated home-page flow in a private browser session before broad rollout.
4. Document the opt-in redirect behavior for help desk teams that support first-time access.

## Where to Find It

- **Open Security** &mdash; Review Entra SSO and home-page auto-login behavior.
