# V2 Comparison Analyze Evidence Matching Fix (v0.261.191)

**Fixed in version: 0.261.191**

The application version is tracked in `application/single_app/config.py`.

Refs #1540.

## Issue

In the V2 chat interface, a user selected two files and asked to compare them: a
narrative PDF containing many tables, and a 200-row CSV. The plan was sound. It
analyzed the PDF, prepared the CSV, then composed the comparison. The run ended
**Partially completed**, and its third step, **Prepare the file comparison**, failed
with:

> The operation did not produce the complete named results declared by the plan.

That step is a `compose` step. It writes the comparison as text for the answer and
never creates a file. The message suggested that compose had produced a malformed
result, but compose never ran. It stopped before calling the model, because one of
its inputs was incomplete.

## Root cause

### How the failure reached compose

Compose's inputs are planned with `allow_partial: false`, because a comparison needs
the complete results of the steps that prepared each source. The PDF's
`document_analyze` step ended with a **partial** result, so the result store refused
to open it for compose and raised `ResultNotReadyError`. That error is a
`ResultContractError`, and the executor reported every contract error as
`result_invalid`, whose message blames the step that could not run.

Refusing the partial input was correct. The failure report was wrong, and so was the
reason Analyze returned a partial result.

### Why Analyze was partial

Analyze produced 35 candidate findings from four windows of the PDF and accepted one.
The saved run recorded these validation issues:

- `unmatched_evidence` ×203
- `invalid_evidence_reference` ×20
- `unresolved_finding` ×18
- `window_requirement_unresolved` ×5

There were three causes.

**Evidence matching was literal.** Each finding must quote passages that the
application can locate in the chunk the finding cites. The check was
`chunk_text.find(quote)`, so a quote matched only when it was identical, character
for character, to the stored chunk. Document Intelligence stores tables as HTML and
keeps line breaks, while models quote tables as readable text. All 226 quoted
passages were compared with the saved chunks:

| What the quote needed in order to match the chunk text | Passages |
| --- | --- |
| Nothing: an exact substring, the only form accepted before this fix | 23 |
| Whitespace and line breaks collapsed | +6 |
| HTML table tags removed | +23 |
| Table pipes treated as cell separators | +174 |
| **Not present in the source at all** | **0** |
| **Present in more than one chunk** | **0** |

Every citation named the correct chunk. Because one unmatched passage leaves its
whole finding unresolved, presentation markup alone rejected correctly grounded
findings.

**Qualifications were treated as blocking issues.** All 35 findings had the status
`supported`, but 18 also listed a qualification under `issues`, such as a year,
currency or unit that the excerpt does not state. Any finding-level issue leaves the
finding unresolved, and the response format offered no other place to put a
qualification.

**The comparison goal reached the per-source step.** Two of the five window-level
issues said that no CSV had been supplied, so the comparison could not be made. The
Analyze step sees only its own source; compose performs the comparison. The other
three window issues were a slice that ended partway through a table and two
informational remarks. Any window-level issue makes the whole Analyze result partial.

### Why it was hard to diagnose

No log named the producer whose partial result stopped compose, or explained why that
result was partial. The run record showed only `result_invalid` on compose.
Separately, the per-window debug line always printed `page_range=None:None`, because
it read keys that the window range does not have.

## Technical details

### Formatting-insensitive evidence matching

`functions_document_analysis_results.py` now locates evidence with
`evidence-matcher-v2`, recorded as `EVIDENCE_MATCHER_VERSION` on each window result
and on the final validation. It tries three tiers in order and stops at the first
tier with a match:

1. `exact`: the previous `find`, with the same offsets.
2. `normalized`: the quote and each cited chunk are compared after presentation
   differences are removed.
3. `normalized_casefold`: the same comparison, ignoring case.

The normalized comparison keeps every word and number separate, and drops only what
renders as nothing:

