---
layout: page
title: "Tableau"
description: "Full guide for the Tableau SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: tableau -->

{% include media.html src="reference/actions-tableau-configuration.png" alt="Tableau action configuration UI." title="Tableau configuration" capture="Capture Server and Site, Authentication, Discovery Limits, and Test Connection. Redact credentials." %}

## What this action does

Tableau is a read-only discovery action built on Tableau Server Client. It searches Tableau content and lists projects, workbooks, views, datasources, and workbook details.

## Why and when to use it

Use Tableau when users need to find or reason about Tableau assets without switching contexts. It is for metadata and content discovery, not rendering Tableau dashboards or editing assets. For underlying data questions, use the source action such as Snowflake, Databricks, or SQL.

## Before you start

- Tableau Server or Tableau Cloud base **Server URL**.
- Optional **Site Content URL**; leave blank for the default Tableau Server site.
- Personal Access Token name/secret or username/password.
- Agents/actions enabled with [`enable_semantic_kernel`]({{ '/admin/agents-actions/' | relative_url }}).

## Configure the action

1. Choose **Tableau**.
2. Set **Server URL** without the site path.
3. Set **Site Content URL** if the site is not the default.
4. Choose **Authentication Method**: **Personal Access Token** or **Username and Password**.
5. Fill **PAT Name** and **PAT Secret**, or **Username** and **Password**.
6. Set **Page Size**, **Max Results**, **Timeout (seconds)**, and **Use Tableau server version negotiation**.
7. Use **Test Connection**.

## Example prompts

- "Find workbooks related to quarterly pipeline and list their views."
- "Which datasources are used by this workbook ID?"
- "Search Tableau projects for finance reporting assets."

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| No content is returned | The Tableau credential can sign in but lacks content access. | Grant Tableau permissions or use a PAT for a user with intended access. |
| Site sign-in fails | Site Content URL includes the full path or is wrong. | Use only the content URL segment, or leave blank for the default site. |
| Version errors appear | Server version negotiation does not match the environment. | Toggle **Use Tableau server version negotiation** and retest. |

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Databricks](../databricks/)
- [Snowflake](../snowflake/)

