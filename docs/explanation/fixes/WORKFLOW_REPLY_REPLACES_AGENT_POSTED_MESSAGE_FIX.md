# Workflow Reply Replaces the Agent-Posted Message Fix

Fixed in version: **0.261.253**

## Issue Description

An agent workflow can create a conversation and post into it through the Simple Chat action. An
alert-triage workflow, for example, creates a group conversation for the response team and posts
its opening briefing as the first message. When the run finishes, SimpleChat mirrors the run's
full reply into the same conversation, with the maps and tool sources attached.

The conversation then opened with the same findings twice, each several screens long with the same
images:

1. the run's own post, stored as the workflow user's message and labelled "posted through an
   agent", so it read as though that person had written it;
2. the mirrored reply, from the agent, with the map and every source.

The workflow's own conversation, **Workflow: *name***, also stayed in the chat list. A scheduled
workflow updates it on every run, so it kept moving to the top of the list above the conversation
people actually needed.

## Root Cause Analysis

- `_mirror_workflow_visualizations_to_created_conversations` mirrored the run's reply into each
  created conversation, but nothing recorded that the run had already posted there.
- The run's post and the reply were separate messages that every client showed.
- Personal workflow conversations are created visible (only group workflow conversations start
  hidden), and nothing changed that once the run delivered its result elsewhere.

## Technical Details

### Files Modified

- `application/single_app/functions_workflow_runner.py`
- `application/v2_ui/src/lib/sharedMessage.ts`
- `application/v2_ui/src/components/chat/MessageList.tsx`
- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/static/js/chat/chat-collaboration.js`
- `application/single_app/config.py`

### Code Changes Summary

- `_extract_run_posted_message_ids_from_citations` reads the run's own posts from its tool results:
  the opening message a `create_*_conversation` call seeded (`seeded_initial_message`) and every
  `add_conversation_message` call. Failed calls are ignored.
- After the reply is mirrored into a conversation, `_hide_run_posts_superseded_by_reply` marks
  those posts with `metadata.superseded_by_workflow_reply` (`message_id` of the reply,
  `workflow_id`, `superseded_at`). The mark is applied only to messages posted through the agent
  action (`posted_via: agent_action`). The message stays stored, and stays in the conversation's AI
  history. The step is best effort and never undoes the mirror.
- The mirrored reply is unchanged: it keeps the full content and every citation, maps included.
- `_hide_workflow_conversation_after_delivery` hides the workflow conversation the first time a run
  delivers into a conversation it created, records `workflow_delivery_hidden_at`, and bumps the
  owner's conversation cache version. A person who shows the conversation again is not overruled
  by later runs. Runs that create no conversation leave it alone.
- V2 (`isSupersededByWorkflowReply` in `MessageList`) and both classic message loops leave a
  superseded message out of the thread. It stays loaded, so a reply that quotes it still resolves.

### Impact Analysis

- The created conversation opens with the run's full reply, once.
- The workflow conversation remains available from the workflow alert's links and the classic
  "show hidden conversations" toggle, and still records every run.
- Messages people write are never hidden, and agent posts made outside a workflow run are
  unaffected.
- Conversations created before this version keep both messages until a new run delivers into
  them.

## Testing Approach

- `functional_tests/test_workflow_reply_replaces_agent_posted_message.py` compiles the real runner
  functions against in-memory stores. It covers group and personal deliveries, which messages are
  hidden, a created conversation with no post of its own, a run that creates nothing, the one-time
  hide of the workflow conversation, a retried mirror, a failed hide, and the classic message loops.
- `ui_tests/test_chat_workflow_results.py::test_a_runs_own_post_gives_way_to_its_mirrored_reply`
  renders the real V2 chat page and checks that only the reply shows, while an agent post without
  the mark still shows.

## Validation

- Before: a created group conversation opened with the briefing (about 7,400 px tall) followed by
  the mirrored reply repeating it (about 7,300 px), and **Workflow: *name*** stayed at the top of the
  chat list.
- After: the conversation opens with the reply, maps and sources included, and the workflow
  conversation steps out of the chat list after the first delivery.

## Related

- [Workflow visualization conversation mirror fix](WORKFLOW_VISUALIZATION_CONVERSATION_MIRROR_FIX.md)
- [V2 inline media and agent-posted messages](../features/V2_INLINE_MEDIA_AND_AGENT_MESSAGES.md)
