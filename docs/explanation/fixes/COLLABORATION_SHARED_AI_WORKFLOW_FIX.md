# Collaboration Shared AI Workflow Fix

Fixed/Implemented in version: **0.241.019**

## Overview

Collaborative conversations were still posting plain shared messages even when the chat toolbar had an active workspace search, web search, image generation, prompt, or agent selection. That meant shared conversations did not enter the same model and agent workflow that single-user chat already uses.

## Root Cause

The collaboration composer only posted to the shared message endpoint with message text, reply metadata, and participant mentions. The single-user orchestration path lives behind `/api/chat/stream`, so the shared flow never carried model selection, agent selection, workspace scope, document selections, web search, image generation, or reasoning settings into the AI workflow.

## What Changed

- Added a collaborative streaming route that saves the shared AI request, proxies the existing `/api/chat/stream` workflow against a hidden backing source conversation, and mirrors the final assistant or image response back into the collaboration message store.
- Extended collaboration persistence helpers so shared messages can be stored as explicit `ai_request` messages and can mirror source assistant/image messages without losing source linkage or thought access.
- Reused the existing single-user frontend request builder so shared AI sends use the same payload for model, agent, workspace, web, image, prompt, and reasoning settings.
- Added a visible invocation target chip to shared AI request messages so the sender and participants can see whether the request targeted `@Image`, a selected agent, or the current model.
- Added collaboration-side rendering support for mirrored image responses.

## Files Modified

- `application/single_app/functions_collaboration.py`
- `application/single_app/route_backend_collaboration.py`
- `application/single_app/static/js/chat/chat-collaboration.js`
- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/static/js/chat/chat-streaming.js`
- `application/single_app/config.py`

## Validation

- Added regression coverage in `functional_tests/test_collaboration_shared_ai_workflow.py`.
- Verified diagnostics were clean for the touched backend and frontend files.

## User Impact

- Shared workspace and web requests now enter the same model or agent workflow as single-user chat.
- Shared image requests now route to image generation and mirror the resulting image back into the collaboration conversation.
- Shared AI requests now display an explicit target chip instead of silently acting like a plain participant message.