---
layout: page
title: "Databricks"
description: "Full guide for the Databricks SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: databricks -->

{% include media.html src="reference/actions-databricks-configuration.png" alt="The Databricks configuration pane showing workspace URL, cloud, SQL warehouse ID, default catalog and schema, personal access token authentication, and execution limits." title="Databricks action configuration" capture="Capture Workspace and Warehouse, Authentication, Execution Limits, and Test Connection. Redact tokens and IDs if needed." %}

## What this action does

Databricks uses the Databricks SQL Statement Execution API for Azure Commercial workspaces. It can execute SQL, list catalogs, list schemas, list tables, and describe a table through a configured SQL Warehouse.

## Why and when to use it

Use Databricks when governed analytics data lives in Databricks and users should query it through approved agents instead of direct warehouse tools. It is read-oriented and configured with row/time limits. Do not use it for Snowflake, generic SQL databases, or spreadsheet uploads; use Snowflake, SQL Query, or Tabular Processing instead.

## Before you start

- Azure Commercial Databricks **Workspace URL**, not the SQL statement API path.
- **SQL Warehouse ID**.
- Optional default **Catalog** and **Schema**.
- Personal access token, bearer token, service principal, managed identity, or compatible reusable identity.
- Agents/actions enabled with [`enable_semantic_kernel`]({{ '/admin/agents-actions/' | relative_url }}).

## Configure the action

1. Choose **Databricks**.
2. Set **Workspace URL**.
3. Confirm **Cloud** is **Azure Commercial**.
4. Enter **SQL Warehouse ID** and optional **Default Catalog** and **Default Schema**.
5. Choose **Authentication Method**: **Personal Access Token**, bearer token, **Service Principal**, or **Managed Identity**.
6. Fill **Token** or **Client ID**, **Client Secret**, and **Tenant ID** when those auth modes are selected, or choose **Reusable Identity**.
7. Set **Max Rows**, **Timeout (seconds)**, and **Wait Timeout (seconds)**.
8. Use the connection check in **Authentication**.

## Example prompts

- "Show the top product categories by revenue in the last completed quarter."
- "List tables in the finance schema and describe the invoice table."
- "Run a read-only query that groups daily active users by week for the past 90 days."

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Connection test cannot reach Databricks | Workspace URL is not the base workspace URL or warehouse ID is wrong. | Use the `https://adb-...azuredatabricks.net` workspace URL and SQL Warehouse ID. |
| Authentication fails | Token, service principal, or managed identity lacks workspace/warehouse access. | Grant Databricks SQL permissions and retest. |
| Long queries fail | Timeout or wait timeout is too low. | Tune the SQL or raise **Timeout** and **Wait Timeout** within limits. |


## V2 catalogue behavior

The action catalogue now de-duplicates Databricks entries by action type, so new actions show one Databricks SQL Warehouse connector. The legacy `databricks_table` type is hidden from new-action creation but existing actions of that type remain editable for review and migration.

Connection testing appears in **Authentication**, after the selected Databricks credential. The V2 editor no longer offers ad hoc custom fields; preserved legacy values remain available in **Advanced → JSON**.

## Related

- [SQL Query](../sql-query/)
- [Snowflake](../snowflake/)
- [Actions reference index]({{ '/reference/actions/' | relative_url }})
