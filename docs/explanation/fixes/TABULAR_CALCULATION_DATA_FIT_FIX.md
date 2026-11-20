# A calculation that did not fit the data failed without being told why

Fixed in version: **0.261.470**

## Issue

In the 0.261.468 rerun of 20 November 2026, tabular analysis was the largest group of
failures. A second attempt, once the server could start one, repeated the same failure in 6 of
9 cases. What stopped each run:

| What stopped the calculation on the real data | Runs | Reported as |
|---|---|---|
| Aggregate over a column holding text | 6 | `result_invalid` |
| Comparison between mismatched types | 4 | `result_invalid` |
| Arithmetic on an empty or boolean value | 2 | `result_invalid` |
| A join matched more rows than the program declared | 2 | `relationship_grain_invalid` |
| A missing column | 1 | `calculation_program_invalid` |
| The model call itself failed | 4 | `result_invalid` |

## Root cause

A prepared calculation is written by the model at run time, in a loop that already existed:
write a program, check it, evaluate it on the complete tables, and on a rejection return the
reason for a corrected program (three model calls at most). Three things were missing.

1. **The author was not told what the columns hold.** Preparation reads every cell of every
   table, but passed on only the headers, the distinct values of columns the plan asked about
   and type facts for join keys. For any other column, including the ones being summed, the
   author had a header name and nothing else.
2. **A formatted number was not a number.** The reader accepted `1250.00` and rejected
   `1,250.00`, `$400`, `(300)` and `12%`. In a CSV file every cell is text, so an amount column
   written this way could not be summed at all.
3. **A failure on the data was never returned to the author.** The loop returned four kinds of
   structural rejection. A well-formed program that could not evaluate a row raised a different
   error class, which the loop did not catch, so the step failed at once. A second attempt
   starts a fresh loop, and the model wrote the same program again.

## Change

### Formatted numbers are numbers (`functions_tabular_transformations.py`)

`read_formatted_number` reads text that writes a number with presentation marks. Accepted,
each at most once:

- one currency symbol (any Unicode currency symbol) before or after the digits;
- commas between complete groups of three digits;
- a negative written as a leading minus, a trailing minus or surrounding parentheses;
- a trailing percent sign, which divides by one hundred, as a percent-formatted cell does.

The decimal mark is a point. Text with more than one reading, or none, is still not a number:
`1.250,00`, `1,25`, `12,34,567`, `USD 5`, `about 5`, `N/A`. The reader is used wherever a number
is required: arithmetic, aggregates, number-typed comparisons, numeric output fields
(`_parse_decimal_value`) and allocation and cumulative values (`_decimal` in
`functions_tabular_relational.py`). It is not applied to untyped comparisons or to join keys,
so an identifier is never turned into a number.

### Every column's value kinds (`functions_tabular_merge.py`)

`prepare_tabular_source_context` now returns `column_values`: for every column, how many
cells are `number`, `numeric_text`, `blank`, `boolean`, `date_text`, `text` or `other`. The
kinds come from `tabular_value_kind`, which uses the same reader as the calculation, so a cell
counted as `numeric_text` is one a sum accepts and a cell counted as `text` is one that stops
it.

These are counts, never rows or cell values, so their size does not depend on the number of
rows: a table of 50,000 rows adds only the digits of the counts (tested). The prepared context
keeps its existing 96 KB ceiling, above which preparation fails instead of sending more.

### Evaluation findings return to the author (`functions_orchestration_native_results.py`)

The loop now catches a `TabularTransformationEvaluationError` raised while evaluating the
authored program and returns it as a correction: the closed category, the step and operand,
and the kind of value expected and found. No cell value is included. The corrected program
passes the same validation and evaluation as the first, within the same three-call limit.
`[ORCHESTRATION_NATIVE] Calculation program returned to its author.` records each return with
its category, origin and calls used.

The description of the calculation language (`RELATIONAL_EXPRESSION_GRAMMAR`) states what a
numeric operand is and that comparing text that writes a number with a number needs
`value_type` number. No instruction was added to any prompt; the correction wording is
unchanged.

### Not changed, on purpose

- **A join whose matches contradict its declared cardinality is still not returned to the
  author** (`relationship_grain_invalid`). The easy correction is to relax the declaration,
  which duplicates rows and inflates totals that then pass every check. The guard from
  0.261.446 (`test_program_correction_never_repairs_genuine_interval_or_numeric_faults`)
  stands, and is asserted for this case.
- **No check rejects a program before it runs because a column contains text.** An earlier
  step of the program may legitimately remove those rows, so such a check would refuse valid
  programs. Evaluation is the exact check, and its finding now returns to the author.

## Files modified

- `application/single_app/functions_tabular_transformations.py`
- `application/single_app/functions_tabular_relational.py`
- `application/single_app/functions_tabular_merge.py`
- `application/single_app/functions_orchestration_native_results.py`
- `functional_tests/test_tabular_formatted_numbers_and_column_profile.py` (new)
- `functional_tests/test_orchestration_relational_results.py`
- `application/single_app/config.py`

## Validation

- `test_tabular_formatted_numbers_and_column_profile.py`: 30 passed. Formatted numbers are
  read and summed exactly; ambiguous text is refused; the profile and the calculation agree
  cell by cell; the profile of 50,000 rows is under 1 KB.
- `test_orchestration_relational_results.py`: a well-formed program that fails on the data is
  returned once and the corrected program completes (2 model calls); three failing programs
  stop at the limit; the join guard still refuses.
- Relational, preparation, transformation and relational-result files: 248 passed.
- `test_orchestration_research_selection.py` has 23 failures that are the same on the commit
  before this change.

## Not verified

- **Not run against a live model or the deployed application.** Whether the model, given the
  value kinds and the finding, writes a program that fits is the thing the next rerun shows.
- The four runs where the model call itself failed (`model_failed`) are not explained.
- Saved steps from earlier versions fingerprint differently because the language description
  changed, so their checkpoints are not reused; they run again.
