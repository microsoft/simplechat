# Native audit answer delivery fix

Fixed/Implemented in version: **0.261.425**.
Application version: `application/single_app/config.py`.
Related implementation: `NATIVE_DOCUMENT_FIDELITY_FIX.md`.
Dependencies: the existing native parsers, private retained-result/checkpoint
store, Document Search action and configured orchestration models. No package,
browser asset, setting, public route or cloud service is added.

## Issue and root causes

A successful native inspection was not necessarily followed by a useful audit
answer. Two different integration failures were identified:

| Failure | Root cause | Repair |
|---|---|---|
| An audit stopped at answer checking after native reads succeeded. | The native answer protocol allowed only a fact-set reference. Every valid reference became the same fixed evidence table, while a correction containing the requested explanation was rejected. Correction also lacked the combined native contract/digest supplied during preparation. | A checked customer explanation and immutable source evidence use one consistent preparation/check/correction contract. |
| Broad Excel inspection failed before answer preparation. | The shared tool exposed `all` for PDF/PPTX, but the Excel reader accepted only individual inventory sections. | Excel supports a bounded, paged union of its supported sections; both the actual tool annotations and manifest document format-specific choices. |
| Deeply nested saved workbook layout became inaccessible during the handoff. | Ordinary citation-wrapper depth consumed the generic sanitizer's budget before the native fact value was reached. | A closed, count/byte-bounded native-fact shape is sanitized per value. Redaction and individual value depth limits still apply. |

The handoff failure was reproduced locally using the source-backed Excel path.
It does not establish that an observed difference in an older exported payload
arose at the same stage. Tool results, retained composition inputs and exported
presentation are separate checkpoints.

## Customer-facing behavior

Missing information is not, by itself, an execution error. An audit can report:

> The supplied native records do not establish the rendered reading order.
> Here is the logical order actually stored in the file, with its source locations.

The answer should address each requested check with a supported finding or a
precise limitation. `absent`, `present_empty`, `present_value` and `inaccessible`
remain distinct. An unread file must not be described as a file that was inspected
and found to lack a property.

An invalid continuation, denied or held source, parsing failure, unavailable
provider or persistence failure remains a genuine technical/access error.
Unsupported claims are corrected or rejected rather than being published as
native evidence. None of these checks certifies WCAG, Section 508 or PDF/UA
conformance.

## Technical changes

### Source-bound answers and checked correction

`functions_native_audit.py` separates the source-fact protocol from the answer
preparation protocol, `native-audit-answer-v2`. New native composition replies
contain:

```json
{
  "native_claims": {
    "scope": "all_returned",
    "fact_set_sha256": "<the supplied fact-set digest>"
  },
  "answer": "<the requested source-grounded Markdown explanation>"
}
```

The digest references returned native facts, not source-file bytes.
`source_sha256` continues to identify the inspected file separately. A reference
without an answer no longer satisfies new composition. The low-level reference
validator retains compatibility with earlier fact-reference payloads.

The server validates fact references and rejects invented citation markers. It
renders the factual table from retained values/states, rather than accepting
replacement values from the explanation. The model supplies the requested
interpretation; the existing configured semantic review evaluates that
explanation against the authoritative native facts, not against an action
model's conflicting paraphrase.

`functions_orchestration_composition.py` gives checking and correction the
complete native contract. The candidate under review is rendered customer
Markdown; JSON describes the preparation/correction transport, not the displayed
answer. Validated preparation envelopes are retained privately with the original
and current candidate, so reload or explicit checking retry can reconstruct the
same representation without repeating document reads.

An explicit retry of an older failed native check can prepare under the new
grammar from still-authorized retained gather results. It does not silently
accept an old approval, relax checkpoint binding, replay an ambiguous same-attempt
correction, or repeat an external action.

### Excel all-section paging

`functions_excel_inventory.py` reads `all` in a deterministic order across
comments, objects, tables, defined names, hyperlinks, validations, property
records, custom properties, extended properties and available image analyses.
Each returned all-section record identifies its `inventory_section`.

The existing 1-200 record page limit, response-byte bounds, complete-record
fragments, authorization checks and source/schema/section-bound cursors remain.
Section counts include supported sections with zero records. Existing focused
sections keep their record shapes and remain useful for narrow questions.
The stored native inventory schema is unchanged; this additive reader does not
force existing inventories to rebuild.

`all` does not enumerate every worksheet cell or recalculate formulas. Requests
such as `Budget!B4` still use the saved-cell reader and its bounded A1 range.
Word's opt-in strict comment reader and its defaults are unchanged.

### Native fact transport and aggregate coverage

Source owners construct bounded facts from authorized full records before
emitting previews or long-record fragments. Those record objects stay private;
they are not an extra unbounded response field. A shortened parent preview
cannot override an object's source fields, and a fragmented transport record
does not prevent the owner from supplying its supported facts.

`semantic_kernel_plugins/plugin_invocation_logger.py` recognizes only the closed
native-audit shape defined in `functions_native_audit.py`. A native report retains
the existing 1,000-fact and 100,000-byte fact budget plus a bounded header.
Each value still goes through the normal secret redaction, string bound and
depth limit. A nested object cannot impersonate another native envelope to reset
that value's depth budget repeatedly. Other plugin payloads keep their existing
depth behavior.

