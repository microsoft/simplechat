---
layout: page
title: "Use web search"
description: "Ground a chat answer in current public web results, and understand exactly what leaves SimpleChat when you do."
section: "Guides"
audience: user
---

## What this does

**Web** grounds a single chat message in current public web results. When you turn it on and send a message, SimpleChat hands that message to an Azure AI Foundry agent your administrator configured. That agent uses the Grounding with Bing Search service to run the search and returns summarized results together with the source links. Those results are added to the context for your answer, so the model can respond with information published after its training cutoff, and you get citations you can click and verify.

This replaced the direct Bing search integration that Microsoft retired. The agent-based path is why an administrator has to configure a Foundry project and agent before the **Web** control appears at all.

{% include media.html src="workflow-web_search.png"
                      alt="Flow diagram: a prompt goes from the user through the web UI to the backend API, which decides whether web search is used. If it is, an Azure AI Foundry agent queries Bing Search and returns grounded context and citations, which are combined with workspace context in the Azure OpenAI chat completion that produces the answer."
                      title="How a web-search message is answered"
                      caption="Conversation history goes to the chat completion. Only the search query goes to the Foundry agent and on to Bing." %}

## What leaves SimpleChat

This is the part worth reading carefully, because web search is the one chat feature that sends your content to a service outside the Azure compliance boundary.

**Exactly one thing is sent to the search boundary: the message you just typed.** SimpleChat derives the search query from the current user message alone, trimmed of surrounding whitespace. It is not rewritten using earlier turns, not summarized from the conversation, and not expanded with anything the model already knows about your session.

The following are **never** sent for web search:

- Earlier messages in the conversation, from you or the assistant.
- Documents in your personal, group, or public workspaces.
- The contents of files you attached to the conversation.
- System prompts, agent instructions, or agent action configuration.
- Workspace names, document titles, tags, or classification labels.

The practical consequence is simple and worth internalizing: **the message you type is the disclosure decision.** If you would not paste that sentence into a public search engine, do not send it with **Web** turned on. Nothing else in the conversation goes with it, and nothing you said earlier gets pulled along behind you.

Everything else behaves normally. Conversation history and any workspace results are still sent to Azure OpenAI to compose the answer, exactly as they are for a message without web search. The narrow boundary described above is specifically the external search hop.

### Deep Research sends more queries, but still no history

[Deep Research]({{ '/guides/use-deep-research/' | relative_url }}) builds on this same search path. Instead of a single query, it plans several related queries and runs each one through the same Foundry agent.

Those additional queries are all derived from your current message. Turning on Deep Research increases how many searches leave SimpleChat; it does not widen what they are derived from, and it does not start sending conversation history.

### Compliance boundary

An administrator had to accept this notice before web search could be enabled:

> When you use Grounding with Bing Search, your customer data is transferred outside of the Azure compliance boundary to the Grounding with Bing Search service. Grounding with Bing Search is not subject to the same data processing terms (including location of processing) and does not have the same compliance standards and certifications as the Azure AI Agent Service, as described in the Grounding with Bing Search TOU.

If your organization has rules about what may be sent to consumer search services, those rules apply to the text you type into a web-search message.

## Why you would use this

Use web search when the answer depends on current public information rather than on your workspace documents or the model's training data. Product releases, current prices, recent news, changed public documentation, and "what is the latest version of X" all qualify.

It is the wrong tool when the authoritative answer lives in your own approved files, when the prompt itself is confidential, or when you need a reproducible answer, since public sources change underneath you.

## Before you start

- An administrator must enable `enable_web_search` **and** accept the data-handling consent. Both are required; the toggle alone does nothing until consent is recorded. See [Search and Extract]({{ '/admin/knowledge/' | relative_url }}).
- An administrator must configure a Foundry project endpoint and an agent ID. If the agent is missing, SimpleChat tells you web search is unavailable rather than quietly answering from training data.
- If your tenant enables the user notice, a banner appears above the composer while **Web** is active.

## Steps

1. Open **Chat**.
2. Write a question that needs current public information. Write it as a self-contained question, because the rest of the conversation is not sent with it. "What changed in the latest release of X" works; "what about the newest one" does not, since the search never sees what "one" referred to.
3. Select **Web**.

{% include media.html src="guides/use-web-search-step-3.png"
                      alt="The chat composer with the Web control switched on and the data notice banner visible above the message box."
                      title="Turning on Web for a message"
                      capture="Show the chat composer with Web enabled and the web search notice banner visible above it. Use a neutral sample question." %}

4. Read the notice if it appears. Dismissing it hides it for the rest of the browser session; it does not turn web search off.
5. Select **Send Message**.

{% include media.html src="guides/use-web-search-step-5.png"
                      alt="A chat answer grounded in web search, with source links listed beneath the response."
                      title="A grounded answer with its sources"
                      capture="Show a completed web-search answer with the source citations visible beneath it. Use a neutral public topic and redact any tenant identifiers." %}

6. Turn **Web** off for later messages that should not go to public search. It stays on until you turn it off.

## Verify it worked

A grounded answer arrives with source links attached, the same way [Deep Research]({{ '/guides/use-deep-research/' | relative_url }}) presents its sources. Open one and confirm it supports the claim you care about.

If the search could not run, the assistant says so explicitly. It is instructed not to fall back to training data and present it as current, so "I could not complete the web search" is the correct, working behavior rather than a failure to answer.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| **Web** is missing from the composer | Web search is disabled, or consent was never accepted | Ask an admin to review `enable_web_search` and the consent step. |
| The assistant says web search is unavailable | No Foundry agent ID is configured | Ask an admin to finish the Foundry agent configuration and use the built-in test button. |
| The assistant says the search failed | The Foundry agent call errored | Retry. If it persists, ask an admin to check the agent's credentials and role assignments. |
| The answer ignores current information | **Web** was off when the message was sent | Turn **Web** on and resend. It applies per message. |
| **Web** turns off in **Image** mode | Image generation disables source controls | Turn off **Image** first. |
| The notice stopped appearing | You dismissed it earlier in this browser session | It returns in a new session. Web search is unaffected either way. |

## Related

- [Use deep research]({{ '/guides/use-deep-research/' | relative_url }})
- [Review pasted URLs]({{ '/guides/review-pasted-urls/' | relative_url }})
- [Search and Extract]({{ '/admin/knowledge/' | relative_url }})
