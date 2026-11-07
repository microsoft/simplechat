# Chat Stream Conversation Reference Scope Fix

Fixed/Implemented in version: **0.261.387**

Related config.py update: `VERSION = "0.261.387"`

## Issue and root cause

Document-grounded chat returned "Something went wrong while streaming the response.
Please try again." Selecting another file did not help because the failure was in
the shared chat stream, not the selected document.

Application Insights recorded repeated `UnboundLocalError` exceptions for
`stream_conversation_reference_resolution`, with zero response content emitted.
The conversation-reference change in [#1835](https://github.com/microsoft/simplechat/pull/1835)
initialized this state in `chat_stream_api()` but also assigned it inside the
nested `generate()` function. Python consequently treated it as a new local
variable, and the generator read it before assigning it. The same binding affected
new and existing conversations, ordinary messages, and document-grounded messages.

Runtime regression coverage also exposed an adjacent rejection-path bug:
conversation-reference and destination-admission refusals attempted to call
`CHAT_STREAM_REGISTRY.finish_session()`, which does not exist. This replaced the
intended safe refusal with an exception and prevented normal cleanup.

## Technical details

`application/single_app/route_backend_chats.py` now declares the reference
resolution `nonlocal` inside the stream generator. The generator uses the existing
request-owned state rather than a new, uninitialized local. New destinations still
revalidate their references after creation, and retry/edit requests retain their
saved evidence and revision metadata. No state is shared between independent
requests.

Both pre-stream refusal paths publish a safe terminal error through the existing
session API and close that session. Reference refusals also release the acquired
destination lease; an admission refusal does not release another request's lease.
Authorization and public error codes remain unchanged.

Additional files:

- `functional_tests/test_chat_stream_conversation_reference_scope.py`: fresh-process,
  offline tests exercising the real Flask route and stream generator.
- `application/single_app/config.py`: application patch-version increment.

No frontend, search index, application settings, or document data changes are
required.

## Validation

Before the fix, the new offline runtime regression reproduced the same
`UnboundLocalError` and generic SSE error as the Azure logs. After the fix, it
checks actual response content, terminal completion, and persistence rather than
accepting HTTP 200 as proof of success.

Coverage includes new/existing conversations without references, selected-file
retrieval and citations, explicit conversation references, destination
revalidation, saved references on prepared retry/edit attempts, independent
request isolation, unauthorized references, and a busy destination. Refused
requests must not reach the model or save chat messages, and their sessions must
be terminal rather than left active.

The targeted runtime, conversation-reference, and retry/edit suites passed
**34 tests**. The three route-policy scripts passed **28 checks**. External
storage, model, and search I/O are faked; the harness blocks external network
access. These checks do not prove live Azure AI Search availability.

Commands:

```powershell
python -m pytest functional_tests\test_chat_stream_conversation_reference_scope.py functional_tests\test_conversation_references.py functional_tests\test_chat_retry_edit_streaming_parity.py -q
python functional_tests\route_tests\test_route_blueprint_policy_inventory.py
python functional_tests\route_tests\test_route_unauthenticated_policy_contract.py
python functional_tests\route_tests\test_route_policy_test_coverage.py
```

The runtime probe also passed with optimization enabled:

```powershell
python -O functional_tests\test_chat_stream_conversation_reference_scope.py --probe
```

The final combined pytest run of the three targeted suites and three route-policy
files passed **64 tests**. Python compilation and `git diff --check` also passed.

An additional existing lifecycle-observability test reaches its version check
and fails because it requires the historical exact version `0.241.111`.
The unchanged baseline was already `0.261.386`; this unrelated stale assertion
was not modified.

## Operational impact

The change repairs local source code only. It was not deployed, and no Azure
configuration was changed. The affected live application needs a separate,
authorized deployment before users receive the fix.
