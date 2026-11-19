# Native audit multi-source citation delivery fix (v0.261.428)

Fixed/Implemented in version: **0.261.428**.
Application version: `application/single_app/config.py`.
Dependencies: existing authorized retained results, Document Search invocations,
native document readers, configured orchestration models, and private checking
checkpoints. No new package, route, setting, browser asset, or service is required.

## Issue and root cause

A native document review could successfully inspect one selected file and read a
different supporting file, yet deliver only a partial-result explanation instead
of the requested review. Native-answer validation admitted supporting citations
only when their document had also supplied a native accessibility report.

That restriction confused two authorities: the source of immutable native file
facts and the sources allowed to support the answer's other claims. A selected
Markdown evidence file, for example, can support an engineering checklist without
establishing any native PowerPoint properties.

In the investigated saved attempt, both Document Search operations succeeded.
The gather was retained without a partial flag, and composition received two
located document citations. The first and final candidates failed
`native_answer_citation_unknown`. An intervening semantic assessment rejected a
corrected candidate that inaccurately claimed the supplied supporting-file content
was unavailable. After the configured correction allowance, no checked answer was
committed and the executor selected its existing partial-result explanation.

The exact rejected markers in the private initial and final candidates were not
recovered. The over-narrow citation contract was independently reproduced through
the real HTTP/action/retention path: same-document supporting citations passed,
while valid citations from a separate selected supporting document failed.

This is distinct from an older analysis dependency being rejected because its
required upstream result was genuinely incomplete. It is not evidence that an
optional metadata field, model quota, or service timeout caused this failure.

## Technical changes

### Separate native facts from answer support

`native_audit_contract()` now accepts an explicit internal
`authorized_answer_citations` argument. Composition supplies it from the existing
retained-result owner's named-input citation projection, after that owner has
checked result authority and recorded source lineage.

| Authority | Evidence admitted | What it establishes |
| --- | --- | --- |
| Native facts and appendix citations | Actual native-reader invocation results, with the existing source version, hash, and canonical field-state checks | The inspected native records and their stated coverage |
| Answer-support citations | Exact owner-issued citations for the bound named inputs, including other selected documents | Supporting content for the answer's non-native claims |

The answer registry does not add supporting documents to the native fact set,
native source list, or immutable appendix citations. Native fact digests do not
change merely because another authorized supporting citation is admitted.
Matching native-source version conflicts still fail.

Embedded source text, action notes, filename fragments, and an arbitrary
`document_citations` dictionary do not grant another document's citation.
Only the explicit owner projection can extend the answer registry. Validation
still rejects invented or altered markers rather than stripping or rewriting
them into apparent success.

Preparation, correction, and semantic review receive the same answer citation
authority. Their native policy explains that returned supporting content remains
available evidence even when its document has no native inspection; it does not
make supporting prose authoritative for native properties.

### Preserve retained-result access semantics

Workspace document authorization remains at its existing fresh-read boundary.
For retained results, the recorded workspace sources are provenance; the owning
conversation/run and current external integration checks govern access.

This fix does not add workspace source rereads, require a supporting file to have
native metadata, or change retention/revocation policy. The existing owner still
rejects citations naming another source, invalid lineage, and unavailable current
action access.

### Renew checking under an explicit contract version

The private preparation/checkpoint contract advances from
`native-audit-answer-v3` to `native-audit-answer-v4`. The customer preparation
transport remains `native_claims` plus a nonempty Markdown `answer`.

An explicit new checking retry can renew an older failed preparation under the
new citation contract using its still-authorized retained gather. The existing
retry path discards the obsolete checking state instead of applying an old
assessment to a different request identity. Completed native reads and supporting
searches are not repeated.

No retry is started automatically. Correction limits, deterministic marker
validation, semantic checks, ownership fencing, and refusal to publish an
unchecked candidate remain unchanged.

### Files and impact

