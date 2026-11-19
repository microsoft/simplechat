---
layout: page
title: "RocksDB"
description: "Reference for the RocksDB SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: rocksdb -->

{% include media.html src="reference/actions-rocksdb-configuration.png" alt="The RocksDB configuration pane showing the service base URL and authentication scheme, and data handling options for column family, read-only mode, key and value encoding, and key prefix hints." title="RocksDB action configuration" capture="Capture the RocksDB action setup or assignment UI with relevant fields visible. Redact secrets and user identifiers." %}

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

## Connection destinations

Implemented in version: **0.261.435** (`application/single_app/config.py`).

Private service FQDNs and private IPs remain supported when reachable from
SimpleChat. Connection tests and runtime operations now refuse loopback,
link-local and cloud infrastructure destinations, including DNS aliases and
redirects to those addresses. Localhost refers to the SimpleChat host, not
an operator's workstation.

Unchanged actions keep their credentials. When moving a service to a different
origin, re-enter or clear its stored token rather than carrying a masked value
to the new server. Connection probes read a bounded health/scan response.
See [connection compatibility]({{ '/guides/workspace-agents-and-actions/' | relative_url }}#connection-destinations-and-compatibility)
for existing-action upgrade considerations.

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents-actions/' | relative_url }})
- [Workspace identities]({{ '/admin/workspaces/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
