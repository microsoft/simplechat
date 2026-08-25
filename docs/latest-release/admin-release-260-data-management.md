---
layout: latest-release-feature
title: 'Enterprise Data Management: Backup, Restore & Migration'
description: Admins can run durable backup, restore, migration, and inspection workflows from the refreshed Backup, Migrate & Restore experience.
section: Latest Release
generated_from_catalog: true
---

Current release version for Enterprise Data Management: Backup, Restore & Migration: **0.261.001**

Backup jobs now cover Cosmos DB, AI Search, and Blob Storage with keyset paging, ETag verification, adaptive throttling, resume, and retention policies. Restore adds admin-only preflight checks, overwrite confirmation, durable restore jobs, and the migration engine supports delta and mirror modes with provenance tracking and per-resource checkpoints.

## Why It Matters

This matters because tenant data operations can be planned, audited, resumed, and recovered without relying on one-off scripts.

## How to Try It

1. Open Admin Settings > Backup, Migrate & Restore and review the setup guidance before enabling production jobs.
2. Configure storage, source resources, and retention policies for Cosmos DB, AI Search, and Blob Storage backups.
3. Use preflight checks and overwrite confirmations before running restore jobs against live tenant data.
4. Choose delta or mirror migration mode deliberately and monitor per-resource checkpoints for long-running migrations.

## Where to Find It

- **Open Data Management** &mdash; Configure backup, migration, restore, storage, and inspection workflows.
