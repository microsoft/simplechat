# explanation/scenarios/workspaces/index.md
---
layout: libdoc/page
title: Workspace Scenarios
order: 162
category: Explanation
---

{% assign fix_pages = site.pages | where_exp: "p", "p.path contains 'explanation/scenarios/workspaces/public/'" %}
{% assign grouped = fix_pages | group_by_exp: "p", "p.path | split: '/' | slice: -2, 1 | first" %}
{% assign sorted = grouped | sort: "name" | reverse %}

{% for group in sorted %}
  {% unless group.name == "fixes" %}
## {{ group.name }}

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