---
layout: latest-release-feature
title: "RocksDB Key-Value Store Action"
description: "A new RocksDB action type lets agents read from an ordered key-value store through a conforming HTTP and JSON service, with get, scan, and stats tools."
section: "Latest Release"
---

Current release version for RocksDB Key-Value Store Action: **0.261.001**

The RocksDB action targets an HTTP and JSON service in front of a RocksDB store. It exposes get, scan, and stats tools for reads, plus guarded write operations, and supports no-auth, bearer token, and API key authentication. A dedicated configuration card and a Test Connection button let you confirm the endpoint before saving.

## User Side

A new RocksDB action type lets agents read from an ordered key-value store through a conforming HTTP and JSON service, with get, scan, and stats tools.

## Admin Side

Admins decide whether RocksDB Key-Value Store Action is available in your environment. If you cannot find Open Personal Workspace and Open Agents, ask whether the related settings, governance policy, or workspace access has been enabled for your account.

## Why It Matters

This matters because ordered key-value data is common in telemetry and logging systems, and agents can now query it directly instead of asking a person to run a lookup.

## How to Try It

1. Open Personal Workspace and go to the Actions section.
2. Create a new action and choose the RocksDB action type.
3. Enter the base address of the HTTP and JSON service that fronts your RocksDB store.
4. Choose no-auth, bearer token, or API key authentication to match that service.
5. Click Test Connection and confirm the endpoint responds before saving.
6. Attach the saved action to an agent and confirm the get, scan, and stats tools appear.
7. Open Chat, select that agent, and ask for a specific key or a range scan over a key prefix.

## Notes

- The RocksDB Key-Value Store Action guide belongs to the SimpleChat 0.261.001 latest-feature set.
- The gallery for this page uses `release_260_rocksdb_action_1.png`, `release_260_rocksdb_action_2.png`, `release_260_rocksdb_action_3.png` from the app Latest Features catalog.
