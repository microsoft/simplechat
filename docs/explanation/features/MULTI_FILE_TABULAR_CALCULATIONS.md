# Multi-file tabular calculations

Version: **0.261.437**

Implemented in version: **0.261.437**

Application version tracking remains in `application/single_app/config.py`.

## Purpose

Use Orchestrate to match records from separate CSV or Excel files, calculate
derived values, identify unmatched records, and summarize complete datasets.
For example, match orders to a price list and calculate line amounts without
asking the answering model to count sampled rows or perform the arithmetic.

This complements document accessibility/layout inspection; it does not replace
it. Native properties, comments, formatting and layout use compatible document
readers. A request involving both native inspection and numerical analysis
prepares those results separately.

## Dependencies and availability

The existing `tabular_analyze` capability must be available to the conversation,
with authorized replayable workspace CSV, XLSX, XLSM or XLS sources. There is no
new setting or external service. Each source passes the existing ownership,
workspace, content-screening and source-revision checks.

The deterministic calculation does not call an AI provider or create a file.
Planning and answer composition still use their configured models. A separate
Render step delivers a file from the retained result.

## Reading the complete selected data

Each dataset has an alias and an exact `document_id`; labels and filenames are
not authorization. Its columns are addressed as `alias.column`. Different
schemas stay separate until the plan explicitly relates their columns.

CSV identifiers and source values remain text, including leading zeros.
An optional exact `columns` array detects a changed schema. For workbooks with
multiple visible worksheets, select the intended `sheet` explicitly.

XLSX/XLSM datasets can additionally select a saved named `table_id`, or an
explicit `cell_range` with the actual worksheet `header_row`. These selectors
are mutually exclusive. Named tables exclude their declared totals row. Lineage
keeps the original worksheet row numbers, not row positions in a preview.
Each file contributes one selected dataset in this contract.

Formula cells require saved results in the selected XLSX/XLSM region. Missing
caches are errors, never zeros or empty successful results. The application does
not execute formulas, macros or external refreshes. Legacy XLS uses its saved
cell values; named-table and range selection require XLSX/XLSM.

## Executable relationship contract

The native operation is `relate`, with a `tabular-relate-v1` `relational_spec`.
Other native `query`, `transform` and `analysis` operations retain their existing
single-source contracts. Merely adding more IDs to an old operation is invalid.

The new specification declares:

| Field | Meaning |
|---|---|
| `datasets` | Ordered aliases and source IDs, matching `document_ids`; optional sheet/table/range/header/schema selectors |
| `steps` | Up to 32 ordered operations, referring only to datasets or earlier steps |
| `result` | The table whose complete records will be returned; every bound dataset must contribute |
| `output` | A deterministic `tabular-transform-v2` projection with explicit output names, types and optional nullability |

Supported operations are:

| Operation | Behavior |
|---|---|
| `join` | Explicit left, inner, anti or full join with named key pairs and declared one-to-one, many-to-one, one-to-many or many-to-many cardinality |
| `filter` | A typed Boolean predicate using the precise transformation grammar |
| `derive` | Additional fields computed with deterministic precise expressions |
| `project` | A new table containing only the explicitly projected fields, preserving source row lineage |
| `aggregate` | Grouped count, distinct count, exact decimal sum, minimum or maximum |

Keys match exactly by default. `normalization="trim_casefold"` is an explicit
alternative for text keys; it is not fuzzy entity matching. Empty keys never
match each other. `unmatched="error"` refuses missing required matches; otherwise
the chosen join kind determines whether unmatched rows are retained or excluded,
and coverage reports both sides' unmatched counts.

A join can declare an `effective` lookup with the left date field, right start
and end fields, and explicit `end_inclusive`. Dates must be ISO dates. An empty
right end is open-ended. A unique lookup rejects overlapping date intervals or
duplicate matches rather than selecting the first rate.

Use precise decimal expressions and explicit rounding for division or currency
rules. Aggregated sum/minimum/maximum values are decimal strings, so they do not
silently lose precision through binary floating-point conversion. Group counts
are integers. Source values are not rewritten.

## Example: match orders to prices

This abbreviated step shows the complete argument shape; the planner declares
`records`, `lineage` and `coverage` as named outputs.

```json
{
  "question": "Calculate order line amounts from the selected orders and price list.",
  "native_operation": "relate",
  "document_ids": ["orders-id", "prices-id"],
  "relational_spec": {
    "version": "tabular-relate-v1",
    "datasets": [
      {"alias": "orders", "document_id": "orders-id"},
      {"alias": "prices", "document_id": "prices-id"}
    ],
    "steps": [
      {
        "id": "matched",
        "op": "join",
        "left": "orders",
        "right": "prices",
        "how": "left",
        "cardinality": "many_to_one",
        "unmatched": "error",
        "on": [{"left": "orders.code", "right": "prices.sku"}]
      },
      {
        "id": "calculated",
        "op": "derive",
        "input": "matched",
        "transform": {
          "version": "tabular-transform-v2",
          "fields": [{
            "name": "amount",
            "type": "string",
            "expression": {
              "op": "multiply",
              "left": {"source": "orders.quantity"},
              "right": {"source": "prices.unit_price"}
            }
          }]
        }
      }
    ],
    "result": "calculated",
    "output": {
      "version": "tabular-transform-v2",
      "fields": [
        {"name": "code", "type": "string", "expression": {"source": "orders.code"}},
        {"name": "amount", "type": "string", "expression": {"source": "calculated.amount"}}
      ]
    }
  }
}
```

Ask in ordinary language and select the intended files. For example:

> Match the selected order lines to the selected price list by product code.
> Preserve the original quantities and prices, calculate line amounts with
> two-decimal half-up rounding, and show missing or duplicate matches separately.

A genuinely ambiguous key, worksheet, date rule or match cardinality requires
clarification. The application does not supply business rules or expected totals
from an answer key.

## Retention, exports and limits

The Reason step retains three outputs atomically:

- `records`: the complete computed table, with its exact output schema.
- `lineage`: each output record's contributing dataset/document, sheet and original
  row ranges, including all contributors to an aggregate.
- `coverage`: per-source counts and schema hashes, operation counts, matching
  diagnostics, total input/output counts and the operation contract.

Source access and revisions are checked before reading and again before
retention; producer/attempt ownership fences the final commit. Existing retained
result access, citation authority and recovery contracts remain in effect.

Compose explains the computed records rather than manufacturing them. Bind
`records` directly to an exact-tabular CSV/XLSX renderer for a download. Append
or union requests still use `tabular_merge`; a union is not a keyed calculation.

The operation uses the administrator's existing chat Merge file/row limits,
with a maximum of 100 distinct source bindings in this contract. The reader
also enforces source, workbook, column and cell limits. Graph work and cumulative
materialized values are bounded. Oversized work fails explicitly; it is not
silently shortened or automatically queued/replayed. This is a synchronous,
bounded extension, not unrestricted code execution or an unlimited database
engine. It does not admit narrative files or multiple dataset aliases for the
same document.

## Testing and validation

`functional_tests/test_tabular_relational_calculations.py` covers differing
schemas, one through ten sources, exact arithmetic, joins/unmatched records,
date-effective rates, duplicate/overlap refusal, grouped lineage, named
tables/ranges, missing formula caches and limits.

`functional_tests/test_orchestration_relational_results.py` exercises real
authorization, retained outputs, source changes/revocation, attempt fencing,
cancellation, storage failures, the compiler/executor and exact CSV rendering.
Existing merge and precise-transformation suites remain compatibility controls.
These are offline regressions, not evidence of deployment or live acceptance.
