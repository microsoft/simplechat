---
layout: page
title: "SQL Query"
description: "Full guide for the SQL Query SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: sql-query -->

{% include media.html src="reference/actions-sql-query-configuration.png" alt="SQL Query action configuration UI." title="SQL Query configuration" capture="Capture the SQL Database Configuration panel with Query Plugin selected. Redact connection strings and credentials." %}

## What this action does

SQL Query executes SQL against configured SQL Server, Azure SQL, PostgreSQL, MySQL, or SQLite databases. It can validate a query, run row-returning queries, run scalar queries, and answer database questions with supplied SQL. **Max Rows** and **Timeout (seconds)** limit result size and execution time.

## Why and when to use it

Use SQL Query when the answer depends on exact relational data: joins, filters, counts, current rows, or scalar values. Pair it with SQL Schema when the agent needs table and column discovery before writing SQL. Do not use it for Snowflake or Databricks warehouses; those have dedicated actions. Do not use it for spreadsheets; use Tabular Processing. Keep **Read Only Mode** set to **Yes (Recommended)** unless writes have been separately reviewed.

## Before you start

- A reachable SQL Server, Azure SQL, PostgreSQL, MySQL, or SQLite database.
- A connection string or individual **Server**, **Database**, optional **Port**, and SQL Server **ODBC Driver** values.
- Credentials through **Username & Password**, **Integrated Authentication**, **Managed Identity (Azure)**, **Service Principal (Azure)**, **Connection String Only**, or a compatible **Reusable Identity**.
- Agents/actions enabled with [`enable_semantic_kernel`]({{ '/admin/agents-actions/' | relative_url }}).

## Configure the action

1. Choose **SQL Query**. If the combined SQL panel opens, select **Plugin Type** > **Query Plugin**.
2. Choose **Database Type**: **SQL Server**, **Azure SQL**, **PostgreSQL**, **MySQL**, or **SQLite**.
3. Choose **Connection Method**: **Connection String** or **Individual Parameters**.
4. Fill **Connection String**, or fill **Server**, **Database**, optional **Port**, and **ODBC Driver** when shown.
5. Choose **Authentication Type** and fill the shown credential fields, or choose **Reusable Identity** when available.
6. Under **Query Plugin Settings**, leave **Read Only Mode** at **Yes (Recommended)** unless writes are approved.
7. Set **Max Rows** and **Timeout (seconds)**.
8. Use **Test Connection**, then save.

## Example prompts

- "How many open support tickets were created last week by product area?"
- "List the top 20 customers by renewal risk score and include account owner."
- "Validate this query before running it: SELECT COUNT(*) FROM dbo.Events."

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Connection test fails | Connection string, server, database, driver, or credentials do not match the target. | Test the same credentials outside SimpleChat, then correct the modal fields. |
| The agent writes invalid SQL | It does not know the schema. | Pair the agent with SQL Schema or provide table and column names in instructions. |
| Results are truncated | **Max Rows** is lower than the result size. | Ask for a grouped or filtered result, or raise **Max Rows** within governance limits. |

## Related

- [SQL Schema](../sql-schema/)
- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents-actions/' | relative_url }})

