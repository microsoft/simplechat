# Orchestration Analyze execution-bound storage fix

**Fixed in version: 0.261.127**, recorded in
`application/single_app/config.py`.
Refs [#1509](https://github.com/microsoft/simplechat/issues/1509).

## Issue and root cause

A real contract-v2 Analyze task could finish its document work but fail while
saving the final native result. Its work-unit checkpoints used the initialized,
execution-bound result store, while the final saved-analysis helper constructed
a different store through its legacy default callback.

The lifecycle guard correctly rejected that new store: a token alone cannot
authorize a writer once the parent execution claim is bound. Adapter-only
fixtures used an injected store and did not exercise this production mismatch.

## Technical details

`functions_orchestration_adapters.py` now supplies the existing
`save_orchestration_analysis(..., save_result=...)` extension point with the
same store that owns the task's checkpoints. Every section write still requires
the actual guard token and `require_analysis_guard=True`.

The subsequent bounded native reader uses
`load_orchestration_analysis_input(..., load_result=...)` with that same store.
Native result validation, conversation/run authorization, source access,
screening, count/digest checks, and generic result retention remain unchanged.
No global client, new store factory, checkpoint schema, or relaxed guard was
introduced.

This affects only internal v2 Analyze execution. Legacy Analyze callers and
standalone/workflow persistence keep their default APIs and behavior.

## Validation

`functional_tests/test_orchestration_reason_render_pipeline.py` reproduces the
original failure using the actual application root, execution claim, Analyze
producer, work-unit checkpoints, saved-result helper and private storage.
After the fix, the same plan retains every finding and its report, renders
CSV and Markdown, and downloads both after rebuilding the services. CSV
preserves the native retained ordering and the report includes the final
original finding. Observation performs no new content-generation or source
chunk reads.

The same suite covers actual Compare to JSON/Markdown and one durable native
computation to complete CSV/JSON without model work. The joined producer,
scheduler, native-adapter and saved-analysis compatibility run passed
**328 tests in both normal and optimized Python** with external I/O doubled.
This is local production-boundary coverage, not live tenant validation.

See [the harness contract](../features/ORCHESTRATION_RENDERING_HARNESS.md) and
[retained Analyze results](../features/ANALYZE_RESULTS.md).
