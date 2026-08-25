---
layout: latest-release-feature
title: Document Access Index for Faster Workspace Reads
description: Admins can serve workspace document lists from a companion index partitioned by access scope instead of querying the source containers across every partition.
section: Latest Release
generated_from_catalog: true
---

Current release version for Document Access Index for Faster Workspace Reads: **0.261.001**

Source document containers are partitioned by document id, which suits opening a single document but is expensive for list screens that ask which documents a user, group, or public workspace can see. The Document Access Index is a companion Cosmos container partitioned by access scope, so list, count, filter, and paging reads resolve inside one partition. Write-through projection keeps rows current, automatic repair and backfill reconcile drift, and an optional Redis read-through cache covers document lists, tag lists, and legacy counts with scope-version invalidation. The source containers stay authoritative and opening a document still validates access against them.

## Why It Matters

This matters because document list performance is dominated by a partitioning mismatch, and this addresses the cause rather than adding more throughput on top of it.

## How to Try It

1. Open Admin Settings > Scale > Cosmos and review Document Access Index status before changing anything.
2. Confirm write-through projection and automatic repair or backfill are enabled and healthy.
3. Read the production panel for DAI-served reads, Redis cache hits, source fallbacks, RU, and latency in your own deployment.
4. Treat a rising fallback rate as the signal to investigate rather than a reason to disable the index.
5. Use the Redis document list cache TTL to trade freshness against read cost once the fallback rate is stable.

## Where to Find It

- **Open Scale** &mdash; Review Document Access Index health, fallbacks, RU, and latency.
