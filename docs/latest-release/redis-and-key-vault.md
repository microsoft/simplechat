---
layout: page
title: "Redis and Key Vault"
description: "How cache and secret-storage guidance support more secure and predictable operations"
section: "Latest Release"
---

Redis and Key Vault improvements make it easier for teams to configure caching and secret storage patterns correctly.

## Why It Matters

The practical outcome is usually reliability and performance, with fewer environment-level issues caused by cache or secret misconfiguration.

## Where to Look

1. Review the relevant **Admin Settings** cache configuration when enabling or adjusting Redis.
2. Use Key Vault-backed secret storage when your environment standardizes on named secrets instead of raw keys.
3. Revisit the configuration if repeated-access performance or secret-handling setup needs improvement.

## Notes

- This is primarily an admin and operations feature.
- Users generally notice the results indirectly through better stability and smoother repeated access patterns.