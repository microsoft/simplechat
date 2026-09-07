---
layout: page
title: "Actions reference"
description: "Reference for SimpleChat action types and when to use each one."
section: "Reference"
audience: user
---

## What actions are

Actions are approved tools that agents can call. They may query data, search documents, call APIs, render charts, or work with Microsoft 365 depending on how admins and workspace owners configure them.

## Common action setup steps

1. Select an action type from **Select Type**.
2. Fill **Display Name**, review generated **Name**, and add a useful **Description**.
3. Complete action-specific **Configuration** fields described on each action page.
4. In **Advanced**, optionally add **Metadata (JSON)**, **Additional Fields (JSON)**, or Key Vault expiration reminder metadata when secret tracking is enabled.
5. Review **Action Summary**, use **Test Connection** where provided, then save the action.

If an action type does not appear, check Agents settings, workspace action permissions, and Governance policy.

## Data and analytics

| Action | What it does | Typical use | Depth |
| --- | --- | --- | --- |
| [Cosmos Query](./cosmos-query/) | Runs read-only Azure Cosmos DB for NoSQL queries and validates Cosmos SQL-style queries. | Use it for governed lookup over one Cosmos container. Use SQL Query for relational databases. | overview |
| [Databricks Table](./databricks-table/) | Compatibility wrapper for legacy `databricks_table` manifests. | Use only to keep older manifests working. For new work, use Databricks. | overview |
| [Document Search](./document-search/) | Searches accessible SimpleChat documents, retrieves chunks, and summarizes documents using current user access. | Use it when an agent should reason over workspace documents as a tool. Use the normal grounded-search panel for one-off user searches. | overview |
| [Log Analytics](./log-analytics/) | Discovers Azure Log Analytics table schemas and runs read-only KQL queries against one workspace. | Use it for operational telemetry and App Insights-style investigation. Use SQL/Snowflake/Databricks for business data. | overview |
| [SQL Query](./sql-query/) | Executes SQL queries and scalar queries against configured SQL Server, Azure SQL, PostgreSQL, MySQL, or SQLite databases. | Exact relational data questions with joins, filters, counts, or current rows. | full guide |
| [SQL Schema](./sql-schema/) | Discovers tables, table schemas, and relationships for configured SQL databases. | Schema discovery before an agent writes SQL. | full guide |
| [Databricks]({{ '/reference/actions/databricks/' | relative_url }}) | Runs read-only SQL and discovers catalogs, schemas, tables, and table details through Databricks SQL Statement Execution. | Governed analytics queries in Azure Commercial Databricks. | full guide |
| [Snowflake](./snowflake/) | Runs read-only Snowflake SQL and discovers databases, schemas, tables, and table details. | Governed analytics queries in Snowflake. | full guide |
| [Tableau](./tableau/) | Discovers Tableau projects, workbooks, views, datasources, and workbook details. | Finding Tableau assets and metadata. | full guide |
| [Tabular Processing](./tabular-processing/) | Analyzes CSV and Excel files from workspaces and chat uploads with deterministic tabular operations. | Exact spreadsheet and CSV questions. | full guide |

## Microsoft 365 and identity

| Action | What it does | Typical use | Depth |
| --- | --- | --- | --- |
| [Microsoft Graph](./msgraph/) | Uses delegated Microsoft Graph permissions for profile, mail, calendar, directory, OneDrive, and security-alert operations. | User-context Microsoft 365 workflows. | full guide |

## Protocols and integration

| Action | What it does | Typical use | Depth |
| --- | --- | --- | --- |
| [Azure Maps OpenLayers](./azure-maps-openlayers/) | Creates inline OpenLayers map payloads and proxies Azure Maps raster tiles through SimpleChat. | Use it when an agent needs to turn known locations, areas, or paths into a map inside chat. Do not use it for general GIS editing or broad geocoding. | overview |
| [Yamcs](./yamcs/) | Retrieves read-only Yamcs telemetry, mission database, archive, event, packet, alarm, and link information. | Use it for mission-control visibility. Do not use it for commanding; the plugin source intentionally does not support commands or writes. | overview |
| [MCP](./mcp/) | Connects to a Model Context Protocol server and exposes selected server tools to agents. | Standard tool-server integrations. | full guide |
| [OpenAPI](./openapi/) | Turns an uploaded OpenAPI specification into callable API operations. | Documented REST API integrations. | full guide |
| [Smart HTTP](./smart-http/) | Fetches web and PDF content with content-size management, text extraction, and PDF processing. | Reading URLs, web pages, and PDFs. | full guide |

## Storage and messaging

| Action | What it does | Typical use | Depth |
| --- | --- | --- | --- |
| [Blob Storage](./blob-storage/) | Lists, reads, and uploads supported files in one configured Azure Blob container, optionally narrowed to a prefix. | Use it when an agent should work with a controlled container path without broad storage access. Use Workspace upload/search for normal SimpleChat documents. | overview |
| [Queue Storage](./queue-storage/) | Sends messages to an Azure Queue Storage queue. | Use it when an agent should enqueue work for another system. Do not use it for long-form storage. | overview |
| [RocksDB](./rocksdb/) | Reads and optionally writes keys through a RocksDB HTTP/JSON service with prefix/range scans. | Use it for low-level key-value lookup behind an approved service. Keep read-only unless writes are reviewed. | overview |

## Utilities

| Action | What it does | Typical use | Depth |
| --- | --- | --- | --- |
| [Chart](./chart/) | Builds validated inline chart payloads for line, bar, pie, scatter, area, bubble, radar, and stacked chart variants. | Use it when a visual answer is easier to understand than prose. Pair it with a data action for computed values. | overview |
| [Embedding Model](./embedding-model/) | Creates embeddings for supplied text through a configured embedding endpoint. | Use it for workflows that need vector representations, not for conversational answers. | overview |
| [Fact Memory](./fact-memory/) | Stores, updates, deletes, and retrieves persistent facts for agent context. | Use it for durable preferences or background facts. Do not store secrets or regulated data as memory facts. | overview |
| [Math](./math/) | Performs deterministic calculations such as multiply, divide, power, square root, and modulus. | Use it when an agent should calculate instead of approximating arithmetic. Use Tabular or SQL for dataset aggregations. | overview |
| [SimpleChat](./simplechat/) | Lets agents create groups, conversations, workflows, alerts, messages, and generated documents using SimpleChat APIs. | Use it for in-app automation. Do not enable capabilities beyond what the agent should do for users. | overview |
| [Text](./text/) | Provides Semantic Kernel text functions with invocation logging. | Use it for simple text transformations inside agent workflows; plain prompting is enough for many cases. | overview |
| [Time](./time/) | Provides time-related functions with invocation logging. | Use it when an agent needs current time or time calculations as a tool. | overview |
| [Wait](./wait/) | Provides wait/sleep behavior with invocation logging. | Use it only in workflows or tool chains that intentionally pause between operations. | overview |
