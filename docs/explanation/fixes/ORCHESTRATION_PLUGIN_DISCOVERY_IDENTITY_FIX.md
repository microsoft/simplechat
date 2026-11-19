# Orchestration plugin discovery identity fix (v0.261.421)

Fixed/Implemented in version: **0.261.421**, tracked in
`application/single_app/config.py`.

## Issue and root cause

Selected-document orchestration could validate its plan and permissions, load the
Document Search action, and then fail before its first document-reading function.
Later report-writing steps were skipped because their required evidence had never
been collected. Similar failures across different files were not evidence that
each file was corrupt.

In plain language, the application made two copies of the same tool. A safety
check expected one copy, but the loader supplied the other. Python treated them
as different classes even though they shared a name and source file.

`semantic_kernel_plugins/plugin_loader.py` executed a fresh module object for each
discovery call without reusing Python's registered module. The source-binding
guard added in 0.261.419 imported the canonical `DocumentSearchPlugin` and used
`isinstance` to verify the actual reader. That correct guard exposed the older
duplicate-class loading behavior.

The previous authenticated end-to-end fixture replaced discovery with a direct
reference to the canonical class. Its successful replay therefore did not test
the loader/guard combination used in production.

Read-only Application Insights, Log Analytics, and App Service console correlation
on version 0.261.420 showed the same boundary in the six reported runs: verified
source identity/access, successful plugin registration, immediate action failure,
and no native read checkpoint. An isolated replay using real discovery reproduced
the exact reader rejection with zero action-model calls and zero report reads.
Hosting metrics did not indicate CPU or memory exhaustion as their cause.

## Changes

`plugin_loader.py` now uses `importlib.import_module` for installed plugins.
Repeated and concurrent discovery reuse canonical class objects while logged
loading continues to construct separate instances with their own configurations.
No additional registry, reload mechanism, source widening, or class-name-only
validation was introduced. Failed module imports emit a tagged warning with the
module name and exception type, not the exception message.

`functions_orchestration_actions.py` attaches an application-owned failure code
only at known initialization, reader identity, document-result error, and missing
function-result boundaries. Unclassified action errors still preserve their
existing provider causes. The document-reader type guard, source rechecks,
function-call budget, and cancellation behavior remain in place.

`functions_orchestration_schema.py` admits those codes through the existing safe
failure contract. `functions_orchestration_adapters.py` logs the safe code/stage
and hashed run/step/conversation identity. Saved step details and the final
failure explanation retain the original action failure instead of explaining
only the dependent step's skip.

| Code | Meaning and response |
| --- | --- |
| `action_initialization_failed` | Check action/model configuration; the tools or function-calling capabilities could not initialize. |
| `document_reader_identity_mismatch` | Repair or update the deployed application before retrying. Re-uploading or changing timeouts does not repair duplicate class identity. |
| `document_action_read_failed` | Check the selected source's availability and requested inspection; a failed read was not accepted as findings. |
| `action_results_missing` | No usable function results were returned; review the action/model tool support if it repeats. |

These codes are not automatic transient retries. Permitted manual failed-step
recovery remains available after the underlying problem is repaired. No unknown
exception code or private exception message is accepted as public failure text.

### Fresh-container template dependency

The container startup probe exposed a separate installation problem: the
configured feed installed Semantic Kernel's Handlebars adapter without its
required `pymeta` module. This was not the cause of the six historical failures,
which had already reached planning and action loading.

`application/single_app/requirements.txt` now explicitly pins the existing
template-parser dependency, `PyMeta3==0.5.1`, matching the working test environment.
Fresh normal/optimized import tests and the Linux image probe exercise the real
Semantic Kernel import rather than treating a completed package install as proof
that the application starts.

## Validation

`functional_tests/test_orchestration_document_action_end_to_end.py` now runs
production discovery. Its authenticated HTTP-to-saved-answer cases verify native
PDF/Word facts, limits, citations, failed reads, and debug on/off.

`functional_tests/test_plugin_discovery_identity.py` verifies every discovered
class against its registered module, repeated/concurrent loading, separate
request-local users and configuration, safe import-error logging, and real
bootstrap/web/headless imports in fresh normal and optimized processes.

`functional_tests/test_orchestration_document_loader_reliability.py` derives its
format matrix from `config.py` rather than listing only the reported extensions.
It exercises actual source checks, SDK-shaped document records, ordered chunk
retrieval, real action loading, retention, and saved cited answers using indexed
text. This matrix does not claim that every upload format has native PDF/Office
properties or that a filename change proves extraction support.

Fault-injected initialization, wrong reader identity, document-read, and missing
result cases verify the exact safe code in the saved step API, its user-facing
explanation, hashed telemetry, attempt flags, privacy, and absence of composition
after failed acquisition. Provider timeout/connection causes remain transient;
the new code faults do not.

Existing real-package PDF, Word, PowerPoint, and Excel accessibility/native
inspection fixtures separately cover extraction and its stated limitations.
The CI storage-contract workflow explicitly executes the real discovery and
document-action regressions with network access blocked before collection.

