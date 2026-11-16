---
layout: page
title: "Features"
description: "Find the SimpleChat capabilities for your task, with visual explanations, practical guides, and configuration references."
section: "Features"
permalink: /features/
version: "0.261.398"
---

Start with what you need to do, then open a capability for its explanation,
full-slide illustrations where available, and practical guidance. Availability
depends on your deployment's enabled services, permissions, and source access;
not every capability has a separate switch.

## Start with the task

- **Answer from your documents:** choose a [workspace]({{ '/features/personal-workspace/' | relative_url }}),
  [process its files]({{ '/features/document-extraction/' | relative_url }}), then
  [search the permitted knowledge]({{ '/features/grounded-document-search/' | relative_url }})
  and [inspect citations]({{ '/features/enhanced-citations/' | relative_url }}).
- **Reuse a way of working:** keep instructions in [saved prompts]({{ '/features/saved-prompts/' | relative_url }}),
  equip a focused [agent]({{ '/features/agents/' | relative_url }}) with
  [approved actions]({{ '/features/core-actions/' | relative_url }}), or save a
  repeatable process as a [workflow]({{ '/features/workflows/' | relative_url }}).
- **Investigate a question:** [analyze documents]({{ '/features/document-analysis/' | relative_url }}),
  [compare revisions]({{ '/features/document-compare/' | relative_url }}),
  [compute spreadsheet results]({{ '/features/tabular-analysis/' | relative_url }}),
  or use policy-controlled [external research]({{ '/features/deep-research/' | relative_url }}).
- **Turn a goal into an outcome:** [review an orchestration plan]({{ '/features/chat-orchestration/' | relative_url }})
  and request [real files and visuals]({{ '/features/generated-deliverables/' | relative_url }}).
  Check delivery status rather than treating a planned output as a finished file.
- **Work together without losing context:** use [group knowledge]({{ '/features/group-workspaces/' | relative_url }})
  or a [collaborative conversation]({{ '/features/collaborative-conversations/' | relative_url }}),
  understand the [workspace scope lock]({{ '/features/workspace-scope-lock/' | relative_url }}),
  and inspect [conversation]({{ '/features/conversation-details/' | relative_url }})
  and [message details]({{ '/features/message-details/' | relative_url }}).
- **Govern and operate the deployment:** configure [content checks]({{ '/features/content-safety/' | relative_url }}),
  [document screening]({{ '/features/content-screening/' | relative_url }}),
  [MCP destination policy]({{ '/features/mcp-governance/' | relative_url }}),
  [retention]({{ '/features/retention-policies/' | relative_url }}),
  and [coordinated scale]({{ '/features/scale-and-cache/' | relative_url }}).

The catalog below reads directly from the same feature data as the detail pages,
so summaries and links stay together as capabilities change. Follow each page's
settings and guide links for prerequisites rather than assuming a catalog entry
means the feature is enabled.

{% assign feature_groups = site.data.features | group_by_exp: "entry", "entry[1].area" | sort: "name" %}
{% for group in feature_groups %}
{% assign entries = group.items | sort %}
## {{ group.name | escape }}

| Capability | What it does |
| --- | --- |
{% for entry in entries -%}
| [{{ entry[1].name | escape }}]({{ '/features/' | append: entry[0] | append: '/' | relative_url }}) | {{ entry[1].summary | escape | replace: '|', '&#124;' }} |
{% endfor %}
{% endfor %}
