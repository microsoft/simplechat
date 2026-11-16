# Microsoft 365 agent stream context and interrupted replies (v0.261.129)

Fixed in version: **0.261.129**

Related version update: `application/single_app/config.py`, from `0.261.128`
to `0.261.129`. Associated issue: [#1523](https://github.com/microsoft/simplechat/issues/1523).
This follows the [Microsoft 365 agent streaming fix](M365_AGENT_STREAMING_FIX.md)
from 0.261.031.

## Reported failure

An agent with the Microsoft 365 actions ended its answer with
`Stream interrupted: Agent streaming failed`. The banner said the partial
content had been saved, but after a reload the conversation didn't contain the
answer that had streamed. The agent had also told the user that it could only
see recent mail and calendar items.

Application Insights for the reported request recorded this exception while
the Microsoft 365 continuation journal closed at the end of the stream:

```text
ValueError: <Token ...> was created in a different Context
```

## Root causes

### Each streamed chunk ran in a new context

The chat route wraps the selected agent in `AgentExecution` from
`agent_delegation_runtime.py`, and reads that stream through the
`SyncAsyncStream` bridge added in 0.261.031, so the outer stream keeps one
context. Inside it, `AgentExecution` awaited each pull of the agent's own stream
through `await_agent_operation`, which used `asyncio.ensure_future`. Every pull
therefore ran in a new task with a fresh copy of the context.

The continuation journal sets ContextVars during the stream's first pull and
resets them after its last. That reset ran in a different context than the one
that set them, and raised `ValueError`. The journal, and therefore this failure,
applies when an agent has a OneDrive or SharePoint Online action or runs in a
workflow.

### Interrupted replies weren't saved

The route's handler for agent stream errors sent an error event and returned.
That skipped the stream-level handler that saves an interrupted reply, so the
content already shown in the browser never reached the conversation.

### The banner claimed the reply was saved

`chat-streaming.js` always said "The partial content above has been saved."
whether or not the server had saved anything.

### Mail and calendar reads only reached recent items

The agent's statement was accurate for the tools it had. **Read my mail**
returned only the newest inbox messages, with no date range or search. **Read my
calendar events** without a range read `me/events` from the earliest start, so
it returned the calendar's oldest events and recurring series rather than
upcoming occurrences. Microsoft Graph permissions weren't the limit: the same
`Mail.Read` and `Calendars.Read` scopes cover mail and events of any age.

## Changes

`await_agent_operation` accepts a caller-owned `contextvars.Context`.
`AgentExecution` creates the agent stream, pulls every chunk, and closes the
stream in one copied context, and still checks cancellation and time limits
while each pull is awaited. Callers that don't pass a context keep the previous
behavior.

The agent stream error handler in `route_backend_chats.py` now re-raises
unexpected failures to the stream-level handler. That handler saves any content
already streamed, marks the message `incomplete` with the `stream_interrupted`
error, and reports `message_persisted` with the saved `message_id`. Token
budget and Foundry sign-in errors keep their dedicated responses. Microsoft 365
approval and sign-in waits bypass the save and reach the request-level
handlers, which record the resumable wait instead of an interrupted reply.

The browser banner now says the partial content was saved only when the error
reports a persisted assistant message with an ID. Otherwise it says the visible
content wasn't saved and won't appear after a reload. Approval waits say the
request continues after the decision.

**Read my mail** and **Read my calendar events** gained search words, date
ranges, and continuation arguments. See
[Microsoft 365 actions](../features/MICROSOFT_365_ACTIONS.md#mail-and-calendar-history)
for that design. No capability, permission, or app registration change is
required.

## Validation

`functional_tests/test_agent_delegation_runtime.py` checks that agent
operations can share one caller-owned context.

`functional_tests/test_m365_agent_streaming.py` runs a delegated agent stream
with the real continuation journal. It covers:

- the journal and model context staying set until the stream completes
- the journal closing in the context where it opened, for both completed and
  cancelled streams
- unexpected agent stream failures reaching the interrupted-reply handler
- Microsoft 365 approval and sign-in waits bypassing that handler

`functional_tests/test_m365_chat_action_cards.py` sends an agent reply that
fails after streaming text through the real Flask chat route. It checks that
the browser receives the partial text with `message_persisted` and a message
ID, that no exception text reaches the browser, that the saved message is
marked `incomplete` with the `stream_interrupted` error, and that reopening the
conversation shows it. Against the previous route the browser receives only
"Agent streaming failed. Please try again." and nothing is saved.

`ui_tests/test_chat_stream_error_persistence_banner.py` drives the real
`chat-streaming.js` in a browser. It checks that the banner reports a saved
reply only when the error names one, and that the visible partial content stays
on screen. Nine of its eleven cases fail against the previous script.

`functional_tests/test_m365_mail_calendar_search.py` runs the real Graph plugin
and transport with scripted Graph responses, covering date ranges, search,
continuation without repeats, ties at range boundaries, and rejected input. All
of its tests fail against the previous plugin.

## Deployment and impact

Deploy the updated application and restart it. No database migration, SDK
upgrade, Graph permission, or deployer change is required. Replies that were
already lost can't be recovered; send the request again.

Offline tests don't show that a tenant's mailbox or calendar holds a given
item. Retention policies, archive mailboxes, and shared calendars still bound
what Microsoft 365 returns.
