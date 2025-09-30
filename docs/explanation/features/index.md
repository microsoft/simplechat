# explanation/features/index.md
---
layout: libdoc/page
title: Features
order: 140
category: Explanation / Version History
---

This section contains feature-related documentation grouped by folder.

{% assign feature_pages = site.pages | where_exp: "p", "p.path contains 'explanation/features/'" %}
{% assign grouped = feature_pages | group_by_exp: "p", "p.path | split: '/' | slice: -2, 1 | first" %}
{% assign sorted = grouped | sort: "name" | reverse %}

{% for group in sorted %}
  {% unless group.name == "features" %}
## {{ group.name | capitalize }}

  <ul>
    {% for page in group.items %}
      {% unless page.name == "index.md" %}
        <li>
          <a href="{{ page.url | relative_url }}">
            {{ page.title | default: page.name }}
          </a>
        </li>
      {% endunless %}
    {% endfor %}
  </ul>
  {% endunless %}
{% endfor %}