- Whitespace, Markdown table pipes and delimiter rows, HTML comments, and structural
  tags such as `<td>`, `<br>`, `<p>` and `<sup>` each become a single separator. A
  quote of `North $1,200` matches `<td>North</td><td>$1,200</td>`, but `Units 1200`
  does not match `<td>Units</td><td>1</td><td>200</td>`, and `1,200` does not match
  `1, 200`. The amount of whitespace does not matter; whether there is any does.
- Inline formatting tags such as `<b>`, `<em>`, `<span>` and `<a>` are dropped, as
  are soft hyphens, zero-width and text-direction characters, and emphasis or code
  marks (`*`, `_` and backticks) at the edge of a word, as in `**Note**:`.
- Character entities are decoded only after tags are handled, so escaped text is never
  read as markup.
- Typographic quotes, and the prime and double prime, fold to `'` or `"`. An acute
  accent typed as an apostrophe, as in `can´t`, also folds to `'`. Hyphen, dash and
  minus variants fold to `-`.
- Unicode NFKC is applied to non-ASCII characters, such as ligatures and full-width
  digits. Each character is normalized together with the marks that follow it, so a
  decomposed accent or a two-part vowel sign matches its single-character form.
  Superscripts, subscripts, fractions, and circled or squared forms keep their shape,
  so `10⁶` never becomes `106`.
- A leading `[Page X, Chunk Y]` label is ignored. The window prompt places that label
  before each chunk, and a model may copy it.

The quote and the chunk go through the same steps.

What counts as evidence has not been relaxed:

- Written characters are compared, never removed. Signs, comparison symbols, bullets,
  list and heading markers, checkbox symbols, and an asterisk or underscore that
  stands alone or joins two letters or digits must appear in the quote as they do in
  the source. So `>50% of cases` does not match `<50% of cases` or `≤50% of cases`,
  and `23` does not match `2*3`.
- A normalized match must start and end on whole words and numbers.
  - A word includes its combining marks, such as Indic vowel signs and Arabic vowel
    marks, and connectors such as the `_` in `snake_case_name`. So `rate` never
    matches inside `separate`, even when a soft hyphen splits the word, and
    `case_name` never matches inside `snake_case_name`.
  - A number includes digits joined by `,`, `.`, `'`, an Arabic decimal or thousands
    separator, or a single no-break, narrow no-break, figure or thin space. So
    `Total revenue 1,200` does not match `Total revenue 1,200,000`, `Rate 4` does
    not match `Rate 4.5%`, and `Total 1 200` does not match `Total 1 200 000`
    grouped with narrow no-break spaces.
  - A match never ends before an apostrophe that joins two letters or digits, because
    the suffix can change the meaning. So `They can` does not match `They can't renew`,
    and `The 1990` does not match `The 1990's trend`. A match may still start after an
    elided prefix, so `augmentation des prix` matches `l'augmentation des prix`.
  - A match may still end before a sentence period or a list comma, as in
    `Revenue 1,200.` or `1.5, 2.5`, because no digit follows.
- Citations stay strict. A passage needs a `chunk_sequence`, `page_number` or
  `chunk_id`, and every selector it gives must match the chunk. A quote that exists
  only in another chunk still fails.
- If more than one cited chunk matches at a tier, the passage is ambiguous and is
  rejected; later tiers are not tried.
- Paraphrases, ellipses, partial words and quotes joined from different chunks are not
  located. A quote that is empty once normalized, such as one containing only markup
  or a chunk label, is rejected.
- One unlocated passage still leaves its finding unresolved.

An independent review of an earlier draft, which deleted whitespace, pipes and line
markers instead of treating them as separators, showed why this matters: `1,200`
matched `1, 200`, and `>50%` matched `<50%`. A second review found two more gaps.
A match could stop partway through a number, as in `1,200` inside `1,200,000`, or
beside a vowel sign or other combining mark, which the boundary check did not count
as part of a word. The whole-word and whole-number rule above closes both. A third
review found that a match could still end before an apostrophe inside a word, so
`They can` matched `They can't renew`, and `Vendor can` matched the table cells
`Vendor` and `can't comply`. The apostrophe rule above closes that. Each case from
the three reviews is now a rejection test.

