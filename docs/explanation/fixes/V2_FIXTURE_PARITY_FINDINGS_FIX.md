# V2 Fixture Parity Findings Fix

Fixed/Implemented in version: **0.261.164**

## Issue

The fixture parity pins added after version 0.261.161 hold each V2 group
fixture to the real routes. Along the way they found four places where the V2
app didn't do what the server meant, and each was pinned as a strict `xfail`
until it was fixed.

1. **Coded failures showed their machine code.** Some failures answer with a
   lowercase code and a sentence, for example:

   ```json
   {"error": "document_propagation_incomplete",
    "message": "The operation changed stored data, but required cleanup or propagation is incomplete. Refresh before retrying."}
   ```

   V2 showed `document_propagation_incomplete`.
2. **The conversation delete guard didn't say which conversation.** Deleting a
   document that a conversation depends on is refused, and the refusal names
   the conversation. The V2 confirmation showed only the server's message.
3. **Batch downloads were always saved as `documents.zip`.** The group and
   public routes name their archives `group-documents.zip` and
   `public-documents.zip`.
4. **The group agent editor offered public knowledge.** A group agent never
   keeps a public knowledge source, because the server's scope policy drops it.
   The editor offered one anyway.

## Root cause

1. `readErrorMessage` in `lib/apiClient.ts` preferred the body's `error` field
   over its `message`, and coded failures carry the code in `error`.
2. The delete dialog never read the guard's `conversation` object.
3. The document explorer named every multi-document download `documents.zip`
   and never read the response's `Content-Disposition`.
4. The group agent workbench listed the `group` and `public` knowledge scopes.

## Fix

1. **Error text.** When `error` is a bare lowercase code and `message` is a
   sentence, V2 shows the sentence. The response payload still carries the code,
   which is what code checks read. The sentence now appears for:
   - document management, File Sync and collaboration refusals;
   - the Microsoft 365 pending-action routes;
   - the terms-of-use gate;
   - the CI bearer authentication answers.

   Bodies whose `error` is already a sentence, the capitalized "Unauthorized"
   and "Forbidden" answers, and bodies with no `message` show what they did
   before.
2. **The conversation.** The delete confirmation adds "Conversation:" and the
   conversation's title, always as text.
   - The title links to the conversation in V2 chat, `/v2/chat?conversationId=<id>`,
     in a new tab, when the guard carries the conversation's id.
   - Without an id, the title still links when the guard carries a link to this
     site that names the conversation.
   - The guard's own link is never followed or shown. A link to another site, a
     protocol-relative or scripted link, one with a backslash, and a link to
     the classic `/chats` page don't make the title a link.
3. **Archive names.** A multi-document download is saved under the name the
   server gives the archive, reduced to a bare file name. When the server gives
   none, it's `documents.zip`.
   - A single document keeps its own file name, because the server's name for
     one file is a lossy `secure_filename` of it: `报告.pdf` arrives as `pdf`.
   - Personal downloads are unchanged.
4. **Agent knowledge.** The group agent editor offers only group knowledge.
   Personal agents still offer personal and public knowledge.

## Files modified

| File | Change |
| --- | --- |
| `application/v2_ui/src/lib/apiClient.ts` | Shows a coded failure's sentence (1). |
| `application/v2_ui/src/lib/documentOperations.ts` | Reads the guard's conversation (2), and the archive name and `documentDownloadName` (3). The download adapter now returns the file and its name. |
| `application/v2_ui/src/lib/conversationUrl.ts` | `chatHrefForConversation` (2). |
| `application/v2_ui/src/components/documents/DocumentDialogs.tsx` | The conversation line in the delete confirmation (2). |
| `application/v2_ui/src/components/documents/DocumentExplorer.tsx` | Saves downloads under `documentDownloadName` (3). |
| `application/v2_ui/src/lib/agentWorkbench.ts` | Group agents list group knowledge only (4). |

## Testing

- **Logic tests** that import the real modules:
  - `functional_tests/test_v2_api_error_message_logic.mjs` (8);
  - `test_v2_delete_guard_conversation_logic.mjs` (7);
  - `test_v2_document_download_name_logic.mjs` (7).
- **The four strict `xfail` tests now pass:**
  - three in `ui_tests/test_v2_group_document_management.py`;
  - one in `functional_tests/test_group_agent_fixture_parity.py`, now run for
    both the group and personal adapters against the server's scope policy.
- **New browser cases in `test_v2_group_document_management.py`:**
  - the conversation link, 7 cases, including links to another site,
    protocol-relative, backslash, scripted and `/chats` links, and a title
    containing markup;
  - archive and single-file names, 7 cases, including `报告.pdf`.
- **Personal, in `test_v2_personal_document_scope.py`:** downloads keep their
  names whatever the personal routes send.
- **Public, in `test_v2_public_documents.py`:** the metadata failure's sentence
  and `public-documents.zip`.
- **Mutations:** 7 mutations of the four fixes, all killed.

## Validation

| Case | Before | After |
| --- | --- | --- |
| A group or public metadata save that stored data but couldn't finish | `document_propagation_incomplete` | "The operation changed stored data, but required cleanup or propagation is incomplete. Refresh before retrying." |
| Deleting a document a conversation depends on | The server's message only | Also names the conversation, linked to it in V2 chat |
| Downloading several group documents | `documents.zip` | `group-documents.zip` |
| Downloading several public documents | `documents.zip` | `public-documents.zip` |
| Downloading one document | Its own name | Its own name |
| The group agent editor's knowledge sources | Group and public | Group only |

Results, on the tree integrated at version 0.261.164:

- **Browser:** 27 suites, 758 passed. The only failures are the five that
  also fail on the React V2 base branch: the four participant invite tests
  and one content screening admin test. Document management went from 34
  passed and 3 `xfail` to 39 passed, and personal document scope from 11 to
  12.
- **Functional:**
  - agent fixture parity 26, up from 24 and one `xfail`;
  - action parity 27, document parity 91, context parity 206;
  - agent and action APIs 92 and 63;
  - group document reads 208, public payload redaction 48, and the document
    management transport 21.
- **Logic:** the three new tests pass 8, 7 and 7. Document operations (19),
  group workspace context (27), statistics (31) and workspace authoring (27)
  are unchanged.

## Related

- [V2 Group Document Management](../features/V2_GROUP_DOCUMENT_MANAGEMENT.md)
- [V2 Group Agents](../features/V2_GROUP_AGENTS.md)
