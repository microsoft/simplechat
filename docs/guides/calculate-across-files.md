---
layout: page
title: "Calculate across selected files"
description: "Match and calculate complete CSV or Excel records without confusing data with document layout."
section: "Guides"
audience: user
version: "0.261.437"
---

Implemented in version: **0.261.437**, tracked in
`application/single_app/config.py`.

## Select the related data and name the relationship

Select the intended workspace CSV or Excel files and use Orchestrate. Explain
which columns connect the files and what should be calculated. Files do not
need identical columns.

> Match Orders to Prices using product code. Keep the original quantities and
> prices, calculate each line amount with two-decimal half-up rounding, and show
> missing or duplicate matches rather than guessing a price.

For date-dependent reference data, state which date determines the lookup and
whether an ending date is included. An ambiguous rate, duplicate key or unclear
worksheet may require clarification. Document names and instructions do not
grant access to another workspace.

Combining rows is different from matching them. Ask to append/stack files when
you want one combined table; ask to match/relate records when values in one file
depend on keys in another.

## Choose the intended workbook region

Name the worksheet when a workbook has several sheets. For separate data regions,
name the saved Excel table or give its range and actual header row. The
calculation reads that complete selected table, not a few displayed examples.
Named tables exclude their declared totals row so it is not counted twice.

CSV identifiers keep leading zeros. Workbook calculations use saved cell values;
missing formula results are not zeros. Save recalculated results in Excel if
needed. SimpleChat does not run workbook formulas, macros or external refreshes.

## Keep calculations and layout inspection separate

Both capabilities remain available. For example:

> Calculate the monthly totals from these selected files. Separately inspect the
> workbook's native comments and formatting, and explain any inspection limits.

The plan uses compatible readers for each part. A CSV has rows but no Word,
PDF or Excel native-layout inventory. An unsupported layout check does not mean
that its data file is missing, and a successful data calculation does not prove
accessibility compliance.

For an explicitly related follow-up, such as “use the same files to explain the
unmatched items,” the server rechecks the intended file references. A new explicit
selection takes precedence. Suggested files are not an exhaustive workspace list.

## Check the result before relying on it

Review source coverage, matched/unmatched counts and the stated relationship.
The retained calculation includes the complete computed records and their
contributing document, sheet and original row references. The answer explains
those computed values rather than estimating them from a preview.

Ask for a CSV or workbook when you need a download. It is delivered only after
the calculation and the separate file-creation step succeed. A planned file or
an inline table is not a completed download.

File, row, column, source-size and processing limits still apply. Work that
exceeds a bound fails explicitly; results are not silently shortened. This
contract supports a selected dataset from each distinct file, not unrestricted
database queries or multiple aliases for different regions of the same file.

See [Tabular Processing]({{ '/reference/actions/tabular-processing/' | relative_url }})
and [Inspect Excel data, comments, and structure]({{ '/guides/inspect-excel-workbooks/' | relative_url }})
for related capabilities.