| File | Change |
| --- | --- |
| `application/single_app/functions_native_audit.py` | Explicit owner-authorized answer citation registry, unchanged native fact authority, v4 checking contract, and consistent preparation/review guidance |
| `application/single_app/functions_orchestration_composition.py` | Pass the verified named-input citation projection into the native answer contract |
| `application/single_app/config.py` | Application patch version 0.261.428 |
| `functional_tests/test_native_audit_reliability.py` | Registry shape, separate supporting inputs, native version fences, unchanged facts, and embedded-marker controls |
| `functional_tests/test_native_audit_answer_delivery.py` | Real mixed-source delivery, correction, action-access refusal, unknown-marker rejection, and v3 check-only recovery |

No source deck is changed. Absent/inaccessible optional properties and incomplete
native inventory coverage remain honest review limitations, not new execution
failure gates. Genuine failed reads, unsupported claims, strict upstream
dependencies, and explicitly permitted available-information handling keep their
existing distinct outcomes.

## Validation and before/after comparison

Before the fix, the two selected-supporting-document HTTP cases failed while the
same-document PDF and PowerPoint controls passed. After the fix, all four save
checked answers with their exact owner-issued citations. The separate supporting
file is not promoted into native fact evidence.

Additional regressions demonstrate that correction can restore supplied
supporting-file findings without losing their valid citation; invented markers
still exhaust bounded correction without publication; disabling the retained
action during preparation blocks delivery; and an explicit v3 retry with an
obsolete identity renews checking without another native download or supporting
search.

The following local selections passed. Their coverage overlaps, so the counts
are not a combined unique-test total.

| Selection | Result |
| --- | --- |
| Native contracts/delivery, real action HTTP path and lineage, completeness engine/runtime, and available-information controls | 218 passed |
| Optimized Python: native contracts/delivery, source-backed native pipeline, and inspection request contracts | 127 passed |
| Final application-version and focused citation-contract selection | 38 passed |
| Cosmos boundary inventory | 1,094 owners, 425 doubles, zero review gaps |
| Documentation surface coverage / site quality | 7/7 and 6/6 checks passed |
| Changed Python syntax / filename headers | 5 files passed |
| Whitespace | Passed |

Commands used the existing network guard and external-I/O/provider doubles:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPATH="$PWD\application\single_app;$PWD\functional_tests"
python -B -m pytest .\functional_tests\test_native_audit_reliability.py .\functional_tests\test_native_audit_answer_delivery.py .\functional_tests\test_orchestration_document_action_end_to_end.py .\functional_tests\test_orchestration_document_action_lineage.py .\functional_tests\test_task_completeness_engine.py .\functional_tests\test_task_completeness_runtime.py .\functional_tests\test_orchestration_available_information.py -q --tb=short -p test_support.cosmos_network_guard -p no:cacheprovider --disable-warnings
python -O -B -m pytest .\functional_tests\test_native_audit_reliability.py .\functional_tests\test_native_audit_answer_delivery.py .\functional_tests\test_native_document_fidelity_pipeline.py .\functional_tests\test_native_inspection_request_contract.py -q --tb=short -p test_support.cosmos_network_guard -p no:cacheprovider --disable-warnings
python -B -m pytest .\functional_tests\test_native_audit_reliability.py .\functional_tests\test_native_audit_answer_delivery.py::test_native_audit_delivery_version -q --tb=short -p test_support.cosmos_network_guard -p no:cacheprovider --disable-warnings
python -B .\scripts\check_cosmos_response_boundaries.py
python -B .\functional_tests\test_docs_app_surface_coverage.py
python -B .\functional_tests\test_docs_site_quality.py
git --no-pager diff --check
```

Existing dependency and SWIG deprecation warnings remain. These cases prove
application contract, correction, and publication behavior with controlled
provider replies; they do not prove that an arbitrary live model always produces
a valid or complete answer.

No production settings, logging configuration, service state, deployment, or
saved attempt was changed, and no live retry was submitted. Live acceptance
requires a separately authorized deployment with verified serving-build identity
and an explicit new checking attempt; a mutable image tag is not that proof.

Related background:
[Native audit reliability and truthful coverage](NATIVE_AUDIT_RELIABILITY_FIX.md)
and [Native audit answer delivery](NATIVE_AUDIT_ANSWER_DELIVERY_FIX.md).