| Before | After |
| --- | --- |
| Discovery made another class object that the native-reader guard rejected. | Discovery and the guard use the same registered class. |
| A shortcut fixture hid production loading behavior. | The authenticated regression uses the production loader. |
| Distinct action failures collapsed into a generic operation message. | Safe initialization, identity, read, and missing-result meanings survive saved details and the failure explanation. |
| Debug-off errors lacked usable run/step correlation at the action boundary. | The first action error retains safe stage/code and hashed correlation with debug on or off. |

### Executed checks

The shared discovery/native/action-runtime selection passed **81 tests** with the
eight fresh-process import-order cases excluded from that combined selection.
Those eight normal/optimized startup cases passed in the preceding discovery
selection. Real PDF/Word/PowerPoint/Excel extraction and Excel native-inspection
fixtures passed **63 tests** separately.

The complete config-derived stored-text format matrix passed independently,
requiring a saved cited answer for every allowed extension. The **15** remaining
failure/contract cases passed independently, including the eight debug-on/off
saved-step failures. These selections are not presented as an aggregate test count.

```powershell
$env:PYTHONPATH = "$PWD\application\single_app;$PWD\functional_tests"
python -m pytest -q -p no:cacheprovider -p test_support.cosmos_network_guard --disable-warnings --tb=short --show-capture=no .\functional_tests\test_plugin_discovery_identity.py .\functional_tests\test_orchestration_document_action_end_to_end.py .\functional_tests\test_orchestration_action_runtime.py .\functional_tests\test_orchestration_document_action_binding.py -k 'not real_cold_import_orders'
```

```powershell
python -m pytest -q -p no:cacheprovider -p test_support.cosmos_network_guard --disable-warnings --tb=short --show-capture=no .\functional_tests\test_document_accessibility_extraction.py .\functional_tests\test_excel_document_accessibility_extraction.py .\functional_tests\test_excel_native_inspection_chat_evidence.py
```

The reviewed SDK boundary inventory remains at **1,094 owners, 425 doubles and
zero review gaps**; regeneration introduced no inventory changes.

After the final version update, the exact new CI regression selection passed
**37 tests**, including the complete **81-extension** retrieval matrix and all
fresh-process cases. The route-policy/manual-recovery selection passed **77
tests**. The full reviewed offline SDK gate passed **2,026 tests and 431 subtests**:

```powershell
python .\scripts\check_cosmos_response_boundaries.py --run-contracts
```

Documentation surface coverage and site quality passed **7/7** and **6/6**
checks. Changed Python compilation, CI YAML/network-guard validation, the changed
browser-sink scan and whitespace checks passed.

The fresh local production Docker build passed the V2/native build stages but
stopped during dependency installation with an HTTPS handshake failure to
`files.pythonhosted.org`. Normal certificate-verified host and container probes
reproduced that network failure. TLS verification was not disabled, and this is
not attributed to the document-reader defect.

Using the machine's existing verified-HTTPS package feed in a temporary build
context resolved that transport problem. The feed's missing FFmpeg metadata
sidecar was avoided by selecting the exact verified `ffmpeg-binaries-compat`
1.0.1 wheel with its SHA-256 hash in that temporary context; the repository's
FFmpeg pin and pip configuration were not changed.

After the explicit PyMeta3 declaration, the full CI-equivalent regression gate
passed **38 tests**. The production Linux image built successfully and its real
application/WSGI authentication, canonical reader loading, compiled V2 assets,
five implementation-file hashes, Gunicorn configuration, and installed-package
consistency checks passed with external networking disabled. The default
external healthcheck switch remains disabled in the offline fixture; its 400
response was not reported as a healthy endpoint or silently enabled in Azure.

Release pages were regenerated and preserve all **313** source releases.

### Packaged-runtime replay

The actual Linux production image also passed **101 existing regression cases**:
the **38** discovery/native-action/runtime cases, including the full
**81-extension** indexed-text matrix, plus **63** real PDF/Word/PowerPoint/Excel
extraction and evidence cases. There were zero errors, failures, or skipped
cases.

All **221** original production package versions remained unchanged. Only the
four missing, pinned pytest tooling packages were installed into the disposable
container's owned scratch user site. The shipped image, production dependencies,
and application source were not replaced to make the tests pass. Docker
networking was disabled, fixtures were mounted read-only, and the existing
pre-collection network guard remained active.

All five raw implementation-file hashes also matched the worktree. The earlier
smoke fingerprints explicitly correspond to UTF-8 text with CRLF converted to
LF; a raw-byte comparison against those normalized fingerprints is not a valid
stale-build test.

## Scope and rollout

No new upload type, extractor, model provider, administrator toggle, route, or
browser dependency is added. Existing workspace permissions, selected-source
bindings, native-inspection limitations, and historical run records are preserved.
A missing native property in an available report is still different from a report
that cannot be read.

Offline regressions are not a guarantee that every live model response will be
valid. Deploy the verified version/build, then prove actual saved cited answers
with approved live canaries. HTTP 200 and a healthy web endpoint do not establish
successful orchestration. A separately observed partial document-search run was
not attributed to this loader defect and must be diagnosed independently if it
persists.

Related references: [Document Search](../../reference/actions/document-search.md),
[action access](../features/CHAT_ORCHESTRATION_ACTIONS.md), and
[plugin/action failure logging](../../reference/logging-tags.md#plugin-discovery-and-action-failures).