Original value digests are not rewritten after redaction or shortening. Changed
values remain `inaccessible`, never source blanks.

Aggregate `inventory_coverage` distinguishes a contiguous completed returned page
chain from a last page whose predecessors were not supplied. It tracks fragments
and source/section grouping, and removes stale continuation warnings only when
completion is demonstrated. A complete returned chain is still not proof of
unsupported or uninspected source content.

### Safe diagnostics and the unresolved historical continuation

`native_document_evidence.py` defines stable request errors used by native and
Excel readers. Cursor syntax, binding changes, offsets and fragment failures have
distinct codes. A binding diagnostic identifies the changed identity field
without exposing its value.

Document action checkpoints can record supplied/next cursor hashes and lengths.
`functions_appinsights.py` allows these hashes, not plaintext cursors or source
content. Native checking checkpoints record status, reason code and counts.

A previous C04 PDF retest completed its first read and failed its continuation.
The available logs did not preserve the complete original cursor or the exact
failing invariant. Exact valid continuations and deliberate invalid/source-change
controls are covered locally; this change does **not** claim to establish that
historical failure's precise cause or explain the separate later blank browser.

## Files and affected surfaces

| Component | Responsibility |
|---|---|
| `native_document_evidence.py`, `functions_native_document_inspection.py` | Stable request/cursor diagnostics; unchanged source guards. |
| `functions_excel_inventory.py`, `functions_search_service.py` | Bounded all-section workbook reads and existing saved-cell access. |
| `semantic_kernel_plugins/document_search_plugin.py` | Consistent format-specific manifest/tool guidance and safe request errors. |
| `functions_native_audit.py`, `functions_orchestration_composition.py` | Immutable facts, customer explanations, coverage, checking and versioned recovery. |
| `semantic_kernel_plugins/plugin_invocation_logger.py`, `functions_appinsights.py` | Bounded redacting native transport and content-free diagnostics. |

## Validation and before/after controls

The regression suites use the existing verified synthetic fixture ZIP and
SDK-default storage doubles. They replace external I/O, not source ownership,
native parsing, Auto model binding, retention, checking or publication.

| Control | Required result |
|---|---|
| Selected PDF/XLSX/PPTX, exact broad audit requests | Useful saved answer and real execution-stream content with supported findings, source citations and honest limitations. |
| Auto model routing and automatic approval | Both paths are explicit; automatic approval alone is not treated as an Auto routing test. |
| Incomplete first draft / false native assertion / hash-only response | A checked correction can produce a real explanation without replacing source facts; an unrepaired false assertion is not published. |
| C08/C11 `native_section="all"` | Ordered supported-section union, byte/page limits, Unicode fragments, field states and true-checkbox identity survive. |
| Saved check retry and legacy native check | Authenticated/versioned HTTP retry reuses retained evidence without a second source read; legacy grammar is upgraded only for an explicit new attempt. |
| Native transport | Value digests survive the handoff and deeper citation wrappers; secrets are redacted; ordinary and nested-value depth limits remain. |
| C04 continuation controls | Valid cursor succeeds; wrong source/revision/section, malformed cursor, offsets and fragments fail with safe diagnostic codes. |
| Strict Word comments | Existing comments/replies/resolution, reviewer separation and zero-comment controls remain correct. |

Primary suites:

- `functional_tests/test_native_audit_answer_delivery.py`
- `functional_tests/test_native_inspection_request_contract.py`
- Existing native-fidelity, Excel inventory, action binding/lineage, completeness,
  plugin identity/privacy and real SDK owner suites.

### Recorded local results

| Selection | Result |
|---|---|
| New native delivery/request suites, existing native fidelity and Excel persistence | 114 passed |
| Shared action binding/lineage, Auto routing and completeness engine/runtime | 138 passed |
| New delivery/request suites under optimized Python | 55 passed |
| Canonical plugin identity plus affected real SDK owner evidence, clean process | 14 passed |
| Final affected search/upload storage-owner SDK regression | 1 passed |
| Legacy privacy suite, isolated process | 5 passed |
| Registered Cosmos contract gate | 2,015 passed and 431 subtests passed |
| Cosmos inventory review | 1,094 owners, 425 doubles, zero review gaps |
| Documentation surface coverage / site quality | 7/7 and 6/6 checks passed; generated surface inventory unchanged |
| Whitespace check | Passed |

These selections overlap; their counts are not added into a unique-test total.
External network access was blocked for functional/SDK runs. Existing dependency,
Swagger and test deprecation warnings remain. The full registered gate completed
on the final source; an earlier sweep was stopped before the final handoff edits.
The legacy privacy suite installs import stubs, so its independent success is not
used to claim that it can share a process with every unrelated fixture.

Local model replies are controlled test inputs, not evidence that a particular
live model will always judge an audit correctly. Earlier local tests that
disabled completeness or always approved an inventory did not establish checked
customer-answer delivery. Deployment identity and live beta acceptance must be
verified separately; this fix does not imply a deployment, customer reprocessing,
source-document repair or completion of unsubmitted trials.
