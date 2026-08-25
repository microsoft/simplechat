---
layout: latest-release-feature
title: Per-Model Output Token Ceilings
description: Admins can set optional output-token ceilings per global model endpoint instead of relying on one tenant-wide response limit.
section: Latest Release
generated_from_catalog: true
---

Current release version for Per-Model Output Token Ceilings: **0.261.001**

Each model in the global multi-endpoint GPT configuration can now carry its own output-token ceiling. The chat path applies the correct backend token parameter for GPT-5 and o-series models as well as other OpenAI-compatible providers.

## Why It Matters

This matters because administrators can balance cost, latency, and answer depth independently for each deployed model.

## How to Try It

1. Open Admin Settings > AI Models and review each global GPT endpoint.
2. Set an output-token ceiling for high-cost or latency-sensitive models that need tighter limits.
3. Leave the ceiling empty for models that should keep provider or application defaults.
4. Test representative prompts after changing limits to confirm responses remain useful for end users.

## Where to Find It

- **Open AI Models** &mdash; Set per-model output token ceilings.
