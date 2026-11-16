# Content Screening and React V2 Integration

## Issue and root cause

The content-screening branch and React V2 independently changed shared model
configuration, Analyze execution, history, and publication boundaries. Taking
either side of their merge conflicts alone would lose either screening holds or
the newer saved-result, checkpoint, and AI-connection behavior.

**Fixed in version: 0.261.113**, recorded in
`application\single_app\config.py`.

**Related work:** [#1476](https://github.com/microsoft/simplechat/issues/1476)
and [#1485](https://github.com/microsoft/simplechat/pull/1485).

## Integration changes

The merged Analyze producer keeps bounded source loading, durable work units,
and isolated concurrent invokers. Screening wraps each invocation, retains
source-generation provenance in coverage, and checks final results before
returning them, including completed-checkpoint reuse. A hold is propagated
rather than retried as an ordinary model error.

Chat assistant publication occurs once, inside both the Analyze attempt fences
and the screening persistence guard. A source hold rolls back the output.
Saved-result explanation and formatting remain subject to source screening;
conversation exports suppress thoughts for either unavailable saved analyses or
screening-held content.

Admin saves retain embedding compatibility preflight, authoritative screening
configuration validation, safe errors from both systems, and truthful storage
failure responses. Model connection handling preserves strict screening secret
hydration alongside the incoming embedding and image capabilities.

## Validation

`functional_tests\test_content_screening_analyze_merge.py` exercises the real
producer and screening access layer with mutable fake Cosmos records. It covers
holds before invocation, during a response, after a completed window, and before
checkpoint reuse across legacy, sequential, factory, and parallel execution.

Existing Analyze integration tests cover single assistant persistence, rollback,
saved-result access, and workflow checkpoints. Screening settings, model
connection, history, citation, route-policy, and browser coverage exercise the
remaining merged boundaries. All fixtures use synthetic data rather than live
workspace documents or cloud deployment.

## Impact

This reconciles the feature with the current React V2 branch without replacing
either feature set. Screening remains off by default, independent of Content
Safety, and dependent on Enhanced Citations storage for activation. No held
document is released by this merge.
