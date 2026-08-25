---
layout: latest-release-feature
title: Cosmos Maintenance and Throughput Guardrails
description: Admins can apply missing Cosmos indexes, rebuild caches, and let SimpleChat scale throughput within explicit guardrails.
section: Latest Release
generated_from_catalog: true
---

Current release version for Cosmos Maintenance and Throughput Guardrails: **0.261.001**

Cosmos Maintenance keeps its status view read-only and requires an explicit confirmation before applying missing expected composite indexes. Those updates are additive and preserve existing indexing policy paths, but they add write-index overhead and trigger asynchronous Cosmos index transformation. Maintenance also rebuilds low-churn and conversation caches and clears retired operational artifacts in bounded batches. Separately, throughput automation raises and lowers RU using configurable thresholds, steps, and cooldowns, bounded by minimum and maximum guardrails, with SimpleChat-managed scaling stopping at 10,000 RU/s.

## Why It Matters

This matters because index and capacity changes are exactly the operations that should be deliberate, reversible, and bounded rather than automatic and silent.

## How to Try It

1. Open Admin Settings > Scale > Cosmos and refresh Cosmos Maintenance status.
2. Review which expected composite indexes are reported missing before applying anything.
3. Read the confirmation dialog carefully; index transformation runs asynchronously after you confirm.
4. Set throughput thresholds, steps, and cooldowns against your observed RU baseline, not a guess.
5. Keep the minimum and maximum guardrails in place so automation cannot scale beyond intended spend.

## Where to Find It

- **Open Scale** &mdash; Run Cosmos maintenance and configure throughput guardrails.
