---
layout: latest-release-feature
title: "See Exactly What Shaped Each Answer"
description: "Every response now carries a Conversation Context citation showing the model, app version, workspace scope, selected documents, agent, and capabilities that were active when it was written."
section: "Latest Release"
---

Current release version for See Exactly What Shaped Each Answer: **0.261.001**

The context snapshot is both given to the model as hidden grounding and shown to you as a citation on the response. It covers streaming answers, retries, fallbacks, collaboration conversations, and document actions, so the record is consistent no matter which path produced the answer.

## User Side

Every response now carries a Conversation Context citation showing the model, app version, workspace scope, selected documents, agent, and capabilities that were active when it was written.

## Admin Side

Admins decide whether See Exactly What Shaped Each Answer is available in your environment. If you cannot find Open Chat, ask whether the related settings, governance policy, or workspace access has been enabled for your account.

## Why It Matters

This matters because when an answer surprises you, the first question is usually which model and which documents were actually in play, and now that is one click away.

## How to Try It

1. Open Chat and send any question.
2. When the response arrives, open the citations area on that message.
3. Select the Conversation Context citation.
4. Review the model name and SimpleChat version that produced the answer.
5. Check the workspace scope and the specific documents that were selected.
6. Confirm which agent and which capabilities were active for that turn.
7. Change your model or document selection, ask again, and compare the two context snapshots.

## Notes

- The See Exactly What Shaped Each Answer guide belongs to the SimpleChat 0.261.001 latest-feature set.
- The gallery for this page uses `release_260_conversation_context_grounding_1.png`, `release_260_conversation_context_grounding_2.png`, `release_260_conversation_context_grounding_3.png` from the app Latest Features catalog.
