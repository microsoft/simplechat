---
layout: page
title: "Merge files in chat"
description: "Combine several CSV or Excel files that share the same columns into one CSV or Excel file."
section: "Guides"
audience: user
version: "0.261.218"
---

## What this does

Merging takes several spreadsheets with the same columns, such as one sales export per
region or one timesheet per month, and stacks their rows into a single table. The chat
then gives you that table as a downloadable CSV or Excel file.

Code does the merge, not a model. Every row is copied exactly, in the order you list the
files, so codes such as `007` keep their leading zeros, and nothing is summarized,
rounded or rewritten. The number of rows in the result is checked against the files it
came from.

## Why you would use this

Use it when you would otherwise open each file and copy-paste rows into one sheet, or ask
chat to "write a combined CSV" and hope nothing was dropped. Merging is exact and fast,
and it keeps a **Source File** column so you can always see which file each row came from.

It is not a lookup or join. Merging adds rows; it does not match rows from one file to
another on a key column, such as adding each customer's region from a second file. Ask
for that work separately.

## Before you start

- Use the V2 chat with **Orchestrate** on. An administrator must enable Chat
  Orchestration and leave **Merge spreadsheets** and **Enable Merge** on; both are on by
  default. See [orchestration settings]({{ '/admin/orchestration/' | relative_url }}).
- The files must be CSV (`.csv`) or Excel (`.xlsx`, `.xlsm`, `.xls`) documents you can
  open in SimpleChat, in a personal, group or public workspace.
- Every file needs the same column headers. The order of the columns can differ.
- Chat merges up to 10 files and 250,000 rows by default. Your administrator may set
  different limits.

## Merge files

1. Select the files in the chat's document picker, or name them in your message.
2. Ask for the merge and the file you want back, for example:

   > Merge these three regional sales files into one Excel file.

   > Combine the selected CSVs into one CSV. Don't add a column for the file name.

   > Stack the "Data" sheet from each of these workbooks into one CSV.

3. Review the plan. It shows a **Merge spreadsheets** task followed by the file to
   create. Check the files listed, then run the plan.
4. Download the file from the answer.

If you don't select the files, you can describe them, for example "merge the monthly
timesheet files from my workspace". The plan then searches for matching files first and
merges the ones it finds, so check the plan's search wording before you run it.

## What you get

- **Columns** follow the first file's column order and spelling. Headers in the other
  files are matched by name, ignoring capitalization and extra spaces.
- **Source File** is added as the first column unless you ask not to include it. If your
  files already have a column with that name, the new column is called
  **Source File (2)** instead.
- **Rows** appear file by file, in the order the files were listed. Completely blank
  rows are skipped, and rows with fewer values than columns are padded with blanks.
- **Excel values** are copied as plain text. Dates become `YYYY-MM-DD`, true and false
  become `TRUE` and `FALSE`, and formulas contribute their last calculated value.
- **Workbooks** contribute their first visible sheet unless you name a sheet, and the
  same sheet name is used in every workbook.

## If the merge doesn't run

| Message | What to do |
| --- | --- |
| The selected files don't all have the same columns | Check that every file has the same headers. Remove the files that differ, or fix their headers, and ask again. |
| A selected file couldn't be read as a CSV or Excel file | The file may be damaged or password-protected. Open and save it again without a password. |
| A selected workbook doesn't have the requested sheet | Check the sheet name, or leave it out to use each workbook's first visible sheet. |
| The merge is larger than chat allows | Merge fewer or smaller files at a time, or ask your administrator about the Merge limits. |
| Merging needs at least two different CSV or Excel files | Select at least two spreadsheets. Word, PDF and other documents can't be merged as tables. |

Nothing is created when a merge stops, so there is never a partial file to clean up.

## Related

- [Create files with orchestration]({{ '/guides/create-files-with-orchestration/' | relative_url }})
- [Orchestration settings]({{ '/admin/orchestration/' | relative_url }})
- [Document Action Capabilities]({{ '/admin/agents-actions/' | relative_url }}#document-action-capabilities-card)