The window prompt asks for a short, contiguous passage copied from one chunk, keeping
its words, numbers, signs and symbols as written. Table cells may be quoted in reading
order.

Saved evidence stays verbatim. Its `text` is the original chunk span,
`chunk_text[start_char:end_char]`, never the model's wording, and `location.match`
records the tier that located it. The `unmatched_evidence` issue for each unlocated
passage now records a diagnostic `reason`: `missing_quote`, `missing_location`,
`ambiguous`, `not_in_cited_location` or `not_in_window`. The issue code and the
acceptance rules are unchanged.

### Caveats and notes

The `analyze-final-v1` window response has two new optional fields, so that
qualifications and observations no longer block a result:

- **Finding `caveats`** are qualifications that do not stop the values being final,
  such as an unstated unit, currency, period or entity. An accepted record carries the
  sorted, de-duplicated caveats of every candidate that contributed to it. The key is
  omitted when there are none, so existing record shapes do not change. Records reach
  compose through Analyze's `findings` output, so compose sees the caveats. The
  report lists them under the finding as `Caveat:` lines.
- **Window `notes`** are observations about the slice, such as a table that continues
  past it. Notes are kept on the work unit and in
  `analysis_diagnostics.work_unit_notes`, and the report lists them under
  **Analysis notes**. They are not validation issues and never change the result's
  status.

A `caveats` value that is not a list of strings gives the finding an `invalid_caveats`
issue. A `notes` value that is not a list of strings makes the window response
invalid, as an invalid `issues` value already does. Responses without the new fields
behave as before, and `issues` still block.

The window prompt now defines `issues` narrowly. At finding level they are only
problems that stop a requested value being concluded from the slice, such as
contradictory values; values absent from the slice are not issues. At window level
they are only task requirements that the slice's own content leaves unresolved, never
sources that are analyzed separately.

### Per-source scoping

- **Planner** (`functions_orchestration_planner.py`). For mixed narrative and tabular
  comparisons, each preparation step is asked only for its own sources' contribution,
  such as values, periods, units and identifiers. A preparation step sees only its own
  sources, so it is never asked to compare them with, or look for, another source.
  Compose performs the comparison.
- **Window prompt** (`functions_document_analysis.py`). Other slices, files and
  datasets are analyzed separately and combined afterwards. The model reports only
  what its slice contributes, and does not compare it with another source or decide
  that another source is missing.

These instructions describe how a plan divides work. Nothing depends on particular
files, formats, names or values.

### Accurate partial-input failure

Behavior is unchanged. A step whose input requires complete results still stops,
before any adapter or model work, when its producer returned a partial result. The
report is now accurate:

- `resolve_step_inputs` in `functions_orchestration_result_runtime.py` raises
  `PartialInputNotAcceptedError` when a partial, non-preview producer result meets an
  input with `allow_partial: false`. It subclasses `ResultNotReadyError`, which now
  records the status it rejected, and it carries the producer's step ID, capability
  and completeness counts.
- The executor reports it as `input_partial_not_accepted`, with the message "An
  earlier step returned only a partial result, and this step requires complete
  results, so it did not run." Other contract errors remain `result_invalid`.

### Logging

- `[DOCUMENT_ANALYSIS] Final findings validated` is logged once for each final Analyze
  result: Information when the result is valid, and Warning otherwise. It carries the
  validation status; finding, window, caveat and note counts; evidence counts for each
  match tier and each miss reason; and a count for each validation issue code. It
  contains no document content or model text. Its only identifier is a SHA-256 hash
  of the conversation ID, present when the analysis runs for a conversation, so it
  can be found with the conversation's other events.
- For `input_partial_not_accepted`, the existing
  `[ORCHESTRATION_EXECUTOR] A dependency-bound step could not complete.` warning now
  names the producer. It adds the producer's capability, its step ID hash, and its
  expected, actual and coverage counts and limitation count. `functions_appinsights.py`
  allowlists `producercapabilityid` as a code key and `producerstepidhash` as a hash
  key.
- The per-window debug line reads `start_page` and `end_page`.

