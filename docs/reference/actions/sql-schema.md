---
layout: page
title: "SQL Schema"
description: "Full guide for the SQL Schema SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: sql-schema -->

{% include media.html src="reference/actions-sql-schema-configuration.png" alt="SQL Schema action configuration UI." title="SQL Schema configuration" capture="Capture the SQL Database Configuration panel with Schema Plugin selected. Redact connection strings and credentials." %}

## What this action does

SQL Schema inspects a configured relational database and returns database schema, table lists, table details, and foreign-key relationships. It is the discovery companion for SQL Query.

## Why and when to use it

Use SQL Schema when an agent must understand table names, column names, types, and relationships before creating SQL. It is safer than pasting schema into prompts and reduces invalid queries. Do not use it to retrieve business rows; use SQL Query for data retrieval. The create-action UI hides the separate `sql_schema` type, but the combined SQL configuration panel includes **Schema Plugin**.

## Before you start

- A supported SQL database reachable by the app.
- Credentials with permission to inspect metadata for the relevant schema.
- A decision about **Include System Tables**; the recommended default is **No**.
- Agents/actions enabled with [`enable_semantic_kernel`]({{ '/admin/agents-actions/' | relative_url }}).

## Configure the action

1. Choose the SQL action flow and select **Plugin Type** > **Schema Plugin**.
2. Choose **Database Type** and **Connection Method**.
3. Fill **Connection String** or individual **Server**, **Database**, **Port**, and **ODBC Driver** fields.
4. Choose **Authentication Type** and provide credentials or a **Reusable Identity**.
5. Under **Schema Plugin Settings**, keep **Include System Tables** set to **No (Recommended)** unless system metadata is required.
6. Use **Table Filter** to narrow discovery, for example `user_*` or `*_log`.
7. Use **Test Connection** before saving.

## Example prompts

- "What tables are available for order history, and how are they related?"
- "Describe the schema for dbo.Customer and dbo.Invoice."
- "Find likely join paths between tickets and accounts before writing a query."

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Schema output includes too much noise | System tables or broad schemas are included. | Turn off **Include System Tables** and add a **Table Filter**. |
| The agent cannot see relationships | Metadata permissions are missing or relationships are not defined as foreign keys. | Grant metadata visibility or document the relationship in agent instructions. |
| The action type is not visible as a separate card | `sql_schema` is hidden from the create-action UI. | Use the combined SQL configuration panel and choose **Schema Plugin**. |

## Related

- [SQL Query](../sql-query/)
- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents-actions/' | relative_url }})

