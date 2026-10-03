---
layout: page
title: "Merge files in chat"
description: "Combine several CSV or Excel files into one CSV or Excel file, even when their columns differ."
section: "Guides"
audience: user
version: "0.261.219"
---

## What this does

Merging takes several spreadsheets, such as one sales export per region or one timesheet
per month, and stacks their rows into a single table. The chat then gives you that table
as a downloadable CSV or Excel file.

Code does the merge, not a model. Every row is copied exactly, in the order you list the
files, so codes such as `007` keep their leading zeros, and nothing is summarized,
rounded or rewritten. The number of rows in the result is checked against the files it
came from.

The files don't need identical columns. You can keep every column from every file, line
up columns that have different names, or leave out files that don't fit, and chat can
inspect the files first to show you how they differ.

## Why you would use this

Use it when you would otherwise open each file and copy-paste rows into one sheet, or ask
chat to "write a combined CSV" and hope nothing was dropped. Merging is exact and fast,
and it keeps a **Source File** column so you can always see which file each row came from.

It is not a lookup or join. Merging adds rows; it does not match rows from one file to
another on a key column, such as adding each customer's region from a second file. Ask
for that work separately.

## Before you start

- Use the V2 chat with **Orchestrate** on. An administrator must enable Chat
  Orchestration and leave **Merge spreadsheets**, **Inspect spreadsheets** and **Enable
  Merge** on; all are on by default. See
  [orchestration settings]({{ '/admin/orchestration/' | relative_url }}).
- The files must be CSV (`.csv`) or Excel (`.xlsx`, `.xlsm`, `.xls`) documents you can
  open in SimpleChat, in a personal, group or public workspace.
- Chat merges up to 10 files and 250,000 rows by default. Your administrator may set
  different limits.

## Merge files

1. Select the files in the chat's document picker, or name them in your message.
2. Ask for the merge and the file you want back, for example:

   > Merge these three regional sales files into one Excel file.

   > Combine the selected CSVs into one CSV. Don't add a column for the file name.

   > Stack the "Data" sheet from each of these workbooks into one CSV.

3. Review the plan. It shows a **Merge spreadsheets** task followed by the file to
   create. Check the files and settings listed, then run the plan.
4. Download the file from the answer.

If you don't select the files, you can describe them, for example "merge the monthly
timesheet files from my workspace". The plan then searches for matching files first and
merges the ones it finds, so check the plan's search wording before you run it.

## Check the files first

Ask what the files contain before you merge them, for example:

> What columns do these spreadsheets have, and do they match?

The plan runs **Inspect spreadsheets**, which reads each file's sheet names, column
headers, row count and a few sample rows. The answer tells you which files share the same
columns, which columns look like the same thing under different names (such as
`Customer ID` and `customer_id`), and whether a file seems to have a title row above its
headers. Inspection never changes your files, and a file that can't be read is reported
rather than stopping the others.

## When the columns differ

Say how you want the differences handled. The plan card shows the choice in words before
you run it.

| What you want | Ask for it like this |
| --- | --- |
| Keep every column from every file. A file that lacks a column leaves it blank. | "Merge these files and keep all the columns." |
| Treat differently named columns as one column. | "Merge them, and treat `cust_id` and `CustomerID` as `Customer ID`." |
| Let chat work out how the columns line up. | "Merge these files and line up the columns that mean the same thing." |
| Keep only some columns. | "Merge them with just the Customer ID, Name and Amount columns." |
| Leave out files or sheets that don't match. | "Merge the files that have the same columns as the first one and skip the rest." |

When chat lines up the columns for you, it inspects the files, prepares a column mapping
and then merges with it. Code checks the mapping before any row is copied, and the merge
report lists which headers were mapped, which were left out, and any mapping chat marked
as uncertain. To review the differences before anything is merged, ask chat to inspect
the files first and merge in your next message.

Files that are left out are named in the merge report, and the merge step's summary says
how many were left out. The merged rows are still complete for the files that were merged.

## More ways to shape the merge

- **Headers below a title.** If each file has a title or notes above the headers, say
  which row holds the headers: "the headers are on row 3".
- **Every sheet.** Ask to merge every sheet of each workbook. Hidden and empty sheets are
  skipped, and a **Source Sheet** column records each row's sheet.
- **Duplicates.** Ask to remove rows that are exactly the same, or rows with the same
  value in one or more columns, such as the same order number. You can keep the first or
  the last copy. Missing values and empty values count as the same, and rows whose key is
  blank are always kept.
- **Order.** Ask to sort by up to three columns, as text, numbers or dates. Numbers may
  use thousands separators or a leading currency symbol; dates sort when they're written
  as `YYYY-MM-DD`, which is how Excel dates are copied. Values that aren't numbers or
  dates sort after those that are, and blanks come last. Sorting is available for merges
  of up to 250,000 rows.

## What you get

- **Columns** follow the first file's column order and spelling. Headers in the other
  files are matched by name, ignoring capitalization and extra spaces. When you keep
  every column, columns found only in later files are added at the end.
- **Source File** is added as the first column unless you ask not to include it. If your
  files already have a column with that name, the new column is called
  **Source File (2)** instead.
- **Rows** appear file by file, in the order the files were listed, unless you ask for a
  sort. Completely blank rows are skipped, and rows with fewer values than columns are
  padded with blanks.
- **Excel values** are copied as plain text. Dates become `YYYY-MM-DD`, true and false
  become `TRUE` and `FALSE`, and formulas contribute their last calculated value.
- **Workbooks** contribute their first visible sheet unless you name a sheet or ask for
  every sheet.

## If the merge doesn't run

| Message | What to do |
| --- | --- |
| The selected files don't all have the same columns | Ask to keep every column, to line up columns that have different names, or to leave out the files that don't match. |
| A selected file couldn't be read as a CSV or Excel file | The file may be damaged or password-protected. Open and save it again without a password. |
| A selected workbook doesn't have the requested sheet | Check the sheet name, leave it out to use each workbook's first visible sheet, or ask to skip workbooks without it. |
| A column named for removing duplicates or sorting isn't in the merged files | Check the column's spelling against the files' headers. Inspecting the files first lists them. |
| None of the selected files had a sheet with column headers that fit the merge | Check that the files have headers, or say which row holds them. |
| This merge's settings can't be used together | Ask again with fewer instructions at once, for example keep every column or list the columns to keep, not both. |
| The column mapping prepared for this merge isn't valid | Ask again, or name the columns to treat as the same yourself. |
| The merge is larger than chat allows | Merge fewer or smaller files at a time, or ask your administrator about the Merge limits. |
| Merging needs at least two different CSV or Excel files | Select at least two spreadsheets. Word, PDF and other documents can't be merged as tables. |

Nothing is created when a merge stops, so there is never a partial file to clean up.

## Related

- [Create files with orchestration]({{ '/guides/create-files-with-orchestration/' | relative_url }})
- [Orchestration settings]({{ '/admin/orchestration/' | relative_url }})
- [Document Action Capabilities]({{ '/admin/agents-actions/' | relative_url }}#document-action-capabilities-card)