The property names and a query are in the
[logging tags reference](../../reference/logging-tags.md), under
**Analyze validation and partial-input events**.

### Files modified

| File | Change |
| --- | --- |
| `application/single_app/functions_document_analysis_results.py` | Evidence matcher v2, miss reasons and match counts; caveat and note validation; record caveats, work-unit notes and the new report lines. |
| `application/single_app/functions_document_analysis.py` | Window prompt scoping and quoting guidance; note and match-count aggregation; the validation summary event; the `page_range` debug fix. |
| `application/single_app/functions_orchestration_planner.py` | Per-source preparation guidance for mixed comparisons. |
| `application/single_app/functions_orchestration_result_contracts.py` | `PartialInputNotAcceptedError`; `ResultNotReadyError` records the rejected status. |
| `application/single_app/functions_orchestration_result_runtime.py` | Raises the partial-input error with its producer. |
| `application/single_app/functions_orchestration_executor.py` | Reports `input_partial_not_accepted` and logs the producer fields. |
| `application/single_app/functions_orchestration_schema.py` | The `input_partial_not_accepted` message. |
| `application/single_app/functions_appinsights.py` | Allowlists the producer fields. |
| `application/single_app/config.py` | Version 0.261.191. |

## Testing

- `functional_tests/test_document_analysis_evidence_matching.py` (new) runs the real
  collector, finalizer, report and producer against fixture documents with
  deterministic model responses. It covers:
  - each presentation difference, including HTML and Markdown tables, a quote across
    a heading and a bullet, emphasis marks, inline formatting tags, entities,
    typographic characters, NFKC and decomposed forms, a two-part vowel sign, whole
    words with vowel signs, invisible characters, whitespace, case and a copied chunk
    label;
  - boundaries that must still match: a number before a sentence period or a list
    comma, a number grouped by narrow no-break spaces quoted whole, a whole possessive
    or contraction, an acute accent typed as an apostrophe, and a quote that leaves
    out an elided prefix such as `l'`;
  - rejections: paraphrase, ellipsis, partial words, cross-chunk joins, ambiguity,
    wrong or missing citations, a chunk outside the window, and blank, markup-only or
    label-only quotes;
  - token and symbol changes, which are never presentation: merged table cells, digits
    or words, superscripts, changed comparison symbols, signs or checkbox states,
    literal asterisks, a dropped list marker, and a partial word hidden by a soft
    hyphen;
  - partial numbers and words: numbers cut at a thousands comma, a decimal point, an
    Arabic separator, or a no-break or narrow no-break space, in prose and in table
    cells; words cut beside a vowel sign, an Arabic vowel mark or a case-folding
    expansion; words cut before an apostrophe suffix, such as the `'t` of `can't` or
    `won't`, a possessive, or a decade such as `1990's`, including in table cells; and
    partial identifiers;
  - verbatim evidence text and exact-tier offsets;
  - an end-to-end HTML table analysis that is valid, with caveats and notes in the
    result and the report;
  - genuine unresolved issues, which still give a partial result;
  - invalid caveats and notes;
  - the summary event, passed through the real App Insights allowlist, with no model
    text and only a hashed conversation ID.
- `test_orchestration_dependency_runtime.py::test_partial_input_is_never_promoted`
  asserts `input_partial_not_accepted`, its message, and a single warning with the
  producer fields and no limitation text. The `allow_partial: true` case is unchanged.
- `test_orchestration_failure_telemetry.py` checks that the allowlist keeps the
  producer fields and drops arbitrary text.
- `test_orchestration_single_contract.py` checks that the planner prompt keeps the
  per-source guidance.

The new file also passes under `python -O`. The directly affected Analyze and
orchestration suites pass when run individually, both before and after merging the
0.261.190 base branch. In a wider run before that merge, 60 tests in 13 Analyze,
document-analysis, saved-analysis, workflow and mixed-source files failed, and the
same 60 tests fail on the base commit, `01c728bf`.
`test_orchestration_failure_telemetry.py` also fails when it runs in the same process
after `test_analyze_backend_saved_integration.py` and
`test_analyze_live_write_fences.py`; that also happens on `01c728bf`.

