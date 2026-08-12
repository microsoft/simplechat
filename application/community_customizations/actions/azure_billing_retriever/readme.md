**⚠️ NOT PRODUCTION READY — This action is a proof of concept.**

# Azure Billing Action Instructions

## Overview
The Azure Billing action is an experimental Semantic Kernel plugin that helps agents explore Azure Cost Management data, generate CSV outputs, and render dynamic SimpleChat charts for conversational reporting. It stitches together Azure REST APIs and the shared SimpleChat `simplechart` renderer so prototype agents can investigate subscriptions, budgets, alerts, and forecasts without touching the production portal. You will need to move the ```azure_billing_plugin.py``` to the [semantic-kernel-plugins](../../../single_app/semantic_kernel_plugins/) folder, and move the ```schema.json``` and ```definition.json``` to the [schemas](../../../single_app/static/json/schemas) folder.

## Core capabilities
- Enumerate subscriptions and resource groups via `list_subscriptions*` helpers for quick scope discovery.
- Query budgets, alerts, and forecast data with Cost Management APIs, returning flattened CSV for low-token conversations.
- Execute fully custom `run_data_query(...)` calls that enforce ISO-8601 time windows, aggregations, and groupings while emitting plot hints.
- Generate dynamic inline charts (`pie`, `column_stacked`, `column_grouped`, `line`, `area`) through `plot_chart` / `plot_custom_chart`, returning `chart_markdown` for the chat UI.
- Offer helper endpoints (`get_query_configuration_options`, `get_query_columns`, `get_aggregatable_columns`, `get_run_data_query_format`, `get_plot_chart_format`) so agents can self-discover valid parameters.

## Architecture highlights
- **Plugin class**: `AzureBillingPlugin` (see `azure_billing_plugin.py`) inherits from `BasePlugin`, exposing annotated `@kernel_function`s for the agent runtime.
- **Authentication**: supports user impersonation (via `get_valid_access_token_for_plugins`) and service principals defined in the plugin manifest; automatically selects the right AAD authority per cloud.
- **Data rendering**: CSV assembly uses in-memory writers, while charts are returned as validated `simplechart` Markdown blocks rendered by the SimpleChat Chart.js frontend.
- **Sample assets**: `sample_pie.csv` and `sample_stacked_column.csv` demonstrate expected data formats for local experimentation.

## Authentication & configuration
1. Provide a plugin manifest with `endpoint`, `auth` (user or service principal), and optional `metadata/additionalFields` such as `apiVersion` (defaults to `2023-03-01`).
2. Grant `user_impersonation` permission on the **Azure Service Management** resource (`40a69793-8fe6-4db1-9591-dbc5c57b17d8`) when testing user authentication.
3. For sovereign clouds, set the management endpoint (e.g., `https://management.usgovcloudapi.net`) so the plugin can resolve the matching AAD authority.

## Typical workflow
1. **Discover scope**: call `list_subscriptions_and_resourcegroups()` or `list_subscriptions()` followed by `list_resource_groups(subscription_id)`.
2. **Inspect available dimensions**: use `get_query_configuration_options()` plus `get_grouping_dimensions()` to learn valid aggregations and groupings.
3. **Fetch data**: invoke `run_data_query(...)` with explicit `start_datetime`, `end_datetime`, at least one aggregation, and one grouping. The response includes `csv`, column metadata, and `plot_hints`.
4. **Visualize**: immediately pass the returned rows or CSV into `plot_chart(...)`, selecting `x_keys`, `y_keys`, and `graph_type` from `plot_hints`. Include the returned `chart_markdown` in the response so the chat UI renders the dynamic chart.
5. **Iterate**: explore budgets with `get_budgets`, monitor alerts via `get_alerts` / `get_specific_alert`, or generate multi-month forecasts through `get_forecast`.

## Charting guidance
- Supported graph types: `pie`, `column_stacked`, `column_grouped`, `line`, `area`.
- `plot_chart` is a convenience wrapper that forwards to `plot_custom_chart`; both return a validated `chart_payload`, `chart_markdown`, summary, and metadata for inline rendering.
- `suggest_plot_config` can analyze arbitrary CSV/rows to recommend labels and numeric fields when the Cost Management query did not originate from this plugin.

## Outputs & rendering
- Tabular results are returned as CSV strings to minimize token usage while keeping schemas explicit.
- Chart payloads include metadata (axes, graph type, renderer) plus `chart_markdown` containing a fenced `simplechart` block for SimpleChat's local Chart.js renderer.
- The agent should include generated `chart_markdown` in responses so SimpleChat can replace the fenced block with an interactive chart.

## Limitations & cautions
- No throttling, retry, or quota management has been hardened—expect occasional failures from Cost Management when running multiple heavy queries.
- Error handling is best-effort: the plugin attempts to normalize enums, dates, and aggregations but may still raise when inputs are malformed.
- The dynamic chart renderer assumes the surrounding SimpleChat frontend; using the plugin outside that context requires rendering or exporting the returned `simplechart` block separately.
- Security hardening (secret rotation, granular RBAC validation, zero-trust networking) has **not** been completed; do not expose this plugin to production tenants or sensitive billing data without additional review.

## Additional resources
- Review `instructions.md` in the same directory for the autonomous agent persona tailored to this action.
- Leverage the sample CSV files to validate plotting offline before wiring the plugin into a notebook or agent loop.
