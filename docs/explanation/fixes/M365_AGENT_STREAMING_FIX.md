# Microsoft 365 agent streaming failure (v0.261.031)

Fixed in version: **0.261.031**

Related version update: `application/single_app/config.py`, from `0.261.030`
to `0.261.031`. Associated issue: [#1493](https://github.com/microsoft/simplechat/issues/1493);
feature PR: [#1497](https://github.com/microsoft/simplechat/pull/1497).

## Reported failure

An agent using the new Microsoft 365 actions returned
`Agent streaming failed. Please try again.` Azure telemetry for the reported
deployment at **2026-09-18 17:16:44 UTC** identified:

```text
TypeError: Session.request() got an unexpected keyword argument 'partition_key'
```

The same error occurred in request finalization and repeatedly in user-settings
saves. This was a local Cosmos SDK call-contract failure, not a Microsoft Graph
or SharePoint consent rejection.

## Root causes

### Unsupported Cosmos replacement argument

The pinned `azure-cosmos==4.9.0` SDK accepts an explicit partition key for reads
and deletes, but derives a replacement's partition key from the replacement
document. Passing `partition_key` to `replace_item()` falls through the SDK's
generic keyword arguments into the HTTP transport, where `requests` rejects it.

Twenty-three affected calls were present across conversation-memory inventory,
Microsoft 365 request state, approvals, connection caches, workflow
continuations, pending delivery, task/agent checkpoints, and conditional
user-settings saves.

The previous in-memory Cosmos fake explicitly accepted that unsupported
argument. It therefore concealed a failure that the production SDK rejected.

### Execution context lost between streamed chunks

After isolating the storage failure, a separate local reproduction showed that
the synchronous chat route created a fresh asyncio task context for each
`__anext__()` call. The Microsoft 365 journal was visible for the first chunk
but absent on the next. Finalization then attempted to reset a ContextVar token
in a different context and raised `ValueError`.

This second failure was reproduced locally using the same pull pattern as the
route; it is not inferred solely from Azure's context-detach warnings.

## Changes

All affected `replace_item()` calls now retain their authorized document body,
item ID, ETag, and `MatchConditions.IfNotModified`, without forwarding
`partition_key`. Explicitly partitioned reads/deletes and transactional batch
calls are unchanged. No new upsert fallback, cross-partition lookup, or weaker
authorization was introduced.

`functions_async_stream.py` provides `SyncAsyncStream`, which uses one isolated
copied context for iterator creation, every pull, and asynchronous cleanup.
`route_backend_chats.py` uses this bridge for agent streams while preserving
chunk content, model/usage metadata, cancellation checks, and the existing
bounded retry policy. There is no eager prefetch.

The streaming wrappers in `agent_logging_chat_completion.py` and
`functions_m365_agent_continuation.py` explicitly close the iterators they own
before leaving the journal scope. Approval and sign-in exceptions retain their
identity and continue to reach the existing user-interaction handlers.

Unexpected agent-stream failures also use `log_event` with the existing
`[STREAMING]` tag, exception traceback, and request context, independently of
debug logging. Browser errors remain generic rather than exposing diagnostics.

## Validation

`functional_tests/test_m365_cosmos_sdk_contract.py` uses the real Cosmos SDK and
`RequestsTransport`, with only HTTP responses replaced by an autospecced
`requests.Session`. Network access is blocked. It reproduces the original
unsupported-keyword error and verifies:

- Body-derived `/id`, `/user_id`, and `/group_id` partition headers.
- ETag conditional writes and rejection of stale or wrong-partition updates.
- Production memory-inventory, request pause/finalization, and settings writers.
- A source-wide guard against reintroducing the unsupported replacement keyword.

`functional_tests/test_m365_agent_streaming.py` exercises the real
`LoggingChatCompletionAgent` and Semantic Kernel streaming API with an offline
model. It covers multi-chunk completion, stable identity/journal context,
interleaved stream isolation, early close without prefetch, preserved
approval/sign-in exceptions, and failure logging.

The shared Cosmos fake now matches the body-derived replacement contract and
rejects an explicit replacement `partition_key`, so existing M365 regression
suites also exercise the corrected call shapes.

Before the fix, production SDK tests reproduced the reported exception and the
old stream pull pattern lost its journal after the first chunk. After the fix,
the SDK calls retain partition/ETag protections and the agent stream completes
and closes without changing contexts.

The final integrated run passed **571 tests and 96 subtests**. Focused
optimized-Python coverage passed **109 tests and 56 subtests**; all **13**
fresh-process web/scheduler import checks passed. The route policy and
documentation checks also passed.

The existing `test_chat_stream_new_conversation_reattach.py` has an unrelated
exact assertion for historical application version `0.239.191`. It fails
against the pre-fix `0.261.030` code as well; no production behavior or unrelated
test was changed to conceal that stale assertion.

## Deployment and impact

Deploy the updated application to the web workers and scheduler together.
No SDK upgrade, database migration, app-registration permission change, or
deployer-version change is required. Requests that already failed should be
retried explicitly; this fix does not automatically replay uncertain external
operations.

Azure inspection was read-only. Offline SDK and model tests do not establish
live Microsoft Graph permissions or certify the fix on an unrestarted deployment.
See [Microsoft 365 actions](../features/MICROSOFT_365_ACTIONS.md) for the existing
cloud and authorization requirements.
