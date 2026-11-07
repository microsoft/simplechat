# V2 model tools and evidence status (v0.261.389)

## Overview

SimpleChat applies model tool policy at the actual Semantic Kernel request
boundary and offers an explicit Responses transport for supported reasoning
models. V2 answers can also show recorded document-evidence limitations outside
the answer prose, with source details and useful next steps.

Implemented in version: **0.261.389**, coordinated with
`application/single_app/config.py`.

Dependencies are the existing pinned OpenAI and Semantic Kernel SDKs, the
selected model connection, authorized action plugins, and the locally bundled
React V2 interface. No new cloud service, dependency, or third-party browser asset
is required.

## Model execution

### Existing Chat Completions connections

Azure GPT-5.6 function tools on Chat Completions require explicit reasoning
`none`. Omitting the parameter is not the same request. The shared SDK boundary
now preserves this value for budgeted agents and direct tabular helpers,
including correctly configured deployment aliases.

The policy comes from the selected model/provider/protocol record. It is not
implemented in YAMCS, SQL, or individual action plugins. An explicitly requested
positive effort is not silently replaced with None; an incompatible request
receives a safe configuration error instead of repeated generic analysis attempts.

### Opt into reasoning with tools

For a supported OpenAI/Azure connection, select **Use Responses API** and use the
actual deployment name with accurate underlying model metadata. The connection
stores its base URL and boolean `use_responses_api` separately. A pasted full
operation URL selects the switch and is reduced to its base; saved operation
URLs remain compatible. A model-family name alone never switches the transport.

For native OpenAI, a Custom connection with the **OpenAI API** contract can use
`https://api.openai.com/v1` with the switch selected in automatic URL mode. Custom Azure
dated-version, Anthropic, and Gemini API contracts do not become Responses
connections. Exact Custom mode preserves an arbitrary gateway API base. APIM
must expose Responses on its published route; its prefix and configured
subscription/API-key header are preserved.

The existing authorized function-tool loop remains responsible for invoking
actions. The adapter translates message inputs, function schemas and results,
reasoning effort, structured output, usage, and the total generation cap.
Agents and applicable orchestration/workflow callers use the same boundary.
Operator-selected deployments, action permissions, and source provenance remain
unchanged.

Responses execution uses `store: false` and carries required output/reasoning
items across tool rounds in private SDK message state. Those items are not
added to public metadata, copied answers, or persisted conversation history.
An interrupted call does not automatically replay an already-completed tool.
New user turns use the application's authorized conversation history rather
than a persisted provider response ID.

Tool-enabled Responses output currently uses the existing completed-message
chunking interface for streaming delivery. Usage is emitted once and complete
function calls are preserved; this is not provider-token-time streaming or a
promise of faster first output from a reasoning model.

### API-version configuration

A resource-root legacy Azure connection needs a dated API version. A literal
`v1`, `preview`, or `latest` is not a dated Azure `api-version` value. V2 and
the shared save/runtime validators identify that mismatch before issuing the
invalid request.

An explicit `/openai/v1/` inference path uses the OpenAI-style client without a
dated query, including the legacy global and APIM fallback settings. API keys,
managed-identity authentication, and the selected deployment alias are preserved.
Foundry project discovery retains its separate API version.
Changing the dated version does not bypass a model's reasoning/tool restriction.
Existing valid dated connections are not automatically migrated.

## Document-evidence status

### What the status means

The server projects a bounded, sanitized `metadata.evidence_status` from the
authorized source ledger or verified retained Search lineage:

| State | Meaning |
|---|---|
| Complete | Evidence was returned for the recorded sources; no warning footer is needed. |
| Partial | Some document evidence is available, but another recorded source is missing, partial, unavailable, or unknown. |
| Missing | No supporting document evidence was returned from the sources actually searched. This is not an exhaustive-corpus absence claim. |
| Unavailable | Source work failed, was skipped/cancelled, or could not be authorized. This is not evidence that the fact does not exist. |
| Pending | Required source work has not finished. |
| Unknown | The necessary evidence outcome was not recorded. No missing/complete state is invented. |

