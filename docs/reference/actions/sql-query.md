---
layout: page
title: "SQL Database"
description: "Full guide for the SQL Database SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: sql-query -->

{% include media.html src="reference/actions-sql-query-configuration.png" alt="SQL Query action configuration UI." title="SQL Query configuration" capture="Capture the SQL Database Configuration panel with Query Plugin selected. Redact connection strings and credentials." %}

## What this action does

SQL Database executes SQL against configured SQL Server, Azure SQL, PostgreSQL, MySQL, or SQLite databases. It can validate a query, run row-returning queries, run scalar queries, and answer database questions with supplied SQL. **Max Rows** and **Timeout (seconds)** limit result size and execution time.

## Why and when to use it

Use SQL Database when the answer depends on exact relational data: joins, filters, counts, current rows, or scalar values. Schema discovery is included automatically for agents that need table context before writing SQL. Do not use it for Snowflake or Databricks warehouses; those have dedicated actions. Do not use it for spreadsheets; use Tabular Processing. Keep **Read Only Mode** set to **Yes (Recommended)** unless writes have been separately reviewed.

## Before you start

- A reachable SQL Server, Azure SQL, PostgreSQL, MySQL, or SQLite database.
- A connection string or individual **Server**, **Database**, optional **Port**, and SQL Server **ODBC Driver** values.
- Credentials through **Username & Password**, **Integrated Authentication**, **Managed Identity (Azure)**, **Service Principal (Azure)**, **Connection String Only**, or a compatible **Reusable Identity**.
- Agents/actions enabled with [`enable_semantic_kernel`]({{ '/admin/agents-actions/' | relative_url }}).

## Configure the action

1. Choose **SQL Database**. Existing manifests still use the `sql_query` type internally, and the combined SQL panel selects **Query Plugin** for row-returning queries.
2. Choose **Database Type**: **SQL Server**, **Azure SQL**, **PostgreSQL**, **MySQL**, or **SQLite**.
3. Choose **Connection Method**: **Connection String** or **Individual Parameters**.
4. Fill **Connection String**, or fill **Server**, **Database**, optional **Port**, and **ODBC Driver** when shown.
5. Choose **Authentication Type** and fill the shown credential fields, or choose **Reusable Identity** when available.
6. Under **Query Plugin Settings**, leave **Read Only Mode** at **Yes (Recommended)** unless writes are approved.
7. Set **Max Rows** and **Timeout (seconds)**.
8. Use the connection check in **Authentication**, then save.

## Example prompts

- "How many open support tickets were created last week by product area?"
- "List the top 20 customers by renewal risk score and include account owner."
- "Validate this query before running it: SELECT COUNT(*) FROM dbo.Events."

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Connection test fails | The app could not complete the database connection check. The message alone may not identify the cause. | Use the failure categories below and ask an administrator to inspect the correlated SQL connection event. |
| The agent writes invalid SQL | It does not know the schema. | Pair the agent with SQL Schema or provide table and column names in instructions. |
| Results are truncated | **Max Rows** is lower than the result size. | Ask for a grouped or filtered result, or raise **Max Rows** within governance limits. |

### Connection failure categories

Since **0.261.351**, connection testing and SQL action runtime share safe error messages. The API and supported plugin result objects include an application-owned `error_code` for connection failures; provider details remain in server telemetry.

| Error code | Meaning and next step |
| --- | --- |
| `sql_driver_unavailable` | A driver import or driver-manager lookup failed. Ask the administrator to check the deployed database driver and its dependencies. |
| `sql_connection_timeout` | A timeout was reported. Check database availability and the app's network path; this does not establish a particular firewall problem. |
| `sql_authentication_failed` | Structured provider evidence reports authentication rejection. Verify the selected authentication configuration and database access for that identity. |
| `sql_connection_failed` | The available evidence does not support a more specific category. Inspect the server diagnostic before changing authentication, TLS, or permissions. |

Administrators can find `[SQL_CONNECTION]` warnings with validated SQLSTATE and native error numbers when the provider supplies them. See [SQL connection logging]({{ '/reference/logging-tags/' | relative_url }}#sql-connection-diagnostics). A successful login using an operator's own account does not verify the App Service identity, its network path, or its selected authentication mode.

Since **0.261.356**, the connection-check failure includes a **diagnostic
reference**, shown in V2 beneath the safe error. Give that reference to an
administrator rather than copying a connection string or credential into a
support message. The matching server event distinguishes identity/configuration
resolution, driver loading, connection, and the test query. It also records
safe driver/authentication categories and environment-presence booleans, not
provider messages or secrets. These diagnostics do not change authentication,
permissions, or the existing bounded missing-driver fallback.

## V2 naming and schema discovery

The V2 action picker labels this action **SQL Database** so owners can distinguish it from warehouse-specific actions. The stored type remains `sql_query` for compatibility. Schema discovery is included automatically for agents that need table context, so the separate `sql_schema` creation card is hidden while existing `sql_schema` actions remain editable.

Connection testing appears in **Authentication**, after credentials. The V2 editor no longer offers ad hoc custom fields; preserved legacy values remain available in **Advanced → JSON**.

## Related

- [SQL Schema](../sql-schema/)
- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents-actions/' | relative_url }})
