# Action Type Governance

Implemented in version: **0.242.064**

## Overview

Action Type Governance lets admins delegate permission for action families such as SQL, SimpleChat, OpenAPI, MCP, Microsoft Graph, Databricks, Tableau, Chart, Azure Maps, Blob Storage, and Document Search without requiring a configured global action instance first.

This complements existing configured global action policies. Action type policies grant create/use entitlement for a type; global action policies grant access to one deployed global action record with its configured endpoint, identity, credentials, and settings.

## Technical Specifications

Action type policies use the existing governance item policy container with these entity types:

- `personal_action_type`
- `group_action_type`
- `global_action_type`

Action type item IDs are canonicalized before storage. For example, `sql_query` and `sql_schema` both map to `sql`, so one SQL policy governs the SQL action family.

The governance evaluation model is:

- Broad feature policy allows access when its feature policy allows the user or group.
- If broad access is denied, action type policies can explicitly grant access to a specific action family.
- Missing action type policies deny access when the broad feature policy denies access.
- Configured global action use also requires the global action record to be enabled and any configured `global_action` item policy to allow the user.

## Usage Instructions

Admins configure action type access from Admin Settings > Governance > Delegated Item Policies.

Create a new policy and choose one of:

- Personal Action Type
- Group Action Type
- Global Action Type

Then choose the action type and assign allowed users or groups.

Examples:

- Allow the Finance group to create and use personal SQL actions.
- Allow five named users to create and use SimpleChat actions.
- Allow a reporting group to use global Tableau actions, while still restricting individual configured global Tableau actions with separate global action policies.

## Testing and Validation

Coverage includes:

- action type policy semantics for SQL and SimpleChat
- Personal, group, and global action type governance helpers
- global action enabled-state, action type, and configured instance authorization chain
- route and runtime wiring for personal, group, and global action loading
- admin Governance UI support for action type policy entities

Known limitation: action type policies currently control create and use together. Separate create-only and use-only policies can be added later if product requirements need that split.