General chat and historical responses without this metadata do not acquire a
warning simply because they have no citation chips. The status describes
document evidence, not the success or relevance of unrelated YAMCS/database tools.

### Using the V2 controls

Partial evidence has a yellow indicator; missing document evidence has a red
indicator. Text and icons accompany the color. Select **View sources** below
the answer to inspect per-source outcomes and suggestions. The Documents
pane uses the answer whose Sources view was inspected, or the latest answer
when no inspected answer is selected.

Sources that were selected or searched but not cited stay separate from
**Used in answers**. A conversation switch cannot carry another answer's
indicators into the new conversation. Masked or unrecorded evidence remains
unavailable to this presentation. Large source ledgers identify when only the
first 100 rows are displayed.

The answer still states a genuine inability to answer and may suggest a
specific clarification, document, time range, or authorized source. Routine
generic coverage paragraphs are discouraged, not removed with text matching.
Evidence validation and strict partial-input contracts remain enforced.

Copying an answer preserves a short material evidence notice. **Copy with
sources** also includes recorded per-source states; it never includes private
reasoning items.

## Citation compatibility

V2 recognizes the observed Unicode-bracket document marker only when its exact
ID exists in that message's source records. It uses recorded filename and
page/sheet/location metadata, never a global lookup or guessed page. Unknown
or conflicting references show **Source unavailable**. Literal fenced and
inline code is left alone. Existing Source-prefix citations remain supported.

## Tabular diagnostics and limitations

`[TABULAR_SK_ANALYSIS]` records separate `schema_preload` and `model_call`
durations, file count, and analysis attempt number without adding row contents
or prompts to these events. Deterministic model-policy/configuration failures
escape the retry loop and are not converted into successful-looking schema-only
fallbacks.

The existing workbook and dataframe caches are retained. CSV and XLSX still
use the tabular pipeline. No end-to-end customer latency improvement, model
quota allocation, or universal benefit from converting workbooks was measured
by the offline regressions. Provider reasoning cost, TPM/RPM, throttling,
workbook structure, and cold/warm caches still need controlled comparison.

## Testing and validation

The functional suites execute real SDK payloads, complete tool rounds, output
caps, private reasoning continuation, cancellation, safe failures, cold imports,
API version checks, source-ledger projection, and production citation parsers.
The browser suite uses the shared local/Azure Playwright connection and real
V2 components across desktop/mobile and light/dark states.

Relevant suites:

- `functional_tests/test_model_tool_execution_policy.py`
- `functional_tests/test_responses_model_tool_execution.py`
- `functional_tests/test_model_inference_api_versions.py`
- `functional_tests/test_model_responses_selection.py`
- `functional_tests/test_evidence_status.py`
- `functional_tests/test_tabular_model_phase_policy.py`
- `functional_tests/test_inline_citation_filename_fallback.py`
- `functional_tests/test_orchestration_search_citations.py`
- `functional_tests/test_export_evidence_cosmos_contract.py`
- `ui_tests/test_v2_evidence_status.py`
- `ui_tests/test_v2_responses_api_selection.py`

Export-owner regressions exercise real application functions with SDK point
mapping types, preserved ETags, ownership checks, plain query rows, and retained
evidence notices. The storage inventory records these as owner-runtime evidence,
not source-only exemptions.

Mock transport qualification is not a live model/deployment performance result.

## Related work

Refs [#1846](https://github.com/microsoft/simplechat/issues/1846),
[#472](https://github.com/microsoft/simplechat/issues/472),
[#1845](https://github.com/microsoft/simplechat/issues/1845),
[#1847](https://github.com/microsoft/simplechat/issues/1847),
[#1848](https://github.com/microsoft/simplechat/issues/1848), and
[#1849](https://github.com/microsoft/simplechat/issues/1849).
