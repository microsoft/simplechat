---
layout: page
title: "RocksDB"
description: "Reference for the RocksDB SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: rocksdb -->

{% include media.html src="reference/actions-rocksdb-configuration.png" alt="RocksDB action setup or assignment UI." title="RocksDB action" capture="Capture the RocksDB action setup or assignment UI with relevant fields visible. Redact secrets and user identifiers." %}

## What this action does

Reads and optionally writes keys through a RocksDB HTTP/JSON service with prefix/range scans.

## Why and when to use it

Use it for low-level key-value lookup behind an approved service. Keep read-only unless writes are reviewed.

## Before you start

- RocksDB service URL and optional bearer/API key auth.
- Users also need access to the action through workspace or governance policy where applicable.

## Configuration overview

Set Service Base URL, Authentication Scheme, Column Family, Read-Only, encodings, prefix hints, and limits.

Shared wizard steps: [Common action setup steps](../#common-action-setup-steps).

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents-actions/' | relative_url }})
- [Workspace identities]({{ '/admin/workspaces/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
