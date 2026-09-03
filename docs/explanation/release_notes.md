<!-- BEGIN release_notes.md BLOCK -->

For feature-focused and fix-focused drill-downs by version, see [Features by Version](https://github.com/microsoft/simplechat/tree/main/docs/explanation/features) and [Fixes by Version](https://github.com/microsoft/simplechat/tree/main/docs/explanation/fixes).

### **(v0.261.034)**

#### Bug Fixes

*   **Shared Conversations Opened Empty In The V2 Interface**
    *   Clicking a shared conversation in the new interface showed a thread with no messages in it. The interface loaded every conversation's messages from the personal chat API, which does not hold shared conversations and answers with an empty list rather than an error, so the conversation opened successfully with nothing in it — and remained the target of the next message sent.
    *   Shared conversations are now read from the collaboration API they actually live in, in both the personal and the group case.
    *   (Ref: V2 chat, `/api/get_messages`, `/api/collaboration/conversations`)

#### New Features

*   **Shared Conversations In The V2 Interface**
    *   The new interface now supports shared conversations in full, matching the classic one. Both shared personal and shared group conversations can be read, replied to and managed there.
    *   **Messages say who wrote them.** Another participant's message appears on the left with their name above it, and your own on the right as before. Uploads shared into the conversation are shown as named attachments, and a message that asked the assistant is labelled as such.
    *   **The assistant only answers when asked.** As in the classic interface, a message in a shared conversation goes to the other people in it and not to the model — unless it `@`-mentions a model or an agent, or you have turned on an assistant tool such as document search, web search, image generation, deep research, reading URLs, an agent or a saved prompt. Tagging a model or agent uses that one for the message, whatever the pickers hold.
    *   **Type `@` to mention somebody.** The menu offers the people already in the conversation, the models and agents you can address, and — if you can manage members — people you could add. Choosing one of the last group invites them.
    *   **The conversation stays live.** Messages other people write appear as they are sent, along with a "typing" indicator, and deletions and masks applied by others are reflected straight away. You are told when somebody mentions you.
    *   **Reply to a specific message** with the reply button on any message; the reply shows what it is answering.
    *   **Share an existing conversation** from the new **people** button in the chat header, or **Share** in the conversation's menu in the left rail. The same panel manages who is in the conversation, promotes members to admin, removes people, and lets you leave it or delete it for everyone. What you are offered follows what you are actually allowed to do.
    *   **Invitations** are shown above the conversation with **Join** and **Decline**. You can read an invited conversation before joining, so you can see what you are being invited to.
    *   **Files the assistant generates** in a shared conversation are held back until approved, and anything waiting on your decision is listed above the thread with Approve and Deny.
    *   Retry, edit, attempt navigation and fork are not offered in a shared conversation, matching the classic interface — those actions have no equivalent there.
    *   Requires **Collaborative conversations** to be enabled in admin settings. With it off, none of these controls appear.
    *   (Ref: V2 chat, collaboration API, participants panel, mentions, live updates)

#### User Interface Enhancements

*   **Mentioning Somebody No Longer Notifies The Wrong Person**
    *   Where one person's display name is the start of another's — "Ada" and "Ada Lovelace" — writing "@Ada Lovelace" also counted as mentioning "Ada", and notified them. The longer name now claims its own text, so only the person actually named is notified. Naming both people in one message still notifies both.
    *   (Ref: shared conversations, mentions)

### **(v0.261.033)**

#### New Features

*   **Save A Diagram As A Picture**
    *   Diagrams in the new interface now have a **PNG** button, matching the one charts have always had. The image is captured from the diagram exactly as it appears on screen, so whatever colours and background you have chosen come with it.
    *   The picture is saved on a solid background rather than a transparent one, so it stays readable wherever you paste it.
    *   (Ref: V2 chat, Mermaid diagrams, PNG download)

*   **Choose The Colours For Diagrams And Charts**
    *   Every diagram and chart in the new interface now has a **Colors** button offering five palettes — Default, Calm, Vivid, Warm and Contrast — the same five the classic interface already used for charts.
    *   Charts additionally let you set each series or slice individually, and both diagrams and charts let you set a background colour. Leaving the background on **Match theme** means it keeps following light and dark mode, as before.
    *   Set your own defaults under Settings → Preferences, in the new **Diagrams** and **Charts** sections. Those apply everywhere you have not chosen something specific.
    *   Colours you choose on an individual diagram or chart are saved with the conversation, so they are still there when you come back to it. Recolouring one chart never changes the others — three charts in a reply keep three independent sets of colours.
    *   Anything you have not touched looks exactly as it did before.
    *   (Ref: V2 chat, Mermaid diagrams, inline charts, user preferences)

### **(v0.261.032)**

#### New Features

*   **Links To A Conversation Now Work In The V2 Interface**
    *   The V2 chat page never put the open conversation in the address bar, so copying the URL shared nothing and reloading the page dropped you into an empty chat. It now names the conversation you are reading, exactly as the classic interface has since v0.237.001.
    *   A link such as `/v2/chat?conversationId=<id>` opens that conversation. Both spellings the application produces are accepted — `conversationId` from notifications and workflow runs, `conversation_id` from chat responses and workspace document rows — so an existing link opens either way.
    *   The address bar keeps up on its own: it follows conversations you open from the list, the one created when you send your first message, and forks. Starting a new chat or deleting the open conversation clears it. Opening several conversations does not fill the back button with an entry for each.
    *   A linked conversation that is older than the loaded list, or hidden, now appears in the rail with its real title instead of leaving the header reading "New chat".
    *   A link to a conversation that was deleted, or that belongs to somebody else, says so and returns you to an empty chat, rather than leaving an error that reappeared on every refresh.
    *   **Back to classic UI** in the account menu carries the conversation across, so switching interfaces keeps your place.
    *   (Ref: V2 chat, conversation deep linking, conversation list)

### **(v0.261.031)**

#### New Features

*   **Ask For A Diagram, Get A Diagram**
    *   Asking for a diagram, flowchart, sequence, architecture or data flow used to come back as ASCII box art in a plain code block — unreadable, impossible to export as a picture, and meaningless to a screen reader. The assistant was never told that SimpleChat can draw real diagrams, so it fell back on drawing with keyboard characters.
    *   Diagram requests now get an answer the app actually draws. Chart requests are unaffected: "plot the sales trend" is still a chart, "draw the request flow" is now a diagram.
    *   The assistant is also steered toward diagram syntax that renders on the first attempt, and toward a diagram rather than a generated image for structural content, so the result stays selectable, searchable and accessible.
    *   (Ref: chat prompt guidance, Mermaid diagrams, inline charts)

*   **Diagrams Now Render In The Classic Chat Interface**
    *   The classic interface could turn a diagram into a picture when you exported it, but showed the same diagram as a block of code in the conversation itself. Diagrams now render on screen where you are reading them.
    *   Diagrams follow light and dark mode, appear as they finish streaming rather than flickering through half-written source, and a diagram that cannot be drawn shows its source instead of vanishing.
    *   Copying a message and exporting one both still produce the original diagram code, so nothing downstream changes.
    *   The diagram library is only downloaded the first time a conversation shows a diagram.
    *   (Ref: classic chat rendering, Mermaid diagrams, dark mode)

#### Bug Fixes

*   **Chart Guidance No Longer Suppresses Genuine Diagrams**
    *   Guidance intended to stop the assistant from answering a chart request with diagram code was worded broadly enough to discourage diagrams entirely, including in answers where a process or architecture diagram was the right thing to show.
    *   It now rules out diagram code only as a substitute for a data chart, and explicitly allows a diagram alongside charts in the same answer.
    *   (Ref: chart guidance, Mermaid diagrams)

*   **Spoken And Preview Text No Longer Read Out Internal Placeholders**
    *   Reply previews and read-aloud could include internal placeholder text left behind where a chart, diagram or image card sits in a message. Those placeholders are now removed before the text is previewed or spoken.
    *   (Ref: reply preview, text-to-speech, inline visuals)

### **(v0.261.029)**

#### New Features

*   **Image Suggestions Can Now Be Approved In The New Interface**
    *   When a reply would be clearer with a picture — a timeline, a slide visual, a diagram — the assistant can suggest one instead of producing it unasked. The new interface previously showed those suggestions as a block of raw JSON, so there was no way to act on them.
    *   Each suggestion now appears as a card in the reply, exactly where the assistant put it, with **Approve** to generate the image, **Edit** to reword the prompt first, and **Cancel** to dismiss it. Nothing is generated until you ask for it.
    *   A reply containing more than two suggestions gets an **Approve all** button, and approvals are run one at a time with their place in the queue shown, rather than starting every image at once.
    *   An approved image appears inside its own card rather than at the end of the conversation, so it stays next to the paragraph it illustrates — including after the conversation is reopened. Clicking it opens the same full-size viewer as any other image.
    *   Approval is refused in shared conversations, which the card now tells you rather than failing silently. A suggestion can only be approved once the reply has finished arriving.
    *   (Ref: `simpleimage` proposals, V2 chat interface, `/api/chat/image-proposals/generate`, image generation)

### **(v0.261.028)**

#### Bug Fixes

*   **Your Configured Chat Notices Now Appear In The V2 Interface**
    *   Two notices administrators can configure — the data-handling notice shown when web search is used, and the AI notice shown under the message box — appeared in the classic interface but never in V2. Anyone who switched interfaces stopped seeing them.
    *   The web search notice now appears above the message box while web search is turned on, using your configured wording, and can be dismissed for the rest of the browser session. It requires the same three settings as before, including the consent acknowledgement.
    *   The AI notice now appears below the message box and respects all four display behaviours: always visible, dismissible once per session, once per day, or once per message version. Editing the notice text still brings it back for everyone who had dismissed the previous wording.
    *   A dismissal now carries across both interfaces in the same browser session, rather than reappearing when you switch.
    *   Dismissing the notice waits for the change to save, so it no longer disappears and then return on the next page load. A failed save is now reported instead of looking like a dead button.
    *   **Behaviour change**: V2 previously showed its own fixed line, "AI responses can be inaccurate. Verify important information.", regardless of your settings. That line has been removed. If you want a notice under the message box, enable the AI notice in Admin Settings → Notices & Agreements → Chat AI Notice and set your own wording; if the AI notice is turned off, V2 now shows nothing there, matching the classic interface.
    *   (Ref: V2 chat composer, web search user notice, chat AI notice, `/api/v2/bootstrap`)

### **(v0.261.027)**

#### New Features

*   **Diagrams In Exports No Longer Need The Browser You Exported From**
    *   Diagrams are drawn by your browser when you export from one that can draw them. Anything else — an export started from an interface that does not, or one the server starts on its own — previously fell back to showing the diagram's code.
    *   Those diagrams are now drawn on the server, using the Chromium the app already installs. No new dependency was added, nothing is fetched from the internet, and a diagram looks the same whichever way it was drawn.
    *   A diagram your browser already drew is never drawn twice, and an export containing no diagrams does no extra work.
    *   Deployments built without the optional Chromium component are unaffected and keep showing the diagram's code, as before.
    *   (Ref: conversation and message exports, Mermaid diagrams, server-side rendering)

### **(v0.261.026)**

#### New Features

*   **Diagrams And Formulas Now Become Pictures In Exports**
    *   Assistant replies often contain Mermaid diagrams and LaTeX formulas. Until now these arrived in an exported file as raw code — a wall of `graph TD` lines or `\frac{a}{b}` — which was unreadable for anyone the file was sent to.
    *   Word, PowerPoint, PDF, Markdown and email exports now render them as images, the same way inline charts have always been handled, so an exported file matches what the conversation shows.
    *   Recognised formula syntax is ` ```math `, ` ```latex ` and ` ```tex ` blocks, `$$…$$`, and `\[…\]`. Single-dollar text is deliberately left alone so a sentence like "costs $100 to $200" is never mistaken for a formula, and a ` ```text ` block is never mistaken for one either.
    *   **Open in Email** treats them like charts: each diagram and formula downloads as a PNG file with a matching reference in the draft body, because a `mailto:` draft cannot carry inline images.
    *   Anything that cannot be drawn — an unusual diagram, or a formula using an environment such as `align` or `matrix` — keeps its original code block rather than failing the export.
    *   (Ref: conversation and message exports, Mermaid diagrams, TeX math, inline export visuals)

### **(v0.261.025)**

#### User Interface Enhancements

*   **Generated Images Now Open In A Viewer Instead Of A New Tab**
    *   In the V2 interface, clicking an image the assistant generated used to open the raw file in a new browser tab, dropping you out of your conversation. It now opens in a viewer over the page, matching how the classic interface has always behaved.
    *   The viewer scales the image to fit and can switch to actual size, where a large image scrolls so its edges stay reachable. Clicking the image toggles between the two.
    *   Saving the image and opening the raw file are both available from the viewer, so nothing is lost by staying in the app. Close it with the close button, the Escape key, or by clicking outside it.
    *   Smaller images previously did nothing at all when clicked, because browsers refuse to open the inline format they arrive in. Those images now open correctly, and can be saved.
    *   Images you upload benefit in the same way, since they are shown through the same message type.
    *   (Ref: V2 chat image messages, image lightbox, image download)

### **(v0.261.024)**

#### New Features

*   **Equations, Diagrams And Charts Render In The V2 Chat**
    *   Answers containing mathematics now show it set as mathematics rather than as raw TeX. `$$…$$`, `\[…\]` and `\(…\)` are recognised. A single `$` is deliberately left alone, so an answer about pricing still reads "costs $5 to $10 per user" rather than turning the sentence into an equation.
    *   Mermaid diagrams render as diagrams. These have been reaching the chat for some time without anyone being able to see them: documents processed with Content Understanding have their figures extracted as Mermaid, so a document containing a flowchart was arriving as diagram source in the middle of an answer.
    *   Charts produced by the built-in chart action now draw in V2 as they already do in the classic interface, instead of showing the underlying data as a block of JSON.
    *   A diagram or chart that cannot be read falls back to showing its source rather than disappearing, and one that is still being written shows a placeholder until it is complete.
    *   (Ref: V2 chat rendering, KaTeX, Mermaid, Chart.js, `AssistantMarkdown.tsx`)

*   **Chart Data And Image Download**
    *   Each chart carries its title, subtitle and description, plus a **Data** control that reveals the numbers behind it and a **PNG** control that downloads the image. The data table starts closed, so the chart stays the answer, and the download is composited onto a solid background so it stays readable wherever it is pasted.
    *   Charts and diagrams follow the light and dark theme rather than staying fixed to whichever was active when they first drew.
    *   (Ref: V2 inline charts, chart data table, PNG export)

#### User Interface Enhancements

*   **Copying A Message Containing A Chart**
    *   Copying an answer with a chart in it used to paste several kilobytes of chart data into the middle of the text. The chart's title and its numbers are now pasted as a small table instead. Equation and diagram sources are left as they are, since those are still readable as text.
    *   (Ref: V2 message copy, `messageText.ts`)

#### Breaking Changes

*   **None.** No settings were added, and the Content-Security-Policy is unchanged. The libraries behind this work are committed to the repository under `application/v2_ui/public/vendor/` and served from SimpleChat itself, so nothing is fetched from a public CDN at run time or from a package registry at build time. Pinning them this way means any future change to that third-party code is a reviewable commit rather than a silent substitution.

### **(v0.261.023)**

#### User Interface Enhancements

*   **V2 Appearance Preferences Now Follow You**
    *   Light and dark mode, the collapsed state of the left navigation, and the chat width were previously remembered only by the browser you set them in, so they reset on a different machine.
    *   They are now saved to your account. Light and dark mode in particular is shared with the classic interface, so choosing dark in either place applies to both.
    *   Your browser still remembers them as well, which is what stops the wrong theme appearing for a moment while your preferences load.
    *   (Ref: V2 theme, navigation and chat width preferences)

### **(v0.261.022)**

#### New Features

*   **The V2 Settings Page Is Now Complete**
    *   All six sections of the personal settings page are built in the V2 interface: Preferences, Stats, Groups, Public, Feedback and Violations. They no longer link out to the classic page.
    *   **Groups** and **Public** list the workspaces you belong to with search and paging, show your role in each, and let you switch which one is active. If a switch is refused — because you are not a member, or the workspace no longer exists — the reason is shown rather than the change quietly failing.
    *   **Feedback** shows the ratings you have given assistant replies, whether each has been reviewed, and any reply from a reviewer, with filters and a CSV export.
    *   **Violations** shows anything flagged on your account with its status and the categories that triggered it. You can add your own notes to a record; status and reviewer notes remain an administrator's to set.
    *   **Stats** charts your conversations, uploads, token use and sign-ins over 7, 30 or 90 days.
    *   (Ref: V2 settings tabs, group and public workspace selection, feedback, safety violations, activity trends)

### **(v0.261.021)**

#### New Features

*   **Text Size And Spoken Reply Voice In V2 Settings**
    *   The V2 Settings page now offers a text size choice that scales the whole interface, using the same sizes as the classic interface so a size chosen in one applies to the other.
    *   When text-to-speech is enabled, you can choose which voice reads assistant replies aloud. Replies are also now read as clean prose: citation markers and masked text are no longer spoken.
    *   Sections for capabilities your administrator has turned off do not appear, and preferences that only affect the classic interface are deliberately left there rather than shown as controls that would do nothing here.
    *   (Ref: V2 settings, text size, text-to-speech voice)

### **(v0.261.020)**

#### New Features

*   **Workspace Tags In The Conversation List**
    *   The conversation list now labels each conversation with the workspace it belongs to — the group or public workspace name, or a note that it is shared with other people. Personal conversations stay unlabelled, so the label means something when it appears.
    *   Previously the only way to tell a group conversation from a personal one was to open it and read the badge beside its title, which made a long list of conversations hard to navigate for anyone working across several groups.
    *   The label is drawn from information the conversation list already receives, so it costs no extra loading time.
    *   (Ref: conversation list, workspace badges, V2 interface)

*   **Personal Settings In The V2 Interface**
    *   A new **Settings** page, reachable from the account menu, gives the V2 interface its own home for personal preferences. It opens on Preferences and keeps the familiar sections from the classic profile page — Stats, Groups, Public, Feedback and Violations — each appearing only when the relevant capability is enabled.
    *   Preferences save as you change them rather than behind a Save button, and a preference that fails to save is put back to its stored value rather than left showing something that was never recorded.
    *   The first preferences available are the new workspace tags toggle and the conversation contents drawer. The remaining sections currently link through to the classic page while they are rebuilt.
    *   (Ref: V2 settings page, `/api/user/settings`, personal preferences)

### **(v0.261.019)**

#### User Interface Enhancements

*   **A Recovered Response No Longer Looks Stalled**
    *   After a dropped connection was picked back up, the message kept saying "Reconnecting" and kept a "Reconnected to the response still being generated" banner in place for the rest of the answer. Because both stayed put while the response was actually arriving, it read as though nothing was happening.
    *   The two moments are now told apart. While the connection is being re-established the message says so plainly, alongside a spinner, and it does this even when part of the answer is already on screen — so a response that stopped mid-sentence no longer just looks frozen. Once content starts arriving again the wording changes to a brief "Reconnected." note, the activity indicator goes back to the usual "Thinking", and the note clears itself a few seconds later so the rest of the answer reads like any other.
    *   (Ref: V2 streaming recovery, reconnect states)

### **(v0.261.018)**

#### Bug Fixes

*   **Copying A Message Pasted Unusable Citation Text In V2**
    *   Copying an answer put the raw citation markers on the clipboard, so a pasted paragraph read `...up to 0.2 mm/s at full load. (Source: NanoPZ.pdf, Page: 13) [#0d4d4eb0-fbbb-4821-a809-8bbd649be6ef_13]` — unusable in an email or a document.
    *   Copy now produces the answer as a person would want to read it: the citation markers are removed, along with the space in front of them so no stray gaps or double spaces are left behind, while bold, lists, headings and paragraph breaks are kept intact.
    *   The same conversion is used when saving a message as Markdown and when reusing one as a prompt, so neither carries the markers either.
    *   (Ref: V2 message copy, citation markers, `messageText.ts`)

*   **Copying A Message Could Reveal Masked Text In V2**
    *   A masked span hides text from other readers, but copying the message wrote the underlying content to the clipboard, so the hidden text could be recovered by pasting it. Saving the message as Markdown had the same problem.
    *   Redactions now survive leaving the app: masked spans are replaced with `[masked]`, and a message masked in its entirety is withheld rather than partially copied.
    *   (Ref: V2 message masking, clipboard, message download)

#### User Interface Enhancements

*   **Copy With Sources**
    *   Removing citations from a copy also removes the attribution, which is sometimes the reason for copying in the first place. The message overflow menu now offers **Copy with sources**, which appends the cited documents and pages as a short numbered list under the answer instead of interleaving them with the prose.
    *   Saved Markdown files include the same reference list, since a file is more likely to be read later by someone who wants to check where a claim came from.
    *   (Ref: V2 message actions, citation references)

### **(v0.261.017)**

#### Bug Fixes

*   **Lists And Line Breaks Disappeared After A Citation In V2**
    *   In the V2 chat page, a bullet list, heading or new paragraph that followed a citation was pulled up onto the citation's own line, so answers that cited a source lost their formatting from that point on.
    *   The citation pattern deliberately absorbs the spacing after a citation marker while it removes the marker, and V2 was discarding that spacing instead of putting it back. The blank line that separates one markdown block from the next went with it, so the following block was no longer recognised as a block.
    *   Answers now keep their structure after a citation. Citations that land inside a heading, list item, table cell or quote are also rendered properly rather than leaving a stray placeholder behind.
    *   (Ref: V2 citation rendering, markdown blocks, `chat-citations.js` parity)

*   **A Dropped Connection Lost The Answer In V2**
    *   If the connection carrying a response was interrupted — a sleeping laptop, a flaky network, a proxy timeout — V2 showed "The response ended unexpectedly" and the answer was lost, even though the server was still writing it.
    *   Responses are generated on the server and outlive the connection that requested them. V2 now checks whether the response is still being produced and picks it back up where the classic interface does, replacing what was on screen with the replayed answer so nothing is duplicated. Opening a conversation whose answer is still being written also joins it in progress rather than showing a message that stops mid-sentence.
    *   A short "Reconnected to the response still being generated" note makes it clear what happened. A reconnect is attempted once; if it fails the error is reported as before.
    *   (Ref: V2 streaming recovery, `/api/chat/stream/status`, `/api/chat/stream/reattach`)

### **(v0.261.016)**

#### Bug Fixes

*   **Document Search Failed In V2**
    *   Turning on **Documents** in the V2 chat page ended with "Something went wrong while streaming the response", while the same search worked in the classic interface.
    *   Two request problems were behind it. First, V2 identified the chosen model by its deployment name alone, but when multiple model endpoints are configured a name is not unique — the server could not resolve the selection and quietly fell back to a different endpoint than the one shown in the picker. Second, the document scope was fixed to "all workspaces" but the workspace identifiers were never sent, so the search was asked to cover workspaces it was given no way to look in.
    *   V2 now sends the full model identity with every message and retry, so the model you pick is the model that answers. The document scope is worked out from the workspaces actually in use — personal only, or personal plus the group or public workspace you are working in — and the matching identifiers travel with it.
    *   (Ref: V2 model selection, document search scope, `/api/chat/stream`)

### **(v0.261.015)**

#### New Features

*   **V2 Conversation Details Rebuilt**
    *   The details panel previously listed every tag as one undifferentiated row of chips, which mixed documents in with model names, participants and topics, and reduced source documents to a bare count.
    *   Each kind of information now has its own section: **Source documents**, **Workspaces**, **Models and agents**, **Participants**, **Topics** and **Web sources**.
    *   **Source documents** are listed properly — file name, the pages or sheets used, how many excerpts, workspace and classification — and marked as **cited** when a response actually referenced them. The list is paged, since a long conversation can draw on dozens of documents.
    *   Conversations that predate citation tracking say so, rather than showing every document as though it went unused.
    *   A conversation **summary** can now be generated on demand from the panel, and regenerated later, showing the model used and when it was produced.
    *   (Ref: V2 conversation details, `/api/conversations/<id>/metadata`, `/api/conversations/<id>/summary`)

#### User Interface Enhancements

*   **Composer Controls Appear When They Are Relevant**
    *   **Read URLs** now appears only once the message you are writing actually contains a URL, and **Deep research** only when there is something for it to research — web search being on, or URLs in the message.
    *   Turning on **Image generation** now disables the controls it is incompatible with and hides the model picker, since the request goes to an image endpoint that ignores them.
    *   A control that disappears also clears its setting, so a request never carries a capability you can no longer see you enabled.
    *   Together this removes the permanently crowded row of buttons in the composer.
    *   (Ref: V2 composer gating)

*   **Chat Width Can Be Changed**
    *   A control in the chat header switches between a comfortable reading width and using the full width of the pane. The choice is remembered.
    *   The message thread and the composer widen together, so the composer controls get the extra room too.
    *   (Ref: V2 chat width)

### **(v0.261.014)**

#### New Features

*   **Message Masking In V2**
    *   You can now mask content in the V2 chat page, which the classic interface has always supported. Masked content is withheld from the AI model when it builds conversation history, so it is a real protection rather than a display setting.
    *   Select any text in a message and a small **Mask selection** control appears over it. The selected text is replaced with a redaction marker.
    *   The hover row also offers masking the whole message, and clearing masks once any exist.
    *   Hovering a redaction shows who applied it and when, so in a shared conversation it is clear whose masking you are looking at.
    *   Masked text is removed before the message is rendered rather than hidden with styling, so it is never present in the page.
    *   If a selection cannot be matched back to the stored message — which can happen when it spans citations or formatting — the interface says so instead of appearing to succeed.
    *   (Ref: V2 message masking, `/api/message/<id>/mask`)

### **(v0.261.013)**

#### New Features

*   **Message Details, Sources And Reasoning In V2**
    *   Hovering a message now offers three new controls that open a panel beneath it, so you can see what a response was built from without leaving the conversation.
    *   **Sources** lists the documents a response cited and where in each one, the web results it used, and any tools it called with their arguments and results.
    *   **Reasoning** shows the steps taken to produce a response *after the fact*, not only while it is being generated. It is presented exactly as it appears live, so the same information does not look like a different feature once the response has finished.
    *   **Details** covers the model or agent used, the reasoning effort, and which capabilities were available versus actually exercised — a response where web search was enabled but never used now says so.
    *   Details also explains how the conversation history was assembled: how many earlier messages were kept, summarised, or skipped because they were an inactive retry attempt or were masked. This is often the answer to "why didn't it know that?".
    *   User messages get their own details panel covering the retry thread and the capabilities that were active when the message was sent.
    *   (Ref: V2 message inspector, `/api/message/<id>/metadata`, `/api/conversations/<id>/messages/<id>/thoughts`)

#### User Interface Enhancements

*   **V2 Message Actions Grouped**
    *   The hover row beneath each message is now spaced into related groups — retry attempts, working with the message, feedback, inspecting it, and branching — rather than one long strip of undifferentiated icons.
    *   (Ref: V2 message actions)

### **(v0.261.012)**

#### Bug Fixes

*   **V2 Chat Exports Now Work**
    *   Export to Word, Export to PowerPoint and Open as email did nothing in the V2 chat page. The request was submitted as a web form, but these endpoints only accept a JSON body, so every attempt was rejected before it started.
    *   All three now work. Word and PowerPoint download the document, and Open as email opens your mail client with the subject and body filled in, saving any charts or images from the response so you can attach them.
    *   Failures are now reported instead of appearing to do nothing.
    *   (Ref: V2 message export, `/api/message/export-word`, `/api/message/export-powerpoint`, `/api/message/export-email-draft`)

*   **Generated Images Display In V2**
    *   Images produced in a conversation showed their internal address as a line of text instead of the picture. V2 now renders the image, and selecting it opens the full-size version.
    *   An image that cannot be loaded now says so and shows the prompt that produced it, rather than leaving a broken image.
    *   (Ref: V2 image messages, `/api/image/<id>`)

*   **Message Retry Counter Was Always Wrong**
    *   Every message in the V2 chat page claimed to be attempt "2 of 2", including messages that had never been retried.
    *   The counter is now correct and only appears once a message actually has more than one attempt.
    *   (Ref: V2 message actions, retry attempts)

*   **Conversation Tag Was The Same On Every Conversation**
    *   The badge beside the conversation title showed your currently selected group rather than anything about the conversation you were reading, so it never changed.
    *   It now shows what the conversation itself is working in: the group or public workspace name, a "shared" marker for shared conversations, nothing for personal ones, plus classification labels and whether the workspace scope is locked.
    *   (Ref: V2 chat header, conversation metadata)

*   **Selecting An Agent Had No Effect In V2**
    *   Choosing an agent in the V2 composer appeared to work but was ignored, because the selection was sent in a form the server does not read.
    *   Agent selection now applies to both new messages and retries.
    *   (Ref: V2 composer, agent selection)

*   **Line Breaks Lost In V2 Responses**
    *   A response written as several short lines was run together into one paragraph, while the same text in your own message kept its line breaks. The two now render the same way, and a single line break is preserved.
    *   (Ref: V2 message rendering)

*   **Conversation Summary Never Displayed In V2**
    *   The summary section of V2's conversation details read a field that does not exist, so a generated summary was never shown.
    *   (Ref: V2 conversation details, conversation summary)

### **(v0.261.011)**

#### Bug Fixes

*   **V2 Composer Menus Opened Off-Screen**
    *   The Model, Agent, Prompt and Reasoning pickers in the V2 chat page dropped their menus downward from a composer that sits at the bottom of the window, so the options rendered below the bottom edge of the browser and could not be seen or clicked.
    *   These menus now open upward when there is not enough room below, and size themselves to the space actually available so they stay on screen in short browser windows. Menus still open downward wherever there is room for them.
    *   The Reasoning picker was the most affected, since it sits on the composer's lower row.
    *   (Ref: V2 composer pickers, shared dropdown placement)

### **(v0.261.010)**

#### New Features

*   **V2 Enhanced Citations**
    *   Selecting a citation in the V2 chat page now opens the source itself rather than only the extracted passage. PDFs open at the cited page, images open in a zoomable viewer, video and audio play from the cited moment, spreadsheets open as a browsable table with a sheet switcher, and Visio drawings render page by page.
    *   Each viewer offers a download of the original file, so the source can be opened in its own application when the in-browser view is not enough.
    *   Documents can still be opted out individually, and file types with no viewer — plain text or Word, for example — continue to show the cited passage as before.
    *   When a source cannot be loaded, the passage is shown instead and the panel says that it fell back, so a misconfigured deployment is visible rather than presenting an empty viewer.
    *   PDFs are rendered by the browser's own viewer, so no PDF engine or other third-party browser asset was added.
    *   (Ref: V2 enhanced citations, `/api/enhanced_citations/*`, `X-Sub-PDF-Page`, `enable_enhanced_citations`)

### **(v0.261.009)**

#### New Features

*   **V2 Research, Reasoning And Voice Controls**
    *   **Deep research** and **Read URLs** are now working controls in the V2 composer rather than placeholders, each appearing only when the corresponding capability is enabled for you.
    *   **Reasoning effort** can be set per message, and the control only appears for models that actually support it — offering the levels that model allows rather than a fixed list. Models with no reasoning support show no control at all.
    *   **Voice input** records from your microphone and inserts the transcription into the composer, with an explicit send or cancel so a misheard phrase can be discarded rather than sent.
    *   **Read aloud** plays any response using the configured speech service.
    *   Every composer control is now wired; none remain marked as previews.
    *   (Ref: V2 composer, `/api/speech/transcribe-chat`, `/api/chat/tts`, deep research and URL access request fields)

### **(v0.261.008)**

#### New Features

*   **V2 Citations**
    *   Responses in the V2 chat page now show citations as compact inline chips instead of the raw `(Source: ...)` text the model emits. Each chip names the file and the page, sheet, or location it came from.
    *   Selecting a chip opens the passage that was actually cited, along with its file name and location.
    *   Citations that point at a web page render as an outbound link instead, opening in a new tab, since there is no stored passage to show for them.
    *   Answers without citations are unaffected, and tables, code blocks, and other formatting continue to render normally around the chips.
    *   (Ref: V2 citations, `/api/get_citation`, citation marker format)

### **(v0.261.007)**

#### New Features

*   **V2 Per-Message Actions**
    *   Added an action row to every message in the V2 chat page, appearing on hover and reachable by keyboard.
    *   **Both roles**: copy, retry, use as prompt, download as Markdown, export to Word or PowerPoint, open as an email draft, and delete.
    *   **Your messages**: edit in place and resend, which creates a new attempt rather than overwriting the original.
    *   **Responses**: rate with thumbs up or down (a thumbs down asks for an optional reason), and fork the conversation from that point into a new one, which then opens.
    *   **Attempt navigation**: when a message has been retried or edited, arrows appear showing which attempt you are viewing and let you page between them.
    *   (Ref: V2 message actions, `/api/message/<id>` retry, edit, switch-attempt, delete, `/feedback/submit`, conversation fork)

### **(v0.261.006)**

#### New Features

*   **V2 Conversation Details**
    *   Added a conversation details view to the V2 chat page, opened from an info button in the header. It shows the title, identifier, last updated time, conversation type, pinned/hidden/scope-locked state, classification, tags, how many documents were used, and the generated summary along with which model produced it and when.
    *   The conversation can be renamed inline from this view. Renaming to the same title does nothing rather than issuing a pointless save.
    *   Only fields the server actually returns are displayed, so the panel never shows permanently blank rows for data that does not exist.
    *   (Ref: V2 conversation details, `/api/conversations/<id>/metadata`)

#### User Interface Enhancements

*   **V2 Dialogs And Menus Are Now Readable Over Content**
    *   Dialogs, dropdown menus, and the account menu in the V2 interface used the same translucent glass treatment as the fixed page furniture, which left chat text legible straight through them and made the panel itself hard to read.
    *   Overlays now use a dedicated near-opaque surface in both light and dark themes, while keeping the glass look. Users who ask their system for reduced transparency continue to get fully solid panels.
    *   (Ref: V2 design tokens, dialog and popover surfaces)

### **(v0.261.005)**

#### New Features

*   **V2 Chat Conversation Drawer**
    *   Added a right-hand panel to the V2 chat page with two modes, matching the drawer in the current interface.
    *   **Contents** lists your questions in order so you can jump straight to a point in a long conversation; selecting one scrolls the thread there and briefly highlights it. It respects the same **Conversation Contents Drawer** admin setting and per-user preference the current interface uses, so turning it off hides it in both.
    *   **Documents** lists the documents behind a conversation, marking which were actually **Cited**, where the citations landed (pages or sheets), which workspace each came from, and its classification. The toggle carries a count badge.
    *   Documents are gathered from all three places the server records them, de-duplicated, so files attached directly to a chat appear alongside ones found through search.
    *   (Ref: V2 conversation drawer, `/api/conversations/<id>/metadata`, `build_used_documents`)

### **(v0.261.004)**

#### Bug Fixes

*   **V2 Workspace Page Crashed To A Blank Screen**
    *   Opening **My Workspace** in the V2 interface blanked the page, leaving only a minified React error in the browser console.
    *   Workspace tags are returned as objects carrying a name, a usage count and a colour, but the V2 tag filter rendered the object itself, which React cannot display. The failure then unmounted the whole interface rather than just the tag row.
    *   Tags are now read correctly in every shape the API uses, and the chips show their document counts.
    *   (Ref: `/api/documents/tags`, `build_workspace_tags_from_counts`, V2 workspace page)

*   **V2 Chat Logged A 404 When Opening A Conversation**
    *   Selecting a conversation in the V2 interface fired a "mark as read" request every time, which failed with a 404 for shared conversations because those are stored separately and have their own endpoint.
    *   The request is now sent only when a conversation actually has an unread response, and shared conversations use the shared endpoint — matching how the existing interface behaves.
    *   (Ref: conversation feed, mark-read endpoints, V2 conversation rail)

*   **V2 Pin And Unread Indicators Never Appeared**
    *   Pinned conversations showed no pin icon and unread conversations showed no dot, because the V2 rail read the wrong field names from the conversation feed. The underlying pin and hide actions worked, so only the indicators were affected.
    *   Pin and hide are also server-side toggles rather than settable states, so V2 now applies whatever the server reports back instead of assuming the result.
    *   (Ref: `is_pinned`, `is_hidden`, `has_unread_assistant_response`, V2 conversation rail)

*   **A Single View Failure No Longer Takes Down The V2 Interface**
    *   Added an error boundary around the V2 content area. An unexpected render failure now shows a contained message with the error and a retry button while the navigation rail keeps working, instead of blanking the entire application.
    *   (Ref: V2 error boundary, `App.tsx`)

### **(v0.261.003)**

#### New Features

*   **React V2 Interface (Preview)**
    *   Added an optional React interface at **/v2**, running alongside the existing UI rather than replacing it. Both surfaces share one login, so you can move between `/chats` and `/v2` freely and compare them directly.
    *   Built with React 18, TypeScript, Vite and Tailwind on a custom glassmorphism design system, with full dark and light modes. The theme is remembered per browser and applied before first paint, so switching to dark mode never flashes white.
    *   Keeps the current layout language: logo in the upper left, a single collapsible left rail carrying navigation, conversations, theme and account, and no top bar. All content lives in the right-hand pane.
    *   Chat is wired to the existing APIs — conversation list with paging and search, rename, pin, hide and delete, streaming responses with a collapsible reasoning panel, stop generation, model, agent and prompt pickers, document and web search toggles, and file upload. Controls that are part of the design but not yet connected are visibly marked **Preview** rather than silently doing nothing.
    *   Personal workspace documents can be listed, searched, filtered by tag, uploaded and deleted.
    *   Nothing in the existing interface changed. No current route, template, or JavaScript module was modified.
    *   (Ref: `application/v2_ui/`, `route_frontend_v2.py`, `route_backend_v2.py`, `docs/explanation/features/REACT_V2_UI.md`)

*   **Search-First Admin Settings In V2**
    *   Reimagined Admin Settings for the V2 interface. The classic page nests 14 groups into 46 tabs into 96 sections, so reaching one toggle can take several clicks through two levels of tabs.
    *   V2 flattens it: a category rail, one scrollable pane, and a search box that matches across every section, tab, group and capability key at once. Press `/` to focus search from anywhere on the page — searching either `retention` or `data lifecycle` finds the retention settings.
    *   Toggles save individually and roll back visually if the save fails, so the switch never claims a change that did not persist.
    *   The structure is still generated from `admin_settings_nav.py`, so it cannot drift from the classic page. Settings needing more than a switch — endpoints, keys, prompts, connection tests — remain on the classic page, which is linked from the V2 page.
    *   (Ref: `admin_settings_nav.py`, `/api/v2/admin/settings`, V2 admin surface)

*   **Optional Standalone Hosting For The V2 Interface**
    *   The V2 interface is served by the existing App Service at `/v2` by default, so it needs no new infrastructure and inherits the current sign-in, CSRF protection and content security policy unchanged.
    *   For deployments that want the front end deployed and scaled on its own, a new opt-in `deployV2FrontendAppService` parameter provisions a dedicated App Service for it. Setting `V2_UI_ALLOWED_ORIGIN` on the API app is the single switch that enables the cross-origin configuration this requires.
    *   Both settings are off by default and have no effect on existing deployments.
    *   (Ref: `deployers/bicep/modules/v2FrontendAppService.bicep`, `main.bicep`, `deployers/azure.yaml`, `V2_UI_ALLOWED_ORIGIN`)

### **(v0.261.002)**

#### User Interface Enhancements

*   **Inbound MCP Enablement Guidance**
    *   Added a visible **Inbound MCP** tab state for deployments where the preview admin UI is disabled by the missing `ENABLE_MCP_UI=true` App Service application setting.
    *   The disabled-state card explains how to enable the preview UI while making clear that the inbound MCP runtime remains off until an admin turns on **Enable inbound MCP server** after authentication, client allowlist, source, and governance prerequisites are ready.
    *   (Ref: `admin/_panes/inbound-mcp.html`, `admin_settings_nav.py`, [#1364](https://github.com/microsoft/simplechat/issues/1364))

#### Bug Fixes

*   **Delegated Governance New Policy Modal Opens On Split Governance Tabs**
    *   Fixed the delegated item governance **New Policy** button so it opens the policy editor after Admin Settings governance was split into Feature Governance, Policies, and MCP Governance tabs.
    *   Updated governance quick links to target the correct split tab panes instead of the retired aggregate Governance pane.
    *   (Ref: `admin_governance.js`, delegated item policy editor, [#1362](https://github.com/microsoft/simplechat/issues/1362))

*   **Large Markdown Files No Longer Fail To Upload**
    *   Uploading a Markdown file could fail with `Failed processing Markdown file ...` and take down the whole document, not just the oversized part of it. Long pages with a big section under a single heading, such as a release notes file, were the usual trigger.
    *   Markdown was the only ingestion path with no maximum chunk size. Its splitter divided the file on headings, and the step afterwards only ever merged chunks that were **too small** — nothing split a chunk that was too large. A heading with no subheading beneath it therefore became one chunk as large as all the text under it, which the embedding model refused.
    *   Lowering **Markdown (words)** in Admin Settings did not work around this, because that value was only ever used as a minimum. It is now a real target, so the setting behaves the way its name implies.
    *   Sections are now split to the configured size, a character limit is applied after merging to catch content such as tables and code blocks that take up more of the model's budget than their word count suggests, and a final safeguard keeps any remaining outlier inside the limit. That safeguard trims only the text used to build the chunk's search vector — the chunk itself is still stored in full, so citations and content are unaffected.
    *   (Ref: `process_md`, `save_chunks`, `functions_content.py`, `functions_documents.py`)

*   **Chunk Size Limits Now Respect Their Unit**
    *   Chunk sizes are configured per file type in words, characters, or pages, but a single shared limit was applied to all of them. That let a word-based field be set to 16,384 words — far more than can be indexed — while implying the value was valid.
    *   Word and character fields now have separate limits, both derived from the embedding model's context window, and the Document Extraction tab shows the current values. A value above its limit is reduced on save and the page names the fields it changed.
    *   Page and slide counts are left uncapped here, since how much text a page holds is not known until extraction runs. They are bounded when the chunk is indexed instead.
    *   No shipping default changed. Only custom overrides that could never have been indexed are affected.
    *   (Ref: `get_chunk_size_cap`, `get_chunk_size_config`, Document Extraction settings, `admin_settings.js`)

### **(v0.261.001)**

#### New Features

*   **Facts And Memories Now Work In Standard Chat, Without Agents Or Actions**
    *   Fact memory is now a chat capability. With it enabled, the assistant recalls a user's saved memories during normal conversation and can save, change, or remove them when the user asks, such as "remember that I prefer bullet points" or "stop calling me Paul". Agents and actions can stay off.
    *   Previously, memory recall worked without agents but memory *writes* did not. The memory tool was only attached to the model on the Semantic Kernel agent path, so a request to remember or forget something silently did nothing unless an administrator had turned on agents.
    *   Writes run through a small memory-only Semantic Kernel pass after the response is already finished, so it never changes or delays the answer. An intent check runs first, so ordinary chat turns take no extra work. If a memory update fails, the chat response is unaffected.
    *   Instruction memories still apply to every prompt, fact memories are still recalled only when relevant, and memory activity appears in processing thoughts. Users continue to review, edit, and delete their own entries from Profile > Fact Memory.
    *   (Ref: `functions_fact_memory_autosave.py`, `route_backend_chats.py`, `fact_memory_plugin.py`, [#1352](https://github.com/microsoft/simplechat/issues/1352), [#1153](https://github.com/microsoft/simplechat/issues/1153))

*   **Admin-Configurable Rate Limit Message With Markdown Support**
    *   A new **Security → Rate Limiting** tab in Admin Settings controls what a user is told when a request is refused with HTTP 429. The message supports Markdown, so it can link to an internal runbook or a capacity request form.
    *   Leaving the toggle off, or saving an empty message, keeps the built-in wording. A throttled user never receives an empty response.
    *   The same message now reaches every surface that returns a 429: chat, chat image generation, text to speech, the Swagger specification endpoints, and inbound MCP tool calls. Inbound MCP keeps its structured limit, window, and reset values so clients can still back off correctly.
    *   (Ref: `functions_rate_limit.py`, `enable_custom_rate_limit_message`, `rate_limit_message`, Security settings, [#1354](https://github.com/microsoft/simplechat/issues/1354))

*   **All App Role Requirements In One Place**
    *   Ten settings across seven tabs can each require an Entra app role, which made the overall access policy impossible to read without hunting through the whole of Admin Settings.
    *   **Security → Access & Roles** now lists every one of them with a switch and a link to the setting in its own tab. Changing a switch here changes the setting itself.
    *   The list is built from the page, so a new role requirement added anywhere appears here automatically.
    *   (Ref: `app-role-requirements-section`, `admin_access_roles_roster.js`)

*   **Admin Settings Navigation Is Now Grouped**
    *   Admin Settings presented 18 tabs in one flat list. Related tabs are now collected under 12 groups such as Appearance, Knowledge, Security and Operations, so the list is scannable and has room to grow.
    *   In the sidebar, groups are collapsible and remember whether you left them open. In the tab layout, a row of group pills filters the tab strip to one group at a time.
    *   Opening a tab always reveals its group first, so a deep link or a cross-reference can never land you on a pane whose tab is hidden.
    *   Sidebar search now matches group names as well as tab and setting names, and expands whatever it needs to show a result.
    *   No settings moved in this release. Every tab keeps its contents; only the navigation around them changed.
    *   (Ref: `admin_settings_nav.py`, `_sidebar_nav.html`, `admin_settings.html`, `admin_sidebar_nav.js`)

*   **Admin Settings Form Field Contract Is Now Enforced**
    *   Admin Settings submits one form and the backend reads every value by field name, so the set of `name` attributes is the real contract between the template and the settings backend. Renaming or dropping one silently stops that setting from saving, with no error anywhere.
    *   A new test pins every field name against a committed baseline, and fails the build if one disappears. Adding settings is unaffected; removing one now requires regenerating the baseline in the same commit, which makes it a visible, reviewed decision.
    *   The same test rejects duplicate field names, which is what prevents a mirrored control from submitting a value twice.
    *   (Ref: `test_admin_settings_field_contract.py`, `admin_settings_field_baseline.json`)

*   **Settings That Need Another Setting Now Say So**
    *   Some Admin Settings options only work when a different option is enabled, and the two often live in different tabs. That was previously explained only in prose, in a tooltip, or in a warning after saving, so you could switch something on and have nothing happen with no visible reason.
    *   Affected cards now show an inline notice naming what they need, with a switch to enable the prerequisite without leaving the tab and a link straight to its full configuration.
    *   **File Sync** announces its **Redis Cache** requirement live, and keeps its save-your-intent behaviour: settings can still be saved and activate once Redis is ready.
    *   The **FeedbackAdmin** role control is disabled until **User Feedback** is enabled, since the role only governs access to the User Feedback report. The unrelated SafetyViolationAdmin control in the same card stays usable.
    *   These notices are guidance only. The server still validates every prerequisite.
    *   (Ref: `admin_settings_dependencies.js`, `data-requires`, File Sync, Permissions)

*   **Admin Settings Template Split Into Per-Tab Partials**
    *   `admin_settings.html` had grown to 13,526 lines in a single 1 MB file. Each tab pane now lives in `templates/admin/_panes/` and is included by the parent, which keeps the global form, the modals, and the script blocks.
    *   No settings behaviour changes: every form field name and all 110 configuration card ids are byte-identical, so the submitted payload and the settings backend are untouched.
    *   **Migration**: code or tests that read `templates/admin_settings.html` directly now see only the parent shell. Use `test_support.templates.read_admin_settings_template()` in functional tests, or `compose_if_admin_settings()` inside a shared file-reading helper. A new contract test fails if a test asserts on a partial-backed card or field without composing the template first.
    *   (Ref: `templates/admin/_panes/`, `functional_tests/test_support/templates.py`, `test_admin_settings_template_composition.py`)

*   **Shared Conversation File Approvals**
    *   Files generated by a participant in a shared conversation are now created immediately and held in a **pending approval** state instead of being refused, because they are saved into the conversation owner's storage.
    *   The conversation owner approves personal shared conversations; any group **Owner**, **Admin**, or **Document Manager** approves group shared conversations. Requesters can never approve their own file.
    *   Approvers get an inline **Approve / Deny** card on the pending file plus a notification. Approving releases the file, denying deletes the stored file and records who declined it.
    *   A staged file is not downloadable by anyone, including the requester, until it is released.
    *   Only downloadable deliverables are gated (CSV, XLSX, DOCX, PDF, JSON, XML). Generated images and charts are never gated.
    *   Unapproved files are automatically declined and deleted after 3 days, matching the existing Control Center approval window.
    *   New Admin Settings toggle **Require approval for participant-generated files**, enabled by default.
    *   (Ref: `functions_generated_file_approvals.py`, `chat-file-approvals.js`, `require_shared_conversation_file_approval`, `/api/collaboration/file-approvals`)

*   **Workflow Alert Configuration Model**
    *   The legacy single `alert_priority` workflow field is superseded by `alert_mode`, `alert_rules`, and `alert_evaluation` for rules-based workflow notifications.
    *   Existing workflows are auto-migrated on read into equivalent failed-run and completed-run notification rules.
    *   **Migration**: Review upgraded workflow alert rules and prune any always-notify completed-run rule that is no longer desired.

*   **New Yamcs Client Dependency**
    *   The Yamcs Mission Control action adds `yamcs-client==2.1.0`, the repository's first LGPL-3.0 dynamically linked pip dependency.
    *   SimpleChat can still start without it, but Yamcs actions return an actionable dependency error until installed.
    *   **Migration**: Run `pip install -r requirements.txt` or rebuild deployment images so the Yamcs client dependency is present where Yamcs actions are used.

*   **Internal Route Name Hardening**
    *   Blueprint security hardening changed internal route names and required broad route policy/test updates.
    *   Shared-conversation streaming regressions from the rename sequence were fixed in the consolidated patch history.
    *   **Migration**: Update any custom integrations that call SimpleChat by internal endpoint name rather than public route URL.

*   **Conversation Cache Fallback Behavior**
    *   Volatile chat bootstrap and conversation cache payloads no longer fall back to the Cosmos `settings` container when Redis is unavailable.
    *   Deployments without Redis keep full functionality, but bypass these cache benefits.
    *   **Migration**: Configure Redis for deployments that depend on chat bootstrap or conversation cache acceleration.

*   **Enhanced Document Extraction and Analysis**
    *   Azure AI Content Understanding supports AI-generated figure descriptions for PDFs/images, with Auto mode figure detection.
    *   Embedded Office images, including EMF/WMF diagrams and legacy DOC/PPT media, are rasterized, analyzed, and indexed as citable chunks.
    *   Optional Document Intelligence formula extraction adds LaTeX equation capture for PDFs when enabled.
    *   (Ref: Azure AI Content Understanding, Document Intelligence, embedded image extraction, formula extraction)

*   **Workflow Multi-Task Automation and Alerts**
    *   Workflows now support ordered instruction tasks with prior-task context chaining, per-task document actions, retry/failure handling, and configurable task limits.
    *   Conditional alert rules cover run status, text/regex matches, File Sync summaries, AI-judged results, and agent-raised signals across five severity levels.
    *   Active workflow runs can be cancelled from workspace rows, run history, or activity surfaces.
    *   (Ref: workflow task sequencing, workflow alert rules, `raise_workflow_alert`, run cancellation)

*   **Expanded Agent and Action Integrations**
    *   Yamcs and RocksDB action types add mission-control and HTTP/JSON data-service integrations.
    *   Inbound MCP exposes governed SimpleChat capabilities for conversations, documents, prompts, tags, and workflows.
    *   Action connection testing now covers OpenAPI, Maps, Blob, Databricks, Log Analytics, MCP, Snowflake, Tableau, RocksDB, Yamcs, SQL, and Cosmos DB.
    *   (Ref: Yamcs action, RocksDB action, MCP inbound server, action test connection)

*   **Governance, Security, and Model Administration**
    *   Governance policies support explicit block lists for feature and delegated item policies alongside allow rules.
    *   Key Vault secret expiration reminders track per-action secrets with background sweeps, notifications, and telemetry.
    *   Model requests can include HMAC-hashed user identity headers, and admins can configure per-model output token ceilings.
    *   (Ref: governance policies, Key Vault secret inventory, model endpoint identity header, output token limits)

*   **Chat Productivity, Grounding, and Notifications**
    *   Users can opt into response completion sounds, desktop notifications, configurable AI notices, and per-message MP3 export.
    *   Conversation grounding now exposes model/workspace/document/agent context, used-document panes, assistant-response forks, and a contents drawer.
    *   User font size preferences, generated JSON/XML export artifacts, and smarter scroll behavior improve long-session usability.
    *   (Ref: chat notifications, grounding citations, used documents pane, conversation fork, contents drawer, export artifacts)

*   **Workspace, Sync, and Data Management Operations**
    *   Azure Blob Storage File Sync adds SAS, managed identity, service principal auth, virtual-folder browsing, and ETag change detection.
    *   Admin operations add automatic Control Center statistics refresh, backup cleanup/retention, restore workflows, Cosmos JSON editing, Redis Explorer, feedback/safety lifecycle controls, and file-processing log cleanup.
    *   Multi-select metadata extraction, configurable Public Workspace naming, and index auto-login improve workspace administration.
    *   (Ref: File Sync, Control Center, Backup Inventory, Data Management, Redis Explorer, metadata extraction)

*   **Caching, Runtime, and Durable Processing Capabilities**
    *   DAI Redis read-through caches document lists, tag lists, and legacy counts with scope-version invalidation.
    *   Conversation list/feed caching adds Redis hit/miss metrics for Admin Settings visibility.
    *   Durable tabular analyze/search preflight parity, FFmpeg audio runtime support, and the model capability catalog broaden platform readiness.
    *   (Ref: DAI Redis cache, conversation cache metrics, tabular durable preflight, FFmpeg, model capability catalog)

*   **Latest Features Release Tiers for v0.260.001**
    *   Shifted the end-user Latest Features page and Admin Settings tab into current, previous, and archive release tiers for the v0.260.001 rollout.
    *   Preserved per-tenant visibility choices across the shift. The new v0.260.001 user-facing cards ship hidden until their placeholder screenshots are replaced, so admins publish each card once its real capture is in place.
    *   (Ref: Latest Features release groups, support catalog, admin catalog, visibility normalization)

*   **Deeper End-User Feature Cards**
    *   Added 20 v0.260.001 end-user cards with seven concrete How To Try It steps and a three-image gallery each.
    *   Expanded the Latest Features card helper with the `images=[...]` gallery form for multi-image cards.
    *   (Ref: `_latest_feature_card`, `_SUPPORT_RELEASE_260_FEATURE_CATALOG`, Latest Features image galleries)

*   **Admin Latest Features Archive Tier**
    *   Brought the Admin Settings Latest Features tab to the same three-tier current, previous, and archive model used by the end-user page.
    *   Keeps v0.250.001 admin cards and older v0.241.x admin highlights available without crowding the current release tier.
    *   (Ref: `_ADMIN_LATEST_FEATURE_RELEASE_GROUPS`, `_ADMIN_RELEASE_260_FEATURE_CATALOG`, Admin Settings Latest Features tab)

*   **Latest Features PR Workflow Hooks**
    *   Added a Latest Features authoring prompt, PR template checklist, and CI warning path so feature PRs consider release notes, cards, and screenshots together.
    *   Helps future releases keep in-app Latest Features content aligned with shipped user and admin changes.
    *   (Ref: `.github/prompts/update-latest-features.prompt.md`, `.github/PULL_REQUEST_TEMPLATE.md`, `release-notes-check.yml`)

*   **Documentation Site Redesign**
    *   The documentation site was rebuilt for search, navigation, page simplicity, mobile support, and content coverage.
    *   Search now indexes page content instead of titles only. Previously 84% of the 986 indexed pages were internal engineering notes, 88% of entries had no description, and no page body text was indexed at all, so a search for "agent" returned mostly internal fix notes. The index is now 165 entries with a description on every one and no engineering notes.
    *   Added a dedicated search results page with section filters and highlighted excerpts, a `Ctrl+K` shortcut, keyboard navigation, and a full-screen mobile search sheet. Search was previously hidden entirely on phones.
    *   Navigation was rebuilt so the top bar and sidebar expose the same six sections: Start, Guides, Features, Administration, Deploy and operate, and Reference. Coverage went from 27 links to 74, all verified to resolve.
    *   (Ref: `docs/search-index.json`, `docs/assets/js/search.js`, `docs/_config.yml` navigation, `docs/search.md`)

*   **Screenshot and Video Placeholders for Documentation**
    *   Documentation pages can now declare a screenshot or video slot. When the asset does not exist yet the page renders a visible card naming the exact file path to create; adding the file at that path replaces the placeholder automatically on the next build with no configuration or code change.
    *   Videos render as a local poster card that links out to YouTube or Microsoft Stream, so no video files are committed to the repository and no third-party embed scripts are loaded.
    *   Added a media status page listing every slot and whether it is filled, as a capture worklist for contributors.
    *   (Ref: `docs/_includes/media.html`, `docs/_data/media.yml`, `docs/contributing/media-status.md`)

*   **Complete Documentation Coverage of the Application**
    *   Added one page per admin settings tab covering what the tab controls, why it matters, every setting with its default and governing settings key, prerequisites, and the common tasks admins perform there.
    *   Added task guides for creating actions, agents, agents with actions, multi-task workflows, triggering workflows, file sync connectors, tags, tags in chat, tags on conversations, and exporting conversations, plus further guides derived from the application surface. Each guide explains what the task does and why before the steps.
    *   Added a chat interface reference covering all 47 chat controls and an action reference covering all 27 actions.
    *   Added a feature catalog in which every one of the 111 capability toggles is claimed by exactly one capability entry.
    *   (Ref: `docs/admin/`, `docs/guides/`, `docs/reference/chat-controls.md`, `docs/reference/actions/`, `docs/_data/features.yml`)

*   **Documentation Coverage Enforcement**
    *   Added a generated inventory of the application surface and functional tests that fail when a new capability toggle, admin settings tab, action plugin, or chat control ships without documentation, so coverage stays complete as changes land.
    *   (Ref: `scripts/build_docs_inventory.py`, `functional_tests/test_docs_app_surface_coverage.py`, `functional_tests/test_docs_site_quality.py`)

*   **Workspace Documents Are Now Configured Per Workflow Task**
    *   Each task in a workflow now owns its own **Workspace documents** setup — document action, document target, selected documents, Compare source and targets, per-document analysis, and windowing — instead of sharing one configuration across the whole workflow.
    *   Adding a task resets the document fields, and returning to a previously configured task restores that task's setup, so tasks are self-contained.
    *   Every task now executes with its own document action at run time. Previously the single workflow-level action only ever applied to task 1, and every later task ran with no document context.
    *   Existing workflows keep working: their saved document action is inherited by task 1 only, matching how they actually ran. Group workflows still force every task into the owning group workspace.
    *   Task cards and the Review step now summarize which documents each task uses.
    *   (Ref: [#1282](https://github.com/microsoft/simplechat/issues/1282), `workspace_workflows.js`, `functions_personal_workflows.py`, `functions_group_workflows.py`, `functions_workflow_runner.py`, per-task document actions)

*   **Optional Mathematical Formula Extraction**
    *   Added an **Extract mathematical formulas** toggle to the Document Intelligence settings. When enabled, equations in PDFs and images are captured as LaTeX instead of being approximated as OCR text.
    *   This requests a **billed Document Intelligence add-on**, so it is off by default and must be turned on deliberately. It applies to the Layout model only, so it has no effect while extraction is set to Standard.
    *   (Ref: [#1277](https://github.com/microsoft/simplechat/issues/1277), `functions_content.py`, `functions_settings.py`, `admin_settings.html`, Document Intelligence formulas add-on)

*   **Index Auto-Login**
    *   Added an opt-in `ENABLE_AUTO_LOGIN_ON_INDEX` setting that redirects unauthenticated home-page visits to the existing Microsoft Entra sign-in flow.
    *   Supports government tenant SSO scenarios where users already have a browser session and should enter SimpleChat without first clicking the sign-in link.
    *   (Ref: `app.py`, `config.py`, `INDEX_AUTO_LOGIN.md`, Microsoft Entra sign-in)

*   **Enhanced Extraction Now Uses Azure AI Content Understanding**
    *   Enhanced extraction for PDFs and images now uses Azure AI Content Understanding (`prebuilt-documentSearch`) instead of Document Intelligence Layout. In addition to tables, page structure, and checkbox states, it returns AI-generated descriptions of figures, charts, and diagrams — structure Document Intelligence never produced.
    *   Standard extraction is unchanged and always uses Document Intelligence, which remains required for workspaces and chat file uploads.
    *   A new **Enable Enhanced extraction** toggle in Admin Settings reveals the Content Understanding configuration. Turning it on defaults the extraction mode to **Auto**, so documents are only upgraded when the sample shows structure worth paying for.
    *   Content Understanding supports both key and managed identity authentication, with a **Test Connection** button and an in-app setup guide covering Foundry resource creation, supported regions, required model deployment defaults, and the Cognitive Services User role.
    *   Enhanced never becomes a hard dependency. Content Understanding is not offered in Azure Government, so Enhanced automatically uses Document Intelligence Layout in Government and custom clouds — the admin UI says so plainly and there is nothing to configure there. Enhanced also falls back when Content Understanding is unconfigured or a request fails, and the reason is recorded on the document and shown in workspace tooltips.
    *   (Ref: [#1277](https://github.com/microsoft/simplechat/issues/1277), `functions_content_understanding.py`, `functions_content.py`, `functions_settings.py`, `route_backend_settings.py`, `admin_settings.html`, `CONTENT_UNDERSTANDING_ENHANCED_EXTRACTION.md`)

*   **Images Inside Word and PowerPoint Files Are Now Analyzed**
    *   Neither extraction engine describes figures inside Office files, so SimpleChat now pulls embedded images out of DOCX and PPTX packages and analyzes them with whichever engine backs the selected extraction mode — Content Understanding when Enhanced is active, Document Intelligence otherwise. This works with Standard extraction too.
    *   Each analyzed image is indexed as its own citable chunk, and PowerPoint images are attributed to the slide that references them.
    *   Cost is bounded by design: icons, bullets, and spacer graphics are filtered out by a configurable minimum size, byte-identical images such as repeated header logos are analyzed once, and a per-document cap limits the total.
    *   Uploaded Office files are treated as untrusted: extracted file names are generated rather than reused from the archive, entries are streamed with a hard byte ceiling instead of trusting the archive's declared size, compression methods and entry counts are bounded, and slide relationship parts are parsed with a hardened XML parser.
    *   Can be turned off entirely with **Analyze images embedded in DOCX and PPTX files**. Image analysis failures never fail the document.
    *   (Ref: [#1277](https://github.com/microsoft/simplechat/issues/1277), `functions_office_media.py`, `functions_documents.py`, embedded Office image analysis)

*   **Test Connection for Eight More Action Types**
    *   Added a **Test Connection** button to the Step 3 configuration for OpenAPI, Azure Maps, Blob Storage, Databricks, Log Analytics, MCP, Snowflake, and Tableau actions. Previously only SQL, Cosmos DB, Yamcs, and RocksDB actions could be validated before saving.
    *   Each test authenticates with the credentials entered in the modal and performs one lightweight read against the configured resource, so a wrong warehouse ID, container name, subscription key, personal access token, or MCP endpoint is caught immediately instead of failing later during a chat.
    *   Failures name the cause — rejected credentials, a missing warehouse or container, an unreachable host, or a driver that is not installed — and successes report useful detail such as the Databricks warehouse state, the Snowflake version, the Tableau API version, or the MCP tool count.
    *   Editing an existing action works without retyping credentials: masked secrets and reusable workspace identities are resolved server-side for the test only, and no credential value is ever returned to the browser.
    *   The MCP test enforces the same stdio scope restriction and outbound destination policy as MCP tool discovery, and it does not overwrite discovered tool metadata.
    *   (Ref: [#1267](https://github.com/microsoft/simplechat/issues/1267), `functions_action_connection_tests.py`, `route_backend_plugins.py`, `_plugin_modal.html`, `plugin_modal_stepper.js`, `ACTION_TEST_CONNECTION.md`)

*   **RocksDB Action**
    *   Added a new `rocksdb` action type so agents can read an ordered [RocksDB](https://github.com/facebook/rocksdb) key-value store, with a dedicated configuration card and Test Connection button in the action modal.
    *   RocksDB is an embedded library with no network protocol, so the action calls a RocksDB-backed HTTP/JSON service that you operate alongside your data. SimpleChat never runs RocksDB locally or opens a database directory on the application host.
    *   Supports no-auth, bearer token, and API key header authentication with a configurable header name. TLS certificate validation is always enforced.
    *   Exposes `get_value`, `get_values`, `key_exists`, `scan_prefix`, `scan_range`, `list_column_families`, and `get_database_stats` for reads, plus `put_value`, `delete_value`, and `write_batch` that stay blocked until an action explicitly allows writes.
    *   Handles binary data through configurable UTF-8, base64, and JSON key and value encodings that are sent to the service on every request, caps returned records, and flags values truncated by the size limit.
    *   The RocksDB HTTP service contract is fully documented so operators can implement a conforming service.
    *   (Ref: `rocksdb_plugin.py`, `route_backend_plugins.py`, `plugin_health_checker.py`, `_plugin_modal.html`, `plugin_modal_stepper.js`, `rocksdb.definition.json`, `test_rocksdb_plugin.py`, `test_workspace_rocksdb_action_modal.py`, `docs/explanation/features/v0.250.216/ROCKSDB_ACTION.md`)

*   **Agent Instruction Context References (`#action` and `#knowledge`)**
    *   Instructions can now reference the exact actions, action capabilities, and assigned knowledge that were selected for the agent, so authors can spell out *when* and *why* each capability or document should be used.
    *   Typing `#` in the Instruction Brief or the instructions editor opens an autocomplete that drills down from the `action` / `knowledge` namespace, to the actions selected in the Actions step, to that action's enabled capabilities. `#knowledge:` lists the assigned documents, workspaces, tag limits, and web sources with type badges.
    *   Tokens such as `#action:"Simple Chat":create_group` and `#knowledge:doc:"Employee Handbook.pdf"` are stored literally with the instructions so they stay editable and round-trip unchanged when an agent is edited. Values containing a space or colon are quoted automatically.
    *   Navigate with the arrow keys, insert with `Tab` or `Enter`, dismiss with `Esc`, or use the mouse. Document titles containing spaces stay searchable while typing.
    *   Foundry agents manage their instructions and tools in Foundry, so the references stay inert for Classic Foundry, New Foundry, and Foundry Workflow agents.
    *   (Ref: [#1257](https://github.com/microsoft/simplechat/issues/1257), [#1263](https://github.com/microsoft/simplechat/pull/1263), `agent_instruction_mentions.js`, `agent_modal_stepper.js`, `_agent_modal.html`)

*   **Context-Aware Draft Instructions**
    *   The **Draft Instructions** helper now receives the selected actions with their enabled capabilities and the assigned knowledge configuration, instead of only the agent name, description, and brief.
    *   Drafts reference only real, selected actions and documents, and use the new `#action:` / `#knowledge:` token convention.
    *   Client-supplied context is normalized, length-capped, count-capped, and bounded by a shared total character budget on the backend. It is used purely as prompt text and never affects authorization, and whitespace collapsing prevents newline-based prompt injection through action or document names.
    *   (Ref: [#1257](https://github.com/microsoft/simplechat/issues/1257), [#1263](https://github.com/microsoft/simplechat/pull/1263), `route_backend_agents.py`, `POST /api/agents/draft-instructions`)

*   **Workflow Alert Rules**
    *   Workflow alerts are now conditional. Instead of a single Pop-up Alert Priority that notified on every run, a workflow can define rules that describe *why* it should notify you, and a run that matches nothing stays completely silent.
    *   Conditions cover run status, task status, output text (contains, does not contain, or regex), File Sync results, empty output, an agent-raised signal, and a plain-English condition judged by a model, such as "any certificate expires within 14 days."
    *   Each rule can be scoped to the final output, any task output, or one specific task.
    *   Model-judged conditions are batched into a single call per run and skipped entirely when a deterministic rule already matched at a higher severity, so workflows that use only deterministic conditions add no model calls.
    *   (Ref: `functions_workflow_alerts.py`, `functions_workflow_runner.py`, `functions_personal_workflows.py`, `functions_group_workflows.py`, `workspace_workflows.js`, `WORKFLOW_ALERT_RULES.md`)

*   **Expanded Alert Severities and a Distinct Failure Style**
    *   The severity ladder grew from low/medium/high to **info, low, medium, high and critical**.
    *   Info and low alerts land quietly in the notification bell, while medium and above open the pop-up. Any rule can override this.
    *   Runs that error now carry a separate *failure* category that changes the icon and wording independently of severity, so "the workflow broke" is visually distinct from "the workflow found something."
    *   When several rules match the same run, the highest severity wins and the alert lists every matched rule with its reason under a new "Triggered by" section.
    *   (Ref: `functions_notifications.py`, `notifications.js`, `base.html`, workflow alert modal)

*   **Agent-Raised Workflow Alerts**
    *   Agents running inside a workflow can now raise an alert signal mid-run with severity, title and reason through the new `raise_workflow_alert` SimpleChat capability, and an `agent_signal` rule decides whether it notifies anyone.
    *   The rule's severity acts as a floor the agent can escalate above but never quiet below, and named signals can route to their own rules.
    *   The capability is opt-in and refuses outside an active workflow run, so existing agents do not gain the ability to create notifications and a normal chat cannot fabricate one.
    *   (Ref: `simplechat_plugin.py`, `functions_simplechat_operations.py`, `agent_modal_stepper.js`, `plugin_modal_stepper.js`)

*   **Alert Decision Visibility**
    *   Each run now records why it did or did not alert, including the winning severity and every matched rule, surfaced through the workflow activity view so noisy or silent workflows can be diagnosed.
    *   (Ref: `functions_workflow_activity.py`, `functions_workflow_runner.py`)

*   **Yamcs Mission Control Action**
    *   Added a first-class, read-only `yamcs` action type that connects agents to a Yamcs mission control server using the official `yamcs-client` Python package.
    *   Exposes eleven read-only tools: instances, data links, mission database parameters and parameter detail, command *definitions*, live parameter values, parameter history, events, packets, alarms, and an optional guarded archive SQL query.
    *   Strictly read-only by design. The action cannot issue commands, set parameter values, run scripts, or enable/disable data links, and command listing returns definitions only.
    *   Archive SQL is disabled by default and, when enabled, is restricted to `SELECT`, `SHOW`, `DESC`, and `DESCRIBE` statements with a forbidden-keyword guard and an automatic row limit.
    *   Every retrieval is bounded by a row limit, a serialized byte limit, and a request timeout so a broad query cannot walk an entire archive, and error text is scrubbed of credentials.
    *   (Ref: `functions_yamcs_operations.py`, `semantic_kernel_plugins/yamcs_plugin.py`, `semantic_kernel_plugins/yamcs_plugin_factory.py`, `docs/explanation/features/YAMCS_ACTION.md`)

*   **Yamcs Action Configuration Panel and Test Connection**
    *   Added a dedicated Yamcs configuration section to the Add/Edit Action modal covering server URL, instance, processor, authentication, TLS verification, archive SQL opt-in, and retrieval limits.
    *   Supports username/password, API key, bearer token, and unauthenticated Yamcs servers, plus reusable workspace identities using `api_key`, `bearer_token`, or `username_password`.
    *   Added a **Test Yamcs Connection** button backed by `POST /api/plugins/test-yamcs-connection`, which verifies reachability and credentials and confirms the configured instance exists. Saved actions resolve their stored credential from Key Vault, so secrets do not need to be re-entered to run a test.
    *   (Ref: `_plugin_modal.html`, `plugin_modal_stepper.js`, `route_backend_plugins.py`, `workspace/view-utils.js`)

*   **Governance Policy Block Lists**
    *   Added admin-managed block lists for feature and delegated item governance policies so specific users or groups can be denied even when allow-all or allow-list rules would otherwise grant access.
    *   Enables administrator-friendly APIM quota-tier separation, such as allowing a high-threshold group to a high endpoint while blocking that group from a default low-threshold endpoint without maintaining a large low-user allow list.
    *   (Ref: [#1252](https://github.com/microsoft/simplechat/issues/1252), `functions_governance.py`, `route_backend_governance.py`, `admin_governance.js`, MCP governance)

*   **Model Endpoint Identity Header**
    *   Added admin controls to send a stable HMAC-hashed user identity key with model endpoint requests for APIM counters, quota policies, and backend routing policies.
    *   Supports global enablement, custom safe header names, selectable identity inputs, and per-endpoint inherit/enable/disable overrides without exposing raw UPN, object ID, or tenant ID values.
    *   (Ref: [#1250](https://github.com/microsoft/simplechat/issues/1250), Model Endpoint Identity Header, `functions_model_endpoint_identity_header.py`, model endpoint runtime, Admin Settings)

*   **Tabular Analyze/Search Durable Preflight Parity**
    *   Unified exhaustive tabular Search and Analyze requests behind a shared route-neutral planner that can queue durable work before bounded foreground tools or immediate synthesis run.
    *   Preserved truthful pending, failed, canceled, and completed evidence across pure tabular, mixed-source, per-document, and multi-table workflows, including deferred mixed-source composition and public lifecycle coverage.
    *   Added backend-only shadow and canary controls, privacy-safe telemetry and status metadata, and evidence-backed legacy fallback retirement while reusing existing authorization, source-version, rollback, and artifact-card contracts.
    *   (Ref: [#1031](https://github.com/microsoft/simplechat/issues/1031), [#1055](https://github.com/microsoft/simplechat/issues/1055), [#1058](https://github.com/microsoft/simplechat/issues/1058), `functions_tabular_orchestration.py`, `functions_workflow_runner.py`, `route_backend_chats.py`)

*   **Chat Used Documents Pane**
    *   Added a Used Documents mode to the existing chat conversation side pane so users can review documents that were actually cited in the conversation without opening the full details modal.
    *   Reuses the same conversation metadata document tags as the details modal, excludes selected-but-unused documents, and auto-opens once when cited documents first appear.
    *   (Ref: [#1209](https://github.com/microsoft/simplechat/issues/1209), conversation contents drawer, cited document metadata, `chat-conversation-contents.js`, `chat-conversation-details.js`)

*   **Configurable Workflow Task Limit**
    *   Added an admin setting that controls how many ordered instruction tasks users can add to a workflow.
    *   The default is 50 tasks, with backend and browser enforcement clamped to a supported range of 1-100 tasks.
    *   (Ref: workflow task sequences, Admin Settings Workflow section, `functions_personal_workflows.py`, `workspace_workflows.js`)

*   **Key Vault Reminder Contact Email Telemetry Opt-In**
    *   Added a default-off admin setting that allows Key Vault reminder contact email addresses to be included in the external Application Insights telemetry event for direct Azure Monitor, Logic App, Function, or webhook routing.
    *   Kept raw secret names redacted from external telemetry and added Reminder ID visibility/search in the admin inventory for fixed admin-channel alert workflows.
    *   (Ref: [#1156](https://github.com/microsoft/simplechat/issues/1156), `functions_appinsights.py`, `functions_keyvault_reminders.py`, Admin Key Vault reminder external alert guidance)

*   **Key Vault Reminder External Telemetry**
    *   Added a privacy-safe, queryable Application Insights event when Key Vault expiration reminder notifications are created, enabling Azure Monitor scheduled query alerts, action groups, Logic Apps, Functions, or webhooks for external notification workflows.
    *   Added admin and feature documentation guidance with a sample KQL query while avoiding raw secret names and email values in telemetry dimensions.
    *   (Ref: [#1156](https://github.com/microsoft/simplechat/issues/1156), `functions_appinsights.py`, `functions_keyvault_reminders.py`, Azure Monitor external notification guidance)

*   **Key Vault Expiration Reminder Inventory**
    *   Added SimpleChat-managed Key Vault secret expiration reminder tracking with per-action reminder metadata, expiration dates, lead days, reminder contact email, friendly labels, and rotation notes.
    *   Added an admin Key Vault reminder dashboard that maps generated Key Vault secret names back to SimpleChat scope, source action, field, owner/contact context, sync status, and remediation details.
    *   Added a background reminder sweep and `key_vault_secret_expiring` in-app notifications while preserving Azure Monitor/Event Grid as the recommended email alert path.
    *   (Ref: [#1156](https://github.com/microsoft/simplechat/issues/1156), `functions_keyvault_reminders.py`, `admin_settings.html`, `plugin_modal_stepper.js`, Key Vault reminder inventory)

*   **Generated JSON and XML Export Artifacts**
    *   JSON and XML generation requests can now save valid generated output as downloadable chat artifacts instead of leaving large file-shaped content in the assistant response.
    *   Document Analyze and generated export flows now recognize natural JSON/XML conversion and XML template-population phrasing, with XML serialization support added to durable generated exports.
    *   XML document processing now uses a consolidated token-aware pipeline for more reliable analysis and export workflows.
    *   (Ref: [#1071](https://github.com/microsoft/simplechat/issues/1071), `functions_generated_file_exports.py`, generated analysis artifacts, XML document processing)

*   **Model Capability Catalog**
    *   Added an initial JSON source of truth for model feature capabilities across OpenAI GPT-5+, recent Claude models, Meta Llama and Code Llama, xAI Grok, and Microsoft Phi/MAI models.
    *   Catalog entries track support for text, image, audio, video, binary/file input, coding optimization, tool calling, and structured output so future multimodal routing can move away from regex-only model-name checks.
    *   This release is data-only and does not change backend or frontend runtime behavior.
    *   (Ref: Closes [#1147](https://github.com/microsoft/simplechat/issues/1147), `model_capabilities.json`, model capability detection)

*   **Per-Model Response Length Overrides**
    *   Administrators can now set an optional response-length/output-token ceiling on each model in global multi-endpoint GPT configuration.
    *   Standard chat applies the selected model's configured ceiling with the correct backend token parameter for GPT-5/o-series aliases and other OpenAI-compatible chat models.
    *   Existing endpoint model records remain compatible when the field is blank or absent.
    *   (Ref: Closes [#1143](https://github.com/microsoft/simplechat/issues/1143), related [#1047](https://github.com/microsoft/simplechat/issues/1047) and [#358](https://github.com/microsoft/simplechat/issues/358), `functions_settings.py`, `route_backend_chats.py`, `admin_model_endpoints.js`)

*   **Configurable Public Workspace Display Name**
    *   Admins can now set an optional end-user display name for Public Workspace, capped at 32 characters, so organizations can present tenant-specific terms such as "Domain Knowledge".
    *   End users see the configured label across navigation, Profile, Public Directory, Public Workspace pages, chat scope selection, and related browser messages while admin settings and internal identifiers continue to use Public Workspace/public_workspace.
    *   Empty or unset values preserve the existing Public Workspace/Public Workspaces defaults.
    *   (Ref: [#1146](https://github.com/microsoft/simplechat/issues/1146), `functions_settings.py`, `admin_settings.html`, public workspace templates and JavaScript, `PUBLIC_WORKSPACE_DISPLAY_NAME.md`)

*   **Backup Cleanup and Retention Policy Controls**
    *   Added Data Management backup cleanup controls so administrators can manually delete backup artifacts and metadata from Backup Inventory.
    *   Added unit-based backup retention settings for days, weeks, months, and years, with automatic cleanup that preserves the newest successful full backup as a restore safety baseline.
    *   Cleanup removes stored backup blobs, job timeline records, and differential sidecar state so future partial backups re-export affected unchanged items instead of pointing to deleted artifacts.
    *   (Ref: Closes [#1130](https://github.com/microsoft/simplechat/issues/1130), `functions_data_management.py`, `route_backend_data_management.py`, `admin_settings.html`, `admin_data_management.js`)

*   **Multi-Select Metadata Extraction**
    *   Personal, group, and public workspace document multi-select bars now include an **Extract Metadata** action when metadata extraction is enabled.
    *   Selected documents are queued through the shared metadata extraction background workflow, preserving generated titles along with authors, abstracts, keywords, publication dates, and organization metadata.
    *   (Ref: Closes [#1134](https://github.com/microsoft/simplechat/issues/1134), `route_backend_documents.py`, `route_backend_group_documents.py`, `route_backend_public_documents.py`, workspace document multi-select actions)

*   **Data Management Backup Restore Workflow**
    *   Added an admin-only restore workflow for completed Data Management backups, with manifest preflight, create-only default policy, explicit overwrite confirmation, durable restore jobs, cancellation/retry support, and sanitized progress in Job History.
    *   Restore supports configured target Cosmos DB, AI Search, and Enhanced Citation blob targets while preserving secret-safe review and job responses.
    *   (Ref: Closes [#1091](https://github.com/microsoft/simplechat/issues/1091), `functions_data_management.py`, `functions_data_management_restore_state.py`, `route_backend_data_management.py`, `admin_settings.html`, `admin_data_management.js`, `DATA_MANAGEMENT_RESTORE.md`)

*   **Reviewed, Scalable Data Migration Workflow**
    *   Replaced the Admin Data Management migration form with a six-stage Target, Scope, Content & Options, Review, Confirm, and Progress workflow.
    *   Added server-paginated principal catalogs, exhaustive all-mode counts, persistent cross-page selections, sanitized preflight checks, single-use administrator-bound review authorization, settings-drift protection, separate destructive confirmation, duplicate-submit prevention, and inline durable job recovery controls.
    *   (Ref: Closes [#1097](https://github.com/microsoft/simplechat/issues/1097), `functions_data_management.py`, `route_backend_data_management.py`, `admin_settings.html`, `admin_data_management.js`)

*   **Configurable AI Response Completion Audio Cues**
    *   Administrators can enable locally bundled completion sounds, while each user can opt in, choose and preview one of ten cues, set volume, or mute cues without losing their preferences.
    *   Cues play once for newly completed personal-chat responses outside the active visible conversation, with server-authoritative gating, cross-tab preference synchronization, and historical/duplicate suppression.
    *   (Ref: Closes [#1062](https://github.com/microsoft/simplechat/issues/1062), `completion-audio-cues.js`, notification polling, Profile and Admin Settings, `AI_RESPONSE_COMPLETION_AUDIO_CUES.md`)

*   **High-Throughput Resumable Source Blob Backups**
    *   Source document backups now stream bounded Azure SDK blocks with configurable file concurrency and chunk size instead of buffering complete blobs or copying files serially.
    *   Added durable per-file verification and resume, source/target generation fencing, adaptive Retry-After-aware throttling, isolated file failures, authenticated chunked encryption, throughput telemetry, and a reproducible AzCopy/server-copy/SDK benchmark harness.
    *   (Ref: Closes [#1095](https://github.com/microsoft/simplechat/issues/1095), `functions_data_management.py`, `test_data_management_blob_backup_transfers.py`, `benchmark_data_management_blob_backup.py`, `DATA_MANAGEMENT_BLOB_BACKUP_THROUGHPUT.md`)

*   **Desktop Conversation Notifications**
    *   Administrators can enable operating system notifications for completed AI responses, and users can manage their own preference from Profile.
    *   Notifications appear only while SimpleChat is open in a hidden or unfocused tab, show the application and conversation titles without response content, and focus the existing tab when selected.
    *   (Ref: Fixes [#866](https://github.com/microsoft/simplechat/issues/866), `chat-desktop-notifications.js`, `chat-streaming.js`, Profile and Admin Settings)

*   **Automatic Overnight Control Center Statistics Refresh**
    *   Added an enabled-by-default daily Control Center metrics refresh at 2:00 AM Eastern, with an administrator toggle and configurable time under Admin Settings > Control Center.
    *   The recurring schedule follows Eastern daylight-saving changes, stores concrete execution timestamps in UTC, and shows last-run and next-run values in each administrator's browser timezone.
    *   (Ref: Closes [#706](https://github.com/microsoft/simplechat/issues/706), `functions_control_center.py`, `background_tasks.py`, `admin_settings.html`, `control-center.js`)

*   **Configurable Chat AI Notice**
    *   Administrators can display custom plain-text AI guidance directly below the chat composer.
    *   Supports non-dismissible, per-session, daily, and once-per-message-version behavior with validated dismissal persistence and automatic redisplay when the configured notice changes.
    *   (Ref: [#715](https://github.com/microsoft/simplechat/issues/715), `functions_ai_notice.py`, `admin_settings.html`, `chats.html`, `chat-ai-notice.js`)

*   **Per-Message Audio Export**
    *   Users can export completed user and assistant chat messages as MP3 audio when text-to-speech is enabled.
    *   Downloads reuse the active Azure Speech voice and speed, include only visible message text, and remain transient without storing generated audio in SimpleChat.
    *   (Ref: [#628](https://github.com/microsoft/simplechat/issues/628), `chat-tts.js`, `chat-message-export.js`, `chat-messages.js`, `MESSAGE_AUDIO_EXPORT.md`)

*   **Adaptive Exhaustive Azure AI Search Backups**
    *   Azure AI Search backups now export personal, group, and public indexes through deterministic keyset-paged artifacts with durable checkpoints, exact resume behavior, schema validation, and restore-readiness integrity status.
    *   Added fair bounded concurrency, Retry-After-aware handling for throttling and service interruptions, adaptive pressure reduction and recovery, and sanitized per-index throughput and failure metrics.
    *   (Ref: Closes [#1094](https://github.com/microsoft/simplechat/issues/1094), `functions_data_management.py`, `test_data_management_ai_search_backup_export.py`, `DATA_MANAGEMENT_BACKUP_MIGRATION.md`)

*   **Conversation Context Grounding**
    *   Models and agents now receive bounded, credential-sanitized metadata for every user turn, including the active model, SimpleChat version, workspace scope, selected documents, agent, and capability state.
    *   Each assistant response exposes the identical snapshot as a visible Conversation Context citation across streaming, non-streaming, retry, fallback, collaboration, and document-action paths.
    *   (Ref: [#508](https://github.com/microsoft/simplechat/issues/508), `functions_conversation_context.py`, `route_backend_chats.py`, `functions_workflow_runner.py`)

*   **MCP Current-State Platform**
    *   Added the governed inbound SimpleChat MCP server with a bounded personal tool surface for conversations, documents, prompts, tags, workflow discovery, and workflow execution.
    *   Hardened outbound MCP actions with presets, server-side preconfiguration catalogs, destination governance, custom headers, result policy controls, and redaction-safe discovery/runtime telemetry.
    *   (Ref: [#1013](https://github.com/microsoft/simplechat/issues/1013), [#1014](https://github.com/microsoft/simplechat/issues/1014), [#1015](https://github.com/microsoft/simplechat/issues/1015), [#1017](https://github.com/microsoft/simplechat/issues/1017), [#1018](https://github.com/microsoft/simplechat/issues/1018), MCP current-state roadmap)

*   **Bounded Parallel Cosmos Backup Export and Source Capacity Recovery**
    *   Cosmos backup export now streams deterministic JSONL checkpoint batches through configurable bounded concurrency, preserving durable fencing, latest-item state, cancellation, retry/resume, and recovery semantics without materializing complete containers in memory.
    *   Added bounded `408`, `429`, `449`, and `5xx` retry with Retry-After-aware jittered backoff, adaptive staging pressure, sanitized per-container and aggregate RU/rate/retry telemetry, and deterministic no-replay checkpoint outcomes.
    *   Added opt-in local/source Cosmos throughput boosts capped at 10,000 RU/s with topology discovery, immutable pre-mutation snapshots, fenced restore-pending recovery, safe external-change protection, minimum ARM role support in Terraform, and explicit fail-or-continue policy for unsupported or denied capacity mutations.
    *   (Ref: Closes [#1093](https://github.com/microsoft/simplechat/issues/1093), `functions_data_management.py`, `admin_data_management.js`, `test_data_management_backup_parallelism.py`, `DATA_MANAGEMENT_BACKUP_MIGRATION.md`)

*   **Admin Feedback and Safety Record Lifecycle**
    *   Added archive, unarchive, and permanently delete actions to the Feedback Review and Safety Violations admin pages, with active/archived filtering across lists, cards, statistics, pagination, and CSV exports.
    *   Archived records are hidden from user profile history, destructive deletion requires confirmation, and safety violations with pending remediation approvals cannot be deleted.
    *   Archive, unarchive, and delete actions create non-sensitive admin activity audit records, while audit persistence failures are surfaced without undoing successful lifecycle changes.
    *   (Ref: [#991](https://github.com/microsoft/simplechat/issues/991), `functions_review_lifecycle.py`, `route_backend_feedback.py`, `route_backend_safety.py`, `ADMIN_REVIEW_RECORD_LIFECYCLE.md`)

*   **File Processing Log Cleanup**
    *   Added admin controls to permanently delete file-processing logs older than a chosen number of days, weeks, or fixed 30-day months, or delete every stored log through a separate action.
    *   Added explicit confirmation, exact and partial deletion counts, admin activity logging, validation, and secured cross-partition Cosmos DB cleanup.
    *   (Ref: [#398](https://github.com/microsoft/simplechat/issues/398), `functions_logging.py`, `route_frontend_admin_settings.py`, `admin_settings.js`, `FILE_PROCESSING_LOG_CLEANUP.md`)

*   **Conversation Contents Drawer**
    *   Added an admin-controlled, default-on conversation contents drawer that indexes persisted user messages and lets users jump directly to earlier prompts in long chats.
    *   Added a default-on user profile preference so each user can hide the drawer while the global admin feature remains enabled.
    *   (Ref: [#1026](https://github.com/microsoft/simplechat/issues/1026), `chat-conversation-contents.js`, `admin_settings.html`, `profile.html`)

*   **Fork Personal Conversations from Assistant Responses**
    *   Added a Fork conversation action for persisted assistant messages, creating an independent personal conversation containing the active history through the selected response while leaving the source unchanged.
    *   Forks remap conversation, message, thread, reply, and artifact identifiers; copy blob-backed attachments to independent paths; reject unauthorized or changed sources; and clean up failed copies before they become visible.
    *   Added confirmation, duplicate-click prevention, failure feedback, immediate fork navigation, backend regression coverage, and browser workflow coverage.
    *   (Ref: [#1025](https://github.com/microsoft/simplechat/issues/1025), `functions_simplechat_operations.py`, `route_backend_conversations.py`, `chat-messages.js`, `FORK_CONVERSATION.md`)

*   **User Font Size Preferences**
    *   Added persisted XS, S, M, L, and XL font-size choices to the user profile, ranging from 75% to 200% with medium as the default.
    *   Font-size selections preview immediately and apply across SimpleChat after the user saves the preference.
    *   (Ref: [#1099](https://github.com/microsoft/simplechat/issues/1099), `profile.html`, `functions_settings.py`, `FONT_SIZE_AND_200_PERCENT_ZOOM_FIX.md`)

*   **Durable Data Management Backup Jobs**
    *   Full and partial backups now persist immutable plans and source cutoffs, fenced attempts, resource/batch checkpoints, and latest-only Cosmos, AI Search, and Blob item state without mutating source records or metadata.
    *   Added source-scoped overlap protection, authenticated cancellation and focused retry/resume controls, stale/queued worker recovery, bounded sanitized progress, and explicit non-destructive differential/deletion semantics in backup manifests.
    *   (Ref: Closes [#1092](https://github.com/microsoft/simplechat/issues/1092), `functions_data_management.py`, `functions_data_management_backup_state.py`, `DATA_MANAGEMENT_BACKUP_MIGRATION.md`)

*   **Azure Blob Storage File Sync**
    *   Added Azure Blob Storage as an admin-controlled File Sync source for personal, group, and public workspaces, with account, container, prefix, selected-path, filter, tag, schedule, and remote-delete controls.
    *   Added managed identity, Key Vault-backed service principal and connection string authentication, connection testing, virtual-folder browsing, ETag change detection, and streamed ingestion through the existing document pipeline.
    *   (Ref: [#1027](https://github.com/microsoft/simplechat/issues/1027), `functions_file_sync.py`, `workspace-file-sync.js`, `AZURE_BLOB_STORAGE_FILE_SYNC.md`)

*   **Task-Level Workflow Model and Agent Selection**
    *   Each ordered workflow task can now inherit the workflow's Default Runner or select its own authorized Direct Model or Agent.
    *   Task runners are normalized on save and revalidated before execution, including current personal/group/global agent scope, group membership, and enabled model endpoint/model availability.
    *   Unavailable runners follow the workflow's retry and stop-or-continue strategy, while task run items record non-secret runner audit details, execution deployment/provider, output preview, and token usage when available.
    *   Existing tasks without runner configuration inherit the workflow default, and workflows without task sequences retain the legacy execution path.
    *   (Ref: [#1084](https://github.com/microsoft/simplechat/issues/1084), `functions_personal_workflows.py`, `functions_group_workflows.py`, `functions_workflow_runner.py`)

*   **Configurable Content Safety Violation Messages**
    *   Administrators can now configure the Markdown message shown when Content Safety blocks a chat request using the standard Markdown editor toolbar.
    *   A new setting controls whether the block reason, detected categories and severities, and blocklist matches are included beneath the custom message.
    *   The editor now renders correctly when the hidden Safety tab opens, and Markdown-only edits activate Save Settings before submission.
    *   (Ref: [#989](https://github.com/microsoft/simplechat/issues/989), `functions_content_safety.py`, `admin_settings.html`, `route_backend_chats.py`)

*   **Optional Terms of Use Gate**
    *   Added an admin-configurable Terms of Use prompt that can require users to accept rules of behavior, terms, or an entry notice before using SimpleChat.
    *   Supports every-session, once-per-day, and once-per-version recurrence modes, with server-side browser/API enforcement and activity logging for accept/decline events.
    *   (Ref: [#504](https://github.com/microsoft/simplechat/issues/504), `TERMS_OF_USE.md`, `functions_terms_of_use.py`, `route_frontend_terms_of_use.py`, `terms_of_use.html`)

*   **Admin Cosmos DB JSON Editor**
    *   Added an admin-only Data Management tool for selecting SimpleChat Cosmos DB containers, running paged SELECT queries, opening individual documents, editing JSON, and saving changes with ETag concurrency protection.
    *   Empty browse mode is capped at the first 100 documents, while custom SELECT queries page beyond 100 through continuation tokens without returning oversized result sets in one request.
    *   The interface is protected by danger acknowledgements, blocks `id` and partition key edits, and records editor actions plus save summaries in Activity Logs.
    *   (Ref: [#1006](https://github.com/microsoft/simplechat/issues/1006), `COSMOS_DB_JSON_EDITOR.md`, `functions_data_management.py`, `route_backend_data_management.py`, `admin_settings.html`, `admin_data_management.js`)

*   **Redis Explorer**
    *   Added an admin-only Redis Explorer in Admin Settings > Scale > Redis Monitoring for read-only, cursor-paginated Redis key browsing with substring filtering and page-size controls.
    *   Admins can select a key to view sanitized metadata and bounded preview content; session, token, cookie, credential, password, secret, authorization, and CSRF-like keys return restricted previews.
    *   JSON previews redact sensitive fields and all browser rendering uses text-safe DOM updates.
    *   (Ref: `REDIS_EXPLORER.md`, `functions_redis_monitoring.py`, `route_backend_settings.py`, `admin_settings.html`, `admin_settings.js`)

*   **Conversation Cache Metrics Dashboard**
    *   Added DAI-style rolling metrics for conversation list, feed, and advanced-search cache activity, including 15-minute hit rate, hits/misses, bypasses/errors, writes/invalidations, operation mix, last cache event, and last invalidation.
    *   Exposed normalized conversation cache settings and metrics through app maintenance status without adding Cosmos reads to the conversation hot path.
    *   Removed the Phase 4 badge from the Conversation Cache card now that the feature is part of the operational dashboard.
    *   (Ref: conversation cache metrics, `functions_conversation_cache.py`, `functions_app_maintenance.py`, `admin_settings.html`, `admin_settings.js`)

*   **Redis Document Access Index Cache**
    *   Added Redis read-through caching for DAI-backed document list, tag list, and legacy-count reads with scope-version invalidation and bounded TTL controls.
    *   Admin Settings now shows Redis DAI cache health, hit/miss/bypass/error metrics, invalidations, and the latest cache event alongside DAI read and maintenance status.
    *   (Ref: DAI Redis cache, `functions_document_access_index.py`, `admin_settings.html`, `admin_settings.js`)

*   **Audio File Runtime Support**
    *   Added default-on FFmpeg and FFprobe packaging for container builds so SimpleChat can transcode a much broader set of audio files before Azure Speech transcription.
    *   Expanded recognized audio upload extensions to include common containers and codecs such as 3GA, AAC, AC3, AIFF, AMR, AU, CAF, FLAC, M4A/M4B/M4R, Matroska audio, MP2/MP3/MPA, OGG/Opus/Speex, WAV, WebM audio, WMA, and WavPack.
    *   Added Admin Settings runtime guidance showing whether FFmpeg broad transcoding is available in the current app runtime and which audio upload extensions are recognized.
    *   Added `SIMPLECHAT_INSTALL_FFMPEG` / `INSTALL_AUDIO_FFMPEG` build controls for deployments that need to opt out of bundling FFmpeg.
    *   (Ref: audio uploads, FFmpeg runtime, `Dockerfile`, `functions_documents.py`, `admin_settings.html`, `AUDIO_FILE_RUNTIME_SUPPORT.md`)

*   **Chat Scroll Behavior and 508 Usability**
    *   Updated chat message rendering so the viewport no longer jumps to the very bottom of long assistant responses when they finish loading while the user is reading near the top.
    *   Auto-scroll now only occurs when the user is already near the bottom of the conversation, and a floating "scroll to latest message" button appears when new content arrives below the current view.
    *   This aligns the chat experience more closely with other AI chat tools and reduces unexpected motion for 508 testers and keyboard users.
    *   (Ref: `chats.html`, `chat-global.js`, `chat-messages.js`)

#### User Interface Enhancements

*   **Fact Memory Moved To Chat Settings**
    *   The fact memory control now lives in **Admin Settings > Chat > Chat Experience > Fact Memory**, with wording that explains it works without agents or actions and that users manage their own entries in Profile.
    *   It was previously only reachable from **Agents & Actions > Actions** as "Enable Fact Memory Action", so administrators running plain chat had no reason to open that tab and never found it.
    *   The Actions tab now shows a read-only note pointing at the Chat setting, matching how Tabular Processing points at Enhanced Citations. Existing configurations are unchanged; the underlying setting and any saved memories are preserved.
    *   (Ref: `chat-experience.html`, `actions.html`, `admin_settings.js`, `admin_settings_nav.py`, [#1352](https://github.com/microsoft/simplechat/issues/1352))

*   **Throttled Chat Responses Now Explain Themselves**
    *   SimpleChat retries throttled model calls with backoff, but once those retries ran out the chat response fell through to the generic "Something went wrong while streaming the response" error. That was indistinguishable from a genuine failure, which mattered most in deployments that throttle deliberately through API Management.
    *   An exhausted throttle is now recognized as rate limiting and shown in its own banner, with an hourglass icon, a "Rate limited:" heading, and the administrator's rendered Markdown. Any partial content already streamed is still saved.
    *   (Ref: `chat-streaming.js`, `appendStreamErrorBanner`, `is_rate_limit_error`, [#1354](https://github.com/microsoft/simplechat/issues/1354))

*   **Admin Settings Pages Show Real Screenshots**
    *   Fourteen admin settings tab pages were rendering "screenshot needed" placeholders even though real screenshots already existed in the repository. Those pages now display the actual screenshots for the General, AI Models, Search and Extract, Workspaces, File Sync, Workspace Identities, Citation, Safety, Security, Agents, Scale, Control Center, Logging, and Send Feedback tabs.
    *   The four tabs with no captured screenshot still show a placeholder naming the exact file to create, so genuine gaps stay visible.
    *   (Ref: `docs/admin/`, `docs/images/admin-settings/`)

*   **Admin Settings Restructure Merged With Current Development**
    *   Version bump covering the merge of the Admin Settings information architecture work with the generated file output fixes developed in parallel. Both reached v0.260.011 independently, so their release notes are combined under that version.
    *   (Ref: Admin Settings navigation, generated file exports)

*   **System Settings Card Split To Where Each Setting Belongs**
    *   One card mixed maximum file size, conversation history, idle timeout, the default system prompt and the access denied message — five unrelated concerns under one heading.
    *   Maximum File Size is now in **Workspaces → Files & Sharing**, Conversation History and Default System Prompt in **Chat → Chat Experience**, and Access Denied Message in **Security → Access & Roles**.
    *   What remains in **Security → Session** is the idle timeout, and the card is now named for it.
    *   Every setting keeps its saved value; nothing needs re-entering.
    *   (Ref: `idle-timeout-section`, `file-size-limit-section`, `conversation-history-section`, `default-system-prompt-section`, `access-denied-message-section`)

*   **Backup, Migrate & Restore Split Into Five Tabs**
    *   One tab carried the entire backup, migration, restore, Cosmos editing and job history surface — over 1,600 lines in a single scroll.
    *   Backup & Recovery now has **Backup** (readiness, backup, schedule, storage, encryption), **Migrate**, **Restore**, **Cosmos Editor** and **Jobs**.
    *   The save button, status line and operational-hours warning are shared by all five tabs, so they sit above the tabs and stay available wherever you are in the group.
    *   This completes the Admin Settings restructure: **14 groups and 44 tabs**, from an original 17 flat tabs.
    *   (Ref: `backup`, `migrate`, `restore`, `cosmos-editor`, `jobs`)

*   **AI Models Split By Model Purpose**
    *   AI Models presented every model setting on one tab. It is now **Model Endpoints** (endpoint and fallback configuration, plus the Chat Model dialog opened from it), **Embeddings** and **Image Generation**.
    *   (Ref: `model-endpoints`, `embeddings`, `image-generation`)

*   **Agents And Actions Are Now Separate Tabs**
    *   A single "Agents and Actions" tab carried agent configuration, template approvals, document action capabilities, action configuration and the whole inbound MCP surface.
    *   It is now **Agents**, **Actions** and **Inbound MCP**.
    *   Inbound MCP is a large area with its own dialogs and diagnostics, and the whole tab is hidden when the inbound MCP interface is turned off rather than showing an empty tab.
    *   (Ref: `agents`, `actions`, `inbound-mcp`)

*   **Knowledge Settings Split By What They Actually Do**
    *   Search & Extract held eight cards spanning four unrelated jobs, from Bing consent to voice transcription.
    *   Knowledge now has **Web & Research** (web search, URL access, deep research), **Search Index** (Azure AI Search), **Document Extraction** (document intelligence, chunk sizes, plus metadata extraction and multi-modal vision brought over from Workspaces) and **Audio & Video** (video intelligence, voice conversations), alongside the existing File Sync.
    *   Voice and video sit under Knowledge rather than Chat because they are extraction pipelines that turn recordings into searchable content.
    *   (Ref: `web-research`, `search-index`, `extraction`, `audio-video`)

*   **Workspaces Focused On Workspaces**
    *   Workspaces mixed workspace types with file rules, workflow and extraction settings.
    *   It is now **Workspace Types** (personal, group, public), **Files & Sharing** (downloads, sharing, and shared conversation file approvals brought over from AI Models) and the existing Global Identities.
    *   (Ref: `workspace-types`, `files-sharing`)

*   **Workflow Is Its Own Area**
    *   Workflow drives approvals and assignment across every workspace type and was too large to sit as one card inside Workspaces. It now has its own group.
    *   (Ref: `workflow`, `workflow-settings-section`)

*   **General Tab Broken Up Into Focused Tabs**
    *   General had grown into a catch-all of eleven unrelated cards: branding sat next to health checks, API documentation, terms of use and system settings.
    *   Appearance now has **Branding** (branding, home page text, appearance), **Notices & Agreements** (classification banner, chat AI notice, terms of use and the user agreement pulled across from Workspaces) and **Pages & Links** (static pages plus external links).
    *   Health Check and API Documentation moved to Operations, which is now **Logging & Health** — they report on how the app is running rather than how it looks.
    *   Support moved to Help as its own **Support Menu** tab, next to Send Feedback.
    *   (Ref: `branding`, `notices`, `custom-pages`, `logging`, `support-menu`)

*   **Security Split Into Five Purposeful Tabs**
    *   Security held a single Key Vault card while an unrelated Safety tab mixed content filtering with role permissions, which are different jobs.
    *   Security is now **Access & Roles** (who gets in and with what role), **Secrets** (Key Vault), **Content Safety** (what may be said once you are in), **Session** (idle timeout and related system settings) and **Network** (Azure Front Door).
    *   (Ref: `access-roles`, `secrets`, `content-safety`, `session`, `network`)

*   **New Data Lifecycle Group For Retention, Classification And Archiving**
    *   Retention policy, document classification and conversation archiving all decide how long content lives and how it is labelled, but they were split across Workspaces and Safety. They now sit together in a **Data Lifecycle** group with a tab each: **Retention**, **Classification** and **Archiving**.
    *   Conversation archiving in particular was buried under Safety, which described what it protects against rather than what it does.
    *   (Ref: navigation map, `retention-policy-section`, `document-classification-section`, `conversation-archiving-section`)

*   **Chat Group Gathers The Settings That Shape A Conversation**
    *   Settings that change what a conversation looks and behaves like were spread across AI Models, Workspaces and Safety. The **Chat** group now holds them in two tabs.
    *   **Chat Experience** collects model thought display, chat file uploads (with the conversation contents drawer) and workspace scope lock.
    *   **Feedback & Alerts** collects user feedback and desktop notifications, which are both about how the app talks back to the user rather than about safety enforcement.
    *   (Ref: `chat-experience`, `feedback-alerts`, `processing-thoughts-section`, `chat-file-uploads-section`, `workspace-scope-lock-section`, `user-feedback-section`, `desktop-notifications-section`)

*   **Settings Keep Their Values Through The Move**
    *   Cards were relocated between tabs without renaming a single field, so every saved value is preserved and the form submits exactly the payload it did before.
    *   Sidebar search still finds a setting by group, tab or card name, so you can reach anything without knowing where it now lives.
    *   (Ref: admin settings field contract, `admin_settings_nav.py`)

*   **Governance And Scale Split Into Focused Tabs**
    *   Governance held five cards covering three different jobs. It is now **Feature Governance** (which features are governed), **Policies** (the policies themselves), and **MCP Governance**.
    *   Scale mixed cache configuration with Cosmos capacity, and is now **Redis & Caching** and **Cosmos**.
    *   **Azure Front Door** moved out of Scale into Security, under a new **Network** tab. It configures authentication and redirect flows rather than throughput, so it never belonged with capacity settings.
    *   Existing links and bookmarks to `#governance` and `#scale` still work and land on the first tab of each group.
    *   No settings changed. Every option keeps its name and its saved value.
    *   (Ref: navigation map, `feature-governance`, `governance-policies`, `mcp-governance`, `redis-caching`, `cosmos`, `network`)

*   **Latest Features No Longer Opens Every Time You Visit Admin Settings**
    *   Latest Features was pinned first in both the top tabs and the admin sidebar, and its pane was hard-coded as the default active tab, so a curated release-notes page behaved like the Admin Settings landing page.
    *   It now sits last in both navigations, after **Send Feedback**, and **General** is the landing tab instead.
    *   The Latest Features content is unchanged, including its **New** badge and the hide/unhide option.
    *   (Ref: `admin_settings.html` top-tab strip, `_sidebar_nav.html`, `admin_sidebar_nav.js` default tab)

*   **Global Identities Is No Longer An Unlabelled Widget**
    *   The Global Identities tab rendered a bare control with no heading or description, unlike every other Admin Settings tab.
    *   It now has a heading and explains that identities are deployment-wide and that secrets are stored in Key Vault when Key Vault storage is configured.
    *   (Ref: Global Identities, `workspace-identities-section`, `functions_workspace_identities.py`)

*   **File Sync Is Now Reachable From The Sidebar**
    *   File Sync is one of the larger settings surfaces but was the only tab with no sidebar submenu, so its sub-areas could not be jumped to or found with sidebar search.
    *   **Visible Source Types**, **Personal Workspace Sync**, **Group Workspace Sync**, and **Public Workspace Sync** are now sidebar destinations.
    *   (Ref: File Sync, `_sidebar_nav.html`, `file-sync-submenu`)

*   **Blob Storage Actions Can Now Use Managed Identity or an Account Key**
    *   The Blob Storage action modal gained an authentication selector offering **Connection String**, **Managed Identity**, and **Account Key**, along with blob service endpoint and account key fields.
    *   Previously the modal only collected a connection string even though the backend accepted other methods, so managed identity was not reachable through the UI.
    *   The endpoint field is validated against the Azure Blob hostname allowlist before the action is saved.
    *   (Ref: `_plugin_modal.html`, `plugin_modal_stepper.js`, `blob_storage.definition.json`)
*   **Shared Conversations No Longer Fail With "Stream interrupted: Forbidden"**
    *   Fixed invited participants being unable to invoke the AI at all in a shared conversation. Any explicit AI request returned `Forbidden` with no content.
    *   Root cause was the hidden source conversation behind every shared conversation being owned by its creator, so participants failed a plain ownership comparison in the chat streaming route even though they are legitimate members.
    *   Because shared conversations only call the AI on an explicit mention, this surfaced the first time a participant asked the assistant for something, which made it look file-specific.
    *   Participants can also now download generated files from a shared conversation, which was blocked by the same comparison.
    *   Also fixed background CSV exports queued by a participant becoming unreadable for the owner, because publication checks looked up the export run under the wrong user partition.
    *   (Ref: `build_conversation_participation_context`, `route_backend_chats.py`, `route_enhanced_citations.py`, `functions_simplechat_operations.py`)

*   **Clearer Group Workspace Save Errors**
    *   Attempting to save a generated document into a group workspace without document rights now names the roles that can complete it and suggests requesting the content as a downloadable file instead of failing with a bare permission error.
    *   (Ref: `_resolve_group_upload_target_for_current_user`)

*   **Tab Now Completes an @ Mention in Shared Conversations**
    *   In multi-user conversations, pressing **Tab** while the `@` suggestion menu is open now accepts the highlighted participant, agent, model, or invite suggestion, exactly like **Enter** already did.
    *   Previously **Tab** moved focus out of the message box and left the half-typed `@par` text behind, which broke the autocomplete habit most people bring from other editors and chat clients.
    *   **Shift+Tab** is deliberately unchanged and still moves focus backwards, and **Tab** still moves focus normally when the menu is showing "No matching participants...".
    *   The chat mention menu now matches the agent instruction mention menu, which already accepted **Tab**.
    *   (Ref: `chat-collaboration.js`, `handleComposerKeydown`, `selectActiveMentionSuggestion`, Fixes #1299)

*   **Mention Menu Is Now Announced Correctly By Screen Readers**
    *   Each `@` suggestion is now exposed as a proper listbox option with `aria-selected`, and the message box references the highlighted suggestion through `aria-activedescendant` paired with `aria-controls` so assistive technology can resolve it.
    *   The highlighted suggestion is also scrolled into view while arrowing through a long list, so keyboard navigation no longer highlights an off-screen entry.
    *   (Ref: `chat-collaboration.js`, `renderMentionMenu`, `updateMentionMenuActiveItem`, `applyMentionComboboxState`, `chats.html`)

*   **Finished Jobs No Longer Look Stuck**
    *   Completed backup jobs no longer display **Current container: Waiting**, which made a finished job look like it was still churning.
    *   Migration jobs no longer display a **Liveness: Running** row after reaching a terminal status.
    *   Live-only telemetry is now hidden once a job is `completed`, `completed_with_warnings`, `failed`, or `canceled`.
    *   (Ref: `admin_data_management.js`, `getBackupLiveMetrics`, `getMigrationLiveMetrics`, `isTerminalJobStatus`)

*   **Run Retention Cleanup Now Explains Itself**
    *   Added a hover tooltip and an `(i)` toggle that expands inline guidance next to the **Run Retention Cleanup** button.
    *   Documents that cleanup permanently deletes backups past the retention period along with their artifacts, skips jobs that are still running, honors **Keep latest full backup**, and deletes at most 25 backups per run.
    *   Clarifies that "found no expired backups to delete" means every backup is still inside the retention window, which is expected rather than a failure.
    *   (Ref: `admin_settings.html`, backup retention cleanup, Data Management)

*   **Agent and Workflow Builder Refresh**
    *   Agent configuration now follows Actions → Knowledge → Instructions, with selected actions visible in the Instructions step.
    *   Workflows use a stepped General/Trigger/Tasks/Reliability/Review builder with per-task runner controls and alert-rule editing.
    *   (Ref: agent modal, workflow builder, workflow runner controls, alert rules editor)

*   **Administration and Configuration UX Improvements**
    *   Workspace sections now use a consistent Documents → Prompts → Identities → Sync → Endpoints → Actions → Agents → Workflows order.
    *   Governance policy copy/inverse/show-users actions, dedicated Log Analytics configuration, refreshed backup/migrate/restore flows, and reviewed data migration steps reduce admin friction.
    *   External links can be reordered, custom pages can be opened directly, and non-blocking Bootstrap toasts replace browser alerts across admin, workspace, and profile pages.
    *   (Ref: workspace section order, governance UI, Log Analytics settings, data migration UI, toast notifications)

*   **Chat, Navigation, and Accessibility Enhancements**
    *   Chat, navigation, and sidebar layouts remain usable at 200% zoom and with large text.
    *   The Conversation Contents drawer adds safe labels, keyboard focus handling, active-location tracking, and responsive desktop/mobile navigation.
    *   Long source lists collapse behind a disclosure, document picker rows show file-name context, and Refresh Documents preserves selection with clearer status.
    *   (Ref: 508 usability, conversation contents drawer, source disclosure, document picker, refresh documents)

*   **Data Explorer and Extraction Status UX**
    *   Redis Explorer uses a fixed-height modal with independent key-list and preview scrolling.
    *   Cosmos query results open in a scrollable modal so the main editor stays focused on query setup.
    *   Extraction badges identify the engine that ran and show Content Understanding vs. Document Intelligence fallback reasons.
    *   (Ref: Redis Explorer, Cosmos editor results modal, extraction badges)

*   **Placeholder Screenshots for Pending Captures**
    *   Added 76 branded "Screenshot pending" placeholders so every v0.260.001 Latest Features card renders a valid local image while final captures are pending.
    *   Placeholders can be replaced in place with real screenshots without changing the catalog configuration.
    *   (Ref: `application/single_app/static/images/features/`, Latest Features image galleries)

*   **Documentation Site Works on Phones and Tablets**
    *   Standardized the responsive breakpoints, which previously mixed `768px` and `767.98px` and left gaps, and exported the desktop breakpoint to JavaScript so it is no longer duplicated by hand.
    *   Wide tables and long code blocks are now contained in horizontal scroll regions instead of widening the page, images are lazy-loaded with intrinsic sizing, touch targets meet a 44px minimum, and the mobile navigation drawer and search sheet trap and restore focus.
    *   Verified with browser tests at 360x640, 390x844, 768x1024, 1280x800, and 1920x1080.
    *   (Ref: `docs/assets/css/main.scss`, `docs/assets/js/sidebar.js`, `ui_tests/test_docs_site_responsive.js`)

*   **Simpler Documentation Pages**
    *   Landing pages were rewritten from hand-written HTML card markup into plain markdown. The home page previously had 82 blocks of card markup and zero markdown headings, and the features page 119 blocks and zero headings, which meant neither page had a working "On this page" table of contents or heading anchors.
    *   The FAQ was rebuilt so every question is its own heading with a linkable anchor.
    *   The decorative page hero, with its gradient banner, pill row, and icon orb, was replaced with a plain documentation header across the 38 pages that used it.
    *   Split the 452 KB release notes page into per-version-series pages while keeping the existing release notes URL working.
    *   (Ref: `docs/index.md`, `docs/features.md`, `docs/start/faqs.md`, `scripts/build_release_notes_pages.py`)

*   **Documentation URLs Now Match Their Section**
    *   Guides previously lived under three different URL spaces that all meant the same thing. Tutorials and how-to guides are consolidated under `/guides/`, orientation pages moved under `/start/`, deployment scenarios under `/deploy/`, and reference pages under `/reference/`.
    *   **Existing links and bookmarks continue to work.** Every moved page redirects from its old URL, and the URLs the application itself links to were deliberately left unchanged.
    *   (Ref: documentation navigation, `jekyll-redirect-from`, `ui_tests/check_docs_links.js`)

*   **"Refresh documents" Now Actually Refreshes**
    *   The **Refresh selected documents** button previously warned `Select one or more workspace documents in the picker first.` even though the picker was empty and nothing could be selected.
    *   It is now labeled **Refresh documents**, reloads the document list while preserving the current selection, and reports what it found — including a clear message when the selected scope has no documents.
    *   (Ref: [#1282](https://github.com/microsoft/simplechat/issues/1282), `workspace.html`, `group_workspaces.html`, `workspace_workflows.js`)

*   **Extraction Badges Name the Engine That Actually Ran**
    *   Extraction tooltips in personal, group, and public workspaces now say whether a document was processed with Azure AI Content Understanding or Document Intelligence Layout, and explain any fallback that occurred.
    *   The **Change Extraction** action now works for images as well as PDFs, and refuses a change to Enhanced while Enhanced extraction is disabled.
    *   (Ref: [#1277](https://github.com/microsoft/simplechat/issues/1277), `workspace-documents.js`, `public_workspace.js`, `group_workspaces.html`, `functions_documents.py`)

*   **Auto Mode Also Upgrades for Figures**
    *   Auto mode still samples the first pages with Document Intelligence Layout as the cheaper detector, but now upgrades to Enhanced when it finds figures or images, not just tables and selection marks. This matters because figure description is the main reason to use Enhanced.
    *   (Ref: [#1277](https://github.com/microsoft/simplechat/issues/1277), `functions_documents.py`, Auto mode detection)

*   **Collapsed Long Source Lists**
    *   The per-message Sources disclosure now shows the first 25 document sources and collapses the rest behind a **Show N more sources** control, so an agent that retrieves hundreds of chunks no longer floods the panel.
    *   No source data is discarded — the full set is still stored, exported, and available for citation matching.
    *   (Ref: [#1239](https://github.com/microsoft/simplechat/issues/1239), `chat-messages.js`, `chat-citations.js`)

*   **Dedicated Log Analytics Configuration Section**
    *   Log Analytics actions now have their own Step 3 configuration section instead of reusing the generic endpoint and authentication form.
    *   Workspace ID, Cloud, API Endpoint, and the authentication method moved out of *Advanced → Additional Fields* and into the main configuration step, next to the new Test Connection button. Authority Host and Endpoint Override appear only when the Custom cloud is selected.
    *   Existing Log Analytics actions are unaffected — the section reads and writes the same manifest fields and preserves stored values such as `query_history`.
    *   (Ref: [#1267](https://github.com/microsoft/simplechat/issues/1267), `_plugin_modal.html`, `plugin_modal_stepper.js`, Log Analytics action configuration)

*   **Agent Modal Step Reorder: Instructions After Actions and Knowledge**
    *   The agent modal now runs Basic Info → Model & Connection → **Actions** → **Knowledge** → **Instructions** → Advanced → Summary, so instructions are written once the agent's real capabilities are known.
    *   Added a collapsible **Selected Actions & Knowledge** panel at the top of the Instructions step listing the selected actions with badges for their enabled capabilities, plus the assigned workspaces, documents, tags, and web sources, each with its reference token.
    *   Step navigation, validation, and Foundry agent-type visibility now key off named steps rather than hard-coded step numbers.
    *   (Ref: [#1257](https://github.com/microsoft/simplechat/issues/1257), [#1263](https://github.com/microsoft/simplechat/pull/1263), `_agent_modal.html`, `agent_modal_stepper.js`)

*   **Workflow Alert Rules Editor**
    *   The Review step of the personal and group workflow builders replaces the single Pop-up Alert Priority dropdown with an alert mode selector and a rule editor for adding, editing, enabling and removing alert rules.
    *   Each rule row exposes its name, condition, severity, delivery and, where relevant, the task or output it should watch, with condition-specific fields appearing as the condition is chosen.
    *   The workflow list now summarizes alerts as the number of active rules, and the Review summary names the rules that will notify you.
    *   Invalid rules are caught before saving, such as a missing regex pattern, empty match values, an unwritten model condition, or a task-scoped rule with no task selected.
    *   (Ref: `workspace.html`, `group_workspaces.html`, `workspace_workflows.js`, workflow builder review step)

*   **Consistent Workspace Section Order**
    *   Workspace sections now follow a single order of operations everywhere they are listed: Documents, Prompts, Identities, Sync, Endpoints, Actions, Agents, Workflows.
    *   The order reflects how a workspace is actually built up, so it is clearer that Identities feed both Sync and Actions, that Actions belong to Agents, and that Workflows run Agents.
    *   Applied to the tab strip, the collapsed Section dropdown, and the left-hand sidebar submenus for personal and group workspaces. Public workspaces already matched this order and were left unchanged.
    *   Sections that an admin has disabled stay hidden; the remaining sections simply close up while keeping their relative positions.
    *   (Ref: [#1255](https://github.com/microsoft/simplechat/issues/1255), `workspace.html`, `group_workspaces.html`, `_sidebar_nav.html`, `WORKSPACE_SECTION_ORDER.md`)

*   **File Name Shown in Document Picker Rows**
    *   Document rows in the chat grounded-search picker now show the file name as a smaller muted line beneath the title whenever the two differ, so it is clear which file a search matched.
    *   Rows without distinct titles are unchanged, and the row tooltip carries both the title and the file name.
    *   (Ref: [#1256](https://github.com/microsoft/simplechat/issues/1256), `chat-documents.js`, `chats.css`, document picker rows)

*   **Governance Policy Copy and Principal Review Actions**
    *   Added Duplicate and Inverse actions for delegated item governance policies so admins can quickly clone a policy or create an allow/block-list-swapped version before saving it as a new policy.
    *   Added a Show Users modal and removed the allowed/blocked user and group columns from the main delegated policy table, keeping the table easier to scan while preserving principal detail access.
    *   (Ref: [#1252](https://github.com/microsoft/simplechat/issues/1252), `admin_governance.js`, `admin_settings.html`, governance delegated item policies)

*   **Backup, Migrate & Restore Admin Refresh**
    *   Reworked the Admin Settings data-management tab into a clearer Backup, Migrate & Restore control center with start-here guidance, setup modals, and plain-language migration choices.
    *   Separated destination Cosmos **RU Boost** configuration and testing from Cosmos data-copy access validation so admins can verify the correct Azure management-plane permissions before migration.
    *   Aligned the refresh with the restore workflow from Backup Inventory so admins can review backup readiness, choose restore policy/surfaces, run preflight, and queue supported restore jobs.
    *   (Ref: [#1140](https://github.com/microsoft/simplechat/issues/1140), `admin_settings.html`, `admin_data_management.js`, `functions_data_management.py`, Data Management docs and tests)

*   **Custom Pages Admin Open Action**
    *   Added an Open action to the Admin Settings Custom Pages table so administrators can launch enabled static or Python-backed custom pages directly from their metadata row.
    *   The action opens encoded `/custom/<slug>` URLs in a new tab while preserving existing Custom Pages route authorization, enabled-state checks, access-level rules, role restrictions, and `.html` alias compatibility.
    *   Disabled or unavailable pages now show a disabled Open action with explanatory tooltip copy instead of silently omitting the action.
    *   (Ref: Closes [#951](https://github.com/microsoft/simplechat/issues/951), PR [#1131](https://github.com/microsoft/simplechat/pull/1131), `admin_custom_pages.js`, `CUSTOM_PAGES.md`)

*   **External Link Ordering Controls**
    *   Admins can now move saved external links up or down and save the resulting navigation order without deleting and recreating links.
    *   The first and last links expose disabled boundary controls, and the visible order stays synchronized with the Admin Settings save payload.
    *   (Ref: Closes [#793](https://github.com/microsoft/simplechat/issues/793), `admin_settings.js`, `test_admin_external_link_ordering.py`, `EXTERNAL_LINK_ORDERING_FIX.md`)

*   **Application-Wide Non-Blocking Toast Notifications**
    *   Replaced native browser alerts across admin, group, public, personal workspace, profile, feedback, safety, and control-center workflows with consistent Bootstrap toast notifications.
    *   Added a shared, accessible toast utility that safely renders dynamic messages as text and preserves specialized chat toast positioning.
    *   (Ref: Closes [#739](https://github.com/microsoft/simplechat/issues/739), `toast.js`, `chat-toast.js`, first-party templates and workspace scripts)

*   **MCP Admin And Observability Surfaces**
    *   Added Admin Settings controls for inbound MCP runtime settings, source governance guidance, Easy Auth setup verification, request-size and throttle tuning, tool registry visibility, and copyable Application Insights starter queries.
    *   Added Governance controls for outbound MCP destination policies and inbound MCP source policies using the current source-first access model.
    *   (Ref: [#1020](https://github.com/microsoft/simplechat/issues/1020), MCP governance/admin UX, `admin_settings.html`, `admin_settings.js`, `admin_governance.js`)

*   **Responsive Long-Chat Navigation**
    *   Added safe plain-text labels, active-location tracking, keyboard focus management, destination highlighting, and persistent desktop or off-canvas mobile layouts.
    *   (Ref: [#1026](https://github.com/microsoft/simplechat/issues/1026), `chats.html`, `chats.css`, `test_chat_conversation_contents_drawer.py`)

*   **200% Zoom and Large-Text Layout Support**
    *   Updated Chat, top navigation, classification banners, and sidebar scrolling to reserve font-relative space and keep messages, navigation, tools, and the composer reachable at 200% browser zoom and large saved font sizes.
    *   (Ref: [#1099](https://github.com/microsoft/simplechat/issues/1099), `chats.css`, `navigation.css`, `sidebar.css`)

*   **Per-Task Runner Controls**
    *   Renamed the workflow-level Runner field to Default Runner and added Workflow default, Direct Model, and Agent selection to each task editor.
    *   Task rows and Review now show the resolved runner, with responsive conditional model/agent controls and text-safe rendering for endpoint, model, and agent labels.
    *   (Ref: [#1084](https://github.com/microsoft/simplechat/issues/1084), `workspace.html`, `group_workspaces.html`, `workspace_workflows.js`)

*   **Versioned Latest Features Navigation Hide Preference**
    *   Users can now hide Latest Features navigation entries for the current SimpleChat version from the ellipsis action and restore them from Profile Settings.
    *   The hidden state is version-aware, so Latest Features automatically appears again after the app version changes.
    *   Added a development-only `is_development=true` environment override that hides Latest Features nav entries without affecting production behavior when unset or false.
    *   (Ref: [#987](https://github.com/microsoft/simplechat/issues/987), `latestFeaturesHiddenVersion`, `_sidebar_nav.html`, `_top_nav.html`, `profile.html`, `latest-features-nav.js`)

#### Bug Fixes

*   **Core Action Toggles No Longer Interfere With Fact Memory**
    *   Fact memory and the built-in core actions were saved through the same admin endpoint, which required fact memory to be included in every request. With the control relocated to Chat, that contract would have let a change to any unrelated core action overwrite the fact memory setting.
    *   The endpoint now treats fact memory as optional and ignores it, so the Chat setting is the only thing that changes it. Older clients that still send the value continue to work.
    *   (Ref: `route_backend_plugins.py`, `route_frontend_admin_settings.py`, core plugin settings endpoint, [#1352](https://github.com/microsoft/simplechat/issues/1352))

*   **Agent Actions Are No Longer Skipped When A Workspace Is In Scope**
    *   Selecting an agent that has actions and enabling a workspace produced answers that never invoked any of the agent's actions. The assistant answered from retrieved document text alone, even when the retrieved excerpts did not contain what the question asked for.
    *   The retrieval prompt instructed the model to base its answer *only* on the retrieved excerpts, so although the agent's actions were attached and available, the model was told not to reach for them. Retrieved excerpts are now framed as starting evidence, and the model is directed to call an available action when the excerpts lack what the question needs, then reason over the excerpts and the action results together. The rule against fabricating unsupported values is unchanged.
    *   (Ref: `build_search_augmentation_system_prompt`, `build_mixed_source_evidence_handoff`, agent actions, workspace search, [#1332](https://github.com/microsoft/simplechat/issues/1332))

*   **Spreadsheets In A Workspace Are Now Actually Computed**
    *   A quantitative question about a spreadsheet could return values that were not in the file. Tabular computation was suppressed whenever workspace search also returned any narrative document, and the heuristic treated topic words such as "report", "policy", and "memo" as reasons to skip computation entirely.
    *   Because only a truncated three-row preview of a spreadsheet is indexed for search, skipping computation left the model deriving totals and averages from those preview rows. Tabular sources in scope are now computed unless the question unambiguously names a narrative artifact such as a PDF or presentation, restoring parity with the behavior already used when mixed-source search is disabled.
    *   (Ref: `should_run_tabular_evidence`, `functions_mixed_source_orchestration.py`, tabular processing, mixed-source evidence, [#1332](https://github.com/microsoft/simplechat/issues/1332))

*   **A Skipped Spreadsheet Now Tells The Model What It Is Missing**
    *   When tabular computation is skipped, the evidence record previously said processing "was not needed", which implied the source was irrelevant and left the model free to compute from indexed preview rows.
    *   It now states that the full table was never read, that any indexed excerpt is a truncated preview, that numeric conclusions must not be drawn from it, and that the tabular analysis action should be called if values from that source are required.
    *   (Ref: `execute_tabular_evidence_sources`, evidence envelopes, tabular citations, [#1332](https://github.com/microsoft/simplechat/issues/1332))

*   **Inline Images And Videos Now Show Only Cited Media**
    *   Assistant messages rendered an inline image or video gallery for every media file that retrieval returned, so a search that surfaced five workspace images produced five inline tiles even when the answer referenced only one of them, or none at all. Media that had nothing to do with the answer was presented inside the message bubble as though it supported the answer.
    *   Inline galleries now render only the media the response actually cited. The five-item gallery cap therefore goes to genuinely cited media instead of retrieval noise, and unreferenced workspace files no longer trigger enhanced-citation fetches.
    *   Galleries produced by an action or tool the assistant actually ran are unaffected, since those are executed results rather than unused search candidates. Conversations created before cited-source tracking existed also keep their previous behavior.
    *   The **Sources** disclosure is unchanged and still lists every retrieved document and web result, so nothing becomes harder to find.
    *   (Ref: `chat-citation-tracking.js`, `chat-inline-images.js`, `chat-inline-videos.js`, `chat-messages.js`, `cited_hybrid_citations`, [#1329](https://github.com/microsoft/simplechat/issues/1329))

*   **Running Simple Chat Directly No Longer Fails To Start When An Agent Has Actions**
    *   Starting Simple Chat with `python app.py` (including via `uv run`) aborted with `RuntimeError: Working outside of request context` whenever any agent had an action assigned. The app started normally until the first action was saved, which made the failure look intermittent.
    *   Semantic Kernel initialization runs before any request exists on that path, but agent plugin loading read the signed-in user from the Flask session. It now resolves the user only when a request is actually in progress and otherwise loads with no user identity, matching how global plugin loading already behaved.
    *   Container and App Service deployments were never affected, because they start through gunicorn and initialize during the first request. Their behavior is unchanged.
    *   Three further identity lookups used for group scope and personal model endpoints had the same latent problem and were corrected at the same time.
    *   (Ref: `semantic_kernel_loader.py`, `functions_authentication.py`, `get_current_user_id_or_none`, issue #1327)

*   **Documentation Screenshot Viewer Validates Its Image Source**
    *   The documentation site's click-to-enlarge screenshot viewer assigned an image URL taken from a data attribute in the page. Because that value flows from page content into a URL, CodeQL flagged it as a potential DOM-based cross-site scripting sink.
    *   The viewer now resolves the value and requires a same-origin `http` or `https` URL ending in an image extension before using it, so scheme-based payloads such as `javascript:` and `data:` URLs, and any off-site source, are rejected. All documentation media is local, so no legitimate image is affected.
    *   (Ref: `docs/assets/js/media.js`, `safeMediaUrl`, `ui_tests/test_docs_media_lightbox_source_validation.js`, CodeQL `js/xss-through-dom`)

*   **Admin Documentation Rebuilt For The Grouped Settings Layout**
    *   Admin Settings was reorganized from 18 flat tabs into 14 groups containing 44 tabs and 93 settings sections. The documentation was still written against the old flat layout, so it described tabs that no longer exist and omitted the new ones.
    *   The admin documentation is now one page per group, with every tab reachable by its own anchor so links to a specific tab keep working. Every retired tab URL redirects to the group that now owns its settings, so existing links and bookmarks continue to resolve.
    *   (Ref: `docs/admin/`, `application/single_app/admin_settings_nav.py`, `docs/_data/app_surface.yml`)

*   **Collaborating In A Conversation Is Now Documented**
    *   Added a guide covering shared conversations end to end: sharing a conversation, mentioning a participant with `@` and Tab completion, how shared files are approved before they become available, and what participants can and cannot do.
    *   The Blob Storage action reference now explains its managed identity and account key options.
    *   (Ref: `docs/guides/collaborate-in-a-conversation/`, `docs/reference/actions/blob-storage/`, `enable_collaborative_conversations`)

*   **Documentation Site Now Reflects the v0.260.001 Release**
    *   The documentation site's Latest Release section was a full release behind, still presenting v0.250.001 as current. It now mirrors the same three-tier model the application uses: v0.260.001 as the current release, v0.250.001 as the previous release, and v0.239.001-v0.241.007 in the archive.
    *   Added 20 feature guides for the v0.260.001 release covering enhanced extraction, embedded Office images, workflow task sequences, the MCP platform, the Yamcs and RocksDB actions, agent instruction references, action test connections, Azure Blob file sync, terms of use, audio file support, completion notifications, the chat AI notice, conversation context grounding, used documents on fork, the conversation contents drawer, font size and zoom, message audio export, public workspace display names, and chat scroll accessibility.
    *   (Ref: `docs/_data/latest_release_features.yml`, `docs/latest-release/release-260-*`, `application/single_app/support_menu_config.py`)

*   **Placeholder Screenshots Are Now Tracked**
    *   The v0.260.001 release ships branded "Screenshot pending" placeholder graphics so feature cards render while final captures are pending. Those placeholders are now listed on the documentation media status page with the exact file paths to overwrite, so they are visible work rather than a silent gap.
    *   (Ref: `docs/_data/media_pending.yml`, `/contributing/media-status/`)

*   **Release Notes Pages No Longer Break On Quoted Template Syntax**
    *   Release notes legitimately quote template syntax when describing template work, such as a Jinja `block` tag. The page generator emitted that verbatim, so the site build failed with an unknown tag error. Quoted template syntax is now escaped in generated pages and renders as literal text.
    *   (Ref: `scripts/build_release_notes_pages.py`)

*   **Release Notes Links To Internal Engineering Notes**
    *   Some release note entries linked to the internal feature and fix note trees, which are intentionally not published on the documentation site. Those links now point at the repository.
    *   (Ref: `docs/explanation/release_notes.md`)

*   **Release Notes Index No Longer Exceeds Its Page Budget**
    *   The release notes page generator inlined a fixed number of recent releases on its index. The consolidated v0.260.001 rollup is large enough on its own that this pushed the index past the maximum page size and failed generation. The index now fills its inline section by size rather than by count, so a single large rollup cannot break it.
    *   (Ref: `scripts/build_release_notes_pages.py`)

*   **Archived Release Notes Links**
    *   The archived release notes page linked to the internal feature and fix note trees, which are intentionally not published on the documentation site. Those links now point at the repository instead.
    *   (Ref: `docs/explanation/archive_release_notes.md`)

*   **Admin Settings Loads Again**
    *   Admin Settings returned a 500 error on every request after the settings restructure. The Document Action Capabilities card moved to the Actions tab but the two values it reads stayed behind in the Agents tab, and each tab is rendered separately, so those values were never there when the card asked for them.
    *   Both values are now defined in the tab that uses them, and a new test renders the two tabs together to keep them there.
    *   (Ref: `admin/_panes/actions.html`, `admin/_panes/agents.html`, document action capabilities)

*   **Server Errors Are Visible In The App Service Log Again**
    *   Once Application Insights was configured it took ownership of logging, which had the side effect of stopping Flask writing unhandled errors to the container log. A failing page left nothing behind but its access-log line, so diagnosing it meant querying Application Insights.
    *   Unhandled errors are now written to both, so the reason for a failure is visible in the App Service log stream.
    *   (Ref: `functions_appinsights.py`, `ensure_console_error_logging`, App Service console logs)

*   **Document Access Index Diagnostics Appear When Enabled**
    *   The Cosmos DB tab checked the wrong thing for the debug setting, so the backfill controls, shadow validation metrics and reset option stayed hidden even after an admin turned the setting on.
    *   (Ref: `admin/_panes/cosmos.html`, `enable_dai_debug`)

*   **Setup Walkthrough Lands On The Right Settings Again**
    *   The guided setup walkthrough sent each step to a named tab. After the Admin Settings restructure, eleven of its twelve steps named tabs that no longer existed, so those steps would have moved nowhere and left the admin looking at whatever was already on screen.
    *   Each step now names the setting it is about and the tab is worked out from the page, so the walkthrough follows settings wherever they live.
    *   (Ref: setup walkthrough, `admin_settings.js`, `admin_card_links.js`)

*   **Cosmos Throughput Validation Reveals The Invalid Field**
    *   When Cosmos throughput values failed validation, the page tried to switch to a tab that no longer exists, so the field needing attention could be left on a hidden tab with no indication of where to look.
    *   Validation now jumps to wherever the invalid field actually is.
    *   (Ref: Cosmos throughput validation, `admin_settings.js`)

*   **Backup Dialogs Remain Available From Every Tab**
    *   The eleven Backup & Recovery dialogs are opened from more than one place and several are opened from code rather than a button. Left inside a tab, a dialog cannot appear while a different tab is showing.
    *   They now sit outside the tabs, so restore, migration cancel, job detail, the Cosmos editor dialogs and the five setup guides all open wherever they are triggered from.
    *   (Ref: Backup & Recovery dialogs, `admin_data_management.js`)

*   **Shared Controls Work In Both Navigation Layouts**
    *   Shared group controls resolve their group from whichever navigation is on screen, so the Backup & Recovery save button is present in the sidebar layout as well as the tab layout.
    *   (Ref: `data-admin-group-shared`, `admin_sidebar_nav.js`)

*   **Model Setup Guide Available From Every Model Tab**
    *   The Azure OpenAI Model Setup Guide dialog is opened from the endpoints, embeddings and image generation cards. Once those moved to separate tabs it could only have opened from one of them.
    *   The dialog now sits outside the tabs, so it opens from all three.
    *   (Ref: `legacyModelDiscoveryIdentityGuideModal`)

*   **Dangling Section Comments Removed**
    *   Seven tabs ended with a comment labelling a card that had since moved to another tab.
    *   (Ref: admin settings tab panes)

*   **Group Workflow Assignment Dialog Could Not Open**
    *   The Group Workflow Assignment dialog ended up in a different tab from the button that opens it. Because an inactive tab is hidden, the dialog would not have appeared at all.
    *   The dialog now sits with its button, and a new check verifies this for every dialog in Admin Settings so it cannot happen again.
    *   (Ref: `groupWorkflowAssignmentModal`, `test_admin_settings_modal_placement.py`)

*   **Misplaced Section Comments In AI Models**
    *   Two section comments had drifted onto the wrong cards while settings were being regrouped, labelling the embeddings card as processing thoughts.
    *   (Ref: `ai-models` pane)

*   **"Open Key Vault Settings" Link No Longer Depends On A Hardcoded Tab**
    *   The link from Data Management to Key Vault switched tabs by a hardcoded id, so it silently stopped working whenever that tab was renamed.
    *   It now uses the standard card link, which finds the owning tab from the page itself and stays correct however the settings are grouped.
    *   (Ref: `data-management-key-vault-link`, `admin_card_links.js`, `admin_data_management.js`)

*   **Admin Settings Always Opens On A Real Tab**
    *   The tab shown on arrival was pinned to a specific id in both the markup and the sidebar script. Regrouping settings could leave Admin Settings opening with no tab selected at all.
    *   The landing tab is now taken from the navigation map, so it follows the settings and can never be Latest Features.
    *   (Ref: `admin_landing_tab`, `get_landing_tab_id`, `admin_sidebar_nav.js`)

*   **Stale Tab Names In Latest Features**
    *   Several Latest Features entries pointed readers at tabs by their old names after the settings moved.
    *   (Ref: `latest-features` pane)

*   **Governance Status Messages No Longer Get Stuck On One Tab**
    *   The inline governance status message lived inside the Governance pane, so a message raised while working in one area could end up rendered on a tab you were not looking at.
    *   It now sits outside the tabs and is visible wherever you are in Governance.
    *   (Ref: `governance-status`, `admin_governance.js`)

*   **Reliable File Generation From Agent Action Results**
    *   Asking an agent for a downloadable file built from action results now produces the complete dataset in the requested format. Previously these requests could fail outright, publish a three-row sample of a large result, overwrite the assistant's written answer, or return nothing at all. Delivered across v0.260.004 through v0.260.011.
    *   **Files no longer fail to generate.** A CSV built from several actions in one turn could stop with `Generated output schema mismatch at row 2`, because each action returned a different set of columns. The export now pins a union of every column before the run starts and pads the missing cells, so mixed-shape results serialize instead of failing.
    *   **The written answer is no longer replaced by the file card.** CSV replies were suppressed alongside JSON and XML, but only JSON and XML withhold their payload from the response. CSV, DOCX, and PDF now keep the assistant's answer and append the file card beneath it.
    *   **Files contain the retrieved data, not a sample of it.** When the assistant pasted a few example rows above its answer, that excerpt outranked the real result set, producing a 3-row file from a 900-row query. Pasted rows are now used only when they are not an excerpt of the data actually retrieved.
    *   **Discovery calls no longer dilute the dataset.** A turn that lists instances, lists parameters, then retrieves history used to blend all three into one file. Rows are grouped by the action that produced them, and the action holding the substantive dataset wins.
    *   **Follow-up requests reuse data already gathered.** Asking "now make that a CSV" after the data was retrieved in an earlier turn no longer returns an empty result. The export reaches back through stored conversation citations, bounded by the **conversation history limit** in Admin Settings, and reuses the rows already collected instead of re-querying the source.
    *   **Answering a clarifying question now delivers the file.** When the assistant asks which rows and columns to include, replying "yes, all columns" now publishes the file that was originally requested. The clarification turn itself no longer publishes a placeholder file built from the question text.
    *   **The assistant no longer claims it cannot create files.** Every format now states the publication contract to the model, including on the turn that only answers a clarification, so replies stop saying "I cannot create or attach a file in this interface" and then producing one anyway.
    *   **Overlapping result pages no longer double the row count.** Agents frequently re-request a range from the same start time rather than paging forward, which produced a 1,000-row file for a window holding roughly 500 distinct records. Rows an earlier page of the same action already returned are dropped, while genuinely repeated records inside a single response are preserved.
    *   **Partial data is now labeled.** When an action reports that it truncated its own results, the file carries a **Partial** badge and a note explaining that it covers only the rows the action returned. Agents are also instructed to request the remainder starting after the last row they already hold, rather than repeating the original range.
    *   **CSV, DOCX, PDF, JSON, and XML now behave identically.** All five formats resolve rows the same way, reach back to earlier turns, decline to publish on a clarification turn, and report truncation.
    *   (Ref: `functions_generated_file_exports.py`, `functions_tabular_generated_exports.py`, `route_backend_chats.py`, `chat-messages.js`, [Generated Artifact Paging, Truncation, and Guidance Carry-Forward Fix](https://github.com/microsoft/simplechat/blob/main/docs/explanation/fixes/GENERATED_ARTIFACT_PAGING_AND_GUIDANCE_FIX.md), Refs #1071)

*   **Shared Conversation File Approvals Is Reachable From The Sidebar**
    *   The Shared Conversation File Approvals card had no navigation entry, so it could only be found by scrolling the AI Models tab. It is now listed like every other setting.
    *   (Ref: `shared-conversation-file-approvals-section`, navigation map)

*   **Navigation Labels And Order Can No Longer Drift**
    *   The tab strip and the sidebar each maintained the same structure by hand and had diverged: tab order differed between them, and Agents, Custom Pages and Search and Extract each showed a different name depending on which navigation you used.
    *   Both now render from one definition, so a change is made once and appears in both.
    *   (Ref: `admin_settings_nav.py`, `test_admin_settings_nav_map.py`)

*   **Cross-Tab Links In Admin Settings Now Point At The Right Place**
    *   Links that send you from one Admin Settings tab to a related setting used to name a tab button directly, so they broke silently whenever a tab was renamed or reorganised: no tab opened, and the address bar was left pointing at nothing.
    *   Two were already wrong. The **Video File Support** and **Audio File Support** references in Citations sent you to the **Workspaces** tab, but those settings live under **Search and Extract**. Both now open the correct card.
    *   All twelve cross-tab links now name the card they want, and the owning tab is worked out when you click. The destination card is briefly highlighted so it is obvious where you landed.
    *   (Ref: `admin_card_links.js`, `data-admin-link`, `openAdminCard`, `test_admin_card_links.py`)

*   **User Agreement Preview Sanitized At The Sink**
    *   The User Agreement preview rendered Markdown through a guarded reassignment, which reads as unsanitized to static analysis and matched the pattern already corrected for the Home Page Text preview.
    *   Now sanitized inline with `DOMPurify.sanitize(...)` at the point of rendering. `marked` and DOMPurify are both loaded globally, so the availability guards were redundant.
    *   (Ref: User Agreement, `admin_settings.html` preview handler, DOMPurify)

*   **Classification Banner Preview Now Updates As You Type**
    *   The live preview in Admin Settings never updated, because its script sat between template blocks where Jinja discards it, so the code was never rendered to the page.
    *   The preview now responds to banner text, background colour, and text colour changes.
    *   (Ref: Classification Banner, `admin_settings.html` `{% block scripts %}`)

*   **Admin Sidebar Section Map Cleaned Up**
    *   The sidebar's `sectionMap` had grown to 72 entries, but 66 of them mapped a key to itself, which the existing fallback already handled, and one pointed at an element that no longer exists.
    *   Reduced to the 6 entries that are genuine aliases. A new test now fails if a redundant, dangling, or unreferenced entry is reintroduced.
    *   (Ref: `admin_sidebar_nav.js`, `scrollToSection`, `test_admin_settings_sidebar_card_parity.py`)

*   **Home Page Text Preview No Longer Reinterprets Editor Text As HTML**
    *   The Home Page Text preview in Admin Settings assigned the raw editor contents to `innerHTML` when the Markdown editor had not initialized, so text typed into the editor was reinterpreted as HTML. CodeQL flagged this as `js/xss-through-dom` (high severity).
    *   The raw fallback now uses `textContent`, which is what the code intended by "just show raw text", and the Markdown path is sanitized inline with `DOMPurify.sanitize(...)` at the sink. DOMPurify is loaded globally from the local vendored bundle, so no external asset is introduced.
    *   (Ref: Home Page Text, `admin_settings.html` `showPreview`, DOMPurify)

*   **Actions Using the Application Identity Are Now Restricted to Azure Endpoints**
    *   Actions that authenticate with the application's own managed identity can no longer be pointed at an arbitrary endpoint. Blob Storage, Queue Storage, Cosmos, Databricks, and Log Analytics actions now accept only canonical Azure service hostnames for the public, US Government, China, and Germany clouds.
    *   Previously a caller holding only the normal **User** role could save a personal action with an attacker-controlled endpoint and application managed-identity authentication, causing the application to send a token minted for its own workload identity to that destination.
    *   Endpoints are validated when the action is saved and again immediately before the client is built, so actions stored before this release stop working rather than continuing to send credentials.
    *   Log Analytics custom clouds can no longer choose the Microsoft Entra token authority or the OAuth resource used for delegated tokens.
    *   Existing actions using standard Azure hostnames are unaffected. Custom domains, development storage, Azure Stack, and direct private-link hostnames are intentionally rejected, matching the Azure Blob File Sync hardening in v0.250.068.
    *   (Ref: `functions_azure_endpoint_validation.py`, `plugin_health_checker.py`, `blob_storage_plugin.py`, `queue_storage_plugin.py`, `cosmos_query_plugin.py`, `databricks_plugin.py`, `log_analytics_plugin.py`, [Action App-Identity Endpoint Hardening Fix](https://github.com/microsoft/simplechat/blob/main/docs/explanation/fixes/ACTION_APP_IDENTITY_ENDPOINT_HARDENING_FIX.md))

*   **Action Authentication Types Are Now Enforced on the Server**
    *   Each action type's supported authentication methods, declared in its schema definition file, are now enforced when an action is saved or tested. Previously the list was only used to populate the action modal and was never checked by the backend.
    *   This prevents an action type from being configured with an authentication method it was never designed to support, such as requesting application-identity authentication for an OpenAPI or Microsoft Graph action.
    *   The auth-types API now resolves through the same helper the save paths use, so the modal and the backend cannot drift apart.
    *   (Ref: `json_schema_validation.py`, `get_allowed_auth_types_for_plugin_type`, `validate_plugin_auth_type_allowed`, `route_backend_plugins.py`)

*   **New Chat Now Clears The Conversation Documents Side Pane**
    *   Fixed the conversation side drawer keeping the previous conversation's documents after clicking **New chat**. The stale list, the header documents toggle, and its count badge all stayed visible, and the drawer would not close.
    *   Root cause was the New chat reset signal carrying a null conversation id while `window.currentConversationId` still pointed at the conversation being left, so the drawer fell back to the old conversation and re-fetched its documents instead of clearing. The **Contents** pane was unaffected because it resets from a separate chatbox observer.
    *   The **Documents** pane now empties out and the drawer closes, matching **Contents** behavior. Switching between existing conversations is unchanged, and one redundant conversation-metadata request per New chat click is eliminated.
    *   (Ref: `chat-conversation-contents.js`, `refreshConversationDocuments`, `chat:conversation-context-changed`, `updateDrawerTriggers`, Fixes #1298)

*   **Data Management Timeline Steps Now Show Their Own Status**
    *   Fixed completed job steps showing a `running` badge on the Data Management job timeline. Events such as "Cosmos DB export step completed" and "Migration reconciliation completed" now read `completed`.
    *   Root cause was `_set_job_progress` stamping the **job** status onto every step event it recorded, so a finished step inherited `running` because the job itself was still running.
    *   Step status is now decoupled from job status: steps that start report `running`, steps that finish report `completed`, and the job continues running until it genuinely finishes.
    *   Applies to backup, restore, and migration timelines.
    *   (Ref: `functions_data_management.py`, `_set_job_progress`, `_complete_job_step`, `_record_data_management_job_event`)

*   **Backup Inventory No Longer Fails To Load**
    *   Fixed the Backup Inventory panel in Admin Settings → Data Management always returning `503` and showing `0` for available, full, and partial backups.
    *   The global summary used a Cosmos `GROUP BY` with a non-VALUE aggregate (`COUNT(1) AS count`), a combination the `azure-cosmos` Python client does not support. Cosmos rejected the query during plan negotiation with `BadRequest ... GroupBy NonValueAggregate`.
    *   Counts are now computed with bounded, fully supported `SELECT VALUE COUNT(1)` queries, so the panel renders real numbers without loading backup history into memory.
    *   This was not a throttling or indexing problem; the composite index was already aligned. Backup Inventory had been broken since the summary shipped.
    *   (Ref: `functions_data_management.py`, `_get_data_management_backup_global_summary`, `_count_data_management_backups`, `/api/admin/data-management/backups`)

*   **Missing Release Highlight Screenshots Now Display**
    *   The Latest Release pages referenced 24 screenshots that were never present in the documentation site, so every one of them rendered as a broken image.
    *   The images already existed in the application at `application/single_app/static/images/features/`, where the in-app Latest Features gallery reads them. They are now also published with the documentation site, so the release highlight pages show the same screenshots users see in the product.
    *   (Ref: `docs/images/latest-release/`, `docs/_data/latest_release_features.yml`, Latest Release highlight pages)

*   **Broken Documentation Links Repaired**
    *   Fixed the remaining broken internal links on the documentation site. Links that pointed at renamed pages now resolve, and links that target files kept in the repository rather than published on the site, such as the Custom Pages developer guide, the Teams app manifest, and a CI workflow, now open on GitHub instead of returning a missing page.
    *   Removed two references to a ServiceNow multi-action setup guide that was never written.
    *   The documentation site now has zero broken internal links across 31,649 checked links.
    *   (Ref: `ui_tests/check_docs_links.js`, ServiceNow guides, Custom Pages guide, upgrade paths guide)

*   **Documentation Site No Longer Overflows Horizontally on Desktop**
    *   The main content region combined a full-width rule with a sidebar offset, so every desktop viewport scrolled sideways by exactly the sidebar width. This was a long-standing defect on the published site.
    *   (Ref: `.docs-main-content`, `docs/assets/css/main.scss`)

*   **Documentation Section Labels and Page Titles**
    *   Path-scoped Jekyll defaults used collection names as their type and therefore never applied, so nearly every page fell back to a generic "Docs" section and search facets were meaningless. Three scenario index pages also had a comment above their front matter, so it was never parsed and they were titled with their own file path and rendered through an empty layout.
    *   (Ref: `docs/_config.yml` defaults, `docs/explanation/scenarios/`)

*   **Documentation Site Loads No Third-Party Assets**
    *   Removed jQuery, DataTables, marked, DOMPurify, and split.js, none of which the site used, and vendored Bootstrap, Bootstrap Icons, Prism, Lunr, and the site fonts locally with their licenses. The site now makes zero external requests.
    *   (Ref: `docs/assets/vendor/`, `docs/_layouts/default.html`, local browser asset policy)

*   **Admin Latest Features Previous and Archive Preview Restored**
    *   The read-only user-facing preview panel in Admin Settings > Latest Features never rendered, because it sat inside a disabled template block that also holds the legacy hardcoded feature cards from before the tab became data-driven.
    *   The admin route was already computing and passing `support_latest_feature_release_groups_preview` for a panel that could never display, so admins had no way to review previous and archive release cards alongside their sharing status.
    *   Closed the disabled block after the legacy cards so the preview panel renders again, and namespaced its element ids to avoid colliding with the admin release-group cards.
    *   (Ref: `admin_settings.html` Latest Features tab, `support_latest_feature_release_groups_preview`, `route_frontend_admin_settings.py`)

*   **Latest Features Sidebar Card Id Special Case Removed**
    *   The admin sidebar built the previous-release section link through a redundant conditional that produced the same id as the general dynamic expression.
    *   Simplified to the dynamic form so every non-current tier, including the new archive tier, is handled the same way.
    *   (Ref: `_sidebar_nav.html`, admin Latest Features navigation)

*   **Orphaned Latest Features Metadata Tables Removed**
    *   Removed `_SUPPORT_CURRENT_FEATURE_IMAGE_METADATA` and `_SUPPORT_CURRENT_FEATURE_USER_METADATA` along with the two helpers that consumed them. Their keys matched no feature id in any release tier, so both helpers were no-ops, and the `_CURRENT_` naming became misleading after the release tiers shifted.
    *   Verified behavior-neutral: the full serialized catalog output across every accessor and several settings permutations is byte-identical before and after removal.
    *   Added a regression test that generically detects orphaned per-feature metadata tables, so this class of drift is caught in future rather than only these two names.
    *   (Ref: `support_menu_config.py`, `test_support_menu_config_dead_metadata_removal.py`)

*   **Citations and Source Rendering**
    *   Citation parsing preserves line breaks after inline citations, agent document search results render as document sources, retrieved and cited sources remain separated, prior grounded references resolve in follow-up turns, and source-reading intent is no longer misclassified as artifact generation.
    *   (Ref: citation parser, agent document search, grounded source references, generated artifacts)

*   **Shared Conversations and Conversation Forks**
    *   Shared conversations load, render messages, generate AI responses, refresh uploads/task documents, and survive Blueprint security hardening.
    *   Forking from group/public workspace knowledge no longer returns HTTP 500, and structured logging normalization prevents logger errors from replacing HTTP responses.
    *   (Ref: shared conversations, streaming bridge, conversation fork, structured logging)

*   **Workflow Execution Reliability**
    *   File Sync summaries reach task-based workflow models, task instructions scope document search queries, run history preserves per-task document status, zero-retry settings persist, and invalid task document actions are contained.
    *   (Ref: workflow execution, task document status, retries, File Sync summaries)

*   **Backup, Restore, and Data Management Reliability**
    *   Backup ETag normalization, Cosmos pagination, checkpoint batching, and provider status diagnostics improve backup completeness and troubleshooting.
    *   (Ref: Data Management backup, Backup Inventory, Cosmos pagination, checkpoint batching)

*   **Tabular Analyze/Search Durability**
    *   Exhaustive Markdown output includes all rows, line-phrased requests route to the durable pipeline, artifact lifecycle finishes before run completion, stale settings migrations correct disabled preflight flags, and `filter_rows contains` semantics match across foreground and durable paths.
    *   (Ref: tabular analyze, durable preflight, generated artifacts, filter_rows)

*   **Document Extraction and Grounded Search**
    *   Legacy DOC/PPT embedded images are analyzed, image chunks merge into the correct surrounding-text chunk, document picker search matches file names, and multi-word grounded queries support punctuation word breaks.
    *   (Ref: embedded images, chunk placement, document picker search, grounded search)

*   **Cosmos, Redis, and Cache Performance**
    *   Settings container idle RU usage is reduced, no-op read invalidation is skipped, Docker multi-worker startup conflicts recover, DAI Redis TTLs are bounded/refreshed, cache invalidation fails closed on unknown safety state, and cache parity improves for pending shared documents, legacy revisions, and generated-artifact identity.
    *   (Ref: Cosmos RU usage, conversation cache invalidation, DAI Redis cache, public workspace artifacts)

*   **Authentication and Security**
    *   Credential-like field names are no longer logged in clear text, action secret references are scoped to their owning action, Terms of Use redirects happen server-side with HTTPS enforcement, and `/getAToken` without an authorization code redirects to sign-in.
    *   (Ref: credential redaction, action secrets, Terms of Use, authentication redirects)

*   **Model Endpoints and MCP Outbound**
    *   Managed identity cloud values are normalized, vision test connection uses the correct multi-endpoint target, GPT 5.6+ models appear in the multi-modal vision selector, and MCP tool arguments no longer get wrapped in incompatible `kwargs` payloads.
    *   (Ref: model endpoints, vision selector, managed identity, MCP outbound)

*   **Governance, Navigation, and Admin Settings**
    *   Retargeting policies no longer creates duplicates, block-list modals stack correctly, Group Workflows appears in the sidebar, hidden tabs hide sidebar links, logo/favicon save paths no longer 500, and update banner version comparison no longer shows stale releases as newer.
    *   (Ref: governance policies, workspace sidebar, admin settings, update banner)

*   **Retention, Notifications, Logging, and Public Workspace Edge Cases**
    *   Group and collaboration conversations now use correct retention policy/activity timestamps, unauthenticated pages avoid notification polling 401 noise, Application Insights events carry sanitized diagnostic values with standardized tags, custom Databricks-prefixed plugin discovery avoids built-in defaults, and hidden public workspace documents can ground chat searches.
    *   (Ref: retention policy, notification polling, Application Insights logging, plugin discovery, public workspace search)

*   **Citations No Longer Eat the Line Break After Them**
    *   Text that came after an inline document citation was jammed onto the end of the closing parenthesis instead of starting a new paragraph — you would see `(Source: uploading_documents.md, Page: 1)Thank you, Paul.` with no break at all.
    *   The citation parser matched the `[#citation-id]` marker along with the whitespace that followed it, then rebuilt the citation without putting that whitespace back. Because this runs on the raw markdown before it is rendered, a deleted blank line did not just remove a space — it changed how the rest of the block was read, so a paragraph after a cited list item got absorbed into the list item itself.
    *   Spacing is now restored exactly as the model wrote it. Paragraphs, bullets, and numbered lists after a citation render in their intended structure, a citation followed by more text on the same line keeps its space, and back-to-back citations stop colliding. Copied and exported message text keeps its line breaks for the same reason.
    *   The cleanup pass for leftover citation markers had the same flaw in reverse and could swallow the blank line *before* a stray marker. It now only removes horizontal spacing, or the marker's whole line when it sits on one.
    *   (Ref: [#1289](https://github.com/microsoft/simplechat/issues/1289), `chat-citations.js`, `parseCitations()`, chat message rendering)

*   **Figures Now Stay in the Chunk They Came From**
    *   Images extracted from Word and PowerPoint files were appended as extra chunks at the end of the document, with page numbers continuing past the real content. A figure on page 5 of a 15-page document became chunk 16, so a search hit on the figure lost its surrounding text and citations pointed at a page that did not exist.
    *   Embedded images are now merged into the chunk containing the text they appear with. PowerPoint images follow the slide that references them; Word images are placed by their position in reading order; and legacy `.doc` and `.ppt` images, which carry no recoverable position, anchor to the final chunk instead of creating a page beyond the document.
    *   Merging rather than adding a chunk also removes a latent indexing hazard: chunk ids are derived from the page number, so a second chunk sharing a page number would have overwritten the first in the search index.
    *   PDFs were already correct — Content Understanding attributes each figure to its page by span, and Document Intelligence Layout inlines tables and figures into the page markdown. That behavior is unchanged and now covered by a regression test.
    *   **Existing documents keep their current chunks until they are extracted again.** Use *Change Extraction* or re-upload to pick up the new placement.
    *   (Ref: [#1277](https://github.com/microsoft/simplechat/issues/1277), `functions_documents.py`, `functions_office_media.py`, figure chunk association)

*   **Shared Conversation Stream Errors Stay Attached to the Shared Conversation**
    *   Follow-up hardening to the v0.250.224 shared conversation fix. When an AI request in a shared conversation failed, the error the browser received did not say which kind of conversation it belonged to, so the recovery path could have reloaded from the personal endpoint and produced the same "Conversation not found" error that was just fixed.
    *   It could not actually happen yet because of an unrelated guard, but it would have come back the moment anyone added a message id to those errors. All shared stream failures now go through a single serializer that always tags the conversation, and a test walks the code to prove no failure path can skip it.
    *   (Ref: [#1281](https://github.com/microsoft/simplechat/issues/1281), `route_backend_collaboration.py`, `chat-streaming.js`, collaborative AI streaming)

*   **Repaired Route Assertions Across the Test Suite**
    *   The recent Blueprint security hardening renamed how routes are declared, but 82 assertions across 40 test files still checked for the old form. Those tests were failing on the rename before they ever reached the behavior they were written to protect.
    *   This is how the shared conversation streaming bug reached users: the test guarding that exact code path was already red for an unrelated reason. 59 assertions across 32 files were corrected, each verified against a real route first. 14 were deliberately left alone because they point at routes that no longer exist, which is a separate issue worth investigating rather than hiding.
    *   (Ref: [#1281](https://github.com/microsoft/simplechat/issues/1281), `functional_tests/`, Blueprint route registration)

*   **File Sync Now Tells the Workflow What Changed**
    *   File Sync builds a summary of each run — the scan counts plus every new or changed document — but that summary never reached the model in any workflow that uses tasks, which is every workflow the builder creates.
    *   The failure was silent and misleading: the summary *was* written into the conversation, so the transcript showed the changed-document list as though the model had received it. In practice the model saw only the raw task instructions and usually replied that it knew nothing about any documents.
    *   This hit **Monitor File Sync Changes** workflows hardest, along with any workflow using Search or no document action, or with **Use changed documents** turned off. The first task in the sequence now receives the summary, and later tasks get it through the first task's response.
    *   The summary is also bounded now, with a clear truncation notice, so a very large sync cannot crowd out the actual instructions.
    *   (Ref: [#1285](https://github.com/microsoft/simplechat/issues/1285), `functions_workflow_runner.py`, File Sync prompt context)

*   **Document Search Queries Are No Longer Diluted by Injected Context**
    *   A workflow's document search used the entire task prompt as its search query, including the File Sync summary and the previous task's full response. A search for "find the renewal clause" could end up querying 50 lines of file paths.
    *   Search queries now use the task's own instructions. Retrieved content and context still reach the model exactly as before — only the query is scoped.
    *   (Ref: [#1285](https://github.com/microsoft/simplechat/issues/1285), `functions_workflow_runner.py`, workflow document search)

*   **Workflow Document Picker No Longer Hangs on "Loading tags..."**
    *   Choosing a Document action of Search, Analyze, or Compare in the workflow builder revealed the document picker but never loaded it. Tags stayed disabled showing `Loading tags...` forever, the document list stayed empty, and no console error appeared.
    *   The picker was only ever loaded when the modal opened, and that path returned early whenever the action was `No document action` — which is always true for a new workflow. The Document action dropdown's change handler only toggled visibility and never triggered a load.
    *   Changing the Document action or Document Target now loads the picker, and the tags control always resolves to the available tags or `No tags available for this scope`.
    *   (Ref: [#1282](https://github.com/microsoft/simplechat/issues/1282), `workspace_workflows.js`, `chat-documents.js`, workflow document picker)

*   **Workflow Run History No Longer Masks a Failed Document**
    *   When two tasks in the same run process the same document, the later task's status used to overwrite the earlier one's, so a document that failed in one task could be shown as succeeded.
    *   Document run items are now recorded per task, and each item records which task produced it.
    *   (Ref: [#1282](https://github.com/microsoft/simplechat/issues/1282), `functions_workflow_runner.py`, workflow run history)

*   **Resume Failed Items Respects Per-Task Documents**
    *   Resuming failed documents narrowed only the workflow-level document action. Now that tasks own their own documents, it also narrows each task's analyze action to the documents that failed in that task, and group resumes keep every task inside the owning group workspace.
    *   (Ref: [#1282](https://github.com/microsoft/simplechat/issues/1282), `route_backend_workflows.py`, resume failed items)

*   **A Workflow Task Configured for Zero Retries Per Window Stays at Zero**
    *   Saving a multi-task workflow rewrote a stored `Retries Per Window` of `0` to `1` on any task other than the one being edited.
    *   (Ref: [#1282](https://github.com/microsoft/simplechat/issues/1282), `workspace_workflows.js`, retries per window)

*   **An Invalid Task Document Action No Longer Aborts the Whole Run**
    *   If a workflow's document action stopped validating between runs — for example an administrator disabled Analyze or Compare, or lowered the workflow document limit — the run failed outright with no task-level error recorded.
    *   The failure is now contained to that task and follows the workflow's retry and failure-handling settings.
    *   (Ref: [#1282](https://github.com/microsoft/simplechat/issues/1282), `functions_workflow_runner.py`, workflow task error handling)

*   **Shared Conversations Load and Answer Again**
    *   Sharing a personal conversation left it unusable. Every reload or click on the shared conversation raised a "Conversation not found" error, because the chat page was still asking for its messages from the personal conversation endpoint — and a shared conversation is stored separately, under its own id.
    *   Shared conversations now load their messages only from the collaboration endpoint, so the failed request and the error banner are gone.
    *   (Ref: [#1281](https://github.com/microsoft/simplechat/issues/1281), `chat-conversations.js`, `chat-collaboration.js`, shared conversation loading)

*   **AI Responses Work Again in Shared Conversations**
    *   Asking the AI anything in a shared conversation failed immediately with "Stream interrupted: Chat streaming endpoint is unavailable" and no answer was ever generated.
    *   The recent Blueprint security hardening renamed the internal chat streaming endpoint, and the shared-conversation bridge was still looking for the old name. The bridge now resolves the endpoint correctly and logs a diagnostic if it ever cannot, so this fails loudly instead of silently. Group shared conversations are restored by the same fix.
    *   (Ref: [#1281](https://github.com/microsoft/simplechat/issues/1281), `route_backend_collaboration.py`, `app.py`, collaborative AI streaming)

*   **Chat Uploads and Task Documents in Shared Conversations**
    *   Files uploaded inside a shared conversation never showed up in the Analyze and Compare document pickers, and task documents from the previously opened conversation stayed attached after switching to a shared one.
    *   Shared conversations now refresh both when their messages load, matching personal conversation behavior.
    *   (Ref: [#1281](https://github.com/microsoft/simplechat/issues/1281), `chat-collaboration.js`, `chat-messages.js`, Compare and Analyze document pickers)

*   **Images in Legacy `.doc` and `.ppt` Files Are Now Analyzed**
    *   Embedded image analysis previously covered only DOCX and PPTX, because legacy Office files are OLE compound documents rather than zip packages and have no media parts to enumerate.
    *   Pictures and embedded equation previews are now carved out of the legacy container by metafile signature, using the length recorded in the metafile's own header, then rasterized and analyzed like any other embedded image.
    *   Validation is strict — record type, signature position, and a length that fits the remaining bytes — so a coincidental byte sequence is not mistaken for an image. Duplicate images are still collapsed and the per-document cap still applies.
    *   (Ref: [#1277](https://github.com/microsoft/simplechat/issues/1277), `functions_office_media.py`, `functions_documents.py`, legacy Office image extraction)

*   **Diagrams in Word and PowerPoint Files Are Now Analyzed**
    *   Images embedded in Office documents as EMF or WMF metafiles were silently skipped. Word stores pasted diagrams, SmartArt, Visio drawings, and charts in this format, so architecture diagrams — often the most information-dense figures in a document — were never analyzed or indexed.
    *   Metafiles are now rasterized in-process and sent to the configured extraction engine like any other image. Text drawn inside the diagram is recovered as well, so figure labels such as service and resource names become searchable even when the vision engine returns no description.
    *   The renderer is pure Python on top of Pillow, with no system packages or external converters, so it behaves the same in the Linux container as it does locally. Fidelity is intentionally a description aid rather than a pixel-accurate reproduction; unsupported drawing records are skipped rather than failing the document.
    *   (Ref: [#1277](https://github.com/microsoft/simplechat/issues/1277), `functions_emf_render.py`, `functions_office_media.py`, embedded Office image analysis)

*   **Embedded Image Processing Is Now Visible in the Workspace Log**
    *   A document whose images were all skipped looked exactly like a document with no images at all, so there was no way to tell whether embedded image analysis had run.
    *   Processing now reports how many embedded images were found, how many were analyzed, and why any were skipped — too small, duplicates, unsupported format, or over the per-document cap. Progress is reported per image rather than only once at the start.
    *   The found, analyzed, and skipped counts are stored on the document so the outcome can be confirmed after processing completes.
    *   (Ref: [#1277](https://github.com/microsoft/simplechat/issues/1277), `functions_documents.py`, `functions_office_media.py`, embedded image diagnostics)

*   **Data Management History Failure Diagnostics**
    *   Backup Inventory and Job History failures returned a generic 503 telling admins to review application logs, while the logs recorded only the exception class name. The provider status code and message were discarded, making the failure impossible to diagnose.
    *   Failures now log the Cosmos status code and sanitized provider message. Provider text stays in operator logs and is never returned to the browser.
    *   (Ref: [#1275](https://github.com/microsoft/simplechat/issues/1275), `functions_data_management.py`, `route_backend_data_management.py`, Data Management history)

*   **Data Management History Throttle Handling**
    *   Throttled history reads previously produced the same opaque error as a permanent failure.
    *   Cosmos throttling is now detected, retried up to three times with jittered backoff, and reported as temporary busy guidance with a retryable flag instead of a generic error.
    *   (Ref: [#1275](https://github.com/microsoft/simplechat/issues/1275), `functions_data_management.py`, Cosmos history query retry)

*   **Data Management History Index Guidance**
    *   Missing-index detection required the exact phrase "composite index", so equivalent provider wording fell through to the generic error.
    *   Detection now also matches `ORDER BY` failures reported as having no corresponding index, keeping the Cosmos indexing maintenance guidance actionable.
    *   (Ref: [#1275](https://github.com/microsoft/simplechat/issues/1275), `functions_data_management.py`, Cosmos indexing maintenance)

*   **Source Blob Backup ETag Failure**
    *   Fixed every source blob failing backup with "Source blob changed while it was being backed up", which meant user documents, group documents, public documents, and chat attachments were never actually backed up.
    *   Root cause was comparing an ETag from `list_blobs()` (unquoted XML element) against one from `get_blob_properties()` (RFC-quoted HTTP header); the two never matched, so the post-transfer consistency check always failed after the blob had already been downloaded and uploaded.
    *   Both values are now normalized before comparison. The precondition sent to Azure is unchanged, and a genuine mid-transfer source change is still rejected.
    *   (Ref: [#1271](https://github.com/microsoft/simplechat/issues/1271), `functions_data_management.py`, source blob transfer verification)

*   **Source Blob Backup Checkpoint Throughput**
    *   Source blob backups previously wrote one Cosmos checkpoint per blob, capping throughput at roughly six items per second and stretching a single container to over an hour.
    *   Checkpoints are now batched per 100 items or 15 seconds, whichever comes first, while still asserting the job lease on every item.
    *   (Ref: [#1271](https://github.com/microsoft/simplechat/issues/1271), `functions_data_management.py`, source blob checkpointing)

*   **Functional Tests Silently Passing Under pytest**
    *   Backup functional tests written with the try/except and `return False` template were reported as passed by pytest because they returned a value instead of raising.
    *   The backup ETag and Cosmos pagination test files now assert directly, so real failures are reported by both pytest and standalone execution.
    *   (Ref: [#1271](https://github.com/microsoft/simplechat/issues/1271), `test_data_management_backup_source_blob_etag.py`, `test_data_management_backup_cosmos_pagination.py`)

*   **Agent Document Search Now Produces Real Document Citations**
    *   Documents an agent retrieved through the document search action are now recorded as document sources instead of only as an agent tool call. Previously they appeared solely as a raw JSON tool modal, so the documents were missing from the message Sources disclosure, were not clickable, never opened in the enhanced citation viewer, and could never reach the Used documents drawer.
    *   Covers all three document search functions — relevance-ranked search, ordered chunk retrieval, and document summarization — across personal, group, and public workspaces.
    *   Document search results now carry a ready-to-copy citation value, and the action instructs the model to reuse it verbatim. When the answer cites a document, it is correctly separated from the retrieved sources and recorded in the conversation's used documents.
    *   Applies to streaming and non-streaming chat, document actions, cancelled and interrupted streams, and scheduled workflow runs.
    *   Retrieved sources are deliberately not capped, so a search that sources hundreds of chunks records all of them. Chunks retrieved by both the document search toggle and an agent are listed once.
    *   Cancelled and interrupted streams keep the documents the agent had already retrieved, and citation locations no longer relabel a valid page or sequence of `0` as page 1, which affected video chunks keyed by second.
    *   Workspace capability metadata now reports document usage for agent-only document turns, which previously under-reported as unused.
    *   (Ref: [#1239](https://github.com/microsoft/simplechat/issues/1239), `functions_agent_document_citations.py`, `route_backend_chats.py`, `functions_workflow_runner.py`, `document_search_plugin.py`, `AGENT_DOCUMENT_SEARCH_CITATION_FIX.md`)

*   **Credential Field Names Logged in Clear Text**
    *   Fixed a gap where credential values could be written to application logs and Application Insights in clear text. The log redactor matched only a fixed list of key-name substrings, so field names this codebase actually uses for secrets were missed. The most significant were `auth_key`, used by the action connection-test routes for the caller-supplied secret, and the plugin manifest's `auth.key`, which holds connection strings and service principal passwords.
    *   Eighteen credential key names were affected in total, including `pwd`, `key_pair`, `master_key`, `primary_key`, `secondary_key`, `encryption_key`, `signing_key`, `session_key`, and `storage_key`.
    *   Benign configuration keys that merely contain the word "key", such as `key_encoding`, `key_prefix_hints`, and `partition_key_path`, deliberately stay visible so logs keep their diagnostic value.
    *   (Ref: `functions_appinsights.py`, `test_log_credential_key_redaction.py`, `LOG_CREDENTIAL_KEY_REDACTION_FIX.md`)

*   **CosmosClient Import Bindings in Helper Scripts**
    *   Completed the v0.250.047 import-binding cleanup by updating the two remaining scripts that bound `CosmosClient` directly, so patching `azure.cosmos.CosmosClient` is observed consistently. No direct `CosmosClient` imports remain in the repository.
    *   (Ref: `scripts/resolve_multiendpoint_gpt.py`, `deployers/bicep/postconfig.py`)

*   **Privacy Logging Audit Test Restored**
    *   The privacy logging and telemetry audit had been failing since v0.242.072 because it asserted an exact `config.py` version and never reached its assertions. It now asserts a version floor, per the repository's version-assertion guidance, so the audit runs again.
    *   (Ref: `test_privacy_logging_telemetry_audit.py`)

*   **Action Secret References Now Resolved Only Within Their Own Scope**
    *   Action connection tests resolve a stored Key Vault secret reference strictly against the scope of the action being tested, instead of resolving any reference name supplied in the request.
    *   The unscoped resolver has been removed, and the existing MCP tool discovery, Cosmos DB, SQL, Yamcs, and RocksDB test paths now share the same scope-checked resolution used by the new connection tests. A reference that does not match the action's scope is rejected instead of resolved.
    *   Loading a global action for a connection test now requires the Admin role at the shared loader, so every test route inherits the check rather than relying on each route to gate it.
    *   Only affects deployments with Key Vault secret storage enabled. Normal editing is unchanged — testing an existing action still works without retyping stored credentials.
    *   (Ref: [#1267](https://github.com/microsoft/simplechat/issues/1267), `route_backend_plugins.py`, `functions_keyvault.py`, action secret scoping)

*   **Retrieved Sources and Cited References**
    *   Separated complete document/web retrieval results from the exact references used in final assistant responses, while preserving all returned results under **Sources**.
    *   Used documents now follows active cited responses, conversation details marks cited items within the full source inventory, and conversation/message export references exclude retrieved-only sources.
    *   Historical conversations retain their previous fallback without a migration or ordinary read-time history parsing.
    *   (Ref: [#1249](https://github.com/microsoft/simplechat/issues/1249), `functions_citation_tracking.py`, `route_backend_chats.py`, `route_backend_conversation_export.py`, `SOURCE_AND_CITED_REFERENCE_DISTINCTION_FIX.md`)

*   **Agent Summary Step Referenced the Wrong Step Number**
    *   The Summary step's empty-actions message pointed authors at "step 4" to add actions. Actions is step 3 under the new order, and step 4 is now Assigned Knowledge.
    *   (Ref: [#1263](https://github.com/microsoft/simplechat/pull/1263), `_agent_modal.html`, agent modal summary step)

*   **Group Workflows Missing From Sidebar Navigation**
    *   Added the missing Group Workflows link to the left-hand group workspace submenu. Group workflows previously had a working tab but no way to reach it from the sidebar.
    *   (Ref: [#1255](https://github.com/microsoft/simplechat/issues/1255), `_sidebar_nav.html`, group workflows navigation)

*   **Sidebar Links Pointing At Unrendered Workspace Tabs**
    *   Fixed left-hand navigation links whose visibility rules did not match the tabs they opened, so a link could appear for a section that was never rendered.
    *   Personal Agents and Actions links now respect the user agent and plugin permissions, group Agents and Actions links now respect per-user Semantic Kernel and group plugin permissions, and both Identities links now match their tab's File Sync and Semantic Kernel conditions.
    *   (Ref: [#1255](https://github.com/microsoft/simplechat/issues/1255), `_sidebar_nav.html`, `test_workspace_section_order.py`)

*   **Chat Document Search Now Matches File Names**
    *   Fixed the chat grounded-search document picker only matching on a document's title, which made file names completely unsearchable for any document that had extracted title metadata.
    *   Typing any fragment of a file name now surfaces the document, anywhere in the name — searching `200` finds `Quarterly_Report_200_final.pdf`.
    *   Multi-word queries are also supported, with `_`, `-`, and `.` treated as word breaks, so `report 200` matches `Quarterly_Report_200_final.pdf`. The same improvement applies to the scope, tags, prompt, model, and agent selectors.
    *   (Ref: [#1256](https://github.com/microsoft/simplechat/issues/1256), `chat-documents.js`, `chat-searchable-select.js`, chat grounded search, document picker)

*   **Leftover Separator Lines in Filtered Dropdowns**
    *   Fixed filtered dropdowns leaving orphaned workspace separator lines behind — commonly two stacked horizontal rules directly under the "Select All" / "Clear All" row — when a search removed the leading sections.
    *   Divider visibility now follows the section it separates instead of the nearest visible row, and separator lines can no longer be leading, trailing, or stacked. Affects the Document, Scope, and Tags dropdowns, plus the Compare modal document picker.
    *   (Ref: [#1256](https://github.com/microsoft/simplechat/issues/1256), `chat-searchable-select.js`, dropdown filtering, section dividers)

*   **Cosmos Backup Continuation Token Failure**
    *   Fixed Data Management backups silently omitting every Cosmos container that held more than one page of documents, which in most deployments meant personal conversations and personal messages were never backed up.
    *   Affected containers failed with `BadRequest: Invalid Continuation Token` and were dropped from the backup artifact set while the job still reported completion with warnings.
    *   Root cause was rebuilding the cross-partition query for each page and replaying the previous pager's continuation token; the backup now drains a single pager so the SDK's cross-partition execution context is preserved.
    *   (Ref: [#1258](https://github.com/microsoft/simplechat/issues/1258), `functions_data_management.py`, Cosmos backup source paging)

*   **Missing Backup Failure Diagnostics**
    *   Source blob transfer failures previously produced no log output at all, so a run with nearly 20,000 failed blobs left no trace in App Service logs.
    *   Backups now log the first failure for each resource plus a bounded rollup of distinct failure reasons and counts when the resource finishes.
    *   (Ref: [#1258](https://github.com/microsoft/simplechat/issues/1258), `functions_data_management.py`, source blob backup logging)

*   **Application Insights Log Message Text**
    *   Structured log events reached Application Insights as the constant `[SIMPLE_CHAT_LOG_EVENT]` with every string property reduced to a character count, making traces unusable for diagnosis.
    *   Traces now carry the sanitized message text and an allowlist of non-sensitive diagnostic values such as job ID, resource, container, status code, and error. Sensitive keys still collapse to a presence flag and secret redaction is unchanged.
    *   (Ref: [#1258](https://github.com/microsoft/simplechat/issues/1258), `functions_appinsights.py`, log event properties)

*   **Intentional Governance Item Policy Retargeting**
    *   Updated delegated item policy edits so admins can intentionally move an existing policy to a different delegated item without creating a duplicate policy document.
    *   The admin UI keeps the policy ID stable, warns that changing the target will move the policy, and the backend saves the new target while deleting the original source document when original target metadata is supplied.
    *   Also prevents ambiguous policy-ID reuse and keeps feature-policy saves and item-policy deletes out of the retarget conflict path.
    *   (Ref: [#1252](https://github.com/microsoft/simplechat/issues/1252), `functions_governance.py`, `route_backend_governance.py`, `admin_governance.js`)

*   **Governance Item Policy Retarget Protection**
    *   Fixed delegated item policy edits so changing the selected target no longer creates a duplicate policy document for the new item while leaving the old policy behind.
    *   Locks the target controls during existing policy edits and rejects conflicting backend saves when an existing policy ID is reused for a different delegated item.
    *   (Ref: [#1252](https://github.com/microsoft/simplechat/issues/1252), `admin_governance.js`, `route_backend_governance.py`, `functions_governance.py`)

*   **Governance Block List Modal Handoff**
    *   Fixed the delegated item block-list editor opening behind the item policy editor by hiding the parent modal before opening the shared principal editor, then restoring the item editor after the principal editor closes.
    *   Keeps Bootstrap modal focus, backdrop, and scroll handling consistent by ensuring only one governance modal is visible at a time.
    *   (Ref: [#1252](https://github.com/microsoft/simplechat/issues/1252), `admin_governance.js`, `test_admin_governance_tab.py`)

*   **Live User Message Metadata During Streaming**
    *   Made submitted user-message metadata available as soon as storage is acknowledged, without waiting for the assistant response to finish or requiring a page refresh.
    *   Preserved finalized metadata across success, server errors, cancellation, disconnect, recovery, image generation, document actions, and shared-chat streams while keeping in-flight message mutations gated until terminal completion.
    *   (Ref: [#1244](https://github.com/microsoft/simplechat/issues/1244), `functions_chat_stream_events.py`, `chat-streaming.js`, `chat-messages.js`, `USER_MESSAGE_METADATA_STREAMING_FIX.md`)

*   **Exhaustive Row-by-Row Markdown Output**
    *   Fixed line-by-line Markdown analysis reading every source row but publishing only 12 summarized findings because the previous hierarchical lane intentionally bounded findings and notable rows.
    *   Search now produces one exhaustive Markdown artifact containing every source row and every requested answer; Analyze produces a concise Markdown summary plus a separate exhaustive row-by-row Markdown artifact.
    *   Exact-row Markdown uses ordered checkpoints, output-aware batching, consecutive answer-field validation, non-empty answer enforcement, final row-count/source-order checks, and literal Markdown escaping for untrusted content.
    *   (Ref: [#1233](https://github.com/microsoft/simplechat/issues/1233), `functions_tabular_orchestration.py`, `functions_tabular_generated_exports.py`, `route_backend_chats.py`, `TABULAR_EXHAUSTIVE_ROW_MARKDOWN_FIX.md`)

*   **Hidden Public Workspace Document Chat Grounding**
    *   Fixed document chat handoffs from accessible public workspaces that users had hidden from the public directory, so the selected document is now available to grounded search instead of appearing selected while being silently excluded.
    *   Adds the selected workspace to the user's visible Chat workspaces without hiding any existing choices and revalidates the requested public workspace before updating user settings.
    *   (Ref: [#1245](https://github.com/microsoft/simplechat/issues/1245), `route_frontend_chats.py`, `test_public_workspace_hidden_document_chat_visibility.py`, `PUBLIC_WORKSPACE_HIDDEN_DOCUMENT_CHAT_VISIBILITY_FIX.md`)

*   **Tabular Analyze/Search Artifact Lifecycle Completion**
    *   Preserved the selected model endpoint for pure-tabular Analyze background work, preventing non-default model selections from falling back to an unavailable deployment on the default Azure OpenAI resource.
    *   Enforced one artifact contract across Search and Analyze: Search CSV produces CSV; Analyze CSV produces Markdown plus CSV; exhaustive requests without an explicit output format produce Markdown in either mode.
    *   Made artifact publication complete before run completion, repaired previously uploaded-but-hidden Markdown artifacts during status reconciliation, and preserved original generation failures instead of masking them as schema errors.
    *   Removed misleading one-row Analyze CSV handoff artifacts and added sanitized user-visible failure reasons without exposing provider errors or endpoint details.
    *   (Ref: `functions_tabular_orchestration.py`, `functions_workflow_runner.py`, `functions_tabular_generated_exports.py`, `TABULAR_DURABLE_ARTIFACT_LIFECYCLE_FIX.md`)

*   **Tabular Parity Stale Settings Migration**
    *   Fixed the four backend-only tabular durable-preflight parity flags (`tabular_request_planner_mode`, `enable_tabular_search_shared_preflight`, `enable_tabular_analyze_durable_preflight`, `enable_tabular_hierarchical_analysis`) silently staying disabled on any deployment whose Cosmos settings document already stored them from before their defaults were raised to active.
    *   `get_settings()` merges code defaults into the persisted document via `deep_merge_dicts()`, which only fills in missing keys and never overwrites an existing one, so raising a default in code alone never took effect for upgraded-in-place deployments.
    *   Both Analyze and Search durable preflight now self-correct to the active defaults on the next settings load and persist the fix back to Cosmos DB; the `SIMPLECHAT_DISABLE_TABULAR_PARITY_DURABLE_PREFLIGHT` emergency rollback env var continues to work unchanged.
    *   (Ref: `functions_settings.py`, `normalize_tabular_parity_durable_preflight_defaults()`, `TABULAR_PARITY_STALE_SETTINGS_MIGRATION_FIX.md`)

*   **Tabular "Line" Terminology Routing**
    *   Recognized "line"-phrased exhaustive tabular requests (for example, "for each line," "line by line," "one line per") as equivalent to "row"-phrased requests across eight duplicated keyword-detection functions, so they route through the durable generated-output/analysis pipeline instead of the bounded foreground tool-calling path.
    *   Activated `enable_tabular_hierarchical_analysis` by default so narrative (non-export) exhaustive whole-dataset Analyze/Search requests can resolve to the durable `hierarchical_analysis` task type, extending the existing emergency env kill switch to also cover this flag.
    *   (Ref: `functions_tabular_orchestration.py`, `functions_tabular_parity_contract.py`, `route_backend_chats.py`, `functions_document_analysis.py`, `TABULAR_LINE_TERMINOLOGY_ROUTING_FIX.md`)

*   **Top Navigation Public Workspace Lockout**
    *   Fixed a server-rendering failure that could lock users out after they selected top navigation while Public Workspaces was enabled.
    *   Preserved the saved navigation preference and default or customized Public Workspace labels without requiring a Cosmos profile repair.
    *   (Ref: `_top_nav.html`, `test_public_workspace_display_name_settings.py`, `TOP_NAV_PUBLIC_WORKSPACE_LABEL_CRASH_FIX.md`)

*   **Analyze Combined Generated Output Routing**
    *   Treats Analyze requests that ask for row-level answers plus CSV/JSON/XML output as first-class combined durable work, producing both the Markdown analysis artifact and requested structured output artifacts.
    *   Queues planner-approved combined tabular Analyze work before foreground tabular tools run, preventing empty inline tool output from becoming a stream-level 500.
    *   Carries the selected model endpoint context into background generated-output runs so non-default endpoints do not fall back to an Azure OpenAI deployment name lookup.
    *   (Ref: [#1233](https://github.com/microsoft/simplechat/issues/1233), `functions_tabular_orchestration.py`, `functions_workflow_runner.py`, Analyze deliverable contract, combined durable generated output)

*   **Data Management Scheduler Context Guard**
    *   Prevented the background Data Management scheduler from using request-context-copying executor APIs when no Flask request context exists.
    *   Scheduler-submitted jobs now use the existing worker-thread path outside request handling, while route-triggered submissions can still use the configured executor.
    *   (Ref: `functions_data_management.py`, Data Management scheduler, background job submission)

*   **Analyze Artifact Copilot Review Cleanup**
    *   Preserved explicit request order for combined JSON/XML artifact requests when both formats share the same action phrase.
    *   Kept explicit unchanged-copy requests eligible even when source field names include descriptive terms such as risk or status.
    *   Made semantic validation shadow mode fail open on verifier errors and prevented the chat UI from falling back to withheld legacy artifacts when `generated_artifacts` is explicitly empty.
    *   (Ref: PR [#1238](https://github.com/microsoft/simplechat/pull/1238), Copilot review comments, generated artifact ordering, semantic validation shadow mode, plural artifact UI)

*   **Analyze Artifact Advanced Security Cleanup**
    *   Replaced a self-comparison float finite check in the tabular transformation validator with an explicit finite-number check.
    *   Simplified an unnecessary callable wrapper in the Phase 7B production-correctness functional test harness.
    *   (Ref: PR [#1238](https://github.com/microsoft/simplechat/pull/1238), GitHub Advanced Security comments, tabular transformation validation)

*   **Analyze Artifact Output Contract Closure**
    *   Made Analyze generated-output delivery Markdown-first and contract-faithful across durable tabular execution by adding reviewed transformation planning, deterministic server-side rules, bounded semantic verification and repair, and exact Search/Analyze 200-row parity validation.
    *   Hardened artifact-set publication so new staged generated artifacts are not downloadable or promotable until the completed run manifest commits every required member, while preserving legacy generated artifact compatibility.
    *   Restored explicit Word/DOCX current-turn function-result serialization and repaired cumulative lifecycle, scale, route, and UI validation harnesses through 30,000-row bounded finalization and 100,000-row deterministic planning/hardening contracts.
    *   (Ref: [#1233](https://github.com/microsoft/simplechat/issues/1233), PR [#1234](https://github.com/microsoft/simplechat/pull/1234), PR [#1235](https://github.com/microsoft/simplechat/pull/1235), PR [#1236](https://github.com/microsoft/simplechat/pull/1236), Analyze deliverable contract, tabular transformation contract, artifact-set publication lifecycle)

*   **Rendered Admin Tabular Run Controls Coverage**
    *   Replaced source-only coverage with an authenticated browser regression that verifies the Admin Settings controls render, submit, survive reload, and restore their original values.
    *   Guarded shared settings mutation behind an explicit isolated-environment opt-in and limited configured-model testing to routable legacy direct or APIM deployments.
    *   (Ref: [#1201](https://github.com/microsoft/simplechat/issues/1201), `ui_tests/test_admin_tabular_run_controls.py`, Admin Settings tabular run controls)

*   **Large Tabular Run Confirmation Deduplication**
    *   Prevented repeated Send clicks or Enter presses from opening concurrent confirmation waiters and starting the same expensive tabular run more than once.
    *   Restored normal sending after the user continues, narrows scope, dismisses the dialog, or an unexpected confirmation error occurs.
    *   (Ref: Fixes [#1200](https://github.com/microsoft/simplechat/issues/1200), `chat-messages.js`, `test_chat_background_generated_export_status.py`)

*   **Tabular Execution Settings Sanitization**
    *   Prevented normal user-facing settings responses from exposing admin-only hierarchical-analysis, chunk-model deployment, and model-validation retry controls.
    *   Preserved the durable-run confirmation settings required by chat so users continue to receive prompts before very large tabular runs.
    *   (Ref: [#1199](https://github.com/microsoft/simplechat/issues/1199), `sanitize_settings_for_user()`, `TABULAR_GENERATION_BACKEND_SETTING_KEYS`)

*   **Tabular Parity Rollout and Lifecycle Hardening**
    *   Enforced parity canary assignment before durable execution and included authorized source versions in request and unit fingerprints.
    *   Preserved failed and canceled durable outputs as terminal incomplete evidence, including all-canceled per-document Analyze results, and corrected Analyze parity telemetry classification.
    *   Renamed incomplete multi-file and deferred-composition controls as planning-only and exposed that durable fan-out and automatic continuation are unavailable without changing working single-source or per-document behavior.
    *   (Ref: PR [#1219](https://github.com/microsoft/simplechat/pull/1219), [#1031](https://github.com/microsoft/simplechat/issues/1031), [#1055](https://github.com/microsoft/simplechat/issues/1055), [#1058](https://github.com/microsoft/simplechat/issues/1058), `functions_tabular_orchestration.py`, `functions_workflow_runner.py`, `route_backend_chats.py`)

*   **getAToken Missing Authorization Code Redirect**
    *   Redirects direct `/getAToken` browser visits without an OAuth authorization code back to the home sign-in page instead of showing a technical callback error.
    *   Preserves the normal Microsoft Entra authorization-code callback flow and keeps `/getATokenApi` explicit error behavior unchanged for API token callbacks.
    *   (Ref: `/getAToken` OAuth callback, `route_frontend_authentication.py`, `test_getatoken_missing_code_redirect.py`)

*   **Prior Grounded Source Continuity**
    *   Follow-up mixed-source turns can now detect references such as "that XML file," "same template," or "previous spreadsheet" and merge reauthorized prior grounded sources with the current selected sources.
    *   Preserved authorization boundaries by deriving prior sources from `last_grounded_document_refs` and revalidating scope before use.
    *   (Ref: [#1204](https://github.com/microsoft/simplechat/issues/1204), mixed-source source continuity, `route_backend_chats.py`, `test_chat_history_grounded_follow_up_fix.py`)

*   **JSON/XML Source-Only Intent Guardrails**
    *   Prevented source-reading prompts such as "Summarize this XML document" and "Validate this JSON object" from being misclassified as generated artifact requests.
    *   Kept explicit output requests such as "Export as JSON" and "Create an XML file" routed to generated artifact workflows.
    *   (Ref: [#1198](https://github.com/microsoft/simplechat/issues/1198), structured artifact intent detection, `functions_generated_file_exports.py`, `test_generated_json_xml_exports.py`)

*   **Tabular Contains Replay Semantics**
    *   Aligned foreground `filter_rows contains` matching with durable CSV replay by using literal, case-insensitive containment in both paths.
    *   Added regression coverage for regex-shaped values such as `A.*` so previews and generated export replays select the same row cohort.
    *   (Ref: [#1197](https://github.com/microsoft/simplechat/issues/1197), tabular durable replay descriptors, `tabular_processing_plugin.py`, `test_tabular_large_result_pagination.py`)

*   **Outbound MCP Tool Argument Normalization**
    *   Fixed outbound MCP tool calls that could wrap parameters inside a `kwargs` object, preventing standards-compliant MCP servers from seeing required top-level fields such as `type`.
    *   Added schema-aware normalization before MCP argument validation and invocation while preserving tools that explicitly define a real top-level `kwargs` property.
    *   (Ref: [#1163](https://github.com/microsoft/simplechat/issues/1163), MCP `tools/call` arguments, `functions_mcp_operations.py`, `mcp_plugin.py`, `mcp_plugin_factory.py`)

*   **Replayable Exhaustive Tabular Exports**
    *   Generalized version-pinned CSV source descriptors so exhaustive `filter_rows` and `search_rows` requests can replay the complete authorized cohort through the existing durable export runner instead of failing on bounded preview gaps.
    *   Added exhaustive per-row request routing for natural phrases such as "for each row," "every row," and "one row per," while preserving direct deterministic aggregation behavior.
    *   Non-replayable semantics such as normalized entity matching now fail closed with an explicit reason and never publish a partial CSV.
    *   (Ref: [#1031](https://github.com/microsoft/simplechat/issues/1031), tabular source descriptors, durable generated exports, `functions_tabular_csv_query.py`, `tabular_processing_plugin.py`, `route_backend_chats.py`)

*   **Enhanced Citations Startup Storage Degradation**
    *   Prevented Enhanced Citations storage connectivity problems from blocking application startup when Cosmos DB is otherwise available.
    *   Deferred live storage container checks to upload/admin-test paths and added Admin Settings diagnostics for explicit storage validation.
    *   (Ref: [#1155](https://github.com/microsoft/simplechat/issues/1155), PR [#1161](https://github.com/microsoft/simplechat/pull/1161), Enhanced Citations storage startup, `config.py`, `functions_documents.py`, Admin Settings)

*   **Functional Test Version Assertion Resilience**
    *   Added shared functional-test version helpers so tests can assert the app version is at least the feature implementation version instead of exactly equal to an older release.
    *   Migrated brittle exact `config.py` version checks and added a guardrail test to prevent reintroducing exact app-version assertions.
    *   (Ref: functional test version helpers, `test_support/versioning.py`, `test_app_version_assertion_guardrails.py`)

*   **Logging Tag Standardization**
    *   Standardized Python logging prefixes to `[UPPERCASE_WITH_UNDERSCORES]` so Application Insights, debug logs, and operational searches use consistent tag names.
    *   Added a logging tag reference inventory and functional coverage to keep future logging tags normalized and documented.
    *   (Ref: logging tag inventory, `docs/reference/logging-tags.md`, `test_logging_tag_standardization.py`)

*   **Key Vault Reminder PR Security Hardening**
    *   Replaced raw exception text returned from plugin/action Key Vault save paths with stable user-safe messages while preserving server-side logging for diagnostics.
    *   Renamed the external Key Vault reminder telemetry event to avoid security scanner false positives on secret-related terminology while keeping queryable Application Insights dimensions.
    *   (Ref: [#1156](https://github.com/microsoft/simplechat/issues/1156), PR [#1157](https://github.com/microsoft/simplechat/pull/1157), `route_backend_plugins.py`, `functions_appinsights.py`, CodeQL findings)

*   **Reliable Key Vault Secret Rotation**
    *   Fixed action secret save behavior so replacing a Key Vault-backed secret with a new literal value writes a new Key Vault version for global, group, and personal actions.
    *   `Stored_In_KeyVault` placeholders now only preserve validated existing references; placeholder-only saves without an existing secret are rejected instead of creating dead references.
    *   Key Vault write failures now surface as errors instead of falling back to raw secret persistence.
    *   (Ref: [#1156](https://github.com/microsoft/simplechat/issues/1156), `functions_keyvault.py`, action save helpers, Key Vault secret reference validation)

*   **Duplicate Chat Stream JSON Import Cleanup**
    *   Removed the redundant local `json` import from the chat streaming route while keeping the existing module-level import, clearing the PR #1145 CodeQL duplicate-module-import notice without changing streaming behavior.
    *   Updated the PR 1145 remediation plan with the implementation version and validation results.
    *   (Ref: [#1145](https://github.com/microsoft/simplechat/pull/1145), `route_backend_chats.py`, CodeQL alert 30)

*   **Semantic Kernel Return Contract Cleanup**
    *   Made the nested chat Semantic Kernel invocation helper return `None` explicitly when an async generator completes without yielding, clearing the PR #1145 CodeQL mixed explicit/implicit return alert without changing runtime behavior.
    *   Added focused functional coverage for direct values, coroutine results, yielded async-generator values, and empty async generators.
    *   (Ref: [#1145](https://github.com/microsoft/simplechat/pull/1145), `route_backend_chats.py`, `test_chat_semantic_kernel_return_contract.py`)

*   **Token Usage Aggregation Fixture Cleanup**
    *   Removed duplicate mocked helper keys from the document action token usage aggregation functional test so the fixture intent is explicit and CodeQL no longer reports overwritten dictionary entries.
    *   Kept comparison coverage focused on cross-format compare behavior while preserving aggregate token usage assertions for analysis, comparison, workflow assistant persistence, and chat persistence markers.
    *   (Ref: [#1145](https://github.com/microsoft/simplechat/pull/1145), `test_document_action_token_usage_aggregation.py`, token usage aggregation fixtures)

*   **Foundry Citation Thought Detail Cleanup**
    *   Fixed a CodeQL finding where Foundry citation thoughts iterated citations without using the citation value, causing duplicate generic thought messages.
    *   Foundry citation thoughts now include safe citation-specific labels when available while avoiding raw payloads, URL query strings, userinfo, and long unbounded text.
    *   (Ref: [#1145](https://github.com/microsoft/simplechat/pull/1145), `route_backend_chats.py`, `test_foundry_citation_thoughts.py`)

*   **Data Management Restore Route Registration**
    *   Fixed application startup failure caused by duplicate Data Management restore review route and endpoint registrations.
    *   Preserved the authorization-aware restore review workflow and added regression coverage requiring unique Blueprint endpoint names.
    *   (Ref: `route_backend_data_management.py`, `test_data_management_security_patterns.py`, `DATA_MANAGEMENT_RESTORE_ROUTE_ENDPOINT_COLLISION_FIX.md`)

*   **Mixed Source Manifest Storage Locator Preservation**
    *   Preserved explicit blob storage locators for authorized non-chat mixed-source manifest entries when archived-revision document metadata already contains a resolved container and blob path.
    *   Updated focused mixed-source Analyze and conversation-continuity tests for the current rollout/version contract.
    *   (Ref: [#1055](https://github.com/microsoft/simplechat/issues/1055), [#1056](https://github.com/microsoft/simplechat/issues/1056), mixed-source manifests, `functions_mixed_source_orchestration.py`, `test_mixed_source_manifest_contracts.py`)

*   **Retry and Edit Streaming Parity**
    *   Retry and edit chat flows now use the same full SSE streaming path as first-send chat, restoring live token updates, streamed thoughts, stop controls, and recovery behavior.
    *   The stream path reuses the retry/edit user message and thread metadata created by the preparation endpoints, preserving carousel attempt history without duplicating user messages.
    *   (Ref: Fixes [#963](https://github.com/microsoft/simplechat/issues/963), `route_backend_chats.py`, `chat-retry.js`, `chat-edit.js`, `test_chat_retry_edit_streaming_parity.py`)

*   **Retention Coverage Across Group and Collaborative Conversations**
    *   Group-scoped private conversations now follow their primary group's retention policy instead of the creator's personal policy.
    *   Personal and group collaborative conversations now use their correct governing policy and activity timestamp, while linked conversion sources are cleaned once without duplicate counting.
    *   Collaboration cleanup now covers messages, per-user state, linked sources, blob-backed files, thoughts, activity logs, and conversation caches; new groups also persist explicit default retention values.
    *   (Ref: Closes [#1054](https://github.com/microsoft/simplechat/issues/1054), `functions_retention_policy.py`, `functions_collaboration.py`, `functions_group.py`, `RETENTION_POLICY_CONVERSATION_SCOPE_COVERAGE_FIX.md`)

*   **Custom Databricks-Prefixed Action Discovery**
    *   Fixed action type discovery so custom plugin types such as `databricks_table_dscmo` no longer inherit the built-in Databricks discovery defaults.
    *   Custom Databricks-prefixed plugin types now stay on the standard plugin configuration path and visual treatment unless their type is exactly `databricks` or `databricks_table`.
    *   Added a regression test that scaffolds a temporary fake custom Databricks-prefixed plugin, schema, and definition file to validate discovery and settings merge behavior.
    *   (Ref: [#1124](https://github.com/microsoft/simplechat/issues/1124), `functions_databricks_operations.py`, `route_backend_plugins.py`, `view-utils.js`, `test_plugin_type_discovery_custom_databricks.py`)

*   **Conversation Fork Workspace Context and HTTP 500 Fix**
    *   Fixed conversation forks returning HTTP 500 when an owned single-user conversation used group or public workspace knowledge.
    *   Forking now revalidates current workspace access, preserves the authorized context and chat type, and returns controlled conflicts when access is stale or unavailable.
    *   Corrected fork-specific structured logging so validation, conflict, cleanup, and cache errors retain their intended response behavior.
    *   (Ref: [#1025](https://github.com/microsoft/simplechat/issues/1025), `functions_simplechat_operations.py`, `route_backend_conversations.py`, `chat-messages.js`, `CONVERSATION_FORK_HTTP_500_FIX.md`)

*   **Application-Wide Log Event Contract Guard**
    *   Fixed conversation fork conflict and recovery logging that used unsupported metadata keywords, preventing logger errors from replacing intended HTTP responses such as eligibility conflicts with HTTP 500.
    *   Standardized structured metadata on `extra=` and added an application-wide call-signature check plus route regression coverage for the HTTP 409 conflict path.
    *   (Ref: [#1112](https://github.com/microsoft/simplechat/issues/1112), `functions_simplechat_operations.py`, `route_backend_conversations.py`, `test_log_event_call_contract.py`)

*   **MCP PR CodeQL Cleanup**
    *   Resolved CodeQL findings from the MCP pull request by replacing exception text returned to clients with stable public messages, tightening inbound MCP correlation IDs, and removing raw query text from search/cache logs.
    *   Cleaned up MCP catalog imports, test stubs, and JavaScript defaults that produced CodeQL note-level findings.
    *   (Ref: [#1013](https://github.com/microsoft/simplechat/issues/1013), CodeQL scan, MCP PR readiness, `functions_appinsights.py`, `route_inbound_mcp.py`, `route_backend_plugins.py`)

*   **MCP Enterprise Hardening**
    *   Added inbound MCP request correlation, bounded payloads, Cosmos-backed tool throttles, clear JSON-RPC tool error transport, and OAuth/PRM discovery compatibility for MCP clients.
    *   Added outbound MCP discovery/factory telemetry with safe destination metadata and redaction to make connector failures easier to diagnose.
    *   (Ref: [#1015](https://github.com/microsoft/simplechat/issues/1015), [#1017](https://github.com/microsoft/simplechat/issues/1017), [#1020](https://github.com/microsoft/simplechat/issues/1020), MCP observability and enterprise readiness)

*   **Selected Public Workspace Prompt Migration**
    *   Selected public-workspace Data Management migrations now copy current prompts owned through `public_id` while retaining compatibility with legacy `public_workspace_id` records.
    *   Prompts outside the selected workspaces remain excluded, transitional records migrate once, and copied prompt artifact counts are accurate. All-workspaces migration behavior is unchanged.
    *   (Ref: [#1033](https://github.com/microsoft/simplechat/issues/1033), `functions_data_management.py`, `test_data_management_public_prompt_migration.py`)

*   **Azure Blob Container SAS Support and Credential Guidance**
    *   Added support for storage connection strings, full container SAS URLs, and standalone SAS tokens. Pasted SAS URLs derive the canonical account, selected container, and default source name without persisting the token in connection metadata.
    *   Validates required Read and List permissions, HTTPS-only protocol, account-SAS Blob resource scope, start time, and expiry. Extra permissions and broader account credentials remain usable but produce least-privilege warnings.
    *   Shows non-secret SAS scope, named permissions, exact expiry, days remaining, stored-policy status, IP restrictions, and warnings in connection tests and source rows.
    *   Supports saving Blob credentials with or without Azure Key Vault; Key Vault is used when enabled and existing File Sync credential persistence is used otherwise.
    *   (Ref: [#1027](https://github.com/microsoft/simplechat/issues/1027), `functions_file_sync.py`, `workspace-file-sync.js`, `AZURE_BLOB_CONTAINER_SAS_SUPPORT_FIX.md`)

*   **Azure Blob File Sync Endpoint and Error Hardening**
    *   Restricted Azure Blob File Sync URLs and connection strings to validated HTTPS Azure Blob endpoints, blocking arbitrary, internal, development-storage, and credential-bearing endpoint forms before SDK requests are created.
    *   Replaced raw File Sync route, run-history, activity, and item exception text with fixed client-safe messages while retaining detailed sanitized diagnostics in server logs.
    *   (Ref: [#1027](https://github.com/microsoft/simplechat/issues/1027), PR [#1088](https://github.com/microsoft/simplechat/pull/1088) security review, `functions_file_sync.py`, `route_backend_file_sync.py`)

*   **GPT 5.6+ Multi-Modal Vision Model Selection**
    *   Enabled GPT 5.6 Luna, Sol, Terra, and later supported GPT deployments to appear in the Multi-Modal Vision Analysis selector across Azure OpenAI and Foundry endpoints.
    *   Model detection now evaluates model, display, and deployment names with normalized separators while preserving disabled-model and unsupported-family filtering.
    *   (Ref: [#1086](https://github.com/microsoft/simplechat/issues/1086), `admin_settings.js`, `test_admin_multimodal_vision_model_options.py`)

*   **Repeatable AI Workflow Task Sequences**
    *   Personal and group workflows can now run with only instructions and a selected model or agent; workspace documents, File Sync, URL access, schedules, and completion alerts remain optional.
    *   Workflows support ordered instruction tasks that share the selected runner and receive bounded prior-task output as context.
    *   Added per-task retries and stop-or-continue error handling, with task outcomes recorded in run history and workflow activity.
    *   Existing document Search, Analyze, and Compare behavior remains available as optional input for the first task, while existing workflows without task sequences retain their prior execution path.
    *   (Ref: [#1082](https://github.com/microsoft/simplechat/issues/1082), `functions_personal_workflows.py`, `functions_group_workflows.py`, `functions_workflow_runner.py`)

*   **Cosmos Container Startup Conflict Recovery**
    *   Fixed a local Docker startup failure where multiple gunicorn workers could race while creating first-run Cosmos containers, causing a `NotFound` followed by a `Conflict` during app import.
    *   Container initialization now re-reads and returns the existing container when another worker creates it first, preserving normal startup behavior for already-provisioned environments.
    *   (Ref: `config.py`, `test_cosmos_container_conflict_recovery.py`, `COSMOS_CONTAINER_STARTUP_CONFLICT_FIX.md`)

*   **Terms of Use Redirect Hardening**
    *   Replaced wildcard config imports in the Terms of Use route with explicit Flask imports.
    *   Moved post-acceptance return paths from hidden form values to server-side session storage, keeping user-controlled return targets local-only.
    *   Restricted admin-configured external decline redirects to HTTPS URLs without embedded credentials while preserving local-path redirects.
    *   (Ref: [#504](https://github.com/microsoft/simplechat/issues/504), `route_frontend_terms_of_use.py`, `functions_terms_of_use.py`, `terms_of_use.html`)

*   **Control Center Left Nav Endpoint Fix**
    *   Fixed an issue where admins could open Control Center while the left navigation Control Center section stayed hidden when ControlCenterAdmin enforcement was disabled.
    *   Updated the sidebar endpoint check to use the blueprint-qualified `frontend_control_center.control_center` route and added regression coverage for the regular Admin fallback.
    *   (Ref: [#1009](https://github.com/microsoft/simplechat/issues/1009), `_sidebar_nav.html`, `test_control_center_left_nav_endpoint.py`)

*   **Cosmos Editor Page Size Enforcement**
    *   Empty Cosmos editor browse mode now respects the selected page size up to the 100-document cap instead of always requesting 100 items.
    *   This keeps small page-size selections useful for compact validation and targeted inspection.
    *   (Ref: [#1006](https://github.com/microsoft/simplechat/issues/1006), Cosmos DB JSON Editor, `functions_data_management.py`)

*   **CosmosClient Import Binding CodeQL Cleanup**
    *   Replaced direct `CosmosClient` imports with module-qualified `azure_cosmos.CosmosClient` lookups so tests and diagnostics that patch `azure.cosmos.CosmosClient` are observed consistently.
    *   Updated the Cosmos query plugin functional test to patch the module-qualified SDK client and avoid live Cosmos connections during app-module imports.
    *   (Ref: `config.py`, `functions_data_management.py`, `route_backend_plugins.py`, `cosmos_query_plugin.py`, `test_cosmos_query_plugin.py`)

*   **Conversation Cache Invalidation Authorization**
    *   Route-level message mutation cache invalidation now loads personal conversations through the existing ownership authorization helper instead of directly reading a request-derived conversation id.
    *   Updated PR-readiness functional test fixtures to match the current document access index config imports and avoid live Cosmos connections during notification regression tests.
    *   (Ref: `route_backend_conversations.py`, `test_chat_completion_notifications.py`, DAI functional test fixtures)

*   **iPhone M4A Upload FFmpeg Fallback**
    *   Fixed supported iPhone `.m4a` audio uploads failing before transcription when the app runtime could not resolve a local `ffmpeg` executable.
    *   Public Azure environments can now fall back to Azure Speech fast transcription using the original supported source audio file and content type when local segmentation fails because FFmpeg is missing.
    *   FFmpeg segmentation now targets the first audio stream and emits mono 16 kHz PCM WAV chunks for Speech when FFmpeg is available.
    *   (Ref: [#974](https://github.com/microsoft/simplechat/issues/974), `.m4a` upload processing, Azure Speech fast transcription, `IPHONE_M4A_FFMPEG_FALLBACK_FIX.md`)

*   **Multi-Endpoint Vision Test Connection**
    *   Fixed the Admin Settings Vision Model test button so multi-endpoint models are tested against their configured endpoint instead of always using the legacy GPT endpoint.
    *   Vision model options now preserve endpoint and model metadata for the test call while keeping the saved deployment-name value compatible with existing settings.
    *   Removed duplicate backend Vision test connection logic and preserved GPT-5/o-series token handling for Vision test requests.
    *   (Ref: Vision Model test, multi-endpoint model endpoints, `admin_settings.js`, `admin_settings.html`, `route_backend_settings.py`, `MULTI_ENDPOINT_VISION_TEST_CONNECTION_FIX.md`)

*   **Malicious PR Security Review Workflow**
    *   Added a static malicious-change review workflow for pull requests into `Development`, with manual dispatch options for custom review ranges and full-file scans.
    *   Added a reusable security review prompt and focused functional coverage for dependency pinning policy, hidden Unicode detection, suspicious egress markers, and workflow wiring.
    *   (Ref: malicious PR security review, `.github/workflows/malicious-pr-security-review.yml`, `scripts/check_malicious_pr_security_review.py`)

*   **Admin Settings Save 500 Fix**
    *   Fixed an issue where saving Admin Settings returned an HTTP 500 error even though configuration changes were successfully persisted.
    *   The `/admin/settings` POST handler now uses Flask's `current_app` when regenerating custom logo and favicon files after a successful settings update, eliminating the `NameError: name 'app' is not defined` in the post-save path.
    *   (Ref: admin settings save, logo/favicon regeneration, `route_frontend_admin_settings.py`, `ADMIN_SETTINGS_SAVE_500_FIX.md`)

*   **Model Endpoint Management Cloud Normalization**
    *   Fixed model endpoint saves so managed identity and other non-editable cloud paths derive `management_cloud` from `AZURE_ENVIRONMENT` instead of persisting the hidden UI default of `public`.
    *   Added custom-cloud handling for inherited model endpoint authority and Foundry scope defaults while preserving explicit Foundry service-principal cross-cloud selections.
    *   (Ref: model endpoint authentication, `normalize_model_endpoints`, `AZURE_ENVIRONMENT`, `test_model_endpoint_management_cloud_environment.py`)

*   **Admin Settings Update Banner Version Comparison**
    *   Fixed stale cached update-check settings so Admin Settings no longer displays an older release such as `v0.250.001` as available when the running app version is newer.
    *   The render path now recomputes `update_available` from the cached latest version and the current app version before showing the banner.
    *   (Ref: Admin Settings update banner, `compare_versions`, `test_admin_update_banner_version_comparison.py`)

### **(v0.250.001)**

#### New Features

*   **Azure Billing Dynamic Charts**
    *   Updated the Azure Billing action chart path to return SimpleChat `simplechart` Markdown instead of server-rendered matplotlib PNG image payloads.
    *   Preserved existing `plot_chart` / `plot_custom_chart` inputs while returning `chart_payload`, `chart_markdown`, summary, and renderer metadata for interactive chat display.
    *   Added regression coverage for stacked and pie Azure Billing chart output.
    *   (Ref: Azure Billing action, dynamic inline charts, `chart_markdown`, `test_azure_billing_dynamic_charts.py`)

*   **Blueprint Route Security Policies**
    *   Migrated SimpleChat route registration to Blueprint-backed route groups with explicit `before_request` authentication policies.
    *   Added reusable Blueprint auth helpers that compose the existing login, user, admin, and external bearer-token decorators.
    *   Added route policy tests covering Blueprint registration, unauthenticated access expectations, public/external route exceptions, and route-test completeness.
    *   Updated route-authentication prompts, Python route instructions, PR-prep guidance, and CI route validation workflow so future route work must update and run the route policy tests.
    *   Preserved Custom Pages as login-required with page metadata role checks layered inside the dispatcher.
    *   (Ref: Blueprint route policies, route auth guardrails, `functional_tests/route_tests/`, `functions_authentication.py`, `app.py`)

*   **Azure OpenAI Identity Setup Guidance**
    *   Added admin setup guidance explaining which identity is used for legacy Azure OpenAI model discovery and which identity or key is used for runtime GPT, embedding, and image generation calls.
    *   Clarifies that `Fetch Models` uses Azure Resource Manager deployment listing while chat generation, embeddings, file-upload embedding generation, and image generation use the Azure OpenAI data plane.
    *   (Ref: Azure OpenAI setup guide, Admin Settings model guidance, `AZURE_OPENAI_IDENTITY_SETUP_GUIDE.md`)

*   **Model Endpoint Setup Guidance**
    *   Added in-product **Setup Guide** buttons beside global, personal, and group model endpoint actions, plus inline setup guidance inside the shared Model Endpoint modal.
    *   Guidance covers Azure OpenAI, Foundry (classic), and New Foundry provider selection, managed identity and service principal RBAC, and API-key inference-only limitations.
    *   (Ref: model endpoint modal, Admin Settings model endpoints, workspace endpoints, Foundry RBAC setup)

*   **Tabular SK Large Result Pagination**
    *   Added continuation metadata for row-returning tabular Semantic Kernel tools, including `start_row`, `page_size`, `has_more`, and `next_start_row`.
    *   Added safe row payload trimming for oversized tool results, while preserving explicit `return_columns` projection and protected row metadata used for sheet context, matched values, and row-linked document evidence.
    *   Raised tabular computed-results handoff guardrails to 100K characters with warning logs when truncation is still required.
    *   Inspired by and adapted from PR #894 by @vivche.
    *   (Ref: tabular SK pagination, `return_columns`, large-result handoff, `tabular_processing_plugin.py`, `route_backend_chats.py`)

*   **Beta Feature Integration with Development Governance**
    *   Prepared the beta feature branch for integration with the latest `Development` governance, custom pages, and user settings cache changes.
    *   Preserved beta capabilities for agent catalog customization, file sync, workflows, workspace identities, Data Management, and chat/workspace productivity while applying Development governance gates where required.
    *   (Ref: Development merge resolution, governance integration, PR readiness)

*   **User Settings Cache Optimization**
    *   Added request-scoped memoization for full user settings reads and a lightweight user UI settings cache that works with Redis-enabled and no-Redis deployments.
    *   Shared page scripts now reuse injected UI preferences for dark mode and navigation layout before falling back to the full user settings API.
    *   (Ref: user settings cache, user UI settings cache, `functions_settings.py`, `app_settings_cache.py`, `dark-mode.js`, `sidebar.js`)

*   **Custom Pages**
    *   Added administrator-managed custom pages with static HTML/CSS/JS assets, optional Python-backed page extensions, and authenticated host routes for publishing internal experiences inside SimpleChat.
    *   Added Admin Settings controls, navigation wiring, example page templates, documentation, and functional coverage for disabled-by-default fail-closed behavior.
    *   (Ref: custom pages, Admin Settings Custom Pages tab, `route_custom_pages.py`, `functions_custom_pages.py`)

*   **Governance Controls for Endpoints, Agents, and Actions**
    *   Added in-app governance policies that let administrators control access to personal, group, and global endpoints, agents, and actions.
    *   Added feature-level policies, delegated item policies, review workflows, backend enforcement, and Admin Settings UI for managing governance allowlists.
    *   (Ref: governance policies, delegated item policies, Admin Settings Governance tab)

*   **Governance and App Settings Cache Versioning**
    *   Added cache-version coordination so settings and governance policy changes can invalidate stale worker process caches across Redis-enabled and non-Redis deployments.
    *   Keeps hot-path settings and governance checks fast while reducing stale reads after admin changes.
    *   (Ref: app settings cache, governance cache versioning)

*   **Pull Request Preparation Prompt**
    *   Added a reusable Copilot prompt for preparing SimpleChat branches for pull requests into `Development`.
    *   The workflow verifies branch freshness against `Development`, runs repo-aligned validation checks, updates release notes when needed, and gates push or PR creation behind explicit user confirmation.
    *   Optional merge or rebase from `Development` is supported only when requested, with conflicts resolved interactively by the agent after explaining each side of the conflict.
    *   (Ref: `.github/prompts/prepare-for-pull-request.prompt.md`, PR readiness workflow, Development branch validation)

*   **Tableau Action**
    *   Added a first-class, read-only Tableau action powered by `tableauserverclient` for discovering Tableau Server and Tableau Cloud projects, workbooks, views, datasources, and workbook details.
    *   Added a dedicated Tableau action configuration workflow with server/site fields, PAT and username/password authentication, reusable workspace identity support, discovery limits, schemas, health validation, and Semantic Kernel loader integration.
    *   (Ref: `tableau_plugin.py`, `tableau_plugin_factory.py`, `functions_tableau_operations.py`, `plugin_modal_stepper.js`, `TABLEAU_ACTION.md`)

*   **Snowflake Action**
    *   Added a first-class Snowflake action type for querying Snowflake data warehouses through the Snowflake Python Connector, focused on read-only data retrieval for agent analysis, charts, generated documents, and exports.
    *   Added tailored action configuration for account, warehouse, default database/schema, role, password/key-pair/OAuth authentication, reusable workspace identities, and query execution limits.
    *   Added read-only SQL enforcement, automatic result limiting, structured column/row responses, Semantic Kernel loader integration, Key Vault secret handling, governance labels, schemas, feature documentation, and functional coverage.
    *   Uses `snowflake-connector-python[pandas]==3.18.0` so the local Python 3.13 development environment can install from wheels without requiring native C++ build tooling.
    *   (Ref: `SnowflakePlugin`, `SnowflakePluginFactory`, Snowflake action modal, `SNOWFLAKE_ACTION.md`)

*   **Workflow Per-Document Analysis and Generated Office Exports**
    *   Added a workflow Analyze mode that runs the same prompt against each selected document separately, then combines the per-document replies, coverage, citations, generated artifacts, and alert targets into the workflow result.
    *   Added SimpleChat action tools for generated Word documents and PowerPoint presentations, with group workflow uploads defaulting to the current group workspace while preserving existing group access checks.
    *   (Ref: `functions_document_actions.py`, `functions_workflow_runner.py`, `functions_simplechat_operations.py`, `simplechat_plugin.py`, `WORKFLOW_PER_DOCUMENT_ANALYSIS_AND_EXPORTS.md`)

*   **Group Workflows**
    *   Added group-scoped workflows with dedicated Cosmos containers for workflow definitions, run history, and per-document run items.
    *   Group workflow APIs now support create, edit, delete, run, history, resume-failed, agent selection, File Sync sources, and activity streaming while revalidating group membership and assignment gating.
    *   Added Admin Settings controls for enabling group workflows, requiring group assignment, managing assigned groups, and applying the existing owner-only management policy to group workflows.
    *   Added a Group Workflows tab to group workspaces and updated the shared workflow UI/activity page to support personal and group workflow scopes.
    *   (Ref: `functions_group_workflows.py`, `route_backend_workflows.py`, `functions_workflow_runner.py`, `group_workspaces.html`, `workspace_workflows.js`, `GROUP_WORKFLOWS.md`)

*   **Voice-Assisted Form Inputs and Agent Instruction Drafting**
    *   Added speech-to-text microphone controls to supported agent, group, public workspace, document metadata, and tag-name fields when speech input is enabled.
    *   Added an agent Instruction Brief field and Draft Instructions action that sends typed or dictated context to the configured GPT/APIM model, then inserts editable Markdown instructions before save.
    *   Dictated tag names are normalized to lowercase safe tag values, and dictated document keywords are normalized to comma-separated values.
    *   (Ref: `form-voice-input.js`, `agent_modal_stepper.js`, `/api/agents/draft-instructions`, `VOICE_ASSISTED_FORM_INPUTS.md`)

*   **Microsoft Graph Send Mail Action**
    *   Microsoft Graph actions can now create manual drafts, prepare delayed-delivery drafts from 5 to 600 seconds, or send mail automatically from the signed-in user's mailbox.
    *   Added plugin configuration for default delivery mode and delay seconds, with runtime validation and Graph scopes for draft creation, delayed draft submission, and immediate send flows.
    *   (Ref: Microsoft Graph action, `MSGraphPlugin.send_mail`, `plugin_modal_stepper.js`, `MSGRAPH_SEND_MAIL_ACTION.md`)

*   **Workspace-Backed Chat Upload Replacement**
    *   Eligible chat uploads now use the personal workspace document as the source of truth instead of also running the legacy chat-local extraction and chat blob storage path.
    *   Chat creates a lightweight workspace-backed file message with processing progress and automatically includes ready linked workspace documents in regular and streaming chat search context for enhanced citations.
    *   Fixed the chat handoff queue helper to use the configured Flask executor extension, preventing orphaned personal workspace rows from remaining at queued 0% when background processing was not submitted.
    *   (Ref: `route_frontend_chats.py`, `route_backend_chats.py`, `functions_documents.py`, `CHAT_UPLOAD_PERSONAL_WORKSPACE_HANDOFF.md`)

*   **Chat Upload Personal Workspace Handoff**
    *   Eligible chat uploads now queue a personal workspace document while preserving the existing chat attachment/image message behavior and fallback flow.
    *   Chat-uploaded workspace documents receive the `conversations` tag plus the conversation ID tag, store explicit source metadata, and surface processing progress in the chat message with the same document status fields used by workspace uploads.
    *   Workspace metadata and delete flows now show when a document is linked to a conversation.
    *   (Ref: `route_frontend_chats.py`, `functions_documents.py`, `workspace-documents.js`, `chat-messages.js`, `CHAT_UPLOAD_PERSONAL_WORKSPACE_HANDOFF.md`)

*   **Chat Upload Personal Workspace Handoff Design**
    *   Added a proposed implementation plan for routing eligible chat file uploads into the user's personal workspace while preserving the existing chat attachment experience and fallback flow.
    *   Documented the recommended metadata, conversation tags, delete lifecycle, search/analyze/compare implications, security checks, failure modes, testing plan, and staged rollout for the handoff.
    *   (Ref: `CHAT_UPLOAD_PERSONAL_WORKSPACE_HANDOFF.md`, chat uploads, personal workspace documents, conversation-linked document lifecycle)

*   **Document Intelligence Auto Mode and PDF Reprocessing**
    *   Added **Auto** extraction for PDFs and images so admins can sample the first PDF pages with Layout and let SimpleChat finish with Read or Layout based on detected tables or selection marks.
    *   Expanded Search & Extract guidance with a Read/Layout/Auto help modal, Auto sample-page control, and clearer Layout benefit/cost copy including the 6X increase for every 1000 pages.
    *   Added Read/Layout extraction badges plus single-document and bulk PDF reprocess actions in personal, group, and public workspaces. New PDF/image uploads preserve their source blob so PDFs can be reprocessed later when available.
    *   (Ref: `DOCUMENT_INTELLIGENCE_PDF_IMAGE_EXTRACTION_MODE.md`, `functions_documents.py`, Admin Settings Search & Extract, workspace document actions)

*   **Cosmos Native Autoscale Conversion**
    *   Added global and per-container policy controls that let admins convert dedicated manual Cosmos throughput to native Cosmos autoscale.
    *   Added manual Convert actions for database and container throughput so admins can move eligible manual throughput to autoscale from the Admin Settings Scale tab.
    *   Background throughput automation can now prioritize eligible manual-to-autoscale conversions before utilization-based RU scale decisions, while preserving configured min and max guardrails.
    *   (Ref: `functions_cosmos_throughput.py`, Admin Settings Scale tab, `COSMOS_NATIVE_AUTOSCALE_CONVERSION.md`)

*   **Document Intelligence PDF and Image Extraction Mode**
    *   Added a Search & Extract admin setting that lets administrators choose Read or Layout extraction for PDF and image uploads.
    *   Read keeps the faster text-extraction path, while Layout captures richer structure such as tables, document layout, and checked or unchecked selection marks with some added parsing latency.
    *   New PDF and image ingestion records `document_intelligence_extraction_mode` metadata so extracted documents identify whether Read or Layout was used.
    *   (Ref: `admin_settings.html`, `functions_content.py`, `functions_documents.py`, `DOCUMENT_INTELLIGENCE_PDF_IMAGE_EXTRACTION_MODE.md`)

*   **Cosmos Container Policy Enforcement**
    *   Added an Admin Settings option to enforce the global Cosmos throughput automation policy across every dedicated-throughput container.
    *   New containers discovered by Refresh or the background autoscale loop inherit the same global thresholds, intervals, RU step sizes, and guardrails automatically.
    *   Added an Apply Global Policy action in the Containers modal to stage the current global policy onto all currently discovered containers while preserving per-container cooldown timestamps.
    *   (Ref: `functions_cosmos_throughput.py`, `admin_settings.html`, `admin_settings.js`, `COSMOS_CONTAINER_POLICY_ENFORCEMENT.md`)

*   **Cosmos DB Throughput Autoscale Controls**
    *   Added Cosmos DB RU monitoring to the Admin Settings Scale tab, including database throughput status, recent normalized RU utilization, and per-container request-unit visibility.
    *   Added guarded manual Scale Up and Scale Down actions plus optional background automation with separate up/down thresholds, intervals, RU step sizes, and minimum/maximum guardrails.
    *   Added deployment metadata app settings and a custom Cosmos throughput operator role so the app identity can adjust throughput and read metrics without exposing Cosmos data-plane access to agents or user actions.
    *   (Ref: `functions_cosmos_throughput.py`, Admin Settings Scale tab, Cosmos throughput autoscale, `COSMOS_THROUGHPUT_AUTOSCALE.md`)

*   **Workflow File Sync Triggers and Batch Resume**
    *   Added File Sync Before Run controls so workflows can trigger selected personal, group, or public File Sync sources before the workflow prompt executes.
    *   Added Monitor File Sync Changes mode, which checks selected sync sources on the configured interval and only runs the workflow when new or changed files are detected.
    *   Added dynamic Analyze targeting for changed synced documents, per-document workflow run item tracking, and a Resume failed action that reruns failed document items from a previous Analyze workflow run.
    *   (Ref: `functions_personal_workflows.py`, `functions_workflow_runner.py`, `functions_file_sync.py`, `route_backend_workflows.py`, `workspace_workflows.js`, `WORKFLOW_FILE_SYNC_TRIGGERS.md`)

*   **OneDrive File Sync and Source Selection UX**
    *   Added OneDrive as a personal-workspace File Sync source that pulls selected OneDrive files and folders into the existing SimpleChat document processing, chunking, embedding, and Azure AI Search indexing pipeline.
    *   Added provider browsing and selected folder/file controls so users can sync the source root, specific folders, or specific files, with Include subfolders moved into the source-selection and filter workflow.
    *   Added remote change-token handling for provider-native IDs and eTags/cTags before content checksum fallback, improving change detection for cloud-drive files.
    *   (Ref: `functions_file_sync.py`, `route_backend_file_sync.py`, `workspace-file-sync.js`, `ONEDRIVE_FILE_SYNC.md`, `test_file_sync_onedrive_personal.py`)

*   **Global Cloud Drive Connector Identities**
    *   Extended global workspace identities so admins can manage File Sync cloud-drive connector credentials separately from personal user sync choices.
    *   OneDrive File Sync now resolves an admin-managed global File Sync client-secret identity before falling back to legacy app registration configuration, keeping tenant-level Graph credentials out of the personal source setup flow.
    *   Updated Admin Settings and workspace identity UI guidance to clarify that users choose what to sync while admins own tenant cloud-drive connector permissions.
    *   (Ref: `functions_workspace_identities.py`, `functions_file_sync.py`, `workspace-identities.js`, `admin_settings.html`, `WORKSPACE_IDENTITIES.md`)

*   **Azure Files File Sync Source**
    *   Added Azure Files as a first-class File Sync source type so workspaces can sync from Azure Storage file shares using a file service URL, share name, and optional directory path.
    *   Added Azure Files-compatible reusable identity support for managed identity, service principal client secret, and storage connection string authentication while keeping SMB sources on username/password or anonymous authentication.
    *   Updated File Sync source selection, admin source-type visibility controls, synced-document badges, documentation, and regression coverage for the new Azure Files connector.
    *   (Ref: `functions_file_sync.py`, `functions_workspace_identities.py`, `workspace-file-sync.js`, `workspace-identities.js`, `AZURE_FILES_FILE_SYNC.md`, `test_file_sync_azure_files_identity.py`)

*   **Conversation Feed Pagination**
    *   Added a paged conversation feed so chat startup loads pinned conversations, unread conversations, and the first 20 recent conversations instead of pulling every accessible conversation into the browser.
    *   Added load-more and near-bottom scroll loading for both the main conversation list and docked sidebar, with backend-driven title search that is not limited to the currently loaded page.
    *   Hidden conversations are excluded from the default feed and reloaded only when users enable the hidden-conversation toggle.
    *   (Ref: `route_backend_conversations.py`, `functions_conversation_feed.py`, `chat-conversations.js`, `chat-sidebar-conversations.js`, `CONVERSATION_FEED_PAGINATION.md`)

*   **Group File Share Approval Notifications**
    *   Added notifications when personal and group documents are shared, approved, or denied so recipients know when a file needs review and share owners know the outcome.
    *   Group document shares now require approval by the receiving group's Owners, Admins, or Document Managers before the file becomes searchable in that group.
    *   Receiving groups now see Approve or Remove actions for shared files, cannot delete the owner group's document, and cannot view the owner group's shared-recipient list.
    *   (Ref: group document sharing approval, `route_backend_group_documents.py`, `route_backend_documents.py`, `functions_notifications.py`, `group_workspaces.html`, `GROUP_FILE_SHARE_APPROVAL_NOTIFICATIONS.md`)

*   **Stats Time Windows and CSV Exports**
    *   Added 7-day, 30-day, 90-day, and custom date windows to personal profile stats, group stats, and public workspace stats so these pages match the Control Center activity-trends experience.
    *   Added CSV export actions for personal, group, and public stats with selectable metric sections and matching predefined or custom export windows.
    *   Centralized stats window parsing and daily bucket generation for consistent labels, chart ranges, and backend filtering across all three stats surfaces.
    *   (Ref: profile stats, group stats, public workspace stats, `functions_stats_windows.py`, `route_frontend_profile.py`, `route_backend_groups.py`, `route_backend_public_workspaces.py`)

*   **Personal Workflow Access Governance**
    *   Added a dedicated Admin Settings Workflow section so personal workflows can be explicitly enabled or disabled.
    *   Added optional `WorkflowUser` Enterprise App role enforcement for workflow UI access, API routes, manual runs, activity views, and SimpleChat workflow creation operations.
    *   Added `WorkflowUser` app role definitions to Azure CLI and Terraform deployer assets, with deployer version tracking updated.
    *   (Ref: workflow access control, `functions_settings.py`, `route_backend_workflows.py`, `route_frontend_admin_settings.py`, `PERSONAL_WORKFLOWS.md`, `WORKFLOW_ACCESS_CONTROL_FIX.md`)

*   **Azure Commercial Databricks Action**
    *   Added a first-class Databricks action type for Azure Commercial workspaces, using the Databricks SQL Statement Execution API rather than an ODBC driver.
    *   Added action modal configuration for workspace URL, SQL Warehouse ID, catalog/schema defaults, token/service-principal/managed-identity auth, execution limits, and reusable identity selection.
    *   Added read-only SQL enforcement, factory-based Semantic Kernel loading, manifest validation, schemas, feature documentation, and functional/UI coverage.
    *   (Ref: `DatabricksPlugin`, `DatabricksPluginFactory`, Databricks action modal, `DATABRICKS_ACTION_CONFIGURATION.md`)

*   **Model Context Protocol Actions**
    *   Added first-class MCP action support with transport, authentication, timeout, tool allowlist, and cached tool metadata configuration in the shared action modal.
    *   Added server-side MCP tool discovery plus runtime tool invocation through Semantic Kernel's MCP connector, including dynamic tool function registration for agents.
    *   Restricted stdio MCP transport to admin-managed global actions because it launches server-side commands, while remote transports support streamable HTTP, SSE, and WebSocket.
    *   (Ref: MCP actions, Semantic Kernel MCP connector, `functions_mcp_operations.py`, `mcp_plugin.py`, `mcp_plugin_factory.py`, `route_backend_plugins.py`, `plugin_modal_stepper.js`, `MCP_ACTION_CONFIGURATION.md`)

*   **Layered Message Masking**
    *   Added mask-plus and mask-minus controls so users can add multiple selected-text masks to the same chat message.
    *   Full-message masks now layer independently from selected-text masks, allowing users to remove the full-message mask while preserving prior selected ranges.
    *   Extended masking support to collaborative personal and group conversations, including shared event updates and source-message metadata sync.
    *   (Ref: message masking, collaborative conversations, `functions_message_masking.py`, `route_backend_chats.py`, `route_backend_collaboration.py`, `chat-messages.js`, `chat-collaboration.js`)

*   **Workspace and Global Identities**
    *   Promoted reusable identities into first-class personal, group, and public workspace tabs instead of managing them from the File Sync source list.
    *   Added an admin-managed Global Identities tab for credentials shared by global agents, actions/plugins, model endpoints, and future global integrations.
    *   Added a dedicated global identity Cosmos DB container while keeping public workspace identities limited to File Sync usage and excluding File Sync from global identities.
    *   (Ref: workspace identities, global identities, `functions_workspace_identities.py`, `route_backend_workspace_identities.py`, `workspace-identities.js`, `_sidebar_nav.html`)

*   **Visio Ingestion and Citation Previews**
    *   Added native `.vsdx` upload support that parses Visio package XML and indexes each diagram page as a structured searchable chunk.
    *   Enhanced citations now render a lightweight PNG preview for the cited Visio page and keep the original `.vsdx` available for download.
    *   Added functional and UI coverage for Visio parsing, preview rendering, and chat citation modal behavior.
    *   (Ref: Visio ingestion, enhanced citations, `functions_visio.py`, `functions_documents.py`, `route_enhanced_citations.py`, `chat-enhanced-citations.js`, `test_visio_ingestion_preview.py`, `VISIO_INGESTION.md`)

*   **Outlook MSG File Ingestion**
    *   Added support for Outlook `.msg` files so saved email messages can be uploaded into workspaces and participate in document processing, metadata extraction, chunking, search, and chat grounding.
    *   Email files now fit the same workspace knowledge workflow as other supported business documents, helping users bring message-based context into conversations without manually copying mail content.
    *   (Ref: Outlook MSG ingestion, workspace uploads, document processing, `functions_content.py`, `functions_documents.py`)

*   **Assigned Knowledge for Agents**
    *   Added agent-level Assigned Knowledge so agent creators can bind agents to governed workspace sources, documents, and tags.
    *   Chat now resolves the selected agent from trusted server-side records and enforces its assigned search scope for both regular and streaming chat, including personal, group, and public workspace boundaries.
    *   When an Assigned Knowledge agent is selected in chat, document search is forced on and the workspace, document, and tag controls become read-only while displaying the agent's configured knowledge context.
    *   (Ref: Assigned Knowledge, agent modal Knowledge step, chat document search enforcement, `functions_assigned_knowledge.py`, `route_backend_agents.py`, `route_backend_chats.py`, `agent_modal_stepper.js`, `chat-agents.js`, `chat-documents.js`)

*   **Deep Research Distroless JavaScript Rendering Runtime**
    *   Added Playwright Chromium packaging for the existing Azure Linux distroless app image so Deep Research can optionally render JavaScript-heavy source pages without changing the final container base image.
    *   Added a runtime capability check that verifies Chromium launch support and surfaces the status in Admin Settings before admins rely on rendered-page fallback.
    *   Kept Chromium sandboxing enabled by default, added an explicit `SOURCE_REVIEW_CHROMIUM_NO_SANDBOX` escape hatch for reviewed deployments, and capped rendered fetch concurrency with `SOURCE_REVIEW_JS_RENDER_MAX_CONCURRENCY`.
    *   (Ref: Deep Research JavaScript rendering, distroless container runtime, `Dockerfile`, `requirements.txt`, `functions_source_review.py`, `admin_settings.html`)

*   **Source Review Load More Support**
    *   Source Review can now use the optional rendered-page path to click visible Load More, Show More, View More, and related archive controls on source pages before extracting links and evidence.
    *   Load More clicks are bounded by a configurable admin cap, stop early when no new content appears, and can stop when requested date-range evidence is visible for prompts such as past three years.
    *   Existing SSRF, redirect, timeout, page-budget, and content-type protections remain enforced.
    *   (Ref: Source Review Load More, `functions_source_review.py`, `admin_settings.html`, `test_source_review_security.py`)

*   **Source Review Model-Assisted Link Planning**
    *   Deep Source Review can now ask the selected chat model to rank server-extracted child links before additional source pages are fetched, improving general multi-source research without adding question-specific heuristics.
    *   The planner is bounded to already extracted, policy-approved candidate URLs; invented URLs are ignored and deterministic ordering remains the fallback.
    *   Added admin control for enabling model-assisted link planning and functional coverage for candidate validation and planner-driven ordering.
    *   (Ref: Deep Source Review, Source Review link planning, `functions_source_review.py`, `route_backend_chats.py`, `admin_settings.html`, `test_source_review_deep_traversal.py`)

*   **File Sync for Workspace Documents**
    *   Added an optional SMB-based File Sync capability for personal, group, and public workspaces, with scope-specific enablement, allow/block controls, and Redis readiness gating before sync can be enabled.
    *   Sync sources support UNC paths, credentials with optional Azure Key Vault storage, fixed and parent-folder-derived tags, include/exclude filters, file type filters, manual runs, scheduled runs, history, counts, and debug logging.
    *   Synced remote file changes reuse the existing same-name document upload behavior to create document versions, and synced-document deletes now ask whether to delete locally only or ignore the remote path for future runs.
    *   Added Control Center activity-log support for File Sync events and admin warnings for scale and performance considerations.
    *   (Ref: File Sync, SMB sync sources, workspace Sync tab, `functions_file_sync.py`, `route_backend_file_sync.py`, `workspace-file-sync.js`, `test_file_sync_capability.py`, `FILE_SYNC.md`)

*   **Source Review for Web Evidence**
    *   Added an optional chat **Sources** toggle that reviews source pages from pasted URLs and Web Search citations before the final model response is generated.
    *   Deep Source Review can follow a bounded set of relevant links from source indexes while enforcing SSRF protections, redirect/page-size/time limits, robots.txt handling, and prompt-injection isolation for fetched page text.
    *   Added admin controls for Source Review defaults, page budgets, domain/user allowlists and blocklists, optional JavaScript rendering fallback, and audit logging.
    *   (Ref: Source Review, `functions_source_review.py`, `route_backend_chats.py`, `admin_settings.html`, `chats.html`, `test_source_review_security.py`, `SOURCE_REVIEW.md`)

*   **Conversation Charts and Workflow Tabular Reuse**
    *   Added chart creation as a core conversation ability so users can request inline charts directly in chat while agents and workflows can still use assigned chart actions.
    *   Added a reusable tabular analysis import surface for workflow document analysis and comparison, reducing workflow coupling to the chat route while preserving existing chat tabular behavior.
    *   Enabled Semantic Kernel auto tool invocation in the model-only fallback path so core conversation tools can be called when chart requests are routed through the kernel.
    *   (Ref: conversation charts, workflow tabular analysis, `semantic_kernel_loader.py`, `route_backend_chats.py`, `functions_tabular_analysis.py`, `functions_workflow_runner.py`, `test_conversation_chart_and_tabular_reuse.py`)

*   **Generated Markdown Artifact Viewer**
    *   Added a `View MD` action beside `Download MD` on generated Markdown artifact cards so users can inspect rendered Markdown directly in Chats before downloading the file.
    *   Reused the citation modal for the rendered view and improved Markdown citation handling so `.md` and `.markdown` citations display as sanitized rendered Markdown instead of raw source text.
    *   Added UI regression coverage for rendered previews, rendered artifact modal content, and unsafe attribute stripping.
    *   (Ref: generated Markdown artifacts, citation modal Markdown rendering, `chat-messages.js`, `chat-citations.js`, `test_chat_generated_tabular_output_card.py`, `GENERATED_ARTIFACT_MARKDOWN_VIEW.md`)

*   **Tabular Related Document Evidence**
    *   Added generic row-level related-document resolution for workspace tabular analysis, so when a CSV or workbook row explicitly references a supporting non-tabular file, the tabular path can pull excerpts from that document and use them alongside the computed row results.
    *   Related document evidence now flows into both the outer tabular handoff and generated structured exports, which helps responses use supporting file context without treating those files as isolated search-only results.
    *   Added focused regression coverage and versioned feature documentation for the related-document matching, evidence summary, and export prompt wiring.
    *   (Ref: tabular related-document evidence, `route_backend_chats.py`, `functions_search_service.py`, `test_tabular_related_document_evidence.py`, `test_tabular_computed_results_prompt_priority.py`, `test_tabular_generated_output_exports.py`, `TABULAR_RELATED_DOCUMENT_EVIDENCE.md`)

*   **Generated Artifact Workspace Promotion Approval**
    *   Added an `Add to Workspace` action to generated analysis artifact cards in Chats so users can move reusable exports out of the conversation and into workspace documents.
    *   Personal promotions now queue immediately, while group and public promotions create a visible pending workspace file that must be approved before it becomes usable for search and chat.
    *   Group and public workspace document lists now show an `Approve` action for pending generated artifacts, and the requester receives approval workflow notifications as the file moves through review and processing.
    *   (Ref: generated artifact promotion, `route_enhanced_citations.py`, `route_backend_group_documents.py`, `route_backend_public_documents.py`, `chat-messages.js`, `group_workspaces.html`, `public_workspace.js`, `test_generated_artifact_workspace_promotion.py`, `test_chat_generated_tabular_output_card.py`)

*   **Chat Clipboard Paste Uploads**
    *   Added direct clipboard upload support in Chats so users can paste copied images and browser-exposed files straight into the main chat message box instead of opening the file picker first.
    *   The pasted upload flow now reuses the existing chat upload pipeline, including automatic conversation creation, upload consent checks, and backend file processing.
    *   Clipboard files with empty names are normalized before upload so pasted screenshots still reach the existing extension-based processing path.
    *   (Ref: chat paste uploads, `chat-input-actions.js`, `test_chat_clipboard_paste_upload_support.py`, `test_chat_clipboard_paste_upload_workflow.py`, `CHAT_CLIPBOARD_PASTE_UPLOADS.md`)

*   **Staging Branch UI Test CI/CD**
    *   Added a protected GitHub Actions workflow for the `Staging` branch that deploys the Azure Developer CLI staging environment, waits for App Service warm-up, and runs live UI smoke coverage before the environment is considered healthy.
    *   Added a reusable staging bootstrap script for GitHub OIDC app registration, federated credentials, Azure role assignments, GitHub Environment variables, App Service CI authentication settings, and Microsoft Playwright Workspace wiring.
    *   (Ref: `.github/workflows/staging-azd-ui-tests.yml`, `deployers/Initialize-GitHubActionsStaging.ps1`, `docs/explanation/features/v0.241.014/STAGING_UI_CICD.md`, `test_staging_ui_cicd_workflow.py`)

*   **Microsoft Playwright Workspaces Staging Runner**
    *   Added Azure-hosted Playwright Workspace support for staging smoke tests, including Node-based Playwright service execution and matching Python smoke coverage for the staging chat experience.
    *   (Ref: `ui_tests/playwright-workspaces/`, `ui_tests/test_staging_chat_smoke.py`, `PLAYWRIGHT_SERVICE_URL`)

*   **Service Principal Authentication for CI UI Tests**
    *   Added a disabled-by-default `/ci-auth/session` endpoint so staging UI tests can create a Flask session from a fresh Entra access token minted by the GitHub OIDC service principal.
    *   (Ref: `functions_authentication.py`, `route_frontend_authentication.py`, `config.py`, `appRegistrationRoles.json`, `SIMPLECHAT_UI_AUTH_RESOURCE`, `ENABLE_CI_BEARER_SESSION_AUTH`)

*   **Profile Sidebar Toggle Style Preference**
    *   Added a profile navigation preference for large versus compact sidebar hide controls and applied it across full and compact sidebar templates.
    *   (Ref: `profile.html`, `_sidebar_nav.html`, `_sidebar_short_nav.html`, `sidebar.css`, `route_backend_users.py`, `test_profile_sidebar_toggle_style_preference.py`)

#### Bug Fixes

*   **Azure OpenAI Model Discovery Identity Split**
    *   Legacy GPT, embedding, and image `Fetch Models` routes now use the configured app registration/service principal management-plane credential for Azure OpenAI deployment discovery instead of implicitly following runtime data-plane managed identity behavior.
    *   Deployer assets now grant the app registration/service principal `Cognitive Services User` for model discovery while preserving the App Service managed identity `Cognitive Services OpenAI User` role for data-plane inference.
    *   (Ref: `route_backend_models.py`, deployer OpenAI RBAC, `AZURE_OPENAI_MODEL_DISCOVERY_IDENTITY_FIX.md`)

*   **Chat Model Icon Avatars**
    *   Fixed saved model endpoint icons and uploaded model images not appearing on model-only assistant responses in chat.
    *   Model icon metadata now flows through multi-endpoint model resolution, streaming and non-streaming response metadata, and assistant avatar rendering for model-only responses.
    *   Preserved agent avatar priority so agent responses never fall through to the model icon when an agent identity is present.
    *   (Ref: chat assistant avatars, model endpoint icons, `route_backend_chats.py`, `chat-messages.js`)

*   **Tabular SK Python 3.13 Kernel Parameter Compatibility**
    *   Updated public tabular `@kernel_function` parameters to avoid `Annotated[Optional[str], ...]` so Semantic Kernel argument parsing works on both Python 3.12 and Python 3.13.
    *   Added a guardrail test that fails if optional string annotations are reintroduced on public tabular tool parameters.
    *   Preserved current Development model-context routing instead of reintroducing older endpoint-specific route wiring.
    *   Inspired by and adapted from PR #892 by @vivche.
    *   (Ref: Python 3.13, Semantic Kernel tool parsing, tabular SK parameters, `test_tabular_kernel_parameter_annotations.py`)

*   **Python 3.12 CI and XSS Guardrail Fix**
    *   Updated GitHub workflow Python setup from 3.11 to 3.12 to match the supported SimpleChat runtime and prevent valid Python 3.12 f-string syntax from failing CI parse checks.
    *   Reworked changed Admin Settings, group workspace delete modal, and profile hero rendering paths to satisfy the XSS sink guardrail without broad suppressions.
    *   (Ref: Python 3.12 CI, XSS sink validation, Admin Settings bootstrap data, group workspace delete modal, profile hero image)

*   **PR Readiness Guardrail Cleanup**
    *   Fixed pull-request validation blockers by removing trailing whitespace, dropping an unnecessary `|safe` filter from JSON-rendered Admin Settings version data, removing a UTF-8 BOM from the Semantic Kernel loader, and documenting reviewed plugin authorization boundaries for the BAC guardrail.
    *   Keeps the beta branch aligned with SimpleChat PR hygiene, XSS, route, and broken-access-control validation before draft PR creation.
    *   (Ref: PR readiness, `check_xss_sinks.py`, `check_broken_access_control.py`, Semantic Kernel plugins)

*   **Governance Admin Rendering XSS Hardening**
    *   Reworked changed admin governance, model endpoint, agent, and plugin table rendering paths so untrusted names, descriptions, IDs, and labels are populated with DOM APIs and `textContent` instead of interpolated HTML attributes.
    *   Added narrow reviewed XSS guardrail suppressions only for static Bootstrap modal shells that do not interpolate untrusted values.
    *   (Ref: governance admin UI, model endpoint table, plugin table rendering, XSS sink validation)

*   **Group Workflow Assignment Cleanup**
    *   Fixed Admin Settings form bloat caused by malformed nested JSON strings being saved as group workflow assignment IDs.
    *   Group workflow assignment settings now preserve valid group UUIDs, drop invalid payload fragments, and compact the hidden admin form field before save.
    *   (Ref: `functions_settings.py`, `admin_settings.js`, `GROUP_WORKFLOW_ASSIGNMENT_CLEANUP_FIX.md`)

*   **Workflow Activity New-Tab Navigation**
    *   Fixed workflow `Activity` actions so they no longer navigate the current workspace tab after opening the activity view in a new tab.
    *   Blocked pop-ups now show a warning toast instead of replacing the workflow list page.
    *   (Ref: `workspace_workflows.js`, workflow Activity button, `WORKFLOW_ACTIVITY_CURRENT_TAB_NAVIGATION_FIX.md`)

*   **Group Workflow Activity View Gate**
    *   Fixed group workflow activity links so the shared `/workflow-activity` page no longer depends on the personal workflow feature flag when opened with `scope=group`.
    *   Group activity views now use group-specific authorization, including group workspaces enabled, group workflows enabled, group assignment gating, and current group membership validation.
    *   Personal workflow activity links still use the existing personal workflow and WorkflowUser app-role policy.
    *   (Ref: `route_frontend_chats.py`, `workflow-activity.js`, `GROUP_WORKFLOW_ACTIVITY_VIEW_GATE_FIX.md`)

*   **Tabular Inline Chart Handoff**
    *   Fixed tabular analysis chart requests so successful grouped CSV/XLSX results now produce SimpleChat inline chart citations instead of relying on the model to emit supported chart syntax.
    *   Workspace-search and chat-uploaded tabular results now share the same deterministic chart handoff in both streaming and non-streaming responses, preventing unsupported Mermaid chart blocks from appearing when users request charts.
    *   (Ref: `route_backend_chats.py`, `functions_chart_operations.py`, `test_tabular_inline_chart_handoff.py`, `TABULAR_INLINE_CHART_HANDOFF_FIX.md`)

*   **Document Intelligence Upload Normalizer Import**
    *   Fixed Azure Document Intelligence upload processing so the shared extractor resolves the extraction-mode normalizer through the existing settings module import, preventing Read/Layout/Auto uploads from failing with a missing normalizer name while avoiding the startup circular import path.
    *   (Ref: `functions_content.py`, Document Intelligence extraction mode)

*   **Cosmos Native Autoscale Migration Action**
    *   Fixed manual-to-autoscale conversions so manual Cosmos throughput offers call the ARM `migrateToAutoscale` action instead of attempting to write `autoscaleSettings.maxThroughput` directly onto a manual offer.
    *   Preserved the existing `PUT autoscaleSettings.maxThroughput` path for database or container throughput that is already in autoscale mode.
    *   Expanded the least-privilege Cosmos throughput operator role with the `migrateToAutoscale/action` and operation-result read permissions required for native conversion without Cosmos data-plane access.
    *   (Ref: `functions_cosmos_throughput.py`, `setPermissions.bicep`, `COSMOS_NATIVE_AUTOSCALE_MIGRATION_ACTION_FIX.md`)

*   **Cosmos Autoscale Background Cadence**
    *   Updated the Cosmos throughput background scheduler so the check cadence follows the configured Metrics Window instead of a hard-coded five-minute sleep.
    *   Added background-specific autoscale start, completion, and sleep logs so scheduler runs are distinguishable from manual Admin Settings Refresh requests.
    *   Clarified Admin Settings copy that background automation refreshes on the Metrics Window cadence while Scale Up/Down intervals remain cooldowns after scaling.
    *   (Ref: `background_tasks.py`, `functions_cosmos_throughput.py`, Admin Settings Scale tab, `COSMOS_AUTOSCALE_BACKGROUND_CADENCE_FIX.md`)

*   **Cosmos Container Metrics REST Metadata Parsing**
    *   Switched Cosmos throughput metric collection from the Azure Monitor Query SDK response model to the raw Azure Monitor Metrics REST response for this feature, because the SDK returned container-split time series without usable metadata names or values.
    *   Restored per-container RU utilization and request-unit rows by parsing REST `collectionname` and `databasename` metadata from the same metric dimensions shown in Azure Metrics Explorer.
    *   (Ref: `functions_cosmos_throughput.py`, Azure Monitor Metrics REST, Cosmos `CollectionName` dimensions, `COSMOS_CONTAINER_METRICS_REST_METADATA_FIX.md`)

*   **Cosmos Container Autoscale Metric Accuracy and Refresh Performance**
    *   Tightened the Azure Monitor query so container-targeted scaling requests `NormalizedRUConsumption` split by the configured database and `CollectionName`, matching the per-container view available in the Azure portal.
    *   Container autoscale now explicitly waits for per-container utilization rows instead of treating aggregate account-level utilization as eligible input for individual container scaling.
    *   Reduced Admin Settings refresh latency by reusing one ARM token and reading per-container throughput settings in a bounded parallel scan instead of serial per-container reads.
    *   (Ref: `functions_cosmos_throughput.py`, Cosmos throughput Azure Monitor dimensions, ARM container throughput reads, `COSMOS_CONTAINER_THROUGHPUT_REFRESH_PERFORMANCE_FIX.md`)

*   **Cosmos Container Metric Dimensions**
    *   Fixed Cosmos throughput status refreshes so Azure Monitor is asked for per-container metric dimensions instead of only aggregate account-level RU metrics.
    *   Preserved the aggregate RU utilization card through a fallback query when container-dimensional metrics are delayed or unavailable, and added clearer Admin Settings messaging for that aggregate-only state.
    *   (Ref: `functions_cosmos_throughput.py`, `admin_settings.js`, Cosmos throughput Azure Monitor metrics, `COSMOS_CONTAINER_METRICS_DIMENSION_FIX.md`)

*   **Cosmos Throughput Cached Status**
    *   Fixed the Admin Settings Cosmos throughput card so it renders the last saved database or container-targeted view immediately after server restart instead of requiring a manual Refresh to rediscover containers.
    *   Manual Refresh and background autoscale checks now persist a compact cached status with capacity scope, throughput summary, metrics, container rows, and timestamps.
    *   Added copy clarifying that background automation checks throughput about every 5 minutes while enabled, and versioned the Admin Settings JavaScript asset to avoid stale browser-side Cosmos UI logic.
    *   (Ref: `functions_cosmos_throughput.py`, `admin_settings.html`, `admin_settings.js`, `COSMOS_THROUGHPUT_CACHED_STATUS_FIX.md`)

*   **Container Policy Save Button Activation**
    *   Fixed the Cosmos throughput container policy modal so saving staged container policies enables the main Admin Settings Save button immediately.
    *   The modal now uses the standard admin form dirty-state handler instead of setting only the internal modified flag.
    *   (Ref: `admin_settings.js`, Admin Settings Scale tab, `COSMOS_CONTAINER_POLICY_SAVE_BUTTON_FIX.md`)

*   **Cosmos Throughput Refresh Logging**
    *   Added backend start, completion, failure, and phase timing logs for Admin Settings Cosmos throughput refreshes so admins can see whether the request is waiting on token acquisition, ARM throughput reads, container scans, or Azure Monitor metrics.
    *   Added a refresh correlation ID across route, ARM, container, and metrics logs to make a single Refresh click traceable in console logs and Application Insights.
    *   (Ref: `functions_cosmos_throughput.py`, `route_backend_settings.py`, Cosmos throughput refresh diagnostics)

*   **Advanced Conversation Search Matching**
    *   Fixed the Advanced Search modal so it searches conversation titles and message content across both legacy and collaborative conversation stores.
    *   Added explicit match modes for partial text, all words, any word, and whole word searches, with partial matching as the default so terms such as `Chase` can match larger tokens like `JPMorganChase`.
    *   Normalized chat type filters so personal and multi-user conversation types are not silently excluded from advanced search results.
    *   (Ref: advanced conversation search, chat search modal, `route_backend_conversations.py`, `chat-search-modal.js`, `ADVANCED_CONVERSATION_SEARCH_FIX.md`)

*   **Visio Connector and Arc Fidelity**
    *   Improved Visio citation previews by approximating `RelEllipticalArcTo` geometry as smooth curves instead of straight endpoint segments.
    *   Removed duplicate fallback center-to-center connection lines when explicit connector geometry is already available, reducing visual clutter through service icons.
    *   Added bounded supersampling to smooth rendered PNG previews while avoiding external office-suite dependencies.
    *   Added regression coverage for curved master stencil geometry in the preview parser path.
    *   (Ref: Visio arc geometry, connector rendering, master stencil preview expansion, `functions_visio.py`, `test_visio_ingestion_preview.py`)

*   **Visio Path and Master Geometry Rendering**
    *   Improved the built-in Visio citation preview renderer to draw supported VSDX geometry rows as actual local paths instead of collapsing those shapes to generic rectangles.
    *   Added preview-only expansion of referenced master stencil geometry so common Azure/service icons render with more recognizable vector structure while indexed Visio chunks stay focused on page content.
    *   Improved label placement for icon-backed shapes and dashed container labels using the Visio-exported SVG/PDF reference fixtures.
    *   Added regression coverage to ensure preview master expansion does not pollute default ingestion parsing.
    *   (Ref: Visio path geometry, master stencil geometry, structural renderer, `functions_visio.py`, `test_visio_ingestion_preview.py`, `architecture.svg`, `architecture.pdf`)

*   **Visio Preview Runtime Simplification**
    *   Removed the optional LibreOffice conversion branch from Visio citation previews after confirming Azure Linux `tdnf` does not provide LibreOffice packages in the app builder image.
    *   Visio previews now consistently use the built-in structural renderer with nested shape coordinates, connector endpoint lines, supported embedded media, and page geometry.
    *   (Ref: Visio previews, structural renderer, `functions_visio.py`, `VISIO_PREVIEW_FIDELITY_FIX.md`)

*   **Visio Citation Preview Fidelity**
    *   Strengthened the built-in Visio renderer so it preserves nested shape coordinates, connector endpoint lines, supported embedded media, and page geometry more accurately.
    *   (Ref: Visio previews, structural rendering, `functions_visio.py`, `VISIO_PREVIEW_FIDELITY_FIX.md`)

*   **Source Review Citation Seeding and Second-Hop Traversal**
    *   Source Review now receives the full Foundry web-search citation set, not only URLs that appeared in the web-search answer text, so official sources returned as raw citations can be reviewed directly.
    *   Added a configurable seed-page budget so initial search-result pages cannot consume the entire Source Review page budget before child source pages are inspected.
    *   Raised bounded Deep Source Review depth to support one additional hop, allowing flows such as official news archive -> press-release section -> year/detail page while preserving page, redirect, timeout, type, and SSRF limits.
    *   (Ref: Web Search citations, Deep Source Review, `route_backend_chats.py`, `functions_source_review.py`, `admin_settings.html`, `test_web_search_current_message_only.py`, `test_source_review_deep_traversal.py`)

*   **Deep Source Review Link Prioritization and Audit Detail**
    *   Fixed Deep Source Review link extraction so relevant press-release/archive links are scored before link inventory limits are applied, preventing noisy navigation links from crowding out useful source-detail candidates.
    *   Generic archive traversal now rejects shallow same-domain navigation such as About and Careers pages unless the link has a stronger source/archive signal.
    *   Source Review audit logs and thought details now expose seed pages, child pages, Deep Source Review usage, planner attempted/used state, planner candidate count, and selected planner URLs.
    *   (Ref: Deep Source Review, Source Review audit logging, `functions_source_review.py`, `route_backend_chats.py`, `test_source_review_deep_traversal.py`)

*   **Deep Source Review Traversal Balance**
    *   Improved Deep Source Review so seed/archive pages are reviewed before child links consume the remaining page budget, giving multi-source research requests better coverage across official sources.
    *   Child-link scoring now favors generic release/detail archive patterns and downranks common navigation pages without adding company-specific heuristics.
    *   (Ref: Deep Source Review, `functions_source_review.py`, `test_source_review_deep_traversal.py`, `SOURCE_REVIEW_DEEP_TRAVERSAL_FIX.md`)

*   **Authenticated Request Login Activity Tracking**
    *   Fixed login analytics so passive authenticated browser visits now contribute to login activity even when the user does not explicitly trigger the OAuth callback during that session.
    *   Added throttled authenticated-request tracking to avoid inflating counts on every page load, while still preserving the explicit `azure_ad` login signal and avoiding an immediate duplicate on the post-login redirect.
    *   This improves Control Center and profile login visibility for seamless SSO and session-reuse scenarios without changing the user-facing login flow.
    *   (Ref: authenticated request login activity, `functions_activity_logging.py`, `app.py`, `route_frontend_authentication.py`, `test_authenticated_request_login_activity.py`, `AUTHENTICATED_REQUEST_LOGIN_ACTIVITY_FIX.md`)

*   **Safety Violation Remediation Workflow**
    *   Fixed the Safety Violations admin flow so `Warn user` now sends a user notification, `Suspend user` applies the same timed access restriction used by Control Center, and `Block user` applies the same indefinite deny path.
    *   Safety admins who do not hold the required approval role now create a pending approval request instead of applying the remediation immediately, while eligible reviewers can still self-approve and execute their own request when policy allows it.
    *   The safety review modal and shared approvals page now expose the notification details, suspension restore date, and explicit warn/suspend/block approval labels needed to review and execute those requests cleanly.
    *   (Ref: `route_backend_safety.py`, `route_backend_control_center.py`, `functions_approvals.py`, `functions_safety_remediation.py`, `functions_notifications.py`, `admin_safety_violations.html`, `admin-safety-violations.js`, `approvals.html`, `test_safety_violation_remediation_approvals.py`)

*   **Group and Public Workspace Hero Color Editing**
    *   Fixed the group and public workspace manage pages so hero color selections now apply to the saved workspace branding instead of leaving those selectors effectively non-functional.
    *   The manage-page hero preview now stays in sync with the selected color, and the saved branding metadata flows back through the workspace APIs for consistent rendering.
    *   (Ref: workspace branding, `manage_group.js`, `manage_public_workspace.js`, `route_backend_groups.py`, `route_backend_public_workspaces.py`)

*   **Chat-Scoped Generated Tabular Exports**
    *   Fixed large tabular JSON and CSV export requests so the generated file now stays attached to the active chat instead of being pushed through the personal workspace document pipeline.
    *   Assistant replies now keep the exhaustive dataset in a downloadable chat artifact with the existing preview card, which makes large structured outputs more reliable while keeping the visible answer concise.
    *   Personal conversation deletion and retention cleanup now remove blob-backed generated chat files when archiving is disabled, closing the lifecycle gap for conversation-scoped exports.
    *   (Ref: generated tabular exports, `route_backend_chats.py`, `functions_simplechat_operations.py`, `route_enhanced_citations.py`, `route_backend_conversations.py`, `functions_retention_policy.py`, `chat-messages.js`)

*   **Fact Memory Delete Confirmation Layering**
    *   Fixed the profile fact-memory workflow so the delete confirmation now opens above the Manage Fact Memories editor instead of appearing underneath it.
    *   Users can now confirm or cancel a delete without closing the editor first, and the manager modal remains active so they can continue reviewing saved memories immediately after the confirmation closes.
    *   Added focused UI regression coverage for the stacked modal behavior.
    *   (Ref: fact memory management, `profile.html`, `test_profile_fact_memory_editor.py`)

*   **Live Tabular Analysis Thought Progress**
    *   Fixed long-running tabular analysis chats so workbook tool activity now streams into the thoughts panel while the answer is still being prepared, instead of waiting until the tabular pass completes.
    *   Tabular requests now show a dedicated progress card with the current step, running and completed tool-call counts, and a clearer completion state when workbook evidence is ready.
    *   Added focused UI regression coverage for the live tabular progress card and kept the adjacent agent-progress behavior covered.
    *   (Ref: tabular analysis streaming, `route_backend_chats.py`, `chat-thoughts.js`, `test_chat_tabular_thought_progress.py`, `test_chat_agent_thought_progress.py`)

*   **Workspace Search Document Action Gating**
    *   Fixed chat document actions so Review and Compare now only apply while Workspace Search is enabled.
    *   Turning Workspace Search off now ignores any previously selected Review or Compare mode instead of routing the request through document-action validation and showing stale "select documents before starting a review" warnings.
    *   Added a focused UI regression test for the workspace-toggle flow so normal chat sends continue using the standard chat stream when workspace search is disabled.
    *   (Ref: workspace search toggle, `chat-messages.js`, `test_chat_document_action_workspace_toggle.py`)

*   **Chat File Upload Client Enablement**
    *   Fixed chat file uploads so the effective per-user upload setting is serialized to the browser upload guards.
    *   Users with chat uploads enabled no longer see the `Chat file uploads are not enabled for your account.` warning caused by a missing client-side flag.
    *   (Ref: chat upload controls, `chats.html`, `test_chat_file_upload_access_control.py`, `CHAT_FILE_UPLOAD_CLIENT_FLAG_FIX.md`)

*   **Document Auto Metadata Extraction Consistency**
    *   Fixed upload processing so all supported file types run the same automatic final metadata extraction flow when metadata extraction is enabled.
    *   Corrected public workspace audio and video chunk scoping so public media files participate correctly in metadata extraction and metadata-to-chunk synchronization.
    *   Preserved final processing statuses that indicate whether metadata was extracted, yielded no new information, or completed with a metadata warning.
    *   (Ref: document upload metadata extraction, public workspace media chunks, `functions_documents.py`, `DOCUMENT_AUTO_METADATA_EXTRACTION_FIX.md`)

*   **Chat Stream Lifecycle Observability**
    *   Improved diagnostics for long-running chat streams so backend status now distinguishes active, detached-but-running, completed, and errored stream states during the replay window.
    *   Added backend lifecycle logging for keepalive, detach, reattach, queue backpressure, and terminal stream outcomes, plus frontend best-effort telemetry for request failures, read failures, premature endings, aborts, and recovery attempts.
    *   Added focused regression coverage and versioned fix documentation for the new stream observability path.
    *   (Ref: `route_backend_chats.py`, `chat-streaming.js`, `test_chat_stream_lifecycle_observability.py`, `CHAT_STREAM_LIFECYCLE_OBSERVABILITY_FIX.md`)

*   **Uploaded File Preview Body XSS Hardening (`f044`)**
    *   Fixed the uploaded-file preview modal so stored file bodies no longer reach the preview pane through raw HTML sinks.
    *   Plain-text previews now render as inert preformatted text, CSV-backed previews are built with DOM text nodes, and legacy HTML-backed table payloads now fall back to inert text instead of live markup.
    *   Added focused functional and UI regression coverage plus versioned fix documentation for the hardened preview path.
    *   (Ref: `chat-input-actions.js`, `test_uploaded_file_preview_xss_fix.py`, `test_uploaded_file_preview_escaping.py`, `UPLOADED_FILE_PREVIEW_XSS_FIX.md`)

*   **Public Workspace Tag Color XSS Hardening (`f043`)**
    *   Fixed the public workspace tag surfaces so stored tag colors no longer reach folder-grid actions, tag badges, tag management rows, or selected-tag chips through inline handler or style interpolation.
    *   Shared tag helper paths now normalize and validate tag colors on create and update across personal, group, and public routes, and previously stored invalid colors fall back to safe deterministic values on read.
    *   Added focused functional and UI regression coverage plus versioned fix documentation for the hardened public tag rendering path.
    *   (Ref: `functions_documents.py`, `route_backend_documents.py`, `route_backend_group_documents.py`, `route_backend_public_documents.py`, `public_workspace.js`, `test_public_workspace_tag_color_xss_fix.py`, `test_public_workspace_tag_color_rendering.py`, `PUBLIC_WORKSPACE_TAG_COLOR_XSS_FIX.md`)

*   **Agent Template Gallery Actions Escaping (`f045`)**
    *   Fixed the agent template gallery so stored `actions_to_load` values no longer reach the recommended-actions row through a raw HTML sink.
    *   Agent template helper paths now normalize `actions_to_load` consistently on read, create, and update flows, and invalid write payload shapes are rejected before they can persist.
    *   Added focused functional and UI regression coverage plus versioned fix documentation for the hardened gallery path.
    *   (Ref: `agent_templates_gallery.js`, `functions_agent_templates.py`, `test_agent_template_gallery_actions_to_load_xss_fix.py`, `test_agent_template_gallery_actions_escaping.py`, `AGENT_TEMPLATE_GALLERY_ACTIONS_TO_LOAD_XSS_FIX.md`)

*   **Stored XSS Share, Activity, and Masking Hardening (`f022`, `f042`, residual `f037`)**
    *   Fixed the remaining stored-XSS share-modal flows so attacker-controlled user names, group names, descriptions, emails, and toast content no longer render through inline handlers or raw HTML sinks.
    *   Hardened the group activity timeline and raw-activity modal so stored activity metadata and serialized activity JSON now render as inert text instead of executable markup.
    *   Rebuilt masked-range rendering with DOM APIs and bound masking display names to the authenticated server-side user instead of trusting browser-supplied identity fields.
    *   Added focused functional and UI regression coverage plus versioned fix documentation for the hardened sharing, activity, and masking paths.
    *   (Ref: `chat-toast.js`, `workspace-documents-sharing.js`, `group-documents-sharing.js`, `manage_group.js`, `chat-messages.js`, `route_backend_chats.py`, `test_stored_xss_share_activity_and_masking_fix.py`, `test_document_share_modal_escaping.py`, `STORED_XSS_SHARE_ACTIVITY_AND_MASKING_FIX.md`)

*   **Chat Scope Picker and Conversation Details XSS Hardening (`f021`)**
    *   Fixed the chat scope-lock picker so stored group and public workspace names no longer reach the locked-workspaces modal through raw HTML interpolation.
    *   Hardened the conversation-details modal so attacker-controlled titles, context names, participant labels, document labels, semantic tags, classifications, and scope-lock names render as inert text, and invalid web-source values no longer produce active `javascript:` links.
    *   Added focused functional and UI regression coverage plus versioned fix documentation for the affected chat modal surfaces.
    *   (Ref: `chat-documents.js`, `chat-conversation-details.js`, `test_stored_xss_chat_scope_and_conversation_details_fix.py`, `test_chat_scope_lock_and_conversation_details_escaping.py`, `CHAT_SCOPE_LOCK_AND_CONVERSATION_DETAILS_XSS_FIX.md`)

*   **Chat Citation and Uploaded File Modal Filename XSS Hardening (`f020`)**
    *   Fixed the first-render chat citation modal so attacker-controlled document filenames returned from citation APIs no longer reach the modal header as raw HTML on the first open.
    *   The uploaded-file preview modal now uses the same safe title-population path, closing the adjacent filename sink before it can regress into the same stored-XSS family.
    *   Added focused functional and UI regression coverage plus versioned fix documentation for both modal title flows.
    *   (Ref: `chat-citations.js`, `chat-input-actions.js`, `test_stored_xss_chat_modal_filename_fix.py`, `test_chat_modal_filename_escaping.py`, `CITATION_AND_FILE_MODAL_FILENAME_XSS_FIX.md`)

*   **Stored XSS Agent and Member Rendering Hardening (`f009`, `f010`)**
    *   Fixed the stored-XSS sink in chat message rendering so agent display names no longer reach the sender header, image header, or metadata drawer as raw HTML.
    *   Public and group workspace member-management views now escape untrusted member display names and emails before rendering member rows, pending requests, ownership-transfer options, bulk-remove summaries, user-search results, and CSV validation previews, and the public member search no longer embeds untrusted values inside an inline `onclick` handler.
    *   `/api/userSearch` now escapes Microsoft Graph OData filter literals before composing the `$filter` expression, so apostrophes in search input cannot break the backend Graph query.
    *   Added focused functional and UI regression coverage plus versioned fix documentation for the hardened chat, workspace member-management, and Graph filter paths.
    *   (Ref: `chat-messages.js`, `manage_public_workspace.js`, `manage_group.js`, `route_backend_users.py`, `test_stored_xss_chat_workspace_rendering_fix.py`, `test_public_workspace_member_rendering_escaping.py`, `test_group_workspace_member_rendering_escaping.py`, `STORED_XSS_AGENT_AND_MEMBER_RENDERING_FIX.md`)

*   **Chat Selected Document Metadata Authorization Fix (`f046`)**
    *   Fixed chat selected-document metadata resolution so `/api/chat`, `/api/chat/stream`, and the selected tabular document helper no longer trust caller-supplied document ids after authentication.
    *   Personal selected documents now resolve only for the owner or a legitimately shared user, group selected documents now honor authorized owner and shared-group access, and public selected documents now resolve only inside the caller's visible public workspaces.
    *   Added focused regression coverage for the shared selected-document resolver and updated the existing all-scope tabular regression so the hardened lookup path stays covered.
    *   (Ref: `route_backend_chats.py`, `test_chat_selected_document_metadata_authorization.py`, `test_tabular_all_scope_group_source_context.py`, `CHAT_SELECTED_DOCUMENT_METADATA_AUTHORIZATION_FIX.md`)

*   **Control Center Public Workspace Members XSS Fix (`f008`)**
    *   Fixed a stored XSS in the Control Center public workspace members modal where stored member `displayName` and `email` values were rendered into an admin-facing HTML sink.
    *   The members modal now builds the member row with DOM text nodes instead of injecting those fields through `innerHTML`, so malicious stored markup renders as inert text while the existing role badge styling remains unchanged.
    *   Added focused regression coverage for the affected modal and documented the hardened sink under the current version line.
    *   (Ref: `workspace-manager.js`, `test_control_center_public_workspace_members_escaping.py`, `test_stored_xss_admin_rendering_fix.py`, `CONTROL_CENTER_PUBLIC_WORKSPACE_MEMBERS_XSS_FIX.md`)

*   **Plugin Log Recent Feed Admin Authorization Follow-Up**
    *   Fixed the adjacent plugin logging route so `/api/plugins/invocations/recent` now enforces the `Admin` role instead of exposing the cross-user recent invocation feed to any authenticated user.
    *   Unauthenticated requests still return `401 Unauthorized`, non-admin users now receive `403 Forbidden`, and the admin response payload remains unchanged for legitimate troubleshooting flows.
    *   Extended the focused plugin logging regression coverage so both admin-only plugin logging endpoints are exercised under unauthenticated, non-admin, and admin conditions.
    *   (Ref: `route_plugin_logging.py`, `test_plugin_logging_clear_logs_authorization.py`, `PLUGIN_LOG_RECENT_INVOCATIONS_ADMIN_FIX.md`)

*   **Public Workspace Details Projection Hardening (`f034`)**
    *   Fixed `GET /api/public_workspaces/<workspace_id>` so authenticated non-members no longer receive the full public workspace Cosmos document.
    *   The route now returns a minimal public summary for non-members and a member-aware payload with explicit `userRole` and `isMember` fields for authorized workspace members, which preserves the manage-page UX without exposing manager lists, pending requests, or other member-only metadata.
    *   Added focused functional and UI regression coverage to lock down the new payload contract and verify the public directory and non-member workspace page continue to behave correctly.
    *   (Ref: `route_backend_public_workspaces.py`, `functions_public_workspaces.py`, `manage_public_workspace.js`, `public_directory.js`, `test_security_authorization_hardening.py`, `test_public_workspace_projection_non_member_ui.py`, `PUBLIC_WORKSPACE_DETAILS_DISCLOSURE_FIX.md`)

*   **Approval Route Authorization Guard Consolidation (`f033`)**
    *   Hardened the approval detail, approve, and deny endpoints so both the admin and non-admin route variants now resolve requests through one shared authorization helper before returning approval data or executing destructive approval actions.
    *   This reduces the chance of future drift between approval handlers while preserving the existing `403 Forbidden` behavior for callers who are not allowed to view or approve a request.
    *   Added focused regression coverage to ensure the approval routes continue using the shared authorization path.
    *   (Ref: `route_backend_control_center.py`, `functions_approvals.py`, `test_security_authorization_hardening.py`)

*   **Feedback Submission Ownership Enforcement (`f038`)**
    *   Fixed the user feedback submission route so caller-supplied `conversationId` and `messageId` values must resolve inside the authenticated user's own conversation before any feedback row is created.
    *   Foreign conversation ids now return `403 Forbidden`, missing assistant targets now return `404 Not Found`, and invalid submissions no longer persist copied prompt or AI response content into the caller's feedback history.
    *   Added focused regression coverage for owner success, foreign-conversation rejection before message lookup, and missing-target rejection without feedback persistence.
    *   (Ref: `route_backend_feedback.py`, `test_feedback_submission_authorization.py`, `FEEDBACK_AND_PLUGIN_LOG_ACCESS_CONTROL_FIX.md`)

*   **Plugin Log Clear Admin Authorization (`f039`)**
    *   Fixed the destructive plugin log clear endpoint so only administrators can wipe the shared in-memory plugin invocation history.
    *   Unauthenticated requests still return `401 Unauthorized`, non-admin authenticated users now receive `403 Forbidden`, and admin behavior remains unchanged for legitimate maintenance flows.
    *   Added focused regression coverage for unauthenticated, non-admin, and admin clear-log requests against the shared logger state.
    *   (Ref: `route_plugin_logging.py`, `test_plugin_logging_clear_logs_authorization.py`, `FEEDBACK_AND_PLUGIN_LOG_ACCESS_CONTROL_FIX.md`)

*   **Authorization State Confusion Settings Hardening**
    *   Completed the remaining settings-boundary hardening so active public workspace selection now validates server-side before it is persisted, instead of accepting arbitrary caller-supplied workspace ids through generic settings updates.
    *   Public workspace selection routes now share the same validated helper path, and public prompt operations now resolve the active workspace through a canonical authorization check instead of trusting raw stored settings values.
    *   The generic user-settings update route also now drops unsupported settings keys and returns a client error when a payload contains no valid settings keys, reducing the chance that authorization-sensitive state can bypass dedicated validators in future changes.
    *   (Ref: `functions_public_workspaces.py`, `route_backend_users.py`, `route_backend_public_workspaces.py`, `route_frontend_public_workspaces.py`, `route_backend_public_prompts.py`, `AUTHORIZATION_STATE_CONFUSION_SETTINGS_FIX.md`)

*   **Key Vault Plugin Secret Scope Enforcement (`f013`)**
    *   Fixed a plugin Key Vault authorization gap where well-formed full secret names could be stored or replayed across user, group, or global scopes and later resolved with the application's Key Vault identity.
    *   Plugin secret save, runtime resolution, SQL connection-test resolution, and delete cleanup now verify that stored secret references match the expected scope and source before any Key Vault operation is attempted.
    *   Added focused regression coverage and versioned fix documentation for the hardened plugin secret boundary.
    *   (Ref: `functions_keyvault.py`, `semantic_kernel_loader.py`, `route_backend_plugins.py`, `test_keyvault_plugin_secret_scope_enforcement.py`, `KEY_VAULT_PLUGIN_SECRET_SCOPE_ENFORCEMENT_FIX.md`)

*   **Log Analytics Query History User Scope Enforcement (`f016`)**
    *   Fixed the Log Analytics plugin so query history now binds to the authenticated user on the server instead of accepting an LLM-controlled `user_id` parameter.
    *   Shared user-settings reads and writes now deny cross-user request access by default unless a reviewed privileged path explicitly opts into a cross-user bypass, and the Control Center admin flows have been updated to use that bypass intentionally.
    *   Added focused regression coverage and versioned fix documentation for the plugin surface change and the shared user-settings authorization boundary.
    *   (Ref: `log_analytics_plugin.py`, `functions_settings.py`, `route_backend_control_center.py`, `test_log_analytics_plugin_user_scope_enforcement.py`, `LOG_ANALYTICS_PLUGIN_USER_SCOPE_ENFORCEMENT_FIX.md`)

*   **Personal Conversation Authorization (`f025`, `f027`)**
    *   Closed personal-conversation authorization gaps so conversation deletion, chat file-content retrieval, and frontend conversation rendering verify ownership before returning or destroying data.
    *   The chat message loader also now handles `403 Forbidden` and `404 Not Found` conversation-message responses explicitly, so the browser shows a controlled error state instead of assuming every message load succeeds.
    *   Added focused functional and UI regression coverage plus a separate follow-up fix document under the current release line.
    *   (Ref: `route_backend_conversations.py`, `route_backend_documents.py`, `route_frontend_conversations.py`, `chat-messages.js`, `test_personal_conversation_followup_authorization.py`, `test_chat_messages_authorization_error.py`, `PERSONAL_CONVERSATION_AUTHORIZATION_FOLLOW_UP_FIX.md`)

*   **Personal Conversation Read Authorization Hardening**
    *   Fixed authenticated personal conversation read paths so message history and inline image retrieval now verify conversation ownership before returning content.
    *   Requests that use leaked or foreign conversation identifiers now return `403 Forbidden` instead of disclosing another user's transcript or image content, while the existing missing-resource response contracts remain unchanged.
    *   Added focused regression coverage and versioned fix documentation for the hardened conversation read boundary.
    *   (Ref: `f024`, `route_backend_conversations.py`, `test_conversations_read_ownership_authorization.py`, `PERSONAL_CONVERSATION_READ_AUTHORIZATION_FIX.md`)

*   **Broken Access Control IDOR Hardening**
    *   Closed the authenticated authorization gaps by enforcing personal conversation ownership in chat, binding tabular blob access to the current authorized request context, and binding fact-memory operations to that same canonical scope.
    *   Request group and public workspace scope is now canonicalized before downstream processing so forged or stale scope identifiers do not survive into plugin execution or grounded-history fallback reuse.
    *   Added focused regression coverage and versioned fix documentation for the hardened chat and plugin authorization boundary.
    *   (Ref: `route_backend_chats.py`, `tabular_processing_plugin.py`, `fact_memory_plugin.py`, `test_security_authorization_hardening.py`, `BROKEN_ACCESS_CONTROL_IDOR_HARDENING_FIX.md`)

*   **Stored XSS Admin Rendering Hardening**
    *   Closed the admin-side stored-XSS findings by escaping stored member and agent metadata before Control Center and Admin Settings HTML row rendering.
    *   Control Center toast rendering now escapes message content by default and requires an explicit opt-in for the small number of admin success messages that intentionally include formatted HTML.
    *   Added focused functional and UI regression coverage plus versioned fix documentation for the hardened admin rendering sinks.
    *   (Ref: `control_center.html`, `control-center.js`, `admin_agents.js`, `test_stored_xss_admin_rendering_fix.py`, `test_control_center_group_members_escaping.py`, `STORED_XSS_ADMIN_RENDERING_FIX.md`)

*   **Web Search Data Egress Hardening**
    *   Fixed the Bing-grounding web-search path so external web search now sends only the user's current message instead of a query derived from prior conversation context.
    *   Updated the admin consent copy and user notice text to match the implemented behavior and warn that sensitive content pasted into the current message may still be sent when web search is used.
    *   Reduced outbound web-search invocation metadata and added focused functional and UI regression coverage for the boundary and disclosure text changes.
    *   (Ref: `route_backend_chats.py`, `functions_settings.py`, `route_frontend_admin_settings.py`, `admin_settings.html`, `chats.html`, `test_web_search_current_message_only.py`, `test_web_search_notice_copy.py`)

*   **Authorization Boundary Hardening Across Search, Groups, Approvals, and History Fallback**
    *   Hardened several authenticated workflows that previously trusted caller-supplied identifiers or stale stored scope values, so active group selection, group-scoped prompt access, approval actions, and history-grounded follow-up reuse now revalidate the current user's authorization before proceeding.
    *   Azure AI Search filter construction now escapes OData literals for document, user, group, shared, and public workspace identifiers, and the Control Center public workspace view now renders untrusted workspace metadata as inert text instead of raw HTML.
    *   Added focused functional and UI regression coverage for the authorization and escaping paths, plus versioned fix documentation for the full hardening pass.
    *   (Ref: `functions_search.py`, `functions_group.py`, `route_backend_users.py`, `route_backend_group_prompts.py`, `route_backend_control_center.py`, `route_backend_chats.py`, `control-center.js`, `test_security_authorization_hardening.py`, `test_control_center_public_workspace_escaping.py`)

*   **SQL ODBC Driver 18 Container Support**
    *   Fixed SQL Server and Azure SQL actions in container deployments by installing Microsoft ODBC Driver 18, copying native driver registration and unixODBC libraries into the distroless runtime, and retrying saved Driver 17 connection strings with Driver 18 only when the failure is a missing-driver error.
    *   (Ref: `Dockerfile`, `sql_odbc_utils.py`, `sql_schema_plugin.py`, `sql_query_plugin.py`, `route_backend_plugins.py`, `test_sql_odbc_driver_18_support.py`)

*   **Entra Application Deployment Stability**
    *   Hardened Entra app registration scripts for Microsoft Graph MFA or conditional-access prompts and persisted app registration outputs into the selected AZD environment.
    *   (Ref: `Initialize-EntraApplication.ps1`, `test_entra_application_graph_mfa_auth.py`, `test_entra_application_azd_env_persistence.py`)

*   **Public Workspace Manage Script Syntax Fix**
    *   Fixed the public workspace management page script so pending request handlers and delegated member-search selection initialize without parser errors.
    *   (Ref: `manage_public_workspace.js`, `test_public_workspace_manage_script_syntax_fix.py`, `test_public_workspace_manage_script_parse.py`)

*   **Chat Document Dropdown Viewport Fit Fix**
    *   Fixed grounded-search document dropdown placement so long document lists stay inside short and mobile-influenced viewports.
    *   (Ref: `chat-documents.js`, `test_chat_document_dropdown_viewport_fit.py`)

#### User Interface Enhancements

*   **Workflow Analyze Mode and Conversation Navigation**
    *   Added a `Run each document separately` switch to personal and group workflow Analyze configuration.
    *   Workflow history and alert conversation actions now open linked conversations in a new browser tab so users keep their workflow context open.
    *   Added Word and PowerPoint upload capability toggles to SimpleChat action and agent builders.
    *   (Ref: `workspace.html`, `group_workspaces.html`, `workspace_workflows.js`, `notifications.js`, `plugin_modal_stepper.js`, `agent_modal_stepper.js`)

*   **Personal Workflow Labeling**
    *   Renamed the existing workspace workflow surface to `Personal Workflows` so users can distinguish personal workflows from the new group workflow experience.
    *   Updated personal workflow navigation, modal headings, primary actions, and documentation to use the new wording without changing existing personal workflow IDs or API contracts.
    *   (Ref: `workspace.html`, `workspace_workflows.js`, `PERSONAL_WORKFLOWS.md`)

*   **Custom Workspace Hero Color Swatches**
    *   Added a custom color swatch to group and public workspace manage pages so workspace owners can choose any valid hero color in addition to the preset palette.
    *   Saved custom colors now reselect the custom swatch and update the live hero preview before saving.
    *   (Ref: `manage_group.html`, `manage_public_workspace.html`, `manage_group.js`, `manage_public_workspace.js`, `GROUP_PUBLIC_WORKSPACE_CUSTOM_HERO_COLORS.md`)

*   **Selectable Conversation-Linked Workspace Document Deletion**
    *   Conversation delete now lists workspace documents created from chat uploads and lets users select one, many, or all documents to delete with the conversation.
    *   Leaving all documents unchecked keeps them in the personal workspace so they follow the normal document retention policy.
    *   Bulk conversation delete no longer removes linked workspace documents automatically.
    *   (Ref: conversation delete modal, `chat-conversations.js`, `route_backend_conversations.py`, `functions_documents.py`)

*   **Document Intelligence Extraction Terminology**
    *   Renamed user-facing PDF/image extraction choices from Read/Layout to Standard/Enhanced while preserving the underlying `read` and `layout` settings and API values.
    *   Added hover text for extraction, citation, and File Sync badges so workspace users can understand Standard, Enhanced, synced, and manually uploaded document states without extra visual clutter.
    *   (Ref: Admin Settings Search & Extract, personal/group/public workspace document details)

*   **Extraction Badge Placement**
    *   Removed Read/Layout extraction badges from top-level document rows and cards while preserving them in expanded document details and metadata views.
    *   (Ref: personal, group, and public workspace document views)

*   **Cosmos Throughput Table Clarity**
    *   Simplified the Admin Settings Cosmos throughput container table by removing the redundant Database column and replacing the Configure text action with a compact gear button.
    *   Added tooltips that distinguish RU Utilization from Request Units, plus a Setup Guide modal with a Run Test action that uses the same status checks as Refresh.
    *   Preserved unavailable container request-unit metrics as unavailable instead of rendering a misleading zero when Azure Monitor does not return a container metric row.
    *   (Ref: `admin_settings.html`, `admin_settings.js`, Cosmos throughput container metrics, `COSMOS_THROUGHPUT_TABLE_CLARITY_FIX.md`)

*   **Container-Targeted Cosmos Throughput Policies**
    *   Added a Containers modal to the Admin Settings Scale tab so admins can review every Cosmos container and configure per-container automation settings.
    *   Each dedicated-throughput container can now have independent min/max RU guardrails, scale-up/down thresholds, RU step sizes, cooldown intervals, and manual scale actions.
    *   The Cosmos throughput status endpoint now falls back to container-targeted management when database-level throughput settings are absent instead of failing the card with a 404.
    *   (Ref: `functions_cosmos_throughput.py`, Admin Settings Scale tab, `COSMOS_CONTAINER_THROUGHPUT_FALLBACK_FIX.md`)

*   **File Sync Source Configuration Flow**
    *   Reworked the File Sync source modal around a combined selection, subfolders, and filters section, including selected path summaries and a browse modal for supported providers.
    *   OneDrive source configuration now presents a global connector identity notice instead of source-local credential fields.
    *   (Ref: `workspace-file-sync.js`, File Sync source workflow, selected paths)

*   **Control Center Group Token Totals**
    *   Added all-time group token usage totals to the Control Center Group Management table so admins can compare group usage alongside members, status, and document metrics.
    *   Included the same token total in the group management modal and CSV export for consistent reporting.
    *   (Ref: Control Center group management, group token usage aggregation, `route_backend_control_center.py`, `control-center.js`, `control_center.html`)

*   **Workspace Identity Modal Workflow**
    *   Simplified workspace and global identity management around real consumers: File Sync, Actions, and Model Endpoints.
    *   Replaced the inline identity form with Add, View, and Edit modals that group identity details, used-for selection, and authentication.
    *   Removed the workspace identity page heading and refresh button so the tab starts with a left-aligned Add Identity action and a focused identity table.
    *   (Ref: workspace identities, identity modal workflow, `workspace-identities.js`, `functions_workspace_identities.py`)

*   **Deep Research Allowed-User Management Modal**
    *   Replaced inline Deep Research user policy controls with a compact **Manage Users** modal that supports directory search, manual user additions, filtering, removal, CSV upload, and example CSV download.
    *   Removed blocked-user policy controls from Deep Research and switched runtime behavior to allow-only user access; legacy blocked-user settings are ignored and cleared on admin save.
    *   Deep Research now applies max/enabled defaults when newly enabled while keeping the master feature toggle off by default.
    *   (Ref: Deep Research access policy, allowed users modal, `admin_settings.html`, `admin_settings.js`, `functions_source_review.py`, `route_frontend_admin_settings.py`)

*   **Assistant Follow-Up Prompt Actions**
    *   Chat responses that include visible next-step options can now render those options as prompt buttons under the assistant message.
    *   Clicking a prompt action stages the text in the chat input and starts a cancelable send countdown, making suggested next steps easier to continue while keeping the user in control.
    *   (Ref: chat follow-up actions, `chat-messages.js`, `chats.css`, `test_chat_follow_up_prompt_actions.py`)

*   **Workspace Document Cards and Folder-Card Views**
    *   Added public workspace document cards and aligned public workspace view controls with personal and group workspaces: List, Cards, Folders, and Folders + Cards.
    *   Folder-card views now let users browse folders first and then review matching documents as cards, while card clicks open the document action menu for quick Chat, Edit, Select, and management actions.
    *   Improved multi-select controls and visible-only select-all behavior across personal, group, and public list, card, folder, and folder-card views.
    *   (Ref: workspace document cards, public workspace views, `workspace-documents.js`, `workspace-tags.js`, `public_workspace.js`, `workspace-responsive.css`, `workspace.html`, `group_workspaces.html`, `public_workspaces.html`, `test_public_workspace_document_cards_views.py`)

*   **Control Center Management Pagination**
    *   Added consistent page-size selectors to User Management, Group Management, and Public Workspace Management in Control Center, with 10, 25, 50, 100, and 250 item options.
    *   Group and public workspace management now use server-driven pagination instead of loading a fixed first page, so admins can navigate larger result sets with accurate filtered totals.
    *   Added regression coverage and fix documentation for the shared management pagination behavior.
    *   (Ref: `route_backend_control_center.py`, `control_center.html`, `control-center.js`, `test_control_center_management_pagination.py`, `CONTROL_CENTER_MANAGEMENT_PAGINATION_FIX.md`)

*   **Workspace Branding Heroes and Shortcuts**
    *   Added logo upload support for group and public workspace manage pages so owners can brand those spaces with a persistent hero image in addition to the hero color.
    *   Group and public workspace pages now show the active workspace hero card with the selected color, owner metadata, optional logo, and a direct manage button for the selected workspace.
    *   Added focused functional and UI regression coverage for the branding metadata, hero rendering, and manage-page flows.
    *   (Ref: `functions_workspace_branding.py`, `group_workspaces.html`, `public_workspaces.html`, `test_workspace_branding_hero_and_logo.py`, `test_workspace_active_hero_shortcuts.py`, `test_manage_group_page_branding.py`, `test_manage_public_workspace_page_load.py`)

*   **GitHub Pages Documentation Redesign**
    *   Redesigned the GitHub Pages documentation shell with fixed top navigation, curated sidebar sections, responsive mobile drawer, documentation search, and a right-side page rail.
    *   (Ref: `docs/_layouts/default.html`, `docs/_includes/sidebar_nav.html`, `docs/assets/css/main.scss`, `docs/assets/js/main.js`, `docs/index.md`, `ui_tests/test_docs_showcase_pages.py`)

*   **Chat and Sidebar Icon-Only Controls**
    *   Refined the chat conversation info button and compact sidebar toggle so they render as quiet icon-only controls while preserving accessible focus states.
    *   (Ref: `chats.html`, `_sidebar_nav.html`, `_sidebar_short_nav.html`, `sidebar.css`, `test_chat_sidebar_toggle_controls.py`)


### **(v0.241.007)**

#### Bug Fixes

*   **Global Agent Scope Gate Fallback**
    *   Fixed per-user Semantic Kernel chats so selecting a global agent no longer silently falls back to the standard GPT model when personal agents are disabled for the tenant.
    *   The per-user loader now treats global, personal, and group agent scopes separately, allowing valid global-agent selections to continue through agent invocation while keeping personal and group scope toggles enforced as configured.
    *   Added regression coverage for the shared scope gate used by the per-user loader.
    *   (Ref: `semantic_kernel_loader.py`, `functions_agent_scope.py`, `test_global_agent_scope_gate.py`, global agent request routing)

### **(v0.241.006)**

#### Bug Fixes

*   **Requests Runtime Dependency Upgrade**
    *   Updated the runtime HTTP client dependency from `requests==2.33.0` to `requests==2.33.1` in the main application requirements to keep deployment environments aligned with the latest pinned patch release.
    *   (Ref: `application/single_app/requirements.txt`)

*   **Speech and Video Indexer Setup Guidance Alignment**
    *   Fixed stale admin guidance around Azure AI Video Indexer and shared Azure Speech configuration so managed-identity setup no longer points admins toward legacy Video Indexer API keys or incomplete Speech instructions.
    *   The admin experience now reflects the shared Speech resource model, adds Speech Resource ID helper fields, and keeps managed-identity voice-response requirements aligned with runtime behavior.
    *   (Ref: `admin_settings.html`, `admin_settings.js`, `route_backend_tts.py`, `functions_documents.py`, shared Speech and Video Indexer guidance)

*   **Agent Output Token Defaults and Foundry Limit Enforcement**
    *   Fixed stale agent output-token defaults so new and normalized agents now use `-1` to defer to the provider or model default instead of silently reintroducing older fixed caps.
    *   Azure AI Foundry agent execution now also honors saved output-token settings in both classic Foundry agent runs and new Foundry Responses-based runs, so configured limits are enforced consistently instead of only being stored in agent configuration.
    *   (Ref: `functions_global_agents.py`, `agent.schema.json`, `foundry_agent_runtime.py`, `test_foundry_token_limit_defaults.py`)

*   **Tabular Exhaustive Result Synthesis Retry**
    *   Fixed exhaustive tabular questions such as "list all" requests so the workflow no longer stops at an answer that claims only sample rows or workbook metadata are available after analytical tool calls already returned the full matching result set.
    *   General tabular analysis now detects full versus partial result coverage from tool metadata, retries incomplete synthesis when necessary, and adds stronger prompt guidance so the final answer uses the returned analytical results directly.
    *   (Ref: `route_backend_chats.py`, `test_tabular_exhaustive_result_synthesis_fix.py`, `TABULAR_EXHAUSTIVE_RESULT_SYNTHESIS_FIX.md`)

*   **Group Workspace Documents and Prompts Load Recovery**
    *   Fixed a Group Workspace page-load regression where active-group initialization could fail on a missing prompt-role UI container and stop the rest of the page from rendering correctly.
    *   Group document and prompt content now continue loading even if the prompt permission banner or create-button container is unavailable during startup, preventing blank content areas caused by a JavaScript null-reference error.
    *   Added functional and UI regression coverage for the guarded prompt-role path so future changes do not reintroduce the same startup failure.
    *   (Ref: `group_workspaces.html`, `test_group_workspace_prompt_role_ui_guard.py`, `test_group_workspace_prompt_role_containers_ui.py`)

*   **Audio and Video Enhanced Citation Badge Consistency**
    *   Fixed blob-backed audio and video documents showing Standard citations in workspace details even when Enhanced Citations was enabled and the same files already opened through the enhanced citation experience on the chat page.
    *   Document metadata now persists and normalizes the `enhanced_citations` flag from blob-backed storage state so existing media uploads and new uploads both render the correct Enhanced badge across workspace and chat flows.
    *   Added regression coverage and fix documentation for the metadata normalization path.
    *   (Ref: `functions_documents.py`, `route_enhanced_citations.py`, `test_media_enhanced_citations_metadata_flag.py`, `MEDIA_ENHANCED_CITATION_BADGE_FIX.md`)

#### User Interface Enhancements

*   **AI Voice Conversations Setup Guide**
    *   Added an in-app Setup Guide modal to the AI Voice Conversations admin card so admins can configure Azure Speech without leaving Admin Settings.
    *   The guide includes a live snapshot of the current Speech configuration, explains key versus managed-identity authentication, and now walks admins through enabling the required custom domain in Azure portal before verifying the endpoint on Keys and Endpoint.
    *   (Ref: `admin_settings.html`, `_speech_service_info.html`, `azure_speech_managed_identity_manul_setup.md`, `test_admin_multimedia_guidance.py`)
    
### **(v0.241.002)**

#### Bug Fixes

*   **Support Pages Respect Custom Application Titles**
    *   Fixed user-facing Support copy so Latest Features, Previous Release Features, and Send Feedback no longer fall back to the default `SimpleChat` name in customized deployments.
    *   Support feedback email drafts now also use the configured application title, keeping the user-facing support flow consistent with branded environments.
    *   (Ref: `support_menu_config.py`, `support_send_feedback.html`, `route_backend_settings.py`, support application-title personalization)

*   **Streaming Retry and Edit Thought Tracking**
    *   Fixed retry and edit requests in streaming chat when they fall back to the compatibility bridge and continue through the legacy `/api/chat` path.
    *   Assistant response tracking is now initialized for both new-message and retry/edit flows before content safety runs, preventing compatibility-mode failures caused by an uninitialized `ThoughtTracker`.
    *   (Ref: `route_backend_chats.py`, `ThoughtTracker`, `/api/chat/stream`, `/api/chat`, retry/edit compatibility bridge)

*   **Streaming Retry and Edit Multi-Endpoint Model Resolution**
    *   Fixed streaming retry and edit requests that route through the compatibility bridge so they no longer fail during AI model initialization in multi-endpoint environments.
    *   The compatibility path now reuses the in-app multi-endpoint GPT resolver and Foundry fallback helpers instead of depending on script-only helper functions that were not available inside the Flask runtime.
    *   (Ref: `route_backend_chats.py`, `/api/chat/stream`, `/api/chat`, multi-endpoint model resolution, Foundry fallback helpers)

*   **Profile Fact Memory Script Deduplication**
    *   Fixed a profile-page load failure where duplicate inline Fact Memory and tutorial script blocks could trigger browser parse errors such as `Identifier 'factMemorySearchInput' has already been declared`.
    *   Removed duplicated profile sections, modal markup, and shadowing helper definitions so Fact Memory, tutorial preferences, and retention settings now initialize from one canonical script path.
    *   Added source-level and UI regression coverage so duplicate profile blocks and page-load JavaScript errors are caught earlier.
    *   (Ref: `profile.html`, `test_profile_fact_memory_script_dedup.py`, `test_profile_fact_memory_editor.py`, profile page script initialization)

### **(v0.241.001)**

#### New Features

*   **Fact Memory Instructions and Facts**
    *   Added a clearer Fact Memory experience that distinguishes always-on Instructions from relevance-based Facts on the profile page and in chat-time recall.
    *   Chat responses now surface saved-memory usage more clearly through separate Instruction Memory and Fact Memory Recall thoughts and citations.
    *   Admin Settings Latest Features and the user-facing Support > Latest Features page now include Fact Memory guidance and screenshots, and admins can show or hide that announcement from General > User-Facing Latest Features.
    *   (Ref: `semantic_kernel_fact_memory_store.py`, `route_backend_chats.py`, `route_frontend_profile.py`, `profile.html`, `support_menu_config.py`, `admin_settings.html`, `latest_features.html`, fact memory guidance and latest-features coverage)

*   **Support Menu and User-Facing Latest Features**
    *   Added a configurable Support menu for signed-in app users so teams can expose Latest Features and Send Feedback directly in everyday navigation.
    *   Admins can rename the Support menu, control the internal feedback-recipient email address, and choose exactly which latest-feature cards are shared with end users from the General tab.
    *   The user-facing Latest Features page now mirrors the available admin screenshots more closely, includes clearer guidance about why each feature matters, and adds direct links into Chat, Personal Workspace, or Support destinations where users can try the feature.
    *   The Admin Settings Latest Features tab now also calls out the General-tab User-Facing Latest Features checklist so admins can see where feature sharing is configured.
    *   (Ref: `support_menu_config.py`, `route_frontend_support.py`, `latest_features.html`, `support_send_feedback.html`, `admin_settings.html`, `test_support_menu_user_feature.py`, support menu configuration and user-facing latest features)

*   **MultiGPT Endpoint Management**
    *   Added multi-endpoint model management so admins can define multiple global model endpoints and users can add personal or group-scoped endpoints when those workspace features are enabled.
    *   Personal Workspace and Group Workspace now surface dedicated model endpoint management cards, and agent/model selection can use combined global plus workspace endpoint lists instead of relying on a single shared deployment.
    *   The endpoint workflow supports Azure OpenAI and Azure AI Foundry discovery flows, including model fetch/test operations and endpoint-based Foundry agent import.
    *   (Ref: `route_backend_models.py`, `route_frontend_admin_settings.py`, `workspace_model_endpoints.js`, `admin_model_endpoints.js`, `workspace.html`, `group_workspaces.html`, `test_workspace_multi_endpoints.py`)
    
*   **Guided Chat Tutorial**
    *   Expanded the in-app chat tutorial into a fuller guided walkthrough of the current chat experience so new users can learn the live interface in context.
    *   The tutorial now walks through the main chat toolbar, workspace and scope controls, conversation search, advanced search, selection mode, bulk actions, export-related flows, and message-level actions such as retry, edit, feedback, thoughts, and citations.
    *   The walkthrough also includes reliability improvements for dynamic chat UI elements, including sidebar expansion, popup alignment, and tutorial-owned surfaces for steps that depend on transient menus.
    *   (Ref: `chat-tutorial.js`, `chats.html`, `chat-sidebar-conversations.js`, `test_chat_tutorial_selector_coverage.py`, chat tutorial walkthrough)

*   **Personal Workspace Guided Tutorial**
    *   Added a dedicated in-app tutorial for Personal Workspace so users can learn document, prompt, agent, action, and tag workflows directly inside the workspace page.
    *   The walkthrough covers uploads, search and filters, list and grid views, document details, row actions, bulk selection flows, tag management, prompt management, agent management, and action management.
    *   It also includes layout-aware positioning and state-restoration behavior so the overlay remains aligned while tabs, filters, menus, and collapsible sections change during the walkthrough.
    *   (Ref: `workspace.html`, `workspace-tutorial.js`, `test_personal_workspace_tutorial_selector_coverage.py`, `test_personal_workspace_tutorial_document_flow.py`, `test_workspace_tutorial_reposition_fix.py`, `test_workspace_tutorial_layer_order_fix.py`)

*   **Conversation Completion Notifications**
    *   Added personal chat completion notifications so users who leave a conversation before the assistant finishes can still see that a response is ready.
    *   Notification clicks deep-link back into the completed conversation, and personal conversations now show a green unread dot until the assistant response is opened.
    *   The unread state and notification lifecycle are wired into the chat conversation list, sidebar list, and mark-read flow so the indicator clears once the conversation is actually viewed.
    *   (Ref: conversation notifications, unread assistant responses, `route_backend_chats.py`, `route_backend_conversations.py`, `functions_notifications.py`, `functions_conversation_unread.py`, `chat-conversations.js`, `chat-sidebar-conversations.js`)

*   **Background Chat Completion Away From Chat Page**
    *   Updated streaming chat execution so assistant responses can continue running after the user leaves the chat page instead of stopping when the browser disconnects from the stream.
    *   This keeps final assistant persistence, unread markers, and completion notifications reachable even when users navigate into Personal, Group, or other pages while a reply is still generating.
    *   (Ref: background stream execution, `BackgroundStreamBridge`, `route_backend_chats.py`, `test_chat_stream_background_execution.py`, `test_streaming_only_chat_path.py`)

*   **SimpleChat Startup and Scheduler Separation**
    *   Added deployment guidance for local development, Azure App Service native Python startup, and container runtimes so administrators can choose between direct Gunicorn startup and optional `python app.py` handoff behavior with clear environment-variable guidance.
    *   Extracted the scheduler-style logging timer, approval expiration, and retention loops into a shared background task module and added a dedicated `simplechat_scheduler.py` entrypoint so scheduled work can run in a separate process or job.
    *   This allows the web app to use Gunicorn with `workers=2` without duplicating scheduler loops inside every worker process, while keeping a legacy override available for single-process environments.
    *   (Ref: `app.py`, `background_tasks.py`, `simplechat_scheduler.py`, `SIMPLECHAT_STARTUP.md`, `test_startup_scheduler_support.py`)

*   **Deployment, Setup, and Upgrade Documentation Refresh**
    *   Expanded the deployment guidance so teams can more quickly choose between manual deployment, Azure CLI, Bicep, Terraform, and special-environment setup paths from the main setup documentation.
    *   Added a dedicated upgrade guide for existing deployments that separates native Python App Service upgrades from container-based App Service upgrades, including when to use VS Code deployment, ZIP deploy, deployment slots, `azd deploy`, `azd provision`, or `azd up`.
    *   Clarified developer and production runtime documentation with explicit local-development guidance, Azure production startup expectations, Gunicorn startup rules, container entrypoint behavior, and scheduler-separation recommendations.
    *   (Ref: `setup_instructions.md`, `setup_instructions_manual.md`, `how-to/upgrade_paths.md`, `running_simplechat_azure_production.md`, `running_simplechat_locally.md`, `SIMPLECHAT_STARTUP.md`, deployment and developer documentation)

*   **Chat Completion Notifications**
    *   Added personal chat completion notifications so users who leave a streaming conversation before the assistant finishes now receive a notification when the AI response is ready.
    *   Notification clicks deep-link directly back to the completed conversation, and personal conversations now show a green unread dot in both chat conversation lists until that response is opened.
    *   The unread state is cleared automatically when the conversation is opened or when the user stays on the chat page through stream completion, keeping the active-view experience clean without adding heartbeat tracking.
    *   (Ref: `route_backend_chats.py`, `route_backend_conversations.py`, `functions_notifications.py`, `functions_conversation_unread.py`, `chat-conversations.js`, `chat-sidebar-conversations.js`, `chat-streaming.js`, `test_chat_completion_notifications.py`)

*   **Configurable Tabular Preview Blob Size Limit**
    *   Added an admin-configurable maximum blob size for tabular file previews, replacing the previous hardcoded limit. Default is 200 MB.
    *   New **Tabular Preview Limits** card in the Enhanced Citations section of Admin Settings (Citations tab) lets admins increase or decrease the limit based on their compute resources and user population.
    *   Setting is stored as `tabular_preview_max_blob_size_mb` and accepts values from 1 to 1024 MB.
    *   (Ref: `route_enhanced_citations.py`, `functions_settings.py`, `admin_settings.html`)

*   **Tabular Preview Memory Optimization**
    *   The `/api/enhanced_citations/tabular_preview` endpoint no longer loads entire files into a DataFrame. It now uses `nrows` limits in `pandas.read_csv`/`read_excel` to read only the rows needed for the preview, and checks blob size before downloading to reject oversized files early.
    *   (Ref: `route_enhanced_citations.py`)

*   **Persistent Conversation Summaries**
    *   Summaries generated during conversation export are now saved to the conversation document in Cosmos DB for future reuse.
    *   Cached summaries include `message_time_start` and `message_time_end` — when a conversation has new messages beyond the cached range, a fresh summary is generated automatically.
    *   The conversation details modal now shows a **Summary** card at the top. If a summary exists it displays the content, generation date, and model used. If no summary exists a **Generate Summary** button with model selector lets users create one on demand.
    *   A **Regenerate** button is available on existing summaries to force a refresh with the currently selected model.
    *   New `POST /api/conversations/<id>/summary` endpoint accepts an optional `model_deployment` and returns the generated summary.
    *   The `GET /api/conversations/<id>/metadata` response now includes a `summary` field.
    *   Extracted `generate_conversation_summary()` as a shared helper used by both the export pipeline and the new API endpoint.
    *   (Ref: `route_backend_conversation_export.py`, `route_backend_conversations.py`, `chat-conversation-details.js`, `functions_conversation_metadata.py`)

*   **PDF Conversation Export**
    *   Added PDF as a third export format option alongside JSON and Markdown, giving users a print-ready, visually styled conversation archive.
    *   PDF output renders chat messages with colored bubbles that mirror the live chat UI: blue for user messages, gray for assistant messages, green for file messages, and amber for system messages.
    *   Message content is converted from Markdown to HTML for rich formatting (bold, italic, code blocks, lists, tables) inside the PDF.
    *   Full appendix structure is included (metadata, message details, references, processing thoughts, supplemental messages), matching the Markdown export layout.
    *   Rendering uses PyMuPDF's Story API on US Letter paper with 0.5-inch margins and automatic multi-page overflow.
    *   Works with both single-file and ZIP packaging; intro summaries are supported in PDF as well.
    *   Frontend format step updated to a 3-column card grid with a new PDF card using the `bi-filetype-pdf` icon.
    *   (Ref: `route_backend_conversation_export.py`, `chat-export.js`, PyMuPDF Story API, conversation export workflow)

*   **Conversation Export Intro Summaries**
    *   Added an optional AI-generated intro summary step to the conversation export workflow, so each exported chat can begin with a short abstract before the full transcript.
    *   Summary model selection now reuses the same model list shown in the chat composer, keeping the export flow aligned with the main chat experience.
    *   Works for both JSON and Markdown exports, including ZIP exports where each conversation keeps its own summary metadata.
    *   (Ref: `route_backend_conversation_export.py`, `chat-export.js`, conversation export workflow)

*   **Agent & Action User Tracking (created_by / modified_by)**
    *   All agent and action documents (personal, group, and global) now include `created_by`, `created_at`, `modified_by`, and `modified_at` fields that track which user created or last modified the entity.
    *   On updates, the original `created_by` and `created_at` values are preserved while `modified_by` and `modified_at` are refreshed with the current user and timestamp.
    *   New optional `user_id` parameter added to `save_group_agent`, `save_global_agent`, `save_group_action`, and `save_global_action` for caller-supplied user tracking (backward-compatible, defaults to `None`).
    *   (Ref: `functions_personal_agents.py`, `functions_group_agents.py`, `functions_global_agents.py`, `functions_personal_actions.py`, `functions_group_actions.py`, `functions_global_actions.py`)

*   **Activity Logging for Agent & Action CRUD Operations**
    *   Every create, update, and delete operation on agents and actions now generates an activity log record in the `activity_logs` Cosmos DB container and Application Insights.
    *   Six new logging functions: `log_agent_creation`, `log_agent_update`, `log_agent_deletion`, `log_action_creation`, `log_action_update`, `log_action_deletion`.
    *   Activity records include: `user_id`, `activity_type`, `entity_type` (agent/action), `operation` (create/update/delete), `workspace_type` (personal/group/global), and `workspace_context` (group_id when applicable).
    *   Logging is fire-and-forget — failures never break the CRUD operation.
    *   All personal, group, and admin routes for both agents and actions are wired up.
    *   (Ref: `functions_activity_logging.py`, `route_backend_agents.py`, `route_backend_plugins.py`)

*   **Tabular Data Analysis — SK Mini-Agent for Normal Chat**
    *   Tabular files (CSV, XLSX, XLS, XLSM) detected in search results now trigger a lightweight Semantic Kernel mini-agent that pre-computes data analysis before the main LLM response. This brings the same analytical depth previously only available in full agent mode to every normal chat conversation.
    *   **Automatic Detection**: When AI Search results include tabular files from any workspace (personal, group, or public) or chat-uploaded documents, the system automatically identifies them via the `TABULAR_EXTENSIONS` configuration and routes the query through the SK mini-agent pipeline.
    *   **Unified Workspace and Chat Handling**: Tabular files are processed identically regardless of their storage location. The plugin resolves blob paths across all four container types (`user-documents`, `group-documents`, `public-documents`, `personal-chat`) with automatic fallback resolution if the primary source lookup fails. A user asking about an Excel file in their personal workspace gets the same analytical treatment as one asking about a CSV uploaded directly to a chat.
    *   **Six Data Analysis Functions**: The `TabularProcessingPlugin` exposes `describe_tabular_file`, `aggregate_column` (sum, mean, count, min, max, median, std, nunique, value_counts), `filter_rows` (==, !=, >, <, >=, <=, contains, startswith, endswith), `query_tabular_data` (pandas query syntax), `group_by_aggregate`, and `list_tabular_files` — all registered as Semantic Kernel functions that the mini-agent orchestrates autonomously.
    *   **Pre-Computed Results Injected as Context**: The mini-agent's computed analysis (exact numerical results, aggregations, filtered data) is injected into the main LLM's system context so it can present accurate, citation-backed answers without hallucinating numbers.
    *   **Graceful Degradation**: If the mini-agent analysis fails for any reason, the system falls back to instructing the main LLM to use the tabular processing plugin functions directly, preserving full functionality.
    *   **Non-Streaming and Streaming Support**: Both chat modes are supported. The mini-agent runs synchronously before the main LLM call in both paths.
    *   **Requires Enhanced Citations**: The tabular processing plugin depends on the blob storage client initialized by the enhanced citations system. The `enable_enhanced_citations` admin setting must be enabled for tabular data analysis to activate.
    *   (Ref: `run_tabular_sk_analysis()`, `TabularProcessingPlugin`, `collect_tabular_sk_citations()`, `TABULAR_EXTENSIONS`)

*   **Tabular Tool Execution Citations**
    *   Every tool call made by the SK mini-agent during tabular analysis is captured and surfaced as an agent citation, providing full transparency into the data analysis pipeline.
    *   **Automatic Capture**: The existing `@plugin_function_logger` decorator on all `TabularProcessingPlugin` functions records each invocation including function name, input parameters, returned results, execution duration, and success/failure status.
    *   **Citation Format**: Tool execution citations appear in the same "Agent Tool Execution" modal used by full agent mode, showing `tool_name` (e.g., `TabularProcessingPlugin.aggregate_column`), `function_arguments` (the exact parameters passed), and `function_result` (the computed data returned).
    *   **End-to-End Auditability**: Users can verify exactly which aggregations, filters, or queries were run against their data, what parameters were used, and what raw results were returned — before the LLM summarized them into the final response.
    *   (Ref: `collect_tabular_sk_citations()`, `plugin_invocation_logger.py`)

*   **Assistant Citation Artifact Storage for Large Tabular Payloads**
    *   Moved large raw tabular and tool citation payloads off the main assistant message document and into linked child artifact records so tool-heavy answers stay compact in primary chat storage.
    *   Added helper flows in `functions_message_artifacts.py` to keep a compact citation summary on the assistant message, externalize the full raw citation payload into `assistant_artifact` records with `assistant_artifact_chunk` support for larger payloads, and rehydrate those raw payloads later for exports or deeper inspection.
    *   Assistant messages now keep compact summaries such as tool name, reduced arguments, counts, and a few sample rows while the heavy raw citation payload is referenced through `artifact_id` and `raw_payload_externalized=True`.
    *   Updated chat persistence to store the linked artifact records during message save, excluded those artifact records from normal chat history and conversation views, and updated export flows to stitch the preserved raw payloads back together when needed.
    *   This reduced primary assistant message size, lowered the risk of hitting Cosmos DB per-item limits on large tabular responses, reduced heavy citation data carried through normal chat reads, and preserved the full raw evidence for export and debugging.
    *   Additional size reductions in the same phase compacted stored citation summaries, dropped noisy tabular citation arguments such as `user_id`, `conversation_id`, and `source`, and removed the duplicate `user_message` field from assistant message documents.
    *   (Ref: `functions_message_artifacts.py`, `route_backend_chats.py`, `route_backend_conversations.py`, `route_frontend_conversations.py`, `route_backend_conversation_export.py`, `test_assistant_citation_artifact_storage.py`, `ASSISTANT_CITATION_ARTIFACT_STORAGE_FIX.md`)

*   **SK Mini-Agent Performance Optimization**
    *   Reduced typical tabular analysis time from ~74 seconds to an estimated ~30-33 seconds (55-60% reduction) through three complementary optimizations.
    *   **DataFrame Caching**: Per-request in-memory cache eliminates redundant blob downloads. Previously, each of the ~8 tool calls in a typical analysis downloaded and parsed the same file independently. Now the file is downloaded once and subsequent calls read from cache. Cache is automatically scoped to the request (new plugin instance per analysis) and garbage-collected afterward.
    *   **Pre-Dispatch Schema Injection**: File schemas (columns, data types, row counts, and a 3-row preview) are pre-loaded and injected into the SK mini-agent's system prompt before execution begins. This eliminates 2 LLM round-trips that were previously spent on file discovery (`list_tabular_files`) and schema inspection (`describe_tabular_file`), allowing the model to jump directly to analysis tool calls.
    *   **Async Plugin Functions**: All six `@kernel_function` methods converted to `async def` using `asyncio.to_thread()`. This enables Semantic Kernel's built-in `asyncio.gather()` to truly parallelize batched tool calls (e.g., 3 simultaneous `aggregate_column` calls) instead of executing them serially on the event loop.
    *   **Batching Instructions**: The system prompt now instructs the model to batch multiple independent function calls in a single response, reducing LLM round-trips further.
    *   (Ref: `_df_cache`, `asyncio.to_thread`, pre-dispatch schema injection in `run_tabular_sk_analysis()`)

*   **SQL Test Connection Button**
    *   Added a "Test Connection" button to the SQL Database Configuration section (Step 3) of the action wizard, allowing users to validate database connectivity before saving.
    *   Supports all database types: SQL Server, Azure SQL (with managed identity), PostgreSQL, MySQL, and SQLite.
    *   Shows inline success/failure alerts with a 15-second timeout cap and sanitized error messages.
    *   New backend endpoint: `POST /api/plugins/test-sql-connection`.
    *   (Ref: `route_backend_plugins.py`, `plugin_modal_stepper.js`, `_plugin_modal.html`)

*   **Per-Message Export**
    *   Added export and action options to the three-dots dropdown menu on individual chat messages (both AI and user messages).
    *   **Export to Markdown**: Downloads the message as a `.md` file with a role header. Entirely client-side.
    *   **Export to Word**: Generates a styled `.docx` document via a new backend endpoint (`POST /api/message/export-word`). Includes Markdown-to-Word formatting (headings, bold, italic, code blocks, lists) and a citations section when present.
    *   **Use as Prompt**: Inserts the raw message content directly into the chat input box for reuse — no clipboard, one click and it's ready to edit and send.
    *   **Open in Email**: Opens the user's default email client with the message pre-filled in the subject and body via `mailto:`.
    *   New options appear below a divider in the dropdown, preserving existing actions (Delete, Retry, Edit, Feedback).
    *   (Ref: `chat-message-export.js`, `chat-messages.js`, `route_backend_conversation_export.py`, per-message export)

*   **Custom Azure Environment Support in Bicep Deployment**
    *   Added `custom` as a supported `cloudEnvironment` value alongside `public` and `usgovernment`, enabling deployment to sovereign or custom Azure environments via Bicep.
    *   New Bicep parameters for custom environments: `customBlobStorageSuffix`, `customGraphUrl`, `customIdentityUrl`, `customResourceManagerUrl`, `customCognitiveServicesScope`, and `customSearchResourceUrl`. All of these are automatically populated from `az.environment()` defaults except `customGraphUrl`, which must be explicitly provided for custom cloud environments and can be overridden as needed.
    *   The `cloudEnvironment` parameter now defaults intelligently based on `az.environment().name`, and legacy values (`AzureCloud`, `AzureUSGovernment`) are mapped to SimpleChat's expected values (`public`, `usgovernment`).
    *   Custom environment app settings (`CUSTOM_GRAPH_URL_VALUE`, `CUSTOM_IDENTITY_URL_VALUE`, `CUSTOM_RESOURCE_MANAGER_URL_VALUE`, etc.) are conditionally injected only when `azurePlatform == 'custom'`.
    *   Replaced hardcoded ACR domain logic and auth issuer URLs with dynamic `az.environment()` lookups for better cross-cloud compatibility.
    *   Fixed trailing slash handling in `AUTHORITY` URL construction in `config.py` using `rstrip('/')`.
    *   (Ref: `deployers/bicep/main.bicep`, `deployers/bicep/modules/appService.bicep`, `config.py`, sovereign cloud support)

*   **Redis Key Vault Authentication**
    *   Added a new `key_vault` authentication type for Redis, allowing the Redis access key to be retrieved securely from Azure Key Vault at runtime rather than stored directly in settings.
    *   Applies across all Redis usage paths: app settings cache (`app_settings_cache.py`), session management (`app.py`), and the Redis test connection flow (`route_backend_settings.py`).
    *   Uses `retrieve_secret_direct()` from `functions_keyvault.py` to fetch the Redis key by its Key Vault secret name. Respects `key_vault_identity` for a user-assigned managed identity on the Key Vault client.
    *   New admin setting fields: `redis_auth_type` (values: `key`, `managed_identity`, `key_vault`) and `redis_key` (used as the Key Vault secret name when `key_vault` auth type is selected).
    *   **Files Modified**: `app_settings_cache.py`, `app.py` `configure_sessions`, `route_backend_settings.py` `_test_redis_connection`, `functions_keyvault.py` `retrieve_secret_direct`

*   **Cross-Cloud Deployment Improvements**
    *   Updated the Azure CLI, AZD, Bicep, and Terraform deployment paths to better align with the current SimpleChat runtime configuration and reduce post-deployment manual fixes.
    *   Added optional Azure Video Indexer deployment support with cloud-aware defaults, including the correct endpoint and ARM API version handling for Azure Commercial, Azure Government, and registered custom clouds.
    *   (Ref: `deployers/azure.yaml`, `deployers/azurecli/deploy-simplechat.ps1`, `deployers/bicep/main.bicep`, `deployers/bicep/modules/videoIndexer.bicep`, `deployers/terraform/main.tf`, `application/single_app/functions_settings.py`)

*   **Idle Session Timeout Feature**
    *   Added a new idle timer that automatically clears the user session after a configurable set time and redirects to the main chat login page.
    *   Added a frontend idle warning modal that pops up after a configurable set time, but disappears if the user moves the mouse over the chat window or interacts with the app in any way.
    *   Default values are used if the idle logout and warning values are not set. 
    *   Idle logout and idle warning values are validated and auto-fixed as needed.
    *   Added a new admin switch to enable or disable idle session timeout and warning behavior.
    *   Timeout and warning inputs are grouped under a toggleable section in General > System Settings.
    *   (Ref: `application/single_app/templates/admin_settings.html`, `application/single_app/static/js/admin/admin_settings.js`, `application/single_app/route_frontend_admin_settings.py`, `application/single_app/functions_settings.py`, `application/single_app/app.py`, `application/single_app/templates/base.html`, `application/single_app/static/js/idle-logout-warning.js`, `application/single_app/config.py`, `functional_tests/test_idle_logout_timeout.py`, `application/single_app/route_frontend_authentication.py`)

#### User Interface Enhancements

*   **Agent Responded Thought — Seconds & Total Duration**
    *   The "responded" thought now shows time in **seconds** instead of milliseconds, and clarifies it is the total time from the initial user message (e.g., `'gpt-5-nano' responded (16.3s from initial message)`).
    *   A `request_start_time` is now captured at the top of both the non-streaming and streaming chat handlers, so the duration reflects the full request lifecycle — including content safety, hybrid search, and agent invocation — not just the model response time.
    *   Applies to all three agent paths: local SK agents (non-streaming), Azure AI Foundry agents, and streaming SK agents.
    *   (Ref: `route_backend_chats.py`, `request_start_time`, agent responded thoughts)

*   **Enhanced Agent Execution Thoughts**
    *   Added detailed model-level status messages during agent execution, giving users full visibility into each stage of the AI pipeline.
    *   **Model Identification**: A new "Sending to '{deployment_name}'" thought appears immediately after "Sending to agent", showing the exact model deployment being used (e.g., `gpt-5-nano`).
    *   **Generating Response**: A "Generating response..." thought now appears before the agent begins its invocation loop, matching the existing behavior for non-agent GPT calls.
    *   **Model Responded with Duration**: A "'{deployment_name}' responded ({duration}ms)" thought appears after the agent completes, showing total wall-clock execution time.
    *   Applies to all three agent paths: local SK agents (streaming and non-streaming) and Azure AI Foundry agents.
    *   Uses the existing `generation` step type (lightning bolt icon) — no frontend changes required.
    *   (Ref: `route_backend_chats.py`, `ThoughtTracker`, agent execution pipeline)

*   **List/Grid View Toggle for Agents and Actions**
    *   Added a list/grid view toggle to all four workspace areas: personal agents, personal actions, group agents, and group actions.
    *   **Grid View**: Large cards with type icon, humanized name, truncated description, and action buttons (Chat, View, Edit, Delete as applicable).
    *   **List View**: Improved table layout with fixed column widths (28%/47%/25%), humanized display names, and truncated descriptions with hover tooltips for full text.
    *   **View Button**: New eye-icon button on every agent and action that opens a read-only detail modal with gradient-header summary cards (Basic Information, Model Configuration, Instructions for agents; Basic Information, Configuration for actions).
    *   **Name Humanization**: Display names are now automatically parsed — underscores and camelCase/PascalCase boundaries are converted to properly spaced, title-cased words (e.g., `myCustomAgent` → `My Custom Agent`).
    *   **Persistent Preference**: View mode selection (list/grid) is saved per area in localStorage and restored on page load.
    *   New shared utility module `view-utils.js` provides reusable functions for all four workspace areas.
    *   (Ref: `view-utils.js`, `workspace_agents.js`, `workspace_plugins.js`, `plugin_common.js`, `group_agents.js`, `group_plugins.js`, `workspace.html`, `group_workspaces.html`, `styles.css`)

*   **Chat with Agent Button for Group Agents**
    *   Added a "Chat" button to each group agent row, allowing users to quickly select a group agent and navigate to the chat page.
    *   (Ref: `group_agents.js`, `group_workspaces.html`)

*   **Hidden Deprecated Action Types**
    *   Deprecated action types (`sql_schema`, `ui_test`, `queue_storage`, `blob_storage`, `embedding_model`) are now hidden from the action creation wizard type selector. Existing actions of these types remain functional.
    *   (Ref: `plugin_modal_stepper.js`)

*   **Advanced Settings Collapse Toggle**
    *   Step 4 (Advanced) content is now hidden behind a collapsible toggle button ("Show Advanced Settings") instead of being displayed by default. Reduces visual noise for most users.
    *   For SQL action types, the redundant additional fields UI in Step 4 is hidden entirely since all SQL configuration is already handled in Step 3.
    *   Step 5 (Summary) no longer shows the raw additional fields JSON dump for SQL types, since that data is already shown in the SQL Database Configuration summary card.
    *   (Ref: `_plugin_modal.html`, `plugin_modal_stepper.js`)
    
#### Bug Fixes

*   **Chat History Citation Replay Improvements**
    *   Fixed follow-up prompts so prior assistant turns can reuse stored citation results, including tabular tool outputs, instead of relying only on the visible assistant message text.
    *   Assistant history replay now hydrates stored citation artifacts and deduplicates repeated cross-sheet tabular calls so later file results, such as Licensing workbook values, remain available to the next turn.
    *   History-context diagnostics remain available in message metadata and optional debug citations, while the thoughts timeline stays compact.
    *   (Ref: `route_backend_chats.py`, `functions_message_artifacts.py`, `chat-thoughts.js`, `chat-messages.js`, `test_chat_stream_history_context_fix.py`, `CHAT_STREAM_HISTORY_CONTEXT_FIX.md`)

*   **Document Revision Visibility and Storage Preservation**
    *   Fixed same-name document uploads so new revisions now inherit the previous document's editable metadata, including classification, tags, title, abstract, keywords, publication date, authors, and sharing state.
    *   Workspace lists and chat search now only use the current revision, while older revisions remain retained for future comparison work instead of staying active in normal workspace flows.
    *   Document deletion now offers a choice between deleting only the current revision or deleting all stored revisions for that document family.
    *   Blob storage now preserves older source files by keeping the active document at the existing alias path and archiving prior current revisions into a revision-family hierarchy before the alias path is overwritten.
    *   (Ref: document revision families, current-only workspace visibility, hybrid blob alias plus archived revision storage, `functions_documents.py`, `functions_search.py`, `route_enhanced_citations.py`, workspace/group/public document flows)
    
*   **Python Runtime Dependency Refresh and Supply-Chain Hardening**
    *   Continued the requirements hardening work from `v0.240.014` by tightening the main application runtime to exact package pins, reducing dependency drift across local development, CI, and Azure deployments to help mitigate supply-chain exposure.
    *   Upgraded the Flask runtime stack to `Flask==3.1.3` and `Werkzeug==3.1.6`, and updated the shared `Markup` import path to `markupsafe` so the app starts correctly with Flask 3's package boundary changes.
    *   Refreshed key runtime dependencies including `gunicorn`, `requests`, `openai`, `Markdown`, `markdown2`, `azure-ai-projects`, `azure-ai-agents`, `pyjwt`, `pypdf`, `semantic-kernel`, `protobuf`, `redis`, `pyodbc`, `PyMySQL`, `cython`, and `aiohttp` to pick up current security, compatibility, and capability improvements while keeping builds reproducible.
    *   (Ref: `application/single_app/requirements.txt`, `application/single_app/config.py`, `functional_tests/test_flask_markup_import_fix.py`, `docs/explanation/fixes/FLASK_31_MARKUP_IMPORT_FIX.md`)

*   **Dependency Pinning and Requirements Hardening**
    *   Pinned previously floating Python package requirements to exact versions across the main app, UI test, deployer, and external app requirement files to reduce unexpected dependency drift and tighten supply-chain control.
    *   Corrected stale external app dependency entries by replacing `dotenv` with `python-dotenv`, removing the stdlib-only `logging` package, removing an unused `Flask` requirement from the databaseseeder utility, and adding `pytest-playwright` so the UI test dependency set matches the pytest fixture usage in the test suite.
    *   (Ref: `application/single_app/requirements.txt`, `ui_tests/requirements.txt`, `deployers/bicep/requirements.txt`, `application/external_apps/databaseseeder/requirements.txt`, `application/external_apps/bulkloader/requirements.txt`)

*   **Settings Default Merge Persistence Fix**
    *   Fixed app settings merge detection in `get_settings()` where `deep_merge_dicts()` mutates the existing settings object in place, causing change detection to always evaluate as unchanged.
    *   Updated `deep_merge_dicts()` to return a boolean `changed` flag and wired `get_settings()` to call `upsert_item()` when `settings_changed` is `True`, so missing default keys correctly trigger persistence back to Cosmos DB.
    *   Added a functional regression test to validate the merge detection and persistence markers.
    *   (Ref: `application/single_app/functions_settings.py`, `application/single_app/config.py`, `functional_tests/test_settings_deep_merge_persistence_fix.py`)

*   **Legacy Office Binary Upload Support**
    *   Added native OLE-based support for older Word `.doc` and PowerPoint `.ppt` files instead of relying on OOXML-only assumptions during processing.
    *   Legacy `.doc` uploads now extract available metadata and follow the same shared document-processing workflow used for richer Office files, so enhanced citations and final metadata extraction stay consistent when those features are enabled.
    *   Legacy `.ppt` uploads now extract slide text and available summary metadata from the OLE presentation streams while keeping the same enhanced-citation and final-metadata workflow used by `.pptx` uploads.
    *   `.pptx` uploads now also populate presentation metadata such as title, author, subject, and keywords during the initial metadata update when metadata extraction is enabled.
    *   (Ref: `functions_content.py`, `functions_documents.py`, `test_legacy_doc_ole_extraction.py`, `test_legacy_ppt_ole_extraction.py`, legacy Office OLE support and metadata parity)
    
*   **Pillow PSD Upload Hardening**
    *   Updated the application to use `pillow==12.1.1`, moving the app off the vulnerable Pillow range for specially crafted PSD image parsing.
    *   Hardened admin logo and favicon uploads so Pillow now only opens the PNG and JPEG formats already allowed by the route, preventing disguised PSD content from being decoded during upload processing.
    *   (Ref: `application/single_app/requirements.txt`, `application/single_app/route_frontend_admin_settings.py`, `functional_tests/test_pillow_psd_upload_hardening.py`)

*   **Changed-Files GitHub Action Supply Chain Remediation**
    *   Updated the release-notes pull request workflow to use the patched `tj-actions/changed-files@v46.0.1` release after the March 2025 supply chain compromise affecting older tag families.
    *   Added a functional regression check to ensure the workflow does not drift back to the known malicious commit or an older vulnerable action reference.
    *   (Ref: `release-notes-check.yml`, `test_changed_files_action_version.py`, GitHub Actions workflow security, CI dependency pinning)

*   **Personal Conversation Notification Scope Detection**
    *   Fixed a scope-detection bug where personal chat completions could save successfully without creating a completion notification or unread dot when unrelated active workspace state was still present in session.
    *   Personal completion-side effects are now determined from the saved conversation type instead of active workspace session values.
    *   (Ref: personal chat scope gating, `route_backend_chats.py`, `test_chat_completion_notifications.py`)

*   **Distributed Background Task Locks**
    *   Added Cosmos-backed distributed lock documents for approval expiry and retention policy background jobs so duplicate execution is reduced across multiple Gunicorn workers and App Service instances.
    *   Kept the current web-app-hosted scheduler model intact so teams can continue running these jobs from the existing App Service while improving cross-worker coordination.
    *   Updated the startup documentation and added functional validation for the distributed lock wiring.
    *   (Ref: `background_tasks.py`, `SIMPLECHAT_STARTUP.md`, `test_background_task_distributed_locks.py`, `test_startup_scheduler_support.py`)

*   **Background Task Default-On Gating**
    *   Updated the web runtime background task gate so scheduler loops now start by default even when `SIMPLECHAT_RUN_BACKGROUND_TASKS` is unset.
    *   Only explicit false-like values such as `0`, `false`, `no`, or `off` now disable the background loops, which matches the requested deployment behavior.
    *   Updated the startup guide and Gunicorn runtime validation test to reflect the new default-on behavior.
    *   (Ref: `app.py`, `SIMPLECHAT_STARTUP.md`, `test_gunicorn_startup_support.py`)

*   **Gunicorn Production Startup Support**
    *   Updated the app bootstrap so production deployments can run cleanly under Gunicorn instead of relying on Flask's built-in server, which is a poor fit for long-lived streaming chat requests on App Service.
    *   Added a shared Gunicorn config, switched the container entrypoint to Gunicorn, and made application initialization idempotent so startup logic can run safely in multi-worker web processes.
    *   Background timer and retention loops are now disabled by default under Gunicorn workers to avoid duplicating scheduler-style threads across workers, while local debug startup continues to use the Flask development server.
    *   (Ref: `app.py`, `gunicorn.conf.py`, `Dockerfile`, `test_gunicorn_startup_support.py`)

*   **Streaming-Only Chat Path**
    *   Updated the first-party chat experience so normal sends, retries, and message edits now use the streaming chat path instead of maintaining a separate non-streaming UI path.
    *   Preserved parity-sensitive behavior by extending the streaming flow to finalize image-generation responses correctly and by adding a backend compatibility bridge for retry, edit, and image-generation requests while the legacy `/api/chat` route remains in transition.
    *   Removed the chat-page streaming toggle, updated the UI to treat streaming as required behavior, and added regression coverage to prevent first-party chat modules from drifting back to direct `/api/chat` calls.
    *   (Ref: `route_backend_chats.py`, `chat-messages.js`, `chat-streaming.js`, `chat-retry.js`, `chat-edit.js`, `chats.html`, `test_streaming_only_chat_path.py`)

*   **Embedding Retry-After Wait Time Handling**
    *   Fixed embedding retries so `429 Too Many Requests` responses now honor server-provided wait times from `Retry-After` style headers instead of always using local backoff timing.
    *   This reduces avoidable repeat throttling during document processing, batched embedding generation, and search embedding requests when Azure OpenAI asks the client to wait.
    *   The existing exponential backoff behavior remains in place as a fallback when the service does not provide a usable retry delay.
    *   (Ref: `functions_content.py`, embedding retry logic, `test_embedding_rate_limit_wait_time.py`)

*   **SQL Plugin Key Vault Secret Storage**
    *   New and updated SQL Query and SQL Schema actions now store sensitive values such as connection strings and passwords in Azure Key Vault when Key Vault secret storage is enabled.
    *   Editing an existing SQL action now preserves stored Key Vault-backed credentials, including the SQL test connection flow, so users do not need to re-enter unchanged secrets just to validate or save the action.
    *   Personal, group, and global action flows now preserve existing secret references during updates, clean them up correctly on delete, and redact secret-bearing plugin values from logs.
    *   Existing plaintext SQL action credentials are not backfilled automatically; they move to Key Vault the next time the action is saved while Key Vault storage is enabled.
    *   (Ref: `functions_keyvault.py`, `route_backend_plugins.py`, `plugin_modal_stepper.js`, `workspace_plugins.js`, SQL action configuration)

*   **Group/Public Expanded Document Tags**
    *   Fixed group and public workspace list views so expanding a document now shows its tags, matching the personal workspace experience.
    *   The fix adds color-coded tag badges with a `No tags` fallback in expanded document details without changing the existing backend document APIs.
    *   (Ref: `group_workspaces.html`, `public_workspace.js`, expanded document details, workspace tag rendering)

*   **Agent Save Validation for Round-Tripped Metadata**
    *   Fixed agent saves failing when an existing personal, group, or global agent was edited and the browser sent back backend-managed audit fields such as `created_at`, `created_by`, `modified_at`, and `modified_by`.
    *   Agent payload sanitization now strips backend-managed audit and Cosmos metadata before schema validation, while preserving server-side tracking during persistence.
    *   (Ref: `functions_agent_payload.py`, `route_backend_agents.py`, agent schema validation, functional test coverage)

*   **Live Tool Invocation Thoughts During Streaming**
    *   Updated plugin thought handling so the chat can surface an immediate `Invoking Plugin.Function` thought as soon as a tool starts, instead of waiting until the tool completes.
    *   Streaming chat now polls pending thoughts while the response is still in flight, allowing the active status badge to switch from model-sending text to the currently executing plugin call during long-running tools such as `WaitPlugin.wait`.
    *   Completed plugin thoughts still include the richer human-readable summaries for wait, math, and generic plugin executions, and broader plugin coverage remains enabled through auto-wrapping for manifest-loaded plugins.
    *   (Ref: `plugin_invocation_logger.py`, `plugin_invocation_thoughts.py`, `chat-thoughts.js`, `chat-streaming.js`, `logged_plugin_loader.py`, `test_logged_core_plugins.py`)
    
*   **Multi-Sheet Workbook Tabular Analysis**
    *   Fixed multi-sheet Excel workbooks being analyzed from the wrong worksheet during tabular chat responses. Questions that clearly target a specific tab, such as asset values in a workbook with `Assets`, `Balance`, and `Income` sheets, no longer silently default to the first sheet.
    *   Tabular runtime analysis now requires explicit `sheet_name` or `sheet_index` selection for analytical calls on multi-sheet workbooks, and the SK mini-agent preload now includes workbook sheet inventory and per-sheet schemas so the model can choose the correct worksheet before computing results.
    *   Enhanced citations and tabular previews now preserve worksheet context, using `Sheet: <name>` for sheet-specific references and `Location: Workbook Schema` for workbook-level schema citations instead of generic `Page 1` labels. The tabular preview modal also supports switching between workbook sheets.
    *   (Ref: `tabular_processing_plugin.py`, `route_backend_chats.py`, `route_enhanced_citations.py`, `chat-enhanced-citations.js`, `chat-citations.js`, `chat-messages.js`)

*   **Tabular Citation Conversation Ownership Check**
    *   Fixed an IDOR vulnerability on `/api/enhanced_citations/tabular` where any authenticated user who could guess a `conversation_id` and `file_id` could download another user's chat-uploaded tabular files.
    *   The endpoint now reads the conversation document from Cosmos DB and verifies that `conversation.user_id` matches the current user before serving the blob. Returns 403 Forbidden on mismatch and 404 if the conversation does not exist.
    *   (Ref: `route_enhanced_citations.py`, `cosmos_conversations_container`)

*   **Tabular Preview `max_rows` Parameter Validation**
    *   The `max_rows` query parameter on `/api/enhanced_citations/tabular_preview` was parsed with bare `int()`, causing a 500 error on non-integer input. Switched to Flask's `request.args.get(..., type=int)` which silently falls back to the default on invalid input, matching the pattern used by other endpoints.
    *   (Ref: `route_enhanced_citations.py`)

*   **Streaming Chat Post-Finalization JSON Sanitization**
    *   Fixed a repeatable late-stream failure where assistant responses could appear nearly complete and then end with a `Stream interrupted` warning during final persistence.
    *   Normalized non-finite numeric values from citation payloads before assistant messages, assistant artifacts, and terminal chat payloads are written, preventing Cosmos DB from rejecting invalid JSON.
    *   This improves reliability for streaming chat, compatibility streaming, and the standard JSON response path when tool or search citations include sparse or tabular numeric values.
    *   (Ref: `functions_message_artifacts.py`, `route_backend_chats.py`, `test_chat_post_stream_json_sanitization.py`, post-stream citation sanitization)

*   **On-Demand Summary Generation — Content Normalization Fix**
    *   Fixed the `POST /api/conversations/<id>/summary` endpoint failing with an error when generating summaries from the conversation details modal.
    *   Root cause: message `content` in Cosmos DB can be a list of content parts (e.g., `[{type: "text", text: "..."}]`) rather than a plain string. The endpoint was passing the raw list as `content_text`, which either stringified incorrectly or produced empty transcript text.
    *   Now uses `_normalize_content()` to properly flatten list/dict content into plain text, matching the export pipeline's behavior.
    *   (Ref: `route_backend_conversations.py`, `_normalize_content`, `generate_conversation_summary`)

*   **Export Summary Reasoning-Model Compatibility**
    *   Fixed export intro summary generation failing or returning empty content with reasoning-series models (gpt-5, o1, o3) through a series of incremental fixes: using `developer` role instead of `system` for instruction messages, removing all `max_tokens` / `max_completion_tokens` caps so the model decides output length naturally, and adding null-safe content extraction for `None` responses.
    *   Summary now includes ALL messages (user, assistant, system, file, image analysis) for full context, with a simplified prompt producing 1-2 factual paragraphs.
    *   Added detailed debug logging showing message count, character count, model name, role, and finish reason.
    *   (Ref: `route_backend_conversation_export.py`, `_build_summary_intro`, `generate_conversation_summary`)

*   **Conversation Export Schema and Markdown Refresh**
    *   Fixed conversation exports lagging behind the live chat schema. JSON exports now include processing thoughts, normalized citations, and the raw document/web/tool citation buckets stored with assistant messages.
    *   Fixed Markdown exports being too flat and text-heavy by reorganizing them into a transcript-first layout with appendices for metadata, message details, references, thoughts, and supplemental records.
    *   Fixed exported conversations including content that no longer matched the visible chat by filtering deleted messages and inactive-thread retries, then reapplying thread-aware ordering before export.
    *   (Ref: `route_backend_conversation_export.py`, `test_conversation_export.py`, conversation export rendering)

*   **Export Tag/Classification Rendering Fix**
    *   Fixed conversation tags and classifications rendering as raw Python dicts (e.g., `{'category': 'model', 'value': 'gpt-5'}`) in both Markdown and PDF exports.
    *   Tags now display as readable `category: value` strings, with smart handling for participant names, document titles, and generic category/value pairs.
    *   (Ref: `route_backend_conversation_export.py`, `_format_tag` helper, Markdown/PDF metadata rendering)

*   **Export Summary Error Visibility**
    *   Added `debug_print` and `log_event` logging to all summary generation error paths, including the empty-response path that previously failed silently.
    *   The actual error detail is now shown in both Markdown and PDF exports when summary generation fails, replacing the generic "could not be generated" message.
    *   (Ref: `route_backend_conversation_export.py`, `_build_summary_intro`, export error rendering)

*   **Content Safety for Streaming Chat Path**
    *   Added full Azure AI Content Safety checking to the streaming (`/api/chat/stream`) SSE path, matching the existing non-streaming (`/api/chat`) implementation.
    *   Previously, only the non-streaming path performed content safety analysis; streaming conversations bypassed safety checks entirely.
    *   Implementation includes: `AnalyzeTextOptions` analysis, severity threshold checking (severity ≥ 4 blocks the message), blocklist matching, persistence of blocked messages to `cosmos_safety_container`, creation of safety-role message documents, and proper SSE event delivery of blocked status to the client.
    *   On block, the streaming generator yields the safety message and `[DONE]` event, then stops — preventing any further LLM invocation.
    *   Errors in the content safety call are caught and logged without breaking the chat flow, consistent with the non-streaming behavior.
    *   (Ref: `route_backend_chats.py`, streaming SSE generator, `AnalyzeTextOptions`, `cosmos_safety_container`)

*   **SQL Schema Plugin — Eliminate Redundant Schema Calls**
    *   Fixed agent calling `get_database_schema` twice per query even though the full schema was already injected into the agent's instructions at load time.
    *   Root cause: The `@kernel_function` descriptions in `sql_schema_plugin.py` said "ALWAYS call this function FIRST," which overrode the schema context already available in the instructions.
    *   Updated all four function descriptions (`get_database_schema`, `get_table_schema`, `get_table_list`, `get_relationships`) to use the resilient pattern: "If the database schema is already provided in your instructions, use that directly and do NOT call this function."
    *   This eliminates ~400ms+ of unnecessary database round trips per query and aligns with the same pattern already used in `sql_query_plugin.py`.
    *   (Ref: `sql_schema_plugin.py`, `@kernel_function` descriptions, schema injection)

*   **SQL Schema Plugin — Empty Tables from INFORMATION_SCHEMA**
    *   Fixed `get_database_schema` returning `'tables': {}` (empty) despite the database having tables, while relationships were returned correctly.
    *   Root cause: SQL Server table/column enumeration used `INFORMATION_SCHEMA.TABLES` and `INFORMATION_SCHEMA.COLUMNS` views, which returned empty results in the Azure SQL environment. Meanwhile, the relationships query used `sys.foreign_keys`/`sys.tables`/`sys.columns` catalog views which worked perfectly.
    *   Migrated all SQL Server schema queries to use `sys.*` catalog views consistently: `sys.tables`/`sys.schemas` for table enumeration, `sys.columns` with `TYPE_NAME()` for column details, and `sys.indexes`/`sys.index_columns` for primary key detection.
    *   Fixed `pyodbc.Row` handling throughout the plugin — removed all `isinstance(table, tuple)` checks that could fail with pyodbc Row objects, replaced with robust try/except indexing.
    *   This enables the full schema (tables, columns, types, PKs, FKs) to be injected into agent instructions, allowing agents to construct complex multi-table JOINs for analytical queries.
    *   (Ref: `sql_schema_plugin.py`, `sys.tables`, `sys.columns`, `sys.indexes`, pyodbc.Row handling)

*   **SQL Query Plugin — Auto-Create Companion Schema Plugin**
    *   Fixed the remaining issue where SQL-connected agents still asked for clarification instead of querying the database, even after description improvements.
    *   Root cause: Agents configured with only a `sql_query` action never had a `SQLSchemaPlugin` loaded in the kernel. The descriptions demanded calling `get_database_schema` — a function that didn't exist — creating an impossible dependency that caused the LLM to ask for clarification.
    *   `LoggedPluginLoader` now automatically creates a companion `SQLSchemaPlugin` whenever a `SQLQueryPlugin` is loaded, using the same connection details. This ensures schema discovery is always available.
    *   Updated `@kernel_function` descriptions to be resilient: "If the database schema is provided in your instructions, use it directly. Otherwise, call get_database_schema." This dual-path approach works whether schema is injected via instructions or available via plugin functions.
    *   Added fallback in `_extract_sql_schema_for_instructions()` to also detect `SQLQueryPlugin` instances and create a temporary schema extractor if no `SQLSchemaPlugin` is found.
    *   (Ref: `logged_plugin_loader.py`, `sql_query_plugin.py`, `semantic_kernel_loader.py`)

*   **SQL Query Plugin Schema Awareness**
    *   Fixed agents connected to SQL databases asking users for clarification about table/column names instead of querying the database directly.
    *   Root cause: SQL Query and SQL Schema plugin `@kernel_function` descriptions were generic with no workflow guidance, agent instructions had no database schema context, and the two plugins operated independently with no linkage.
    *   Rewrote all `@kernel_function` descriptions in both SQL plugins to be prescriptive workflow guides (modeled after the working LogAnalyticsPlugin), explicitly instructing the LLM to discover schema first before generating queries.
    *   Added auto-injection of database schema into agent instructions at load time — when SQL Schema plugins are detected, the full schema (tables, columns, types, relationships) is fetched and appended to the agent's system prompt.
    *   Added new `query_database(question, query)` convenience function to `SQLQueryPlugin` for intent-aligned tool calling.
    *   Enabled the SQL-specific plugin creation path in `logged_plugin_loader.py` (was previously commented out).
    *   (Ref: `sql_query_plugin.py`, `sql_schema_plugin.py`, `semantic_kernel_loader.py`, `logged_plugin_loader.py`)

*   **Chat-Uploaded Tabular Files Now Trigger SK Mini-Agent in Model-Only Mode**
    *   Fixed an issue where tabular files (CSV, XLSX, XLS, XLSM) uploaded directly to a chat conversation were not analyzed by the SK mini-agent when no agent was selected. The model would describe what analysis it would perform instead of returning actual computed results.
    *   **Root Cause**: The mini SK agent only triggered from search results, but chat-uploaded files are stored in blob storage and not indexed in Azure AI Search. Additionally, the streaming path completely ignored `file` role messages in conversation history.
    *   **Fix**: Both streaming and non-streaming chat paths now detect chat-uploaded tabular files during conversation history building and trigger `run_tabular_sk_analysis(source_hint="chat")` to pre-compute results. The streaming path also now properly handles `file` role messages (tabular and non-tabular) matching the non-streaming path's behavior.
    *   (Ref: `route_backend_chats.py`, `run_tabular_sk_analysis()`, `collect_tabular_sk_citations()`)

*   **Group SQL Action/Plugin Save Failure**
    *   Fixed group SQL actions (sql_query and sql_schema types) failing to save correctly due to missing endpoint placeholder. Group routes now apply the same `sql://sql_query` / `sql://sql_schema` endpoint logic as personal action routes.
    *   Fixed Step 4 (Advanced) dynamic fields overwriting Step 3 (Configuration) SQL values with empty strings during form data collection. SQL types now skip the dynamic field merge entirely since Step 3 already provides all necessary configuration.
    *   Fixed auth type definition schemas (`sql_query.definition.json`, `sql_schema.definition.json`) only allowing `connection_string` auth type, blocking `user`, `identity`, and `servicePrincipal` types that the UI and runtime support.
    *   Fixed `__Secret` key suffix mismatch in additional settings schemas where `connection_string__Secret` and `password__Secret` didn't match the runtime's expected `connection_string` and `password` field names. Also removed duplicate `azuresql` enum value.
    *   (Ref: `route_backend_plugins.py`, `plugin_modal_stepper.js`, `sql_query.definition.json`, `sql_schema.definition.json`, `sql_query_plugin.additional_settings.schema.json`, `sql_schema_plugin.additional_settings.schema.json`)

*   **Workspace Model Endpoint Scope Gate Enforcement**
    *   Fixed personal and group workspace model discovery and model test routes so they now enforce the same custom-endpoint feature gates as the corresponding endpoint management routes.
    *   Restored the intended endpoint modal workflow so users can still fetch and test models before saving a new personal or group endpoint when those scope features are enabled.
    *   Requests that reference a saved endpoint now resolve against the caller's authorized persisted endpoint configuration instead of allowing raw request payloads to override stored settings.
    *   (Ref: `route_backend_models.py`, `workspace_model_endpoints.js`, `test_model_endpoint_scope_gate_enforcement.py`, model endpoint scope gating)

*   **Workspace Agent View Consistency**
    *   Fixed personal and group workspace agent lists so table-view actions now use the same button order, making agent management behavior more predictable across both workspaces.
    *   Fixed group workspace agent grid cards so editable group agents once again show Edit and Delete actions when the current user has permission to manage them.
    *   Fixed personal workspace agent table layout so action buttons stay inside the table instead of overflowing past the Actions column.
    *   (Ref: `workspace.html`, `workspace_agents.js`, `group_agents.js`, `view-utils.js`, `test_workspace_agent_views_consistency.py`)

*   **MultiGPT Endpoint Key Vault Secret Storage and Foundry Fetch Reliability**
    *   MultiGPT endpoint secrets such as API keys and service principal client secrets now move into Azure Key Vault when Key Vault secret storage is enabled, instead of remaining in saved endpoint payloads.
    *   Endpoint fetch, test, Foundry listing, and runtime execution now resolve stored secrets server-side by endpoint ID, so reopening an endpoint no longer depends on the browser still holding plaintext credentials.
    *   Fixed a follow-up regression in Foundry model discovery where sync fetch routes could fail with `'coroutine' object has no attribute 'token'` because async credentials were being reused in a synchronous token acquisition path.
    *   (Ref: `functions_keyvault.py`, `functions_settings.py`, `route_backend_models.py`, `route_frontend_admin_settings.py`, `semantic_kernel_loader.py`, `foundry_agent_runtime.py`, `admin_model_endpoints.js`, `workspace_model_endpoints.js`, `test_model_endpoints_key_vault_secret_storage.py`, `test_foundry_model_fetch_sync_credentials.py`)

### **(v0.239.002)**

#### New Features

*   **Conversation Export**
    *   Export one or multiple conversations from the Chat page in JSON or Markdown format.
    *   **Single Export**: Use the ellipsis menu on any conversation to quickly export it.
    *   **Multi-Export**: Enter selection mode, check the conversations you want, and click the export button.
    *   A guided 4-step wizard walks you through selection review, format choice, packaging options (single file or ZIP archive), and download.
    *   Sensitive internal metadata is automatically stripped from exported data for security.

*   **Retention Policy UI for Groups and Public Workspaces**
    *   Can now configure conversation and document retention periods directly from the workspace and group management page.
    *   Choose from preset retention periods ranging from 7 days to 10 years, use the organization default, or disable automatic deletion entirely.
*   **Owner-Only Group Agent and Action Management**
    *   New admin setting to restrict group agent and group action management (create, edit, delete) to only the group Owner role.
    *   **Admin Toggle**: "Require Owner to Manage Group Agents and Actions" located in Admin Settings > My Groups section, under the existing group creation membership setting.
    *   **Default Off**: When disabled, both Owner and Admin roles can manage group agents and actions (preserving existing behavior).
    *   **When Enabled**: Only the group Owner can create, edit, and delete group agents and group actions. Group Admins and other roles are restricted to read-only access.
    *   **Backend Enforcement**: Server-side validation returns 403 for non-Owner users attempting create, update, or delete operations on group agents and actions.
    *   **Frontend Enforcement**: "New Agent" and "New Action" buttons are hidden, edit/delete controls are removed, and a permission warning is displayed for non-Owner users.
    *   **Files Modified**: `functions_settings.py`, `admin_settings.html`, `route_frontend_admin_settings.py`, `route_backend_agents.py`, `route_backend_plugins.py`, `group_workspaces.html`, `group_agents.js`, `group_plugins.js`.
    *   (Ref: `require_owner_for_group_agent_management` setting, `assert_group_role` permission check)

*   **Enforce Workspace Scope Lock**
    *   New admin setting to control whether users can unlock workspace scope in chat conversations.
    *   **Enabled by Default**: When enabled, workspace scope automatically locks after the first AI search and users cannot unlock it, preventing accidental cross-contamination between data sources.
    *   **Informational Modal**: Users can still click the lock icon to view which workspaces are locked, but the "Unlock Scope" button is hidden and replaced with an informational message.
    *   **Backend Enforcement**: Server-side validation rejects unlock API requests when the setting is enabled, providing defense-in-depth security.
    *   **Admin Toggle**: Located in Admin Settings > Workspace tab in the new "Workspace Scope Lock" section.
    *   **Files Modified**: `config.py`, `functions_settings.py`, `route_frontend_admin_settings.py`, `admin_settings.html`, `chats.html`, `chat-documents.js`, `route_backend_conversations.py`.
    *   (Ref: `ENFORCE_WORKSPACE_SCOPE_LOCK.md`)

*   **Blob Metadata Tag Propagation**
    *   Document tags now propagate to Azure Blob Storage metadata when enhanced citations is enabled.
    *   **Automatic Sync**: When tags are added, removed, or updated on a document, the corresponding blob's metadata is updated with a `document_tags` field containing a comma-separated list of tags.
    *   **Conditional**: Only active when `enable_enhanced_citations` is enabled in admin settings; no blob metadata changes occur otherwise.
    *   **Cross-Workspace**: Works for personal, group, and public workspace documents.
    *   **Non-Blocking**: Blob metadata update failures are logged but do not prevent the primary tag propagation to AI Search chunks.
    *   **Files Modified**: `functions_documents.py`.
    *   (Ref: `BLOB_METADATA_TAG_PROPAGATION.md`)

*   **Document Tag System**
    *   Comprehensive tag management system for organizing documents across personal, group, and public workspaces.
    *   **Tag Definitions**: Tags with custom colors from a 10-color default palette (blue, green, amber, red, purple, pink, cyan, lime, orange, indigo) or user-specified hex codes. Colors assigned deterministically via character-sum hash.
    *   **Full CRUD API**: 15 endpoints (5 per workspace type) for listing, creating, bulk tagging, renaming/recoloring, and deleting tags. Consistent API pattern across `/api/documents/tags`, `/api/group_documents/<id>/tags`, and `/api/public_workspace_documents/<id>/tags`.
    *   **Bulk Tag Operations**: Apply, remove, or replace tags on multiple documents in a single operation with per-document success/error reporting.
    *   **AI Search Integration**: Tags propagate to all document chunks via `propagate_tags_to_chunks()`, enabling OData tag filtering during hybrid search with AND logic (`document_tags/any(t: t eq 'tag')`).
    *   **Tag Validation**: Max 50 characters, alphanumeric plus hyphens/underscores only, normalized to lowercase, duplicates silently deduplicated.
    *   **Tag Storage**: Personal tags in user settings, group tags on group Cosmos document, public workspace tags on workspace Cosmos document.
    *   **Files Modified**: `functions_documents.py`, `functions_search.py`, `route_backend_documents.py`, `route_backend_group_documents.py`, `route_backend_public_documents.py`.
    *   **Files Added**: `static/json/ai_search-index-user.json`, `static/json/ai_search-index-group.json`, `static/json/ai_search-index-public.json`.
    *   (Ref: Document Tag System, AI Search OData filtering, cross-workspace tags, `DOCUMENT_TAG_SYSTEM.md`)

*   **Workspace Folder View (Grid View)**
    *   Toggle between traditional list view and folder-based grid view for workspace documents via radio buttons.
    *   **Tag Folders**: Color-coded folder cards displaying tag name, document count, folder icon, and context menu (rename, recolor, delete).
    *   **Special Folders**: "Untagged" folder for documents with no tags and "Unclassified" folder for documents without classification (when classification is enabled).
    *   **Folder Drill-Down**: Click a folder to view its contents with breadcrumb navigation, in-folder search, configurable page sizes (10, 20, 50), and sort by filename or title.
    *   **Grid Sort Controls**: Sort folder overview by name or file count with ascending/descending toggle.
    *   **View Persistence**: Selected view preference saved to localStorage and restored on page load.
    *   **Tag Management Modal**: Step-through workflow for creating, editing, renaming, recoloring, and deleting tags with color picker.
    *   **Cross-Workspace Support**: Equivalent grid view and tag management available in group workspaces (inline JS) and public workspaces.
    *   **Files Added**: `workspace-tags.js` (1257 lines), `workspace-tag-management.js` (732 lines).
    *   **Files Modified**: `workspace.html`, `group_workspaces.html`, `public_workspaces.html`, `public_workspace.js`.
    *   (Ref: Folder view, tag management modal, grid rendering, `WORKSPACE_FOLDER_VIEW.md`)

*   **Multi-Workspace Scope Management**
    *   Select from Personal, multiple Group, and multiple Public workspaces simultaneously in the chat interface.
    *   **Hierarchical Scope Dropdown**: Organized sections with checkbox multi-selection and "Select All / Clear All" toggle with indeterminate state support.
    *   **Scope Locking**: Per-conversation lock that freezes workspace selection after the first AI Search. Three-state machine: `null` (auto-lockable) → `true` (locked) → `false` (user-unlocked) → `true` (re-lockable).
    *   **Lock Indicator**: Visual lock icon with tooltip showing locked workspace names. Locked workspaces appear grayed out in the dropdown.
    *   **Lock/Unlock Modal**: Dialog for manually toggling scope lock per conversation.
    *   **Lock Persistence**: Lock state stored in conversation metadata via `PATCH /api/conversations/<id>/scope_lock`.
    *   **Workspace Search Container**: Multi-column flex layout (Scope → Tags → Documents) with connected card UI and viewport boundary detection.
    *   **Files Modified**: `chat-documents.js`, `chat-messages.js`, `chats.html`, `route_backend_chats.py`, `route_backend_conversations.py`.
    *   (Ref: Multi-workspace selection, scope locking, search container layout, `MULTI_WORKSPACE_SCOPE_MANAGEMENT.md`)

*   **Chat Document and Tag Filtering**
    *   Checkbox-based multi-document selection replacing the legacy single-document dropdown in the chat interface.
    *   **Custom Document Dropdown**: Checkboxes for each document with real-time search, "All Documents" option, and selected count display ("3 Documents").
    *   **Scope Indicators**: Each document labeled with its source workspace: `[Personal]`, `[Group: Name]`, or `[Public: Name]`.
    *   **Multi-Tag Filtering**: Checkbox dropdown for selecting tags to filter the document list. Classification categories shown with color coding when enabled.
    *   **Dynamic Tag Loading**: Tags load and merge across all selected scope workspaces with aggregated counts.
    *   **DOM-Based Filtering**: Non-matching documents removed from the DOM (not hidden via CSS), following project conventions. Removed items stored for restoration when filters change.
    *   **Backend Integration**: Selected document IDs and tags sent in chat request body. Backend constructs OData AND filter: `document_tags/any(t: t eq 'tag1') and document_tags/any(t: t eq 'tag2')`.
    *   **Files Modified**: `chat-documents.js`, `chat-messages.js`, `functions_search.py`, `route_backend_chats.py`, `chats.html`.
    *   (Ref: Multi-document selection, tag filtering, OData search integration, `CHAT_DOCUMENT_AND_TAG_FILTERING.md`)

#### Bug Fixes

*   **Citation Parsing Bug Fix**
    *   Fixed citation parsing edge cases where page range references (e.g., "Pages: 1-5") failed to generate correct clickable links when not all pages had explicit reference IDs in the bracketed citation section of the AI response.
    *   **Root Cause**: The `parseCitations()` function only generated links for pages with existing `[doc_prefix_N]` bracket references, leaving pages without explicit references as non-functional text.
    *   **Solution**: Added auto-fill logic using `getDocPrefix()` to extract the document ID prefix from known reference patterns and construct missing page references (e.g., if `[doc_abc_1]` exists, infer `doc_abc_2` through `doc_abc_5`).
    *   **Files Modified**: `chat-citations.js`.
    *   (Ref: Citation parsing, page range handling, `CITATION_IMPROVEMENTS.md`)

*   **Public Workspace setActive 403 Fix**
    *   Fixed issue where non-owner/admin/document-manager users received a 403 "Not a member" error when trying to activate a public workspace for chat.
    *   Root cause was an overly restrictive membership check on the `/api/public_workspaces/setActive` endpoint that only allowed owners, admins, and document managers — even though public workspaces are intended to be accessible to all authenticated users for chatting.
    *   Removed the membership verification from the `setActive` endpoint; the route still requires authentication (`@login_required`, `@user_required`) and the public workspaces feature flag (`@enabled_required`).
    *   Other admin-level endpoints (listing members, viewing stats, ownership transfer) retain their membership checks.
    *   (Ref: `route_backend_public_workspaces.py`, `api_set_active_public_workspace`)
*   **Chats Page User Settings Hardening**
    *   Fixed a user-specific chats page failure where only one affected user could not load `/chats` due to malformed per-user settings data.
    *   **Root Cause**: The chats route assumed `user_settings["settings"]` was always a dictionary. If that field existed but had an invalid type (for example string, null, or list), the page could fail before rendering.
    *   **Solution**: Hardened `get_user_settings()` to normalize missing/malformed `settings` to `{}` and persist the repaired document. Hardened the chats route to use safe dictionary fallbacks when reading nested settings values.
    *   **Telemetry**: Added repair logging (`[UserSettings] Malformed settings repaired`) to improve diagnostics for future user-specific data-shape issues.
    *   **Files Modified**: `functions_settings.py`, `route_frontend_chats.py`, `config.py`.
    *   **Files Added**: `test_chats_user_settings_hardening_fix.py`, `CHATS_USER_SETTINGS_HARDENING_FIX.md`.
    *   (Ref: user settings normalization, `/chats` route resilience, `functional_tests/test_chats_user_settings_hardening_fix.py`, `docs/explanation/fixes/CHATS_USER_SETTINGS_HARDENING_FIX.md`)

*   **Tag Filter Input Sanitization (Injection Prevention)**
    *   Added `sanitize_tags_for_filter()` function to validate tag filter inputs against the same `^[a-z0-9_-]+$` character whitelist enforced when saving tags.
    *   Previously, tag filter values from query parameters only passed through `normalize_tag()` (strip + lowercase) without character validation, allowing arbitrary characters to reach OData filter construction in `build_tags_filter()`.
    *   Hardened `build_tags_filter()` in `functions_search.py` to validate tags before interpolating into OData expressions, eliminating the OData injection vector.
    *   Updated tag filter parsing in personal, group, and public document routes to use `sanitize_tags_for_filter()` for defense-in-depth.
    *   Invalid tag filter values are silently dropped (they cannot match any stored tag).
    *   **Files Modified**: `functions_documents.py`, `functions_search.py`, `route_backend_documents.py`, `route_backend_group_documents.py`, `route_backend_public_documents.py`.
    *   (Ref: `TAG_FILTER_INJECTION_FIX.md`, `sanitize_tags_for_filter`)

#### User Interface Enhancements

*   **Extended Document Dropdown Width**
    *   Widened the document selection dropdown in the chat interface for improved readability of long filenames. Dropdown width now dynamically adapts to the parent container.
    *   **Files Modified**: `chat-documents.js`.
    *   (Ref: Document dropdown, UI readability)

*   **Enhanced Citation Links**
    *   Robust inline citation links with support for both inline source references and hybrid citation buttons.
    *   Metadata citation support for viewing extracted document metadata including OCR text, vision analysis, and detected objects via the enhanced citation modal.
    *   Improved error handling in citation JSON parsing with graceful fallback for malformed citation strings.
    *   **Files Modified**: `chat-citations.js`, `chat-enhanced-citations.js`.
    *   (Ref: Citation rendering, metadata citations, enhanced citation modal, `CITATION_IMPROVEMENTS.md`)

### **(v0.237.049)**

#### Bug Fixes

*   **Plugin Schema Validation `$ref` Resolution Fix**
    *   Fixed HTTP 500 error when creating or saving user plugins (actions). The JSON schema validator could not resolve `$ref: '#/definitions/AuthType'` because the `Plugin` sub-schema was extracted without a `RefResolver`, losing access to the parent schema's `definitions` block.
    *   **Root Cause**: `validate_plugin()` created a `Draft7Validator` using only `schema['definitions']['Plugin']`, which did not include the `definitions` section containing `AuthType`. The `validate_agent()` function already handled this correctly with `RefResolver.from_schema(schema)`.
    *   **Solution**: Added a `RefResolver` created from the full schema so that `$ref` pointers resolve correctly during validation.
    *   (Ref: `json_schema_validation.py`, `plugin.schema.json`, `AuthType` definition, `RefResolver`)

*   **Personal Agent Missing `user_id` Fix**
    *   Fixed issue where personal agents were saved to Cosmos DB without a `user_id` field, making them invisible to the user who created them.
    *   **Root Cause**: `save_personal_agent()` built a `cleaned_agent` dict with the correct `user_id`, `id`, and metadata, but the second half of the function switched to operating on the raw `agent_data` parameter. The final `upsert_item(body=agent_data)` saved the object that never had `user_id` assigned.
    *   **Solution**: Changed all `agent_data` references after sanitization to use `cleaned_agent` consistently, ensuring `user_id` and all other fields are included in the persisted document.
    *   (Ref: `functions_personal_agents.py`, `save_personal_agent`, Cosmos DB personal agents container)

*   **Global Agent Creation Blocked by `global_selected_agent` Check Fix**
    *   Fixed HTTP 400 error "There must be at least one agent matching the global_selected_agent" when adding or editing global agents.
    *   **Root Cause**: The add and edit agent routes performed a post-save check verifying that a global agent matched the `global_selected_agent` setting. This check was incorrect for add operations (adding an agent can never remove the selected one) and had a side-effect bug where the agent was already persisted before the 400 error was returned.
    *   **Solution**: Removed the post-save `global_selected_agent` enforcement from the add and edit routes. The delete route already correctly prevents deletion of the selected agent.
    *   (Ref: `route_backend_agents.py`, global agent add/edit routes, `global_selected_agent` setting)

### **(v0.237.011)**

#### Bug Fixes

*   **Chat File Upload "Unsupported File Type" Fix**
    *   Fixed issue where uploading xlsx, png, jpg, csv, and other image/tabular files in the chat interface returned a 400 "Unsupported file type" error.
    *   **Root Cause**: `os.path.splitext()` returns extensions with a leading dot (e.g., `.png`), but the `IMAGE_EXTENSIONS` and `TABULAR_EXTENSIONS` sets in `config.py` store extensions without dots (e.g., `png`). The comparison `'.png' in {'png', ...}` was always `False`, causing all image and tabular uploads to fall through to the unsupported file type error.
    *   **Solution**: Added `file_ext_nodot = file_ext.lstrip('.')` and used the dot-stripped extension for set comparisons against `IMAGE_EXTENSIONS` and `TABULAR_EXTENSIONS`, matching the pattern already used in `functions_documents.py`.
    *   (Ref: `route_frontend_chats.py`, file extension comparison, `IMAGE_EXTENSIONS`, `TABULAR_EXTENSIONS`)

*   **Manage Group Page Duplicate Code and Error Handling Fix**
    *   Fixed multiple code quality and user experience issues in the Manage Group page JavaScript.
    *   **Duplicate Event Handlers**: Removed duplicate event handler registrations (lines 96-127) for `.select-user-btn`, `.remove-member-btn`, `.change-role-btn`, `.approve-request-btn`, and `.reject-request-btn` that were causing multiple event firings.
    *   **Duplicate HTML in Actions Column**: Fixed member action buttons rendering duplicate attributes as visible text instead of functional buttons, causing raw HTML/CSS class names to display in the Actions column.
    *   **Duplicate Pending Request Buttons**: Removed duplicate Approve and Reject buttons in pending requests table that were appearing twice per request.
    *   **Enhanced Error Handling**: Improved `setRole()` and `removeMember()` functions with specific error messages for 404 (member not found) and 403 (permission denied) errors, automatic member list refresh on 404, and user-friendly toast notifications instead of generic alerts.
    *   **Removed Duplicate Comment**: Cleaned up duplicate "Render user-search results" comment.
    *   **Impact**: Member management buttons now render and function correctly, provide better error feedback, and auto-recover from stale member data.
    *   (Ref: `manage_group.js`, event handler deduplication, error handling improvements, toast notifications)

### **(v0.237.009)**

#### New Features

*   **ServiceNow Integration Documentation**
    *   Comprehensive documentation for integrating ServiceNow with Simple Chat, including step-by-step guides for both Basic Authentication and OAuth 2.0.
    *   **OAuth 2.0 Setup**: Detailed guide for Resource Owner Password Credential grant type with production security considerations.
    *   **OpenAPI Specifications**: 7 OpenAPI YAML files for ServiceNow Incident Management and Knowledge Base APIs (both bearer token and basic auth versions).
    *   **Agent Instructions**: Behavioral instructions optimized for ServiceNow operations (263 lines).
    *   **Key Features**: Integration user creation, role assignment guidance, token management strategies, troubleshooting guide, and production deployment considerations.
    *   **Documentation Files**: `SERVICENOW_INTEGRATION.md` (760 lines), `SERVICENOW_OAUTH_SETUP.md` (480+ lines), `servicenow_agent_instructions.txt`, and 7 OpenAPI specs in `docs/guides/servicenow/`.
    *   (Ref: ServiceNow integration, OAuth 2.0, OpenAPI specifications, enterprise integrations)

#### Bug Fixes

*   **Workspace Search Deselection KeyError Fix**
    *   Fixed HTTP 500 error when deselecting the workspace search button after having a document selected. Users would get "Could not get a response. HTTP error! status: 500" in the chat interface.
    *   **Root Cause**: When workspace search was deselected (`hybrid_search_enabled = False`), the `user_metadata['workspace_search']` dictionary was never initialized. However, subsequent code for handling group scope or public workspace context attempted to access `user_metadata['workspace_search']['group_name']` or other properties, causing a KeyError.
    *   **Error**: `KeyError: 'workspace_search'` at lines 468, 479 in `route_backend_chats.py` when trying to set group_name or active_public_workspace_id.
    *   **Solution**: Added defensive checks before accessing `user_metadata['workspace_search']`. If the key doesn't exist, initialize it with `{'search_enabled': False}` before attempting to set additional properties like group_name or workspace IDs.
    *   **Workaround**: Clicking Home and then back to Chat worked because it triggered a page reload that reset the state properly.
    *   (Ref: `route_backend_chats.py`, workspace search, metadata initialization, KeyError handling)

*   **OpenAPI Basic Authentication Fix**
    *   Fixed "session not authenticated" errors when using Basic Authentication with OpenAPI actions, even when credentials were correct.
    *   **Root Cause**: Mismatch between how the UI stored Basic Auth credentials (as `username:password` string in `auth.key`) and how the OpenAPI plugin factory expected them (as separate `username` and `password` properties in `additionalFields`).
    *   **Solution**: Modified `OpenApiPluginFactory` to detect and parse `username:password` format from `auth.key`, splitting credentials into separate properties that the authentication middleware expects.
    *   **Files Modified**: `semantic_kernel_plugins/openapi_plugin_factory.py`.
    *   (Ref: OpenAPI actions, Basic Authentication, credential parsing, `OPENAPI_BASIC_AUTH_FIX.md`)

*   **Group Action OAuth Schema Merging Fix**
    *   Fixed HTTP 401 Unauthorized errors when using OAuth bearer token authentication with group actions. When editing group actions, `additionalFields` was empty, missing all authentication configuration.
    *   **Root Cause**: Group action backend routes did not call `get_merged_plugin_settings()` to merge UI form data with OpenAPI schema defaults, while global action routes did. This caused group actions to be saved without authentication configuration fields like `auth_method`, `base_url`, and authentication credentials.
    *   **Solution**: Updated group action save/update routes in `route_backend_plugins.py` to call `get_merged_plugin_settings()`, ensuring authentication configuration is properly merged and persisted.
    *   **Files Modified**: `route_backend_plugins.py`.
    *   (Ref: Group actions, OAuth authentication, schema merging, `GROUP_ACTION_OAUTH_SCHEMA_MERGING_FIX.md`)

*   **Group Agent Loading Fix**
    *   Fixed issue where group agents were not appearing in the agent list when per-user semantic kernel mode was enabled. Users selecting group agents would fall back to the global "researcher" agent with zero plugins/actions available.
    *   **Root Cause**: The `load_user_semantic_kernel()` function only loaded personal agents and global agents (when merge enabled), but completely omitted group agents from groups the user is a member of.
    *   **Solution**: Updated `load_user_semantic_kernel()` to fetch and load group agents for all groups the user is a member of, ensuring proper agent availability in per-user kernel mode.
    *   **Files Modified**: `semantic_kernel_loader.py`.
    *   (Ref: Group agents, per-user semantic kernel, agent loading, `GROUP_AGENT_LOADING_FIX.md`)

*   **Manage Group Page Syntax Error Fix**
    *   Fixed critical JavaScript syntax error preventing the manage group page from loading. Removed duplicate code blocks including duplicate conditional checks, forEach loops, button tags, and function definitions.
    *   The page was stuck on "Loading..." indefinitely with console error "Uncaught SyntaxError: missing ) after argument list" at line 673.
    *   (Ref: `manage_group.js`, duplicate code removal, syntax error resolution)

*   **File Extension Handling Improvements**
    *   Fixed multiple issues related to file extension handling and audio transcription across the application.
    *   **Missing MP3 Extension**: Fixed issue where .mp3 files were missing from the list of allowed extensions. Users attempting to upload mp3 files to workspaces saw "Uploaded 0/1, Failed: 1" with no error logging to activity_logs or documents containers.
    *   **Centralized Extension Definitions**: Resolved file extension variable duplications throughout codebase by centralizing all allowed file extension definitions in `config.py` and importing them in downstream function and route files. This prevents extension lists from going out of sync during updates.
    *   **Additional Supported Extensions**: Added missing file types supported by Document Intelligence and Video Indexer services: .heic (image), .mpg, .mpeg, .webm (video).
    *   **Browser-Compatible Extensions**: Adjusted file extensions in `chat-enhanced-citations.js` for proper browser rendering. Removed incompatible formats like .heif and added compatible formats like .3gp after thorough testing.
    *   (Ref: `config.py`, file extension centralization, enhanced citations rendering)

*   **Audio Transcription Continuous Recognition Fix (MAG)**
    *   Fixed incomplete audio transcriptions in Azure Government (MAG) environments where transcription stopped at first silence or after 30 seconds of audio.
    *   **Root Cause**: Previous implementation used `recognize_once()` method which stops transcription at the first silence (end of sentence, speaker pauses) and has a maximum 30-second transcription limit.
    *   **Solution**: Implemented continuous recognition using `start_continuous_recognition()` method instead of `recognize_once()`, enabling full-length audio file transcription without interruption at natural speech pauses.
    *   **Impact**: Audio files now transcribe completely regardless of length or natural pauses in speech, improving transcription quality and completeness in MAG regions where Fast Transcription API is unavailable.
    *   (Ref: Azure Speech Service, continuous recognition, MAG support, audio transcription)

*   **Workspace File Metadata Edit Error Fix**
    *   Fixed "'tuple' object has no attribute 'get'" error when clicking Save after editing workspace file metadata in personal, group, or public workspaces.
    *   **Root Cause**: Missing checks and error handling in route backend documents code when processing metadata updates.
    *   **Solution**: Added additional validation checks and proper handling to `route_backend_documents.py` for all workspace types (personal, group, public).
    *   **Impact**: Users can now successfully edit and save file metadata without encountering errors.
    *   (Ref: `route_backend_documents.py`, metadata updates, error handling)

### **(v0.237.007)**

#### Bug Fixes

*   **Sidebar Conversations Race Condition and DOM Manipulation Fix**
    *   Fixed two critical issues preventing sidebar conversations from displaying correctly for users.
    *   **Issue #1 - DOM Manipulation Error**: Fixed JavaScript error `NotFoundError: Failed to execute 'insertBefore' on 'Node'` that caused sidebar conversation list to fail to render. Root cause was incorrect order of DOM element manipulation where `insertBefore()` was called with an invalid reference node after elements had been moved/removed.
    *   **Issue #2 - Race Condition with Empty Conversations**: Fixed race condition where users with no existing conversations who created their first conversation would not see it appear in the sidebar. Root cause was the loading flag never being reset when API returned empty conversations array, causing all subsequent reload attempts to be blocked indefinitely.
    *   **Solution Part 1**: Enhanced DOM manipulation with stricter parent node validation (`dropdownElement.parentNode === headerRow`), wrapped operations in try-catch for graceful fallback to `appendChild()`, and added comprehensive error logging. Ensures sidebar always renders even if timing issues occur.
    *   **Solution Part 2**: Implemented pending reload queue system. Instead of blocking concurrent loads, the code now marks `pendingSidebarReload = true` when a reload is requested during active loading. All code paths (success, empty array, error) now reset the loading flag and check for pending reloads, automatically triggering queued reload after 100ms delay.
    *   **Impact**: Before fix, ~10-15% of page loads had DOM errors and 100% of new users couldn't see their first conversation without manual page refresh. After fix, 0% failures with seamless user experience and no manual refresh needed.
    *   (Ref: `chat-sidebar-conversations.js`, DOM manipulation order, race condition handling, loading flag management, pending reload queue, lines 12-40, 93-115, 169-183)

### **(v0.237.006)**

#### Bug Fixes

*   **Windows Unicode Encoding Issue Fix**
    *   Fixed critical cross-platform compatibility issue where the application crashes on Windows when processing or displaying Unicode characters beyond the Western European character set.
    *   **Root Cause**: Python on Windows uses cp1252 encoding for stdout/stderr (limited to 256 Western European characters), while Azure services and web applications use UTF-8 encoding universally (1.1M+ characters). This mismatch caused `UnicodeEncodeError: 'charmap' codec can't encode character '\uXXXX'` when logging or displaying emojis, international characters, IPA symbols, or special formatting.
    *   **Impact**: Application crashes affecting:
        *   Video transcripts with phonetic symbols
        *   Chat messages containing emojis or international text
        *   Agent responses with Unicode formatting
        *   Debug logging across the entire application
        *   Error messages and stack traces
    *   **Solution**: Configured UTF-8 encoding globally at application startup for Windows platforms by reconfiguring `sys.stdout` and `sys.stderr` to UTF-8 at the top of `app.py` before any imports or print statements. Includes fallback for older Python versions (<3.7). Platform-specific fix only applies on Windows.
    *   **Testing**: Verified with video processing (IPA phonetic symbols), chat messages (emojis/international characters), debug logging (Unicode content), and confirmed no impact on Linux/macOS deployments.
    *   **Issue**: Fixes [#644](https://github.com/microsoft/simplechat/issues/644)
    *   (Ref: `app.py`, UTF-8 encoding configuration, cross-platform compatibility)

*   **Azure Speech Service Managed Identity Authentication Fix**
    *   Fixed Azure Speech Service managed identity authentication requiring resource-specific endpoints with custom subdomains instead of regional endpoints.
    *   **Root Cause**: Managed identity (AAD token) authentication fails with regional endpoints (e.g., `https://eastus2.api.cognitive.microsoft.com`) because the Bearer token doesn't specify which Speech resource to access. The regional gateway cannot determine resource authorization, resulting in 400 BadRequest errors. Key-based authentication works with regional endpoints because the subscription key identifies the specific resource.
    *   **Impact**: Users could not use managed identity authentication with Speech Service for audio transcription. Setup appeared successful but failed at runtime with authentication errors.
    *   **Solution**: Comprehensive setup guide for managed identity requiring:
        *   **Custom Subdomain**: Enable custom subdomain on Speech resource using `az cognitiveservices account update --custom-domain <resource-name>`
        *   **Resource-Specific Endpoint**: Configure endpoint as `https://<resource-name>.cognitiveservices.azure.com` (not regional endpoint)
        *   **RBAC Roles**: Assign `Cognitive Services Speech User` and `Cognitive Services Speech Contributor` roles to App Service managed identity
        *   **Admin Settings**: Update Speech Service Endpoint to resource-specific URL, set Authentication Type to "Managed Identity", leave Speech Service Key empty
    *   **Key Differences**:
        *   Key auth ✅ works with both regional and resource-specific endpoints
        *   Managed Identity ❌ fails with regional endpoints (400 BadRequest)
        *   Managed Identity ✅ works with resource-specific endpoints (requires custom subdomain)
    *   **Troubleshooting Guide**: Added comprehensive troubleshooting for `NameResolutionError` (custom subdomain not enabled), 400 BadRequest (wrong endpoint type), 401 Authentication errors (missing RBAC roles).
    *   (Ref: Azure Speech Service, managed identity authentication, custom subdomain, RBAC configuration, endpoint types)

*   **Sidebar Conversations DOM Manipulation Fix**
    *   Fixed JavaScript error "Failed to execute 'insertBefore' on 'Node': The node before which the new node is to be inserted is not a child of this node" that prevented sidebar conversations from loading.
    *   **Root Cause**: In `createSidebarConversationItem()`, the code was attempting DOM manipulation in the wrong order. When `originalTitleElement` was appended to `titleWrapper`, it was removed from `headerRow`, making the subsequent `insertBefore(titleWrapper, dropdownElement)` fail because `dropdownElement` was no longer a valid child reference in the expected DOM position.
    *   **Impact**: Users experienced a complete failure loading the sidebar conversation list, with the error appearing in browser console and preventing any conversations from displaying in the sidebar. This affected all users attempting to view their conversation history.
    *   **Solution**: Reordered DOM manipulation to remove `originalTitleElement` from DOM first, style it, add it to `titleWrapper`, then insert the complete `titleWrapper` before `dropdownElement`. Added validation to check if `dropdownElement` is a valid child before attempting insertion.
    *   (Ref: `chat-sidebar-conversations.js`, `createSidebarConversationItem()`, DOM manipulation order, line 150)

### **(v0.237.005)**

#### Bug Fixes

*   **Azure AI Search Test Connection Fix**
    *   Fixed test connection functionality for Azure AI Search configuration validation.
    *   (Ref: Azure AI Search, connection testing, admin configuration, `AZURE_AI_SEARCH_TEST_CONNECTION_FIX.md`)

*   **Retention Policy Field Name Fix**
    *   Fixed retention policy to use the correct field name `last_updated` instead of the non-existent `last_activity_at` field.
    *   **Root Cause**: The retention policy query was looking for `last_activity_at` field, but all conversation schemas (legacy and current) use `last_updated` to track the conversation's last modification time.
    *   **Impact**: After the v0.237.004 fix, NO conversations were being deleted because the query required a field that doesn't exist on any conversation document.
    *   **Schema Support**: Now correctly supports all 3 conversation schemas:
        *   Schema 1 (legacy): Messages embedded in conversation document with `last_updated`
        *   Schema 2 (middle): Messages in separate container with `last_updated`
        *   Schema 3 (current): Messages with threading metadata with `last_updated`
    *   **Solution**: Changed SQL query to use `last_updated` field which exists on all conversation documents.
    *   (Ref: retention policy execution, conversation deletion, `delete_aged_conversations()`, `last_updated` field)

### **(v0.237.004)**

#### Bug Fixes

*   **Critical Retention Policy Deletion Fix**
    *   Fixed a critical bug where conversations with null/undefined `last_activity_at` were being deleted regardless of their actual age.
    *   **Root Cause**: The SQL query logic treated conversations with missing `last_activity_at` field as "old" and deleted them, even if they were created moments ago.
    *   **Impact**: Brand new conversations that hadn't had their `last_activity_at` field populated were incorrectly deleted when retention policy ran.
    *   **Solution**: Changed query to only delete conversations that have a valid, non-null `last_activity_at` that is older than the configured retention period. Conversations with null/undefined `last_activity_at` are now skipped.
    *   (Ref: retention policy execution, conversation deletion, `delete_aged_conversations()`)

*   **Public Workspace Retention Error Fix**
    *   Fixed error "name 'cosmos_public_conversations_container' is not defined" when executing retention policy for public workspaces.
    *   **Root Cause**: The code attempted to process conversations for public workspaces, but public workspaces don't have a separate conversations container—only documents and prompts.
    *   **Solution**: Removed conversation processing for public workspaces since they only support document retention.
    *   (Ref: public workspace retention, `process_public_retention()`)

### **(v0.237.003)**

#### New Features

*   **Extended Retention Policy Timeline Options**
    *   Added additional granular retention period options for conversations and documents across all workspace types.
    *   **New Options**: 2 days, 3 days, 4 days, 6 days, 7 days (1 week), and 14 days (2 weeks).
    *   **Full Option Set**: 1, 2, 3, 4, 5, 6, 7 (1 week), 10, 14 (2 weeks), 21 (3 weeks), 30, 60, 90 (3 months), 180 (6 months), 365 (1 year), 730 (2 years) days.
    *   **Scope**: Available in Admin Settings (organization defaults), Profile page (personal settings), and Control Center (group/public workspace management).
    *   **Files Modified**: `admin_settings.html`, `profile.html`, `control_center.html`.
    *   (Ref: retention policy configuration, workspace retention settings, granular time periods)

#### Bug Fixes

*   **Custom Logo Not Displaying Across App Fix**
    *   Fixed issue where custom logos uploaded via Admin Settings would only display on the admin page but not on other pages (chat, sidebar, landing page).
    *   **Root Cause**: The `sanitize_settings_for_user()` function was stripping `custom_logo_base64`, `custom_logo_dark_base64`, and `custom_favicon_base64` keys entirely because they contained "base64" (a sensitive term filter), preventing templates from detecting logo existence.
    *   **Solution**: Modified sanitization to add boolean flags for logo/favicon existence after filtering, allowing templates to check if logos exist without exposing actual base64 data.
    *   **Security**: Actual base64 data remains hidden from frontend; only True/False boolean values are exposed.
    *   **Files Modified**: `functions_settings.py` (`sanitize_settings_for_user()` function).
    *   (Ref: logo display, settings sanitization, template conditionals)

### **(v0.237.001)**

#### New Features

*   **Retention Policy Defaults**
    *   Admin-configurable organization-wide default retention policies for conversations and documents across all workspace types.
    *   **Organization Defaults**: Set default retention periods (1 day to 10 years, or "Don't delete") separately for personal, group, and public workspaces.
    *   **User Choice**: Users see "Using organization default (X days)" option and can override with custom settings or revert to org default.
    *   **Conditional Display**: Default retention settings only appear in Admin Settings when the corresponding workspace type is enabled.
    *   **Force Push Feature**: Administrators can push organization defaults to all workspaces, overriding any custom retention policies users have set.
    *   **Settings Auto-Save**: Force push automatically saves pending settings changes before executing to ensure current values are pushed.
    *   **Activity Logging**: Force push actions are logged to `activity_logs` container for audit purposes with admin info, affected scopes, and results summary.
    *   **API Endpoints**: New `/api/retention-policy/defaults/<workspace_type>` (GET) and `/api/admin/retention-policy/force-push` (POST) endpoints.
    *   **Files Modified**: `functions_settings.py`, `admin_settings.html`, `route_frontend_admin_settings.py`, `route_backend_retention_policy.py`, `functions_retention_policy.py`, `functions_activity_logging.py`, `profile.html`, `control_center.html`, `workspace-manager.js`.
    *   (Ref: Default retention settings, Force Push modal, activity logging, retention policy execution)

*   **Private Networking Support**
    *   Comprehensive private networking support for SimpleChat deployments via Azure Developer CLI (AZD) and Bicep infrastructure-as-code.
    *   **Network Isolation**: Private endpoints for all Azure PaaS services (Cosmos DB, Azure OpenAI, AI Search, Storage, Key Vault, Document Intelligence).
    *   **VNet Integration**: Full virtual network integration for App Service and dependent resources with automated Private DNS zone configuration.
    *   **AZD Integration**: Seamless deployment via `azd up` with `ENABLE_PRIVATE_NETWORKING=true` environment variable.
    *   **Post-Deployment Security**: New `postup` hook automatically disables public network access when private networking is enabled.
    *   **Enhanced Deployment Hooks**: Refactored all deployment hooks in `azure.yaml` with stepwise logging, explicit error handling, and clearer output for troubleshooting.
    *   **Documentation Updates**: Expanded Bicep README with prerequisites, Azure Government (USGov) considerations, and post-deployment validation steps.
    *   (Ref: `deployers/azure.yaml`, `deployers/bicep/`, private endpoint configuration, VNet integration)

*   **User Agreement for File Uploads**
    *   Global admin-configurable agreement that users must accept before uploading files to workspaces.
    *   **Configuration Options**: Enable/disable toggle, workspace type selection (Personal, Group, Public, Chat), Markdown-formatted agreement text (200-word limit), optional daily acceptance mode.
    *   **User Experience**: Modal prompt before file uploads with agreement text, "Accept & Upload" or "Cancel" options, daily acceptance tracking to reduce repeat prompts.
    *   **Activity Logging**: All acceptances logged to activity logs for compliance tracking with timestamp, user, workspace type, and action context.
    *   **Admin Access**: Settings accessible via Admin Settings → Workspaces tab → User Agreement section, with sidebar navigation link.
    *   **Files Added**: `user-agreement.js` (frontend module), `route_backend_user_agreement.py` (API endpoints).
    *   **Files Modified**: `admin_settings.html`, `route_frontend_admin_settings.py`, `base.html`, `_sidebar_nav.html`, `functions_activity_logging.py`, `workspace-documents.js`, `group_workspaces.html`, `public_workspace.js`, `chat-input-actions.js`.
    *   (Ref: User Agreement modal, file upload workflows, activity logging, admin configuration)

*   **Web Search via Azure AI Foundry Agents**
    *   Web search capability through Azure AI Foundry agents using Grounding with Bing Search service.
    *   **Pricing**: $14 per 1,000 transactions (150 transactions/second, 1M transactions/day limit).
    *   **Admin Consent Flow**: Requires explicit administrator consent before enabling due to data processing considerations outside Azure compliance boundary.
    *   **Consent Logging**: All consent acceptances are logged to activity logs for compliance and audit purposes.
    *   **Setup Guide Modal**: Comprehensive in-app configuration guide with step-by-step instructions for creating the agent, configuring Bing grounding, setting result count to 10, and recommended agent instructions.
    *   **User Data Notice**: Admin-configurable notification banner that appears when users activate web search, informing them that their message will be sent to Microsoft Bing. Customizable notice text, dismissible per session.
    *   **Graceful Error Handling**: When web search fails, the system informs users rather than answering from outdated training data.
    *   **Seamless Integration**: Web search results automatically integrated into AI responses when enabled.
    *   **Settings**: `enable_web_search` toggle, `web_search_consent_accepted` tracking, `enable_web_search_user_notice` toggle, and `web_search_user_notice_text` customization in admin settings.
    *   **Files Added**: `_web_search_foundry_info.html` (setup guide modal).
    *   **Files Modified**: `route_frontend_admin_settings.py`, `route_backend_chats.py`, `functions_activity_logging.py`, `admin_settings.html`, `chats.html`, `chat-input-actions.js`, `functions_settings.py`.
    *   (Ref: Grounding with Bing Search, Azure AI Foundry, consent workflow, activity logging, pricing, user transparency)

*   **Conversation Deep Linking**
    *   Direct URL links to specific conversations via query parameters for sharing and bookmarking.
    *   **URL Parameters**: Supports both `conversationId` and `conversation_id` query parameters.
    *   **Automatic URL Updates**: Current conversation ID automatically added to URL when selecting conversations.
    *   **Browser Integration**: Uses `history.replaceState()` for seamless URL updates without new history entries.
    *   **Error Handling**: Graceful handling of invalid or inaccessible conversation IDs with toast notifications.
    *   **Files Modified**: `chat-onload.js`, `chat-conversations.js`.
    *   (Ref: deep linking, URL parameters, conversation navigation, shareability)

*   **Plugin Authentication Type Constraints**
    *   Per-plugin-type authentication method restrictions for better security and API compatibility.
    *   **Schema-Based Defaults**: Falls back to global `AuthType` enum from `plugin.schema.json`.
    *   **Definition File Overrides**: Plugin-specific `.definition.json` files can restrict available auth types.
    *   **API Endpoint**: New `/api/plugins/<plugin_type>/auth-types` endpoint returns allowed auth types and source.
    *   **Frontend Integration**: UI can query allowed auth types to display only valid options.
    *   **Files Modified**: `route_backend_plugins.py`.
    *   (Ref: plugin authentication, auth type constraints, OpenAPI plugins, security)

#### Bug Fixes

*   **Control Center Chart Date Labels Fix**
    *   Fixed activity trends chart date labels to parse dates in local time instead of UTC.
    *   **Root Cause**: JavaScript `new Date()` was parsing date strings as UTC, causing labels to display previous day in western timezones.
    *   **Solution**: Parse date components explicitly and construct Date objects in local timezone.
    *   **Impact**: Chart x-axis labels now correctly show the intended dates regardless of user timezone.
    *   **Files Modified**: `control_center.html` (Chart.js date parsing logic).
    *   (Ref: Chart.js, date parsing, timezone handling, activity trends)

*   **Sovereign Cloud Cognitive Services Scope Fix**
    *   Fixed hardcoded commercial Azure cognitive services scope references that prevented authentication in Azure Government (MAG) and custom cloud environments.
    *   **Root Cause**: `chat_stream_api` and `smart_http_plugin` used hardcoded commercial cognitive services scope URL instead of configurable value from `config.py`.
    *   **Solution**: Replaced hardcoded scope with `AZURE_OPENAI_TOKEN_SCOPE` environment variable, dynamically resolved based on cloud environment.
    *   **Impact**: Streaming chat and Smart HTTP Plugin now work correctly in Azure Government, China, and custom cloud deployments.
    *   **Related Issue**: [#616](https://github.com/microsoft/simplechat/issues/616)
    *   (Ref: `chat_stream_api`, `smart_http_plugin`, sovereign cloud authentication, MAG support)

*   **User Search Toast and Inline Messages Fix**
    *   Updated `searchUsers()` function to use inline and toast messages instead of browser alert pop-ups.
    *   **Improvement**: Search feedback (empty search, no users found, errors) now displays as inline messages in the search results area.
    *   **Error Handling**: Errors display both inline message and toast notification for visibility.
    *   **Benefits**: Non-disruptive UX, contextual feedback, consistency with application patterns.
    *   **Related PR**: [#608](https://github.com/microsoft/simplechat/pull/608#discussion_r2701900020)
    *   (Ref: group management, user search, toast notifications, UX improvement)

### **(v0.235.025)**

#### Bug Fixes

*   **Retention Policy Document Deletion Fix**
    *   Fixed critical bug where retention policy execution failed when attempting to delete aged documents, while conversation deletion worked correctly.
    *   **Root Cause 1**: Documents use `last_updated` field, but query was looking for `last_activity_at` (used by conversations).
    *   **Root Cause 2**: Date format mismatch - documents store `YYYY-MM-DDTHH:MM:SSZ` but query used Python's `.isoformat()` with `+00:00` suffix.
    *   **Root Cause 3**: Duplicate column in SELECT clause when `partition_field='user_id'` caused query errors.
    *   **Root Cause 4**: Activity logging called with incorrect `deletion_reason` parameter instead of `additional_context`.
    *   **Files Modified**: `functions_retention_policy.py` (query field names, date format, SELECT clause, activity logging).
    *   (Ref: `delete_aged_documents()`, retention policy execution, Cosmos DB queries)

*   **Retention Policy Scheduler Fix**
    *   Fixed automated retention policy scheduler not executing at the scheduled time.
    *   **Root Cause 1**: Hour-matching approach was unreliable - only ran if check happened exactly during the execution hour (e.g., 2 AM), but 1-hour sleep intervals could miss the entire window.
    *   **Root Cause 2**: Check interval too long (1 hour) meant poor responsiveness and high probability of missing scheduled time.
    *   **Root Cause 3**: Code ignored the stored `retention_policy_next_run` timestamp, instead relying solely on hour matching.
    *   **Solution**: Now uses `retention_policy_next_run` timestamp for comparison, reduced check interval from 1 hour to 5 minutes, added fallback logic for missed executions.
    *   **Files Modified**: `app.py` (`check_retention_policy()` background task).
    *   (Ref: retention policy scheduler, background task, scheduled execution)

### **(v0.235.012)**

#### Bug Fixes

*   **Control Center Access Control Logic Fix**
    *   Fixed access control discrepancy where users with `ControlCenterAdmin` role were incorrectly granted access when the role requirement setting was disabled.
    *   **Correct Behavior**: When `require_member_of_control_center_admin` is DISABLED (default), only the regular `Admin` role grants access. The `ControlCenterAdmin` role is only checked when the setting is ENABLED.
    *   **Files Modified**: `functions_authentication.py` (decorator logic), `route_frontend_control_center.py` (frontend access computation), `_sidebar_nav.html` and `_top_nav.html` (menu visibility).
    *   (Ref: `control_center_required` decorator, role-based access control)

*   **Disable Group Creation Setting Fix**
    *   Fixed issue where "Disable Group Creation" setting was not being saved from Admin Settings or Control Center pages.
    *   **Root Cause 1**: Form field name mismatch - HTML used `disable_group_creation` but backend expected `enable_group_creation`.
    *   **Root Cause 2**: Missing onclick handler on Control Center's "Save Settings" button.
    *   **Files Modified**: `route_frontend_admin_settings.py` (form field reading), `control_center.html` (button handler).
    *   (Ref: group creation permissions, admin settings form handling)

### **(v0.235.003)**

#### New Features

*   **Approval Workflow System**
    *   Comprehensive approval process for sensitive Control Center operations requiring review and approval before execution.
    *   **Protected Operations**: Take ownership, transfer ownership, delete documents, and delete group operations now require approval.
    *   **Approval Features**: Documented justification, review process by group owners/admins, complete audit trail, auto-expiration after 3 days, notification integration.
    *   **Database**: New `approvals` container with TTL-based expiration.
    *   (Ref: `route_backend_control_center.py`, `route_frontend_control_center.py`, `control_center.html`, approval workflow UI)

*   **Agent Streaming Support**
    *   Real-time streaming support for Semantic Kernel agents with incremental response display.
    *   **Features**: Agent responses stream word-by-word, plugin citation capture during streaming, async generator pattern for efficient streaming, proper async/await handling.
    *   **User Experience**: Matches existing chat streaming experience, see agent thinking in real-time, immediate visual feedback.
    *   (Ref: `route_backend_chats.py`, agent streaming implementation, Semantic Kernel integration)

*   **Control Center**
    *   Comprehensive administrative interface for data and workspace management.
    *   **User Management**: View all users with search/filtering, grant/deny access with time-based restrictions, manage file upload permissions, monitor user engagement and storage.
    *   **Activity Trends**: Visual analytics with Chart.js showing daily activity metrics (chats, uploads, logins, document actions) across 7/30/90-day periods.
    *   **Group Management**: Approval workflow integration, group status management, member activity monitoring.
    *   **Dashboard**: Real-time statistics, key alerts, activity insights.
    *   (Ref: `route_frontend_control_center.py`, `route_backend_control_center.py`, `control_center.html`)

*   **Control Center Application Roles**
    *   Added two new application roles for finer-grained Control Center access control.
    *   **Control Center Admin**: Full administrative access to Control Center functionality including user management, administrative operations, and workflow approvals.
    *   **Control Center Dashboard Reader**: Read-only access to Control Center dashboards and metrics for monitoring and auditing purposes.
    *   **Use Cases**: IT operations monitoring, delegated administration, compliance auditing with appropriate access levels.
    *   **Files Modified**: `appRegistrationRoles.json` (new role definitions).
    *   (Ref: Entra ID app roles, role-based access control, Control Center permissions)

*   **Message Threading System**
    *   Linked-list threading system establishing proper message relationships throughout conversations.
    *   **Thread Fields**: `thread_id` (unique identifier), `previous_thread_id` (links to previous message), `active_thread` (thread active status), `thread_attempt` (retry tracking).
    *   **Benefits**: Proper message ordering, file upload tracking, image generation association, legacy message support.
    *   **Message Flow**: Links user messages to AI responses, system augmentations, file uploads, and image generations.
    *   (Ref: `route_backend_chats.py`, message schema updates, thread chain implementation)

*   **User Profile Dashboard**
    *   Complete redesign into modern dashboard with personalized analytics and visualizations.
    *   **Metrics Display**: Login statistics, chat activity, document usage, storage consumption, token tracking.
    *   **Visualizations**: Chart.js-powered activity trends, 30-day time-series data, interactive charts.
    *   **Features**: Cached metrics for performance, real-time data aggregation, responsive design.
    *   (Ref: `route_frontend_profile.py`, `profile.html`, Chart.js integration)

*   **Speech-to-Text Chat Input**
    *   Voice recording up to 90 seconds directly in chat interface with Azure Speech Service transcription.
    *   **Features**: Visual waveform display during recording, 90-second countdown timer, review before send, cancel anytime, responsive design.
    *   **Browser Support**: Chrome 49+, Edge 79+, Firefox 25+, Safari 14.1+.
    *   **Integration**: Uses existing Azure Speech Service configuration, MediaRecorder API, Web Audio API.
    *   (Ref: `route_backend_settings.py`, `chat-speech-to-text.js`, Speech Service integration)

*   **Text-to-Speech AI Responses**
    *   AI messages read aloud using Azure Speech Service with high-quality DragonHD voices.
    *   **Features**: 27 DragonHD Latest Neural Voices across languages, voice preview in profile, customizable speech speed (0.5x-2.0x), play/pause/stop controls.
    *   **Playback**: Inline "Listen" button per message, visual feedback during playback, auto-play mode option, prevents multiple simultaneous playbacks.
    *   **Integration**: Automatically disables streaming when auto-play enabled, per-user profile settings.
    *   (Ref: `route_backend_tts.py`, `chat-tts.js`, Azure Speech Service)

*   **Message Edit Functionality**
    *   Comprehensive message editing system allowing users to modify their sent messages and regenerate AI responses.
    *   **Features**: Modal interface for editing message text, preserves conversation context and settings, automatically regenerates AI response with edited content, maintains message metadata and threading.
    *   **User Experience**: Edit button on user messages, inline editing workflow, real-time validation, preserves agent/model selection.
    *   **Integration**: Works with `/api/message/<id>/edit` endpoint, updates conversation history, maintains thread relationships.
    *   (Ref: `chat-edit.js`, `route_backend_chats.py`, message edit modal)

*   **Message Delete Capability**
    *   One-click message deletion with proper conversation thread cleanup and metadata updates.
    *   **Features**: Delete button on user messages, ownership validation (author-only), updates message threading chains, removes associated metadata.
    *   **Safety**: Confirmation prompt, author verification, cascading thread updates, preserves conversation integrity.
    *   **Integration**: API endpoint for message deletion, updates conversation message count, maintains thread consistency.
    *   (Ref: `chat-messages.js`, message deletion handlers, thread management)

*   **Message Retry/Regenerate System**
    *   Powerful message regeneration system allowing users to retry AI responses with different models, agents, or settings.
    *   **Features**: Modal interface with agent/model selection, adjustable reasoning effort for o-series models, preserves original user message, generates new AI response with selected configuration.
    *   **Configuration Options**: Switch between agents, change model deployments, adjust reasoning effort (low/medium/high), modify generation parameters.
    *   **User Experience**: Retry button on AI messages, dropdown selection for agents/models, real-time configuration updates.
    *   (Ref: `chat-retry.js`, retry modal interface, agent/model switching)

*   **Message Masking System**
    *   Privacy-focused message masking capability for hiding sensitive information with visual overlays and PII protection.
    *   **Features**: Visual mask overlay on message content, `masked_ranges` metadata tracking character positions, mask/unmask toggle buttons, preserves original content while displaying masked state.
    *   **Privacy Protection**: Masks sensitive data in UI, tracks masked regions in database, supports partial message masking, reversible masking for authorized users.
    *   **Integration**: `/api/message/<id>/mask` endpoint, `masked` and `masked_ranges` metadata fields, visual indicators (bi-front/bi-back icons).
    *   **User Experience**: Mask button on messages, visual overlay showing masked content, toggle between masked and unmasked states.
    *   (Ref: `chat-messages.js`, `route_backend_chats.py`, masked content handling, `applyMaskedState()` function)

*   **Conversation Pinning**
    *   Pin important conversations to the top of the conversation list for quick access and improved organization.
    *   **Features**: Single conversation pinning, bulk pin operations for multiple conversations, persistent pin state in database, visual pin indicators in sidebar.
    *   **Operations**: Pin/unpin toggle, bulk selection interface, priority sorting (pinned conversations appear first), `is_pinned` metadata field.
    *   **API Endpoints**: `/api/conversations/<id>/pin` (POST), `/api/conversations/bulk-pin` (POST).
    *   **User Experience**: Pin icon in conversation list, bulk selection checkboxes, immediate visual feedback.
    *   (Ref: `chat-conversations.js`, `toggleConversationPin()`, `bulkPinConversations()`, conversation state management)

*   **Conversation Hiding**
    *   Hide conversations from the main list to declutter the sidebar without permanent deletion.
    *   **Features**: Single conversation hiding, bulk hide operations, toggle visibility without data loss, `is_hidden` metadata field for state persistence.
    *   **Benefits**: Declutter conversation list, temporary archiving without deletion, reversible operation, maintains conversation data.
    *   **API Endpoints**: `/api/conversations/<id>/hide` (POST), `/api/conversations/bulk-hide` (POST).
    *   **User Experience**: Hide button in conversation list, bulk selection interface, show hidden conversations toggle.
    *   (Ref: `chat-conversations.js`, `toggleConversationHide()`, `bulkHideConversations()`, visibility management)

*   **Quick Search for Conversations**
    *   Real-time client-side conversation filtering for instant search results without server roundtrips.
    *   **Features**: Real-time text filtering, searches conversation titles, client-side performance, keyboard shortcut support (Ctrl+K).
    *   **Search Scope**: Filters visible conversations in current workspace, highlights matching conversations, instant results as you type.
    *   **User Experience**: Search input in sidebar header, keyboard shortcut, clear button, responsive filtering.
    *   (Ref: `chat-conversations.js`, `toggleQuickSearch()`, client-side filtering)

*   **Advanced Search Modal**
    *   Comprehensive search functionality with filters, pagination, and search history for finding conversations across all workspaces.
    *   **Features**: Full-text search across conversation content, classification filters, date range selection, pagination support, search history tracking.
    *   **Search Capabilities**: Search conversation titles and content, filter by workspace scope, filter by date range, view search history, export results.
    *   **User Experience**: Modal interface with filter controls, results pagination, search history dropdown, results summary display.
    *   **Integration**: Server-side search API, search history persistence, results caching.
    *   (Ref: `chat-search-modal.js`, `openAdvancedSearchModal()`, `performAdvancedSearch()`, search history management)

*   **Automated Retention Policy System**
    *   Scheduled automatic deletion of aged conversations and documents based on configurable retention policies.
    *   **Features**: User-configurable retention periods, separate policies for conversations and documents, scheduled execution via daemon thread, exemption support for protected conversations/documents.
    *   **Configuration Options**: Retention periods by workspace scope (personal/group/public), auto-deletion scheduling (daily execution), user opt-in/opt-out controls, admin override capabilities.
    *   **Scopes**: Personal workspace retention, group workspace retention, public workspace retention, per-user policy settings.
    *   **Safety Features**: User exemption lists, dry-run mode for testing, deletion audit logging, grace period before deletion.
    *   **Integration**: Background daemon thread, admin configuration interface, user profile settings, Cosmos DB TTL-based cleanup.
    *   (Ref: `functions_retention_policy.py`, `execute_retention_policy()`, scheduled execution, user settings integration)

*   **Embedding Token Tracking**
    *   Comprehensive token tracking for document embedding generation in personal workspaces.
    *   **Tracking**: Captures token usage per document chunk, accumulates total tokens, stores embedding tokens and model deployment name in document metadata.
    *   **Benefits**: Embedding cost tracking, usage pattern analysis, document-level token metrics.
    *   (Ref: `functions_content.py`, `functions_documents.py`, embedding token capture)

*   **Search Result Caching**
    *   Ensures consistent search results across identical queries with Cosmos DB-based distributed caching.
    *   **Features**: Document set fingerprinting for cache invalidation, score normalization across indexes, 5-minute TTL, multi-instance deployment support.
    *   **Architecture**: Cosmos DB `search_cache` container, SHA256 cache keys, automatic expiration, cache sharing across instances.
    *   **Benefits**: Consistent user experience, reduced Azure AI Search costs, improved performance.
    *   (Ref: `functions_search.py`, `search_cache` container, fingerprint-based invalidation)

*   **Activity Trends Visualization**
    *   Interactive Chart.js visualization of daily activity metrics in Control Center.
    *   **Categories**: Chats, uploads, logins, document actions tracked separately.
    *   **Time Periods**: 7-day, 30-day, and 90-day views.
    *   **Data Sources**: Real data from Cosmos DB containers with sample data fallback.
    *   (Ref: `route_backend_control_center.py`, `control_center.html`, Chart.js implementation)

*   **Group Activity Timeline**
    *   Comprehensive real-time view of all group workspace activities.
    *   **Activity Types**: Document creation/deletion/updates, member additions/removals, status changes, conversations.
    *   **Features**: Icon-based activity display, timestamp tracking, member attribution, detailed metadata.
    *   **Benefits**: Group usage monitoring, audit trail, compliance tracking.
    *   (Ref: `route_frontend_groups.py`, activity timeline UI, activity logs integration)

*   **Dynamic OpenAPI Schema Generation**
    *   Dynamic schema generation reducing hardcoded OpenAPI definitions.
    *   **Features**: Analyzes Flask routes to generate schemas, maps routes to appropriate references, minimal required schemas for common patterns.
    *   **Benefits**: Reduced maintenance overhead, automatic schema updates, comprehensive API documentation.
    *   (Ref: `route_external_openapi_spec.py`, dynamic schema functions)

*   **Enhanced User Management**
    *   Comprehensive user activity metrics and analytics in Control Center.
    *   **Profile Features**: Profile image display with Base64 support, chat metrics (conversations, messages, 3-month activity), document metrics (count, storage, AI search size).
    *   **Analytics**: Last chat activity timestamps, storage estimations, feature status indicators.
    *   (Ref: `route_backend_control_center.py`, enhanced user metrics)

*   **Group Status Management**
    *   Fine-grained control over group workspace operations through status-based access controls.
    *   **Status Types**: Active (full functionality), Locked (read-only), Upload Disabled (no new uploads), Inactive (disabled).
    *   **Features**: Full audit trail logging, operation-level restrictions, compliance support.
    *   **Use Cases**: Legal holds, storage management, project lifecycle, risk mitigation.
    *   (Ref: `functions_groups.py`, `route_backend_groups.py`, status enforcement)

*   **Workflow System**
    *   Document processing workflows including PII analysis and approval workflows.
    *   **Features**: PDF document display in modals, workflow summary generation, approval routing, activity logging.
    *   (Ref: `route_frontend_workflow.py`, workflow templates, CSP configuration)

*   **Full Width Chat Support**
    *   Option to expand chat interface to full browser width for better screen utilization.
    *   (Ref: `chats.html`, responsive layout updates)

*   **Enhanced Document Metrics**
    *   Comprehensive document metadata tracking with enhanced analytics.
    *   (Ref: document metrics implementation across containers)

*   **Group Member Activity Logging**
    *   Detailed logging when group members are added or removed.
    *   (Ref: activity logging system, group member operations)

*   **Enable Group Creation Setting**
    *   Admin toggle to control whether users can create new groups.
    *   (Ref: admin settings, group creation permissions)

*   **YAML OpenAPI Specification Support**
    *   Support for YAML format OpenAPI specifications alongside JSON.
    *   (Ref: OpenAPI plugin system, YAML parsing)

*   **Inline OpenAPI Schema Generation**
    *   Generate OpenAPI schemas inline during plugin configuration.
    *   (Ref: plugin configuration UI, schema generation)

*   **Microphone Permission Management**
    *   Improved handling of browser microphone permissions for speech-to-text.
    *   (Ref: speech-to-text implementation, browser permissions)

#### Bug Fixes

*   **Agent Streaming Plugin Execution Fix**
    *   Fixed agent streaming failure when agents execute plugins during streaming.
    *   **Root Cause**: Event loop conflicts from `loop.run_until_complete(async_gen.__anext__())` pattern breaking async generator protocol.
    *   **Solution**: Proper async/await pattern with `asyncio.run()` for complete async context.
    *   **Impact**: Plugins like SmartHttpPlugin now work correctly in streaming mode.
    *   (Ref: `route_backend_chats.py`, async generator handling, plugin execution)

*   **Search Cache Cosmos DB Migration**
    *   Migrated search caching from in-memory to Cosmos DB for multi-instance deployment support.
    *   **Problem**: In-memory cache didn't share across App Service instances causing inconsistent results.
    *   **Solution**: Cosmos DB `search_cache` container with 5-minute TTL, partition key on `user_id`.
    *   **Benefits**: Cache sharing across instances, consistent user experience, distributed invalidation.
    *   (Ref: `functions_search.py`, `search_cache` container, TTL configuration)

*   **Vision Model Parameter Fix**
    *   Fixed GPT-5 and o-series model failures in vision analysis with "Unsupported parameter: 'max_tokens'" error.
    *   **Root Cause**: GPT-5 and o-series models require `max_completion_tokens` instead of `max_tokens`.
    *   **Solution**: Dynamic parameter selection based on model type.
    *   **Impact**: Vision analysis now works with all model families.
    *   (Ref: `route_backend_settings.py`, `functions_documents.py`, model-aware parameters)

*   **Group Plugin Global Merge Fix**
    *   Fixed group workspaces unable to see globally managed actions when merge setting enabled.
    *   **Root Cause**: `/api/group/plugins` endpoint didn't append global actions.
    *   **Solution**: Merge global actions into group plugins response with read-only badges.
    *   **Impact**: Groups can now select and use global actions while protecting them from modification.
    *   (Ref: `route_backend_groups.py`, global plugin merging)

*   **Workflow Summary Generation O1 API Fix**
    *   Fixed o1 model failures in workflow summary generation with "Unsupported parameter: 'temperature'" error.
    *   **Root Cause**: Unconditional application of `temperature` parameter to all models.
    *   **Solution**: Conditional parameter logic excluding `temperature` for o1 models.
    *   (Ref: `route_frontend_workflow.py`, model-aware parameter handling)

*   **Validation Utilities Consolidation**
    *   Consolidated duplicate validation functions across multiple files into centralized module.
    *   **Duplicated Functions**: `validateGuid()` in 4 locations, `validateEmail()` in 2 locations.
    *   **Solution**: Created `validation-utils.js` module with `ValidationUtils` namespace.
    *   **Benefits**: Single source of truth, easier maintenance, consistency.
    *   (Ref: `validation-utils.js`, code refactoring across control center and workspace files)

*   **Public Workspace Storage Calculation Fix**
    *   Fixed public workspaces showing 0 bytes storage despite having documents.
    *   **Root Cause**: Incorrect folder prefix (`public/{workspace_id}/` instead of `{workspace_id}/`).
    *   **Solution**: Fixed folder prefix, enhanced fallback logic, improved error handling.
    *   (Ref: `route_backend_control_center.py`, storage calculation logic)

*   **Public Workspace Metrics Caching Consistency Fix**
    *   Improved consistency in public workspace metrics caching across Control Center views.
    *   (Ref: metrics caching implementation)

*   **Activity Timeline All Logs Fix**
    *   Fixed activity timeline to properly display all log types.
    *   (Ref: activity log filtering)

*   **Activity Trends Field Mapping Fix**
    *   Corrected field mappings for activity trends data display.
    *   (Ref: activity trends API, field mapping)

*   **All File Types Embedding Token Tracking Fix**
    *   Extended embedding token tracking to all file types beyond just text.
    *   (Ref: `functions_documents.py`, comprehensive token tracking)

*   **PDF Embedding Token Tracking Fix**
    *   Fixed token tracking specifically for PDF document embeddings.
    *   (Ref: PDF processing, token capture)

*   **Create Group Button Visibility Fix**
    *   Fixed group creation button visibility based on admin settings.
    *   (Ref: UI conditional rendering, permission checks)

*   **File Message Metadata Loading Fix**
    *   Fixed metadata loading for file-related messages in conversations.
    *   (Ref: message metadata display, file associations)

*   **Group Agent Metadata Fix**
    *   Corrected agent metadata display and management in group contexts.
    *   (Ref: agent configuration, group agent handling)

*   **Group Document Metrics Date Format Fix**
    *   Fixed date formatting for group document metrics display.
    *   (Ref: document metrics, date formatting)

*   **Group Notification Context Enhancement**
    *   Enhanced notification context for group-related activities.
    *   (Ref: notification system, group context)

*   **Group Status UI Visibility Fix**
    *   Fixed UI visibility of group status indicators and controls.
    *   (Ref: group status display, conditional UI rendering)

*   **Group Table Auto-Refresh Fix**
    *   Fixed automatic refresh of group tables after operations.
    *   (Ref: table refresh logic, UI updates)

*   **Groups Tab Refresh Fix**
    *   Fixed refresh behavior on groups management tab.
    *   (Ref: tab state management, data refresh)

*   **Hidden Conversations Sidebar Click Fix**
    *   Fixed sidebar click handling for hidden conversations.
    *   (Ref: sidebar navigation, conversation visibility)

*   **Sidebar Group Badge Fix**
    *   Fixed group badge display in conversation sidebar.
    *   (Ref: sidebar UI, badge rendering)

*   **Top Nav Sidebar Overlap Fix**
    *   Fixed overlapping issues between top navigation and sidebar in certain layouts.
    *   (Ref: CSS layout, navigation positioning)

*   **Vision Analysis Debug Logging**
    *   Added comprehensive debug logging for vision analysis operations.
    *   (Ref: `functions_documents.py`, debug logging)

*   **Workflow PDF Iframe CSP Fix**
    *   Fixed Content Security Policy for PDF display in workflow iframes.
    *   (Ref: CSP headers, iframe configuration)

*   **Workflow PDF Viewer Height Fix**
    *   Fixed height issues in workflow PDF viewer modals.
    *   (Ref: modal styling, PDF viewer layout)

*   **Workspace Activity Modal Fix**
    *   Fixed workspace activity modal display and interaction issues.
    *   (Ref: modal functionality, workspace activity display)

*   **Search Cache Sharing Fix**
    *   Improved search cache sharing across user contexts.
    *   (Ref: cache key generation, sharing logic)

---

Release notes for versions before v0.230.001 have moved to the [archived release notes](/explanation/archive_release_notes/).
