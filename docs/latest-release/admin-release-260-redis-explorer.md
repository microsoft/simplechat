---
layout: latest-release-feature
title: Redis Explorer & Cache Observability Dashboard
description: Admins can inspect Redis safely and monitor conversation and DAI cache behavior from Scale settings.
section: Latest Release
generated_from_catalog: true
---

Current release version for Redis Explorer & Cache Observability Dashboard: **0.261.001**

Redis Explorer provides read-only, cursor-paginated key browsing with sensitive-key redaction and SimpleChat-specific DAI cache key resolution. Conversation cache and DAI cache dashboards show hit rate, miss, bypass, and invalidation events, while DAI Redis caching, conversation list/feed caching, and low-churn bootstrap caching include enable toggles, TTL controls, and invalidation coverage.

## Why It Matters

This matters because cache performance and cache safety can be observed without exposing sensitive values or using direct Redis tooling.

## How to Try It

1. Open Admin Settings > Scale and review Redis connection and cache enablement state.
2. Use Redis Explorer for read-only key browsing when troubleshooting cache behavior.
3. Review hit, miss, bypass, and invalidation metrics before changing TTL values.
4. Keep sensitive-key redaction enabled and avoid using cache dashboards as a data export path.

## Where to Find It

- **Open Redis & Caching** &mdash; Inspect Redis and review cache metrics, toggles, and TTLs.
