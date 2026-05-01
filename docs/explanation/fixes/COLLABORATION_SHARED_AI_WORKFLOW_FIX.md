# Collaboration Shared AI Workflow Fix

Fixed/Implemented in version: **0.241.021**

## Overview

Collaborative conversations were still posting plain shared messages even when the chat toolbar had an active workspace search, web search, image generation, prompt, or agent selection. That meant shared conversations did not enter the same model and agent workflow that single-user chat already uses.

The shared composer also did not provide an explicit way to target a model without turning on a tool. Users could tag participants, but they could not tag an available model or agent as a first-class AI target in the same shared conversation.

## Root Cause

The collaboration composer only posted to the shared message endpoint with message text, reply metadata, and participant mentions. The single-user orchestration path lives behind `/api/chat/stream`, so the shared flow never carried model selection, agent selection, workspace scope, document selections, web search, image generation, or reasoning settings into the AI workflow.

On the frontend, the `@` suggestion menu was limited to human participants and invite suggestions. Because explicit `@model` and `@agent` tags were never parsed into `ai_invocation_target` metadata, a no-tool shared send still fell back to a plain collaborative message instead of the AI streaming path.

## What Changed

- Added a collaborative streaming route that saves the shared AI request, proxies the existing `/api/chat/stream` workflow against a hidden backing source conversation, and mirrors the final assistant or image response back into the collaboration message store.
- Extended collaboration persistence helpers so shared messages can be stored as explicit `ai_request` messages and can mirror source assistant/image messages without losing source linkage or thought access.
- Reused the existing single-user frontend request builder so shared AI sends use the same payload for model, agent, workspace, web, image, prompt, and reasoning settings.
- Added a visible invocation target chip to shared AI request messages so the sender and participants can see whether the request targeted `@Image`, a selected agent, or the current model.
- Added collaboration-side rendering support for mirrored image responses.
- Extended the collaboration `@` suggestion menu so it now surfaces available agents and available models alongside participant tags and invite suggestions.
- Added explicit `@agent` and `@model` parsing so shared sends can target AI without selecting a toolbar tool, and the raw `@target` text is stripped from the final message body in favor of a structured chip.
- Split shared chip styling so participant mentions, agent targets, and model targets render with different background colors.
- Updated the streaming chat bridge so explicit tagged-agent requests stamp `agent_selection` and the actual resolved model onto the hidden source user message metadata, which keeps shared user-message detail panels aligned with the assistant response.
- Synced source conversation tags and context metadata back into the collaborative conversation record after streaming completes so shared conversation details reflect the resolved agent and actual model used.

## Files Modified

- `application/single_app/functions_collaboration.py`
- `application/single_app/route_backend_collaboration.py`
- `application/single_app/static/js/chat/chat-collaboration.js`
- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/static/js/chat/chat-streaming.js`
- `application/single_app/static/css/chats.css`
- `application/single_app/config.py`

## Validation

- Added regression coverage in `functional_tests/test_collaboration_shared_ai_workflow.py`.
- Extended `ui_tests/test_chat_collaboration_ui_scaffolding.py` to cover target-specific chip styling and `@` suggestion rendering for agents and models.
- Verified diagnostics were clean for the touched backend and frontend files.

## User Impact

- Shared workspace and web requests now enter the same model or agent workflow as single-user chat.
- Shared image requests now route to image generation and mirror the resulting image back into the collaboration conversation.
- Shared AI requests now display an explicit target chip instead of silently acting like a plain participant message.
- Shared conversation authors can now type `@Default Agent` or `@gpt-5.4` to direct a message to an agent or model without selecting a tool first.
- Shared participant tags, agent targets, and model targets now render as visually distinct chips.
- Shared user-message metadata now shows the tagged agent and the actual resolved model instead of only the dropdown model selection.
- Shared conversation details now inherit the resolved model and agent tags from the hidden source conversation after AI completion.