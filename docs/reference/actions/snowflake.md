---
layout: page
title: "Snowflake"
description: "Full guide for the Snowflake SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: snowflake -->

{% include media.html src="reference/actions-snowflake-configuration.png" alt="Snowflake action configuration UI." title="Snowflake configuration" capture="Capture Account and Warehouse, Authentication, Execution Limits, and Test Connection. Redact secrets." %}

## What this action does

Snowflake connects to one Snowflake account and warehouse for read-only data retrieval. It can run SQL and discover databases, schemas, tables, and table details.

## Why and when to use it

Use Snowflake when analytics data is stored in Snowflake and users need governed natural-language access through an agent. Do not use it for Databricks SQL Warehouses or traditional SQL Server/PostgreSQL/MySQL targets; use those dedicated actions.

## Before you start

- Snowflake **Account Identifier** without the `snowflakecomputing.com` suffix.
- **Warehouse** and optional default database, schema, role, and user.
- Password, key-pair private key, OAuth token, or compatible reusable identity.
- Agents/actions enabled with [`enable_semantic_kernel`]({{ '/admin/agents-actions/' | relative_url }}).

## Configure the action

1. Choose **Snowflake**.
2. Fill **Account Identifier** and **Warehouse**.
3. Optionally set **Default Database**, **Default Schema**, **Role**, and **Snowflake User**.
4. Choose **Authentication Method**: **Password**, **Key Pair**, or **OAuth Token**.
5. Fill **Password**, **Private Key** and optional **Private Key Passphrase**, or **OAuth Token**.
6. Set **Max Rows**, **Query Timeout (seconds)**, and **Login Timeout (seconds)**.
7. Use **Test Connection**.

## Example prompts

- "Which regions had the highest subscription growth last month?"
- "List schemas in the ANALYTICS database and describe CUSTOMER_HEALTH."
- "Query the top 50 accounts with declining usage over the last 30 days."

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Login fails | Account identifier, user, role, or credential is wrong. | Verify account identifier format and selected auth method. |
| Queries run in the wrong namespace | Default database/schema are blank or incorrect. | Set **Default Database** and **Default Schema**, or use fully qualified names. |
| Warehouse errors occur | The configured role cannot use the warehouse. | Grant warehouse usage to the role used by the action. |

## Related

- [Databricks](../databricks/)
- [SQL Query](../sql-query/)
- [Actions reference index]({{ '/reference/actions/' | relative_url }})

