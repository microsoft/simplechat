---
layout: page
title: "Media Status"
description: "Every screenshot and video slot in the documentation, and which ones still need to be captured."
section: "Contributing"
permalink: /contributing/media-status/
---

This is the capture worklist. Every screenshot and video slot registered in
`docs/_data/media.yml` is listed here with the exact file path it expects.

## How to fill a slot

1. Find the slot below, or find a placeholder card on any documentation page.
2. Capture the screenshot or record the video.
3. Save the image at the exact path shown. For videos, save the poster frame at
   the poster path and add the watch URL to the slot in `docs/_data/media.yml`.
4. Commit. The placeholder is replaced automatically on the next build — there
   is nothing else to change.

Screenshots should be captured at roughly 1600px wide, cropped to the relevant
region of the interface rather than the whole desktop.

Videos are never committed to the repository. Upload them to YouTube or
Microsoft Stream and link them from the slot, keeping only a small local poster
image in the repo.

{% assign all_slots = site.data.media %}
{% assign filled_count = 0 %}
{% assign missing_count = 0 %}
{% for slot in all_slots %}
  {% assign entry = slot[1] %}
  {% if entry.type == 'video' %}
    {% if entry.url and entry.url != '' %}
      {% assign filled_count = filled_count | plus: 1 %}
    {% else %}
      {% assign missing_count = missing_count | plus: 1 %}
    {% endif %}
  {% else %}
    {% assign check_path = '/images/' | append: entry.file %}
    {% assign found = site.static_files | where: 'path', check_path | first %}
    {% if found %}
      {% assign filled_count = filled_count | plus: 1 %}
    {% else %}
      {% assign missing_count = missing_count | plus: 1 %}
    {% endif %}
  {% endif %}
{% endfor %}

## Summary

| Status | Count |
| --- | --- |
| Registered slots | {{ all_slots.size }} |
| Filled | {{ filled_count }} |
| Still needed | {{ missing_count }} |

## Slots by area

{% assign groups = "" | split: "" %}
{% for slot in all_slots %}
  {% assign entry = slot[1] %}
  {% assign group_name = entry.group | default: 'ungrouped' %}
  {% unless groups contains group_name %}
    {% assign groups = groups | push: group_name %}
  {% endunless %}
{% endfor %}
{% assign groups = groups | sort %}

{% for group_name in groups %}
### {{ group_name | capitalize }}

<table class="docs-media-status-table">
<thead>
<tr><th scope="col">Slot</th><th scope="col">Type</th><th scope="col">Expected file</th><th scope="col">Status</th></tr>
</thead>
<tbody>
{%- for slot in all_slots -%}
  {%- assign slot_id = slot[0] -%}
  {%- assign entry = slot[1] -%}
  {%- assign entry_group = entry.group | default: 'ungrouped' -%}
  {%- if entry_group == group_name -%}
    {%- assign is_filled = false -%}
    {%- assign expected = '' -%}
    {%- if entry.type == 'video' -%}
      {%- if entry.poster -%}{%- assign expected = 'docs/images/' | append: entry.poster -%}{%- endif -%}
      {%- if entry.url and entry.url != '' -%}{%- assign is_filled = true -%}{%- endif -%}
    {%- else -%}
      {%- assign expected = 'docs/images/' | append: entry.file -%}
      {%- assign check_path = '/images/' | append: entry.file -%}
      {%- assign found = site.static_files | where: 'path', check_path | first -%}
      {%- if found -%}{%- assign is_filled = true -%}{%- endif -%}
    {%- endif -%}
<tr>
<td><code>{{ slot_id }}</code><br /><small>{{ entry.title }}</small></td>
<td>{{ entry.type }}</td>
<td><code>{{ expected }}</code></td>
<td>{% if is_filled %}Filled{% else %}<strong>Needed</strong>{% endif %}</td>
</tr>
  {%- endif -%}
{%- endfor -%}
</tbody>
</table>

{% endfor %}

## Adding a new slot

Register it in `docs/_data/media.yml`:

```yaml
my-slot-id:
  type: image
  title: "What this shows"
  file: "guides/my-screenshot.png"
  alt: "Accessible description of what the reader learns from the image."
  capture: "Instruction for whoever takes the screenshot."
  group: guides
  width: 1600
  height: 900
```

Then reference it from any page:

{% raw %}
```liquid
{% include media.html id="my-slot-id" %}
```
{% endraw %}

For a one-off image that does not need tracking, skip the manifest entirely:

{% raw %}
```liquid
{% include media.html src="guides/my-screenshot.png"
                      alt="Accessible description."
                      capture="What to capture." %}
```
{% endraw %}

## Live examples

The three registered seed slots render below. Because their asset files do not
exist yet, each shows the placeholder state a contributor sees.

{% include media.html id="admin-settings-overview" %}

{% include media.html id="admin-video-series" %}