## Validation

The failing run's saved window responses were replayed offline against its saved
chunks, using the new collector:

| | Before | After |
| --- | --- | --- |
| Quoted passages located | 23 of 226 | 226 of 226 (23 exact, 203 normalized) |
| Unresolved candidates | 34 of 35 | 18 of 35 |
| A qualification such as an unstated unit | Blocks the finding | The prompt asks for a caveat, which does not block |
| An observation about the slice, or a remark about another source | Makes Analyze partial | The prompt asks for a note, which does not change the status |
| Compose refusing a partial input | `result_invalid`, blaming compose | `input_partial_not_accepted`, and the log names the producer |
| Explaining a partial Analyze result | Read the diagnostics JSON | One `Final findings validated` event with counts |

Each of the 18 candidates that remain unresolved in the replay carries a model-written
finding issue, such as an unstated unit or the missing CSV. With those saved
responses, they stay unresolved and the result stays partial, which is correct. The
prompt and planner changes address them in new runs, which needs a live run to
confirm. The replay was repeated with the final matcher described above, after the
review changes, and every passage was still located with the same counts.

## Known limitations

- A run that already failed still fails if retried, because the retry reuses the
  saved partial Analyze result. Ask the question again.
- A resumed run reuses its completed window results without checking them again, so a
  run that started before this version keeps the results its windows already had. The
  summary event's `sc_reused_window_count` shows when windows were reused.
- Files exported later from a saved result do not include **Analysis notes**. Caveats
  appear in Markdown and PDF exports, but not in Word, CSV, JSON or XML exports, which
  contain the findings' values.
- Saved evidence is the verbatim source span, so a passage located in a table shows
  the table's markup in the evidence panel.
- Matching fails safe. A quote that adds or removes a space inside a value, such as
  `5%` for `5 %`, or leaves out a bullet or symbol between the words it quotes, is not
  located. The finding stays unresolved, and the miss is counted as `not_in_window`.
- Digits separated by one no-break or thin space, or by a comma, are read as one
  number. A quote that needs normalization therefore cannot stop at that point, as in
  `Q1` when a no-break space joins it to `2023`, or `1200` from the unspaced values
  `1200,2023`. Quoting the whole value avoids this.
- Digits separated by an ordinary space are read as separate numbers, because
  `1 200` could be a list. A quote of `1 200` from `1 200 000` written with ordinary
  spaces is therefore accepted.
- A quote that needs normalization, such as one that crosses a line break, cannot end
  before an apostrophe suffix. So `the company` is not located in
  `the company's results` when a line break separates `the` and `company's`. The rule
  cannot tell a possessive from a contraction such as `can't`, whose suffix reverses
  the meaning. Quoting the whole word avoids this.
- The `exact` tier keeps the previous substring behaviour, so a verbatim quote that
  stops partway through a word or number, such as `1,200` copied from `1,200,000` or
  `They can` copied from `They can't`, with identical spacing, is still accepted by
  that tier. The whole-word, whole-number and apostrophe rules apply only to the
  normalized tiers.
- Text in angle brackets that starts with a letter, such as `<y and y>` in prose, is
  read as an HTML tag.
- The word-boundary rule treats neighbouring letters as one word. In text written
  without spaces, such as Chinese, Japanese or Thai, a quote that needs normalization
  must therefore start and end where the text has a separator. Exact quotes are not
  affected.

## Follow-ups

- Ask the same kind of mixed comparison on a deployed environment, and check the
  `Final findings validated` event. Its `sc_issue_unresolved_finding_count` and
  `sc_issue_window_requirement_unresolved_count` show whether any blocking issues
  remain.
- Apply the whole-number and apostrophe rules, and where the script uses spaces the
  whole-word rule, to `exact` matches, without breaking verbatim quotes in text
  written without spaces.
- Show a readable form of table evidence in the evidence panel.
- Include notes in files exported from a saved result.
