**⚠️ NOT PRODUCTION READY — This action is a proof of concept.**

# Azure Billing Action Instructions

## Overview
The Azure Billing action is an experimental Semantic Kernel plugin that helps agents explore Azure Cost Management data, generate CSV outputs, and render server-side charts for conversational reporting. It stitches together Azure REST APIs, matplotlib rendering, and Cosmos DB persistence so prototype agents can investigate subscriptions, budgets, alerts, and forecasts without touching the production portal. It leverages message injection (direct cosmos_messages_container access) to store chart images as conversation artifacts in lieu of embedding binary data in chat responses.

## Core capabilities
- Enumerate subscriptions and resource groups via `list_subscriptions*` helpers for quick scope discovery.
- Query budgets, alerts, and forecast data with Cost Management APIs, returning flattened CSV for low-token conversations.
- Execute fully custom `run_data_query(...)` calls that enforce ISO-8601 time windows, aggregations, and groupings while emitting plot hints.
- Generate Matplotlib charts (`pie`, `column_stacked`, `column_grouped`, `line`, `area`) through `plot_chart` / `plot_custom_chart`, storing PNGs in Cosmos DB per conversation.
- Offer helper endpoints (`get_query_configuration_options`, `get_query_columns`, `get_aggregatable_columns`, `get_run_data_query_format`, `get_plot_chart_format`) so agents can self-discover valid parameters.

## Architecture highlights
- **Plugin class**: `AzureBillingPlugin` (see `azure_billing_plugin.py`) inherits from `BasePlugin`, exposing annotated `@kernel_function`s for the agent runtime.
- **Authentication**: supports user impersonation (via `get_valid_access_token_for_plugins`) and service principals defined in the plugin manifest; automatically selects the right AAD authority per cloud.
- **Data rendering**: CSV assembly uses in-memory writers, while charts are produced with matplotlib, encoded as base64 data URLs, and persisted to Cosmos DB for later retrieval.
- **Sample assets**: `sample_pie.csv`, `sample_stacked_column.csv`, and `my_chart.png` demonstrate expected data formats and outputs for local experimentation.

## Authentication & configuration
1. Provide a plugin manifest with `endpoint`, `auth` (user or service principal), and optional `metadata/additionalFields` such as `apiVersion` (defaults to `2023-03-01`).
2. Grant `user_impersonation` permission on the **Azure Service Management** resource (`40a69793-8fe6-4db1-9591-dbc5c57b17d8`) when testing user authentication.
3. For sovereign clouds, set the management endpoint (e.g., `https://management.usgovcloudapi.net`) so the plugin can resolve the matching AAD authority.

## Typical workflow
1. **Discover scope**: call `list_subscriptions_and_resourcegroups()` or `list_subscriptions()` followed by `list_resource_groups(subscription_id)`.
2. **Inspect available dimensions**: use `get_query_configuration_options()` plus `get_grouping_dimensions()` to learn valid aggregations and groupings.
3. **Fetch data**: invoke `run_data_query(...)` with explicit `start_datetime`, `end_datetime`, at least one aggregation, and one grouping. The response includes `csv`, column metadata, and `plot_hints`.
4. **Visualize**: immediately pass the returned rows or CSV into `plot_chart(...)`, selecting `x_keys`, `y_keys`, and `graph_type` from `plot_hints`. Include the same `conversation_id` so the base64 PNG is attached to the chat transcript in Cosmos DB.
5. **Iterate**: explore budgets with `get_budgets`, monitor alerts via `get_alerts` / `get_specific_alert`, or generate multi-month forecasts through `get_forecast`.

## Charting guidance
- Supported graph types: `pie`, `column_stacked`, `column_grouped`, `line`, `area`.
- `plot_chart` is a convenience wrapper that forwards to `plot_custom_chart`; both sanitize figure sizes, wrap long titles, and annotate stacked totals.
- `suggest_plot_config` can analyze arbitrary CSV/rows to recommend labels and numeric fields when the Cost Management query did not originate from this plugin.

## Outputs & persistence
- Tabular results are returned as CSV strings to minimize token usage while keeping schemas explicit.
- Chart payloads include metadata (axes, graph type, figure size) plus a `data:image/png;base64` URL; when `conversation_id` is supplied the image is chunked/stored inside `cosmos_messages_container` with retry-friendly metadata.
- The agent should describe generated charts textually to users; binary content is delivered through the persisted conversation artifacts.

## Limitations & cautions
- No throttling, retry, or quota management has been hardened—expect occasional failures from Cost Management when running multiple heavy queries.
- Error handling is best-effort: the plugin attempts to normalize enums, dates, and aggregations but may still raise when inputs are malformed.
- Cosmos DB storage assumes the surrounding SimpleChat environment; using the plugin outside that context requires replacing the persistence hooks.
- Security hardening (secret rotation, granular RBAC validation, zero-trust networking) has **not** been completed; do not expose this plugin to production tenants or sensitive billing data without additional review.

## Additional resources
- Review `instructions.md` in the same directory for the autonomous agent persona tailored to this action.
- Inspect `abd_proto.py` for prompt experimentation tied to Azure Billing dialogues.
- Leverage the sample CSV files to validate plotting offline before wiring the plugin into a notebook or agent loop.

