# test_v2_elicitation_composer.py
"""
Browser regressions for composer-aware inline clarification answers.
Version: 0.261.099
Implemented in: 0.261.096

Exercise the real cards, composer, stores, controller, and request builders.
Only API responses are replaced. The existing Azure Playwright connection fixture
also supports a local browser; no live application data is read or modified.
"""

import copy
import json
import mimetypes
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

# Standalone execution uses the same fixtures as pytest discovery.
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "orchestration"))

import harness_build as hb  # noqa: E402
from playwright_connection import connect_options  # noqa: E402,F401


pytestmark = pytest.mark.ui
ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "application" / "single_app" / "static"
ORIGIN = "http://simplechat.test"
CONVERSATION = "inline-answer-conversation"
DOCUMENTS = [
    {"id": "suggested-document", "title": "Suggested report", "file_name": "suggested.pdf", "status": "Processing complete", "percentage_complete": 100},
    {"id": "different-document", "title": "Different report", "file_name": "different.pdf", "status": "Processing complete", "percentage_complete": 100},
]


def reference(document):
    return {
        "kind": "document", "id": document["id"], "label": document["title"],
        "scope": {"kind": "personal", "id": None, "name": "My workspace"},
    }


def file_question(multiple=True):
    return {
        "elicitation_id": "inline-files",
        "contract_version": 2,
        "run_id": "",
        "revision": 0,
        "message": "Choose the sources for this request.",
        "requested_schema": {
            "type": "object",
            "properties": {"files": {
                "type": "array" if multiple else "string",
                **({"items": {"type": "string"}} if multiple else {}),
                "title": "Source files",
            }},
            "required": ["files"],
        },
        "ui_hints": {
            "order": ["files"], "pages": [["files"]],
            "fields": {"files": {"input": "files", "candidates": [reference(DOCUMENTS[0])]}},
        },
    }


def choice_question():
    return {
        "elicitation_id": "inline-choices",
        "contract_version": 2,
        "run_id": "",
        "revision": 0,
        "message": "Choose the audience and format.",
        "requested_schema": {
            "type": "object",
            "properties": {
                "audiences": {"type": "array", "items": {"type": "string", "enum": ["Staff", "Customers"]}, "title": "Audience"},
                "format": {"type": "string", "enum": ["Summary", "Detailed"], "title": "Format"},
            },
            "required": ["audiences", "format"],
        },
        "ui_hints": {"pages": [["audiences"], ["format"]], "order": ["audiences", "format"]},
    }


class InlineApi:
    def __init__(self, page):
        self.page = page
        self.question = file_question()
        self.plan_calls = []
        self.upload_calls = []
        self.knowledge_calls = []
        self.documents = {item["id"]: copy.deepcopy(item) for item in DOCUMENTS}
        self.fail_next_plan = False
        self.fail_next_upload = False
        self.chat_only_upload = False
        self.hold_next_answer = False
        self.held_answer = None
        self.errors = []
        self.unexpected = []
        self.expected_http_failures = set()

    def handle(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        path = parsed.path
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.unexpected.append(request.url)
            route.abort()
            return
        if request.method == "GET":
            if path == "/harness.html":
                route.fulfill(path=str(hb.HERE / "harness.html"), content_type="text/html")
                return
            if path == "/harness.bundle.js":
                route.fulfill(path=str(hb.BUNDLE), content_type="application/javascript")
                return
            if path.startswith("/static/"):
                asset = (STATIC / path.removeprefix("/static/")).resolve()
                if asset.is_relative_to(STATIC.resolve()) and asset.is_file():
                    route.fulfill(path=str(asset), content_type=mimetypes.guess_type(asset)[0] or "application/octet-stream")
                    return
            if path in ("/api/documents/tags", "/api/group_documents/tags", "/api/public_workspace_documents/tags"):
                route.fulfill(json={"tags": []})
                return
            if path in ("/api/documents", "/api/group_documents", "/api/public_workspace_documents"):
                query = parse_qs(parsed.query).get("search", [""])[0].lower()
                docs = [doc for doc in self.documents.values() if query in f"{doc['title']} {doc['file_name']}".lower()]
                route.fulfill(json={"documents": docs if path == "/api/documents" else [], "total_count": len(docs)})
                return
            if path.startswith("/api/documents/"):
                document = self.documents.get(path.rsplit("/", 1)[-1])
                if document:
                    route.fulfill(json=document)
                    return
            if path == "/api/user/settings":
                route.fulfill(json={"settings": {}})
                return

        if request.method == "POST" and path == "/api/v2/orchestration/plan":
            body = request.post_data_json
            self.plan_calls.append(body)
            if self.fail_next_plan and body.get("elicitation_response"):
                self.fail_next_plan = False
                self.expected_http_failures.add((path, 400))
                route.fulfill(status=400, json={"error": "The answer could not be saved.", "details": ["Please try this answer again."]})
                return
            if self.hold_next_answer and body.get("elicitation_response"):
                self.hold_next_answer = False
                self.held_answer = (route, body)
                return
            if body.get("elicitation_response"):
                frames = [self.answer_frame(body)]
            else:
                frames = [{"type": "orchestration_elicitation", "elicitation": {
                    **self.question, "turn_id": body["turn_id"],
                }}]
            route.fulfill(content_type="text/event-stream", body="".join(
                f"data: {json.dumps(frame)}\n\n" for frame in frames
            ))
            return
        if request.method == "POST" and path == "/api/v2/prompts/fill-variables":
            self.knowledge_calls.append(request.post_data_json)
            route.fulfill(json={
                "values": [{
                    "key": "company",
                    "value": "Contoso",
                    "sources": [{
                        "document_id": "suggested-document",
                        "chunk_id": "company-chunk",
                        "title": "Suggested report",
                        "page_number": 1,
                        "excerpt": "Company: Contoso",
                    }],
                }],
                "unresolved": [],
            })
            return
        if request.method == "POST" and path == "/upload":
            payload = (request.post_data_buffer or b"").decode("utf-8", errors="replace")
            self.upload_calls.append(payload)
            if self.fail_next_upload:
                self.fail_next_upload = False
                self.expected_http_failures.add((path, 500))
                route.fulfill(status=500, json={"error": "Fixture upload failed. Try again."})
                return
            match = re.search(r'filename="([^"]+)"', payload)
            filename = match.group(1) if match else "upload.pdf"
            number = len(self.upload_calls)
            if self.chat_only_upload:
                route.fulfill(json={
                    "conversation_id": CONVERSATION, "file_message_id": f"chat-file-{number}",
                    "message": "File added to the conversation successfully",
                    "workspace_document_id": None, "workspace_document": None,
                })
                return
            document_id = f"uploaded-document-{number}"
            document = {
                "id": document_id, "document_id": document_id, "title": filename,
                "file_name": filename, "scope": "personal",
                "status": "Processing pages", "percentage_complete": 25,
            }
            self.documents[document_id] = document
            route.fulfill(json={
                "conversation_id": CONVERSATION, "file_message_id": f"chat-file-{number}",
                "workspace_scope": "personal", "workspace_document_id": document_id,
                "workspace_document": document,
            })
            return
        self.unexpected.append(f"{request.method} {path}")
        route.fulfill(status=404, json={"error": "Unexpected fixture request."})

    def answer_frame(self, body):
        return {"type": "orchestration_plan", "plan": {
            "plan_id": "accepted-plan", "run_id": "accepted-run",
            "conversation_id": CONVERSATION, "turn_id": body["turn_id"],
            "revision": body["elicitation_revision"] + 1,
            "intent": {"summary": "Use the supplied answer", "complexity": "simple"},
            "steps": [{"step_id": "respond", "capability_id": "respond", "title": "Answer", "arguments": {}}],
            "approval": {"mode": "manual", "state": "pending", "timeout_seconds": 0},
            "status": "awaiting_approval",
        }}

    def release_answer(self):
        assert self.held_answer is not None, "No pending answer request was captured."
        route, body = self.held_answer
        self.held_answer = None
        route.fulfill(content_type="text/event-stream", body=f"data: {json.dumps(self.answer_frame(body))}\n\n")

    def open(self, question=None, main_composer=False):
        self.question = question or file_question()
        self.page.route("**/*", self.handle)
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on("console", self.record_console)
        self.page.goto(f"{ORIGIN}/harness.html")
        self.page.wait_for_function("() => Boolean(window.OrchHarness)")
        styles = list((STATIC / "v2" / "assets").glob("*.css"))
        assert styles, "Build the existing V2 SPA before running browser layout checks."
        for stylesheet in styles:
            self.page.add_style_tag(path=str(stylesheet))
        self.turn_id = self.page.evaluate(
            """async ({conv, main}) => {
                const H = window.OrchHarness;
                H.reset();
                H.stores.bootstrap.useBootstrapStore.setState({data: {
                    version: '0.261.096',
                    user: {id: 'fixture-user', display_name: 'Fixture User', roles: []},
                    features: {enable_user_workspace: true, enable_chat_file_uploads: true},
                    settings: {max_file_size_mb: 25},
                    scope: {groups: [], public_workspaces: []},
                    catalogs: {models: [], agents: [], prompts: [
                        {id: 'summary-prompt', name: 'Summary', content: 'Summarize {{composer}}.', scope_type: 'personal'},
                        {id: 'company-prompt', name: 'Extract company', content: 'Company: {{company}}', scope_type: 'personal'},
                    ]},
                }});
                H.stores.chat.useChatStore.setState({
                    activeConversationId: conv, activeConversationKind: 'personal',
                    messages: [], streaming: false, conversations: [{id: conv, title: 'Inline answers'}],
                });
                await H.controller.startOrchestrationPlan({
                    conversationId: conv, message: 'Analyze the supplied sources', approvalMode: 'manual',
                    seeds: {model_deployment: 'original-model', prompt_info: {id: 'original-prompt'}},
                });
                const turn = H.stores.orchestration.useOrchestrationStore.getState().activeTurns[conv];
                H.mount('mount-b', 'ElicitationCard', {conversationId: conv, turnId: turn}, {strictMode: true});
                if (main) H.mount('mount-a', 'Composer');
                return turn;
            }""",
            {"conv": CONVERSATION, "main": main_composer},
        )
        expect(self.card).to_be_visible()

    def record_console(self, message):
        if message.type != "error":
            return
        path = urlsplit(message.location.get("url", "")).path
        status = re.search(r"^Failed to load resource: the server responded with a status of (\d+)", message.text)
        if status and (path, int(status.group(1))) in self.expected_http_failures:
            return
        self.errors.append(message.text)

    @property
    def card(self):
        return self.page.locator("#mount-b").get_by_role("region", name="Follow-up questions")

    @property
    def finish(self):
        return self.card.get_by_role("button", name="Finish", exact=True)

    @property
    def reply(self):
        return self.plan_calls[-1]

    def ready(self, number=1):
        self.documents[f"uploaded-document-{number}"].update({
            "status": "Processing complete", "percentage_complete": 100,
        })

    def upload(self, filename="source.pdf"):
        with self.page.expect_response(lambda response: urlsplit(response.url).path == "/upload"):
            self.card.locator('input[type="file"]').first.set_input_files({
                "name": filename, "mimeType": "application/pdf", "buffer": b"%PDF-1.4\nfixture",
            })

    def finish_and_wait(self):
        with self.page.expect_request(lambda request: request.method == "POST" and "/orchestration/plan" in request.url):
            self.finish.click()
        self.page.wait_for_function(
            "() => Object.keys(window.OrchHarness.stores.orchestration.useOrchestrationStore.getState().plans).length > 0"
        )


@pytest.fixture
def inline_api(page):
    hb.ensure_bundle()
    api = InlineApi(page)
    yield api
    assert not api.errors, api.errors
    assert not api.unexpected, api.unexpected


def test_file_question_accepts_a_different_hash_reference(inline_api):
    api = inline_api
    api.open()
    expect(api.finish).to_be_disabled()
    editor = api.card.get_by_role("textbox", name="Additional details for Source files (optional)", exact=True)
    editor.fill("#Different")
    option = api.card.get_by_role("option", name=re.compile("Different report"))
    expect(option).to_be_visible()
    editor.press("Enter")
    expect(editor).to_have_value(re.compile(r"#\[Different report\]"))
    expect(api.card.get_by_role("checkbox", name=re.compile("Suggested report"))).not_to_be_checked()
    expect(api.finish).to_be_enabled()
    api.finish_and_wait()
    assert api.reply["elicitation_response"]["content"]["files"] == ["different-document"]
    assert api.reply["elicitation_context"]["files"]["references"][0]["id"] == "different-document"
    assert api.reply["elicitation_id"] == "inline-files"
    assert api.reply["elicitation_submission_id"]
    assert api.reply["prompt_info"]["id"] == "original-prompt"


def test_single_and_multiple_choices_keep_optional_answer_context(inline_api):
    api = inline_api
    api.open(choice_question())
    api.card.get_by_role("checkbox", name="Staff", exact=True).check()
    api.card.get_by_role("checkbox", name="Customers", exact=True).check()
    api.card.get_by_role("textbox", name="Additional details for Audience (optional)").fill("Use the same terminology for both")
    api.card.get_by_role("button", name="Next", exact=True).click()
    expect(api.finish).to_be_disabled()
    api.card.get_by_role("radio", name="Summary", exact=True).check()
    api.card.get_by_role("textbox", name="Additional details for Format (optional)").fill("No more than three paragraphs")
    api.finish_and_wait()
    assert api.reply["elicitation_response"]["content"] == {"audiences": ["Staff", "Customers"], "format": "Summary"}
    assert api.reply["elicitation_context"]["audiences"]["text"] == "Use the same terminology for both"
    assert api.reply["elicitation_context"]["format"]["text"] == "No more than three paragraphs"


def test_upload_waits_for_ready_then_sends_a_real_reference(inline_api):
    api = inline_api
    api.open()
    api.upload("missing-document.pdf")
    expect(api.card.get_by_text("missing-document.pdf", exact=False).first).to_be_visible()
    expect(api.finish).to_be_disabled()
    api.ready()
    expect(api.finish).to_be_enabled(timeout=15000)
    api.finish_and_wait()
    assert api.reply["elicitation_response"]["content"]["files"] == ["uploaded-document-1"]
    assert api.reply["elicitation_context"]["files"]["references"][0]["kind"] == "document"
    assert CONVERSATION in api.upload_calls[0]


def test_conversation_only_upload_is_not_a_fake_workspace_document(inline_api):
    api = inline_api
    api.chat_only_upload = True
    api.open(file_question(False))
    api.upload("notes.pdf")
    expect(api.finish).to_be_enabled(timeout=10000)
    api.finish_and_wait()
    assert api.reply["elicitation_response"]["content"]["files"] == "chat-file-1"
    ref = api.reply["elicitation_context"]["files"]["references"][0]
    assert ref["kind"] == "chat_attachment"
    assert ref["scope"]["id"] == CONVERSATION


def test_failed_submit_keeps_draft_and_retries_with_same_identity(inline_api):
    api = inline_api
    api.open()
    api.card.get_by_role("checkbox", name=re.compile("Suggested report")).check()
    editor = api.card.get_by_role("textbox", name="Additional details for Source files (optional)")
    editor.fill("Focus on the conclusions")
    api.fail_next_plan = True
    api.finish.click()
    expect(api.card.get_by_role("alert")).to_contain_text("Please try this answer again.")
    expect(editor).to_have_value("Focus on the conclusions")
    expect(api.card.get_by_role("checkbox", name=re.compile("Suggested report"))).to_be_checked()
    first_attempt = api.reply["elicitation_submission_id"]
    api.finish_and_wait()
    assert api.reply["elicitation_submission_id"] == first_attempt
    assert len(api.plan_calls) == 3


def test_failed_upload_does_not_silently_ignore_the_missing_file(inline_api):
    api = inline_api
    api.open()
    api.card.get_by_role("checkbox", name=re.compile("Suggested report")).check()
    api.fail_next_upload = True
    api.upload()
    expect(api.card.get_by_text(re.compile("Fixture upload failed"))).to_be_visible()
    expect(api.finish).to_be_disabled()
    expect(api.card.get_by_role("checkbox", name=re.compile("Suggested report"))).to_be_checked()
    expect(api.card.get_by_role("button", name=re.compile("Retry", re.I)).first).to_be_enabled()
    api.card.get_by_role("button", name=re.compile("Remove.*source.pdf", re.I)).click()
    expect(api.finish).to_be_enabled()


def test_double_submission_is_guarded_while_the_card_waits(inline_api):
    api = inline_api
    api.open()
    api.card.get_by_role("checkbox", name=re.compile("Suggested report")).check()
    api.hold_next_answer = True
    with api.page.expect_request(lambda request: request.method == "POST" and "/orchestration/plan" in request.url):
        api.finish.click()
    expect(api.card.get_by_role("button", name="Submitting...", exact=True)).to_be_disabled()
    duplicate = api.page.evaluate(
        """({conv, turn}) => window.OrchHarness.controller.answerElicitation({
            conversationId: conv, turnId: turn, elicitationId: 'inline-files',
            response: {action: 'accept', content: {files: ['suggested-document']}},
        })""",
        {"conv": CONVERSATION, "turn": api.turn_id},
    )
    assert duplicate["ok"] is False
    assert len(api.plan_calls) == 2
    api.release_answer()
    expect(api.card).not_to_be_visible()


def test_upload_keeps_processing_when_its_question_page_is_hidden(inline_api):
    api = inline_api
    spec = file_question()
    spec["requested_schema"]["properties"]["purpose"] = {"type": "string", "title": "Purpose"}
    spec["requested_schema"]["required"].append("purpose")
    spec["ui_hints"]["pages"] = [["files"], ["purpose"]]
    spec["ui_hints"]["order"] = ["files", "purpose"]
    api.open(spec)
    api.upload()
    api.card.get_by_role("button", name="Next", exact=True).click()
    api.card.get_by_role("textbox", name="Purpose", exact=True).fill("Explain the findings")
    expect(api.finish).to_be_disabled()
    api.ready()
    expect(api.finish).to_be_enabled(timeout=15000)
    api.finish_and_wait()
    assert api.reply["elicitation_response"]["content"] == {
        "files": ["uploaded-document-1"], "purpose": "Explain the findings",
    }


def test_late_draft_updates_cannot_change_a_new_question_revision(inline_api):
    api = inline_api
    api.open()
    result = api.page.evaluate(
        """({conv, turn}) => {
            const H = window.OrchHarness;
            const store = H.stores.orchestration.useOrchestrationStore;
            const key = conv + '\\u0000' + turn;
            const question = store.getState().elicitations[key];
            store.getState().setElicitation(conv, turn, {...question, revision: 1});
            store.getState().updateElicitationDraft(conv, turn, question.elicitation_id, 0, draft => ({
                ...draft, editors: {...draft.editors, files: {...draft.editors.files, text: 'Late old answer'}},
            }));
            return {
                text: store.getState().elicitationDrafts[key].editors.files.text,
                revision: store.getState().elicitationDrafts[key].revision,
            };
        }""",
        {"conv": CONVERSATION, "turn": api.turn_id},
    )
    assert result == {"text": "", "revision": 1}
    response = api.page.evaluate(
        """({conv, turn}) => window.OrchHarness.controller.answerElicitation({
            conversationId: conv, turnId: turn, elicitationId: 'inline-files',
            elicitationRevision: 0, response: {action: 'accept', content: {files: ['suggested-document']}},
        })""",
        {"conv": CONVERSATION, "turn": api.turn_id},
    )
    assert response["ok"] is False
    assert len(api.plan_calls) == 1


def test_paging_and_remount_preserve_separate_answers(inline_api):
    api = inline_api
    api.open(choice_question())
    api.card.get_by_role("checkbox", name="Staff", exact=True).check()
    api.card.get_by_role("textbox", name="Additional details for Audience (optional)").fill("First answer")
    api.card.get_by_role("button", name="Next", exact=True).click()
    api.card.get_by_role("radio", name="Detailed", exact=True).check()
    api.card.get_by_role("textbox", name="Additional details for Format (optional)").fill("Second answer")
    api.page.evaluate(
        """({conv, turn}) => {
            const H = window.OrchHarness;
            H.unmount('mount-b');
            H.stores.orchestration.useOrchestrationStore.getState().pruneSettled('another-conversation');
            H.mount('mount-b', 'ElicitationCard', {conversationId: conv, turnId: turn});
        }""",
        {"conv": CONVERSATION, "turn": api.turn_id},
    )
    expect(api.card.get_by_role("textbox", name="Additional details for Format (optional)")).to_have_value("Second answer")
    api.card.get_by_role("button", name="Back", exact=True).click()
    expect(api.card.get_by_role("textbox", name="Additional details for Audience (optional)")).to_have_value("First answer")
    expect(api.card.get_by_role("checkbox", name="Staff", exact=True)).to_be_checked()


def test_main_and_inline_attached_prompts_have_separate_state_and_ids(inline_api):
    api = inline_api
    api.open(main_composer=True)
    main = api.page.locator("#mount-a")
    main.get_by_role("textbox", name="Message", exact=True).fill("/Summary")
    main.get_by_role("option", name=re.compile("Summary")).click()
    main.get_by_role("textbox", name="Message", exact=True).fill("Main draft stays here")
    inline = api.card.get_by_role("textbox", name="Additional details for Source files (optional)")
    inline.fill("/Summary")
    api.card.get_by_role("option", name=re.compile("Summary")).click()
    inline.fill("Only the selected source")
    api.card.get_by_role("button", name="Edit Summary for this message").click()
    api.card.get_by_role("textbox", name="Prompt text", exact=True).fill("Describe {{composer}}.")
    main.get_by_role("button", name="Edit Summary for this message").click()
    expect(main.get_by_role("textbox", name="Prompt text", exact=True)).to_have_value("Summarize {{composer}}.")
    expect(main.get_by_role("textbox", name="Message", exact=True)).to_have_value("Main draft stays here")
    assert api.page.evaluate(
        "() => { const ids = [...document.querySelectorAll('[id]')].map(el => el.id); return ids.length === new Set(ids).size; }"
    )
    api.card.get_by_role("checkbox", name=re.compile("Suggested report")).check()
    api.finish_and_wait()
    assert api.reply["elicitation_context"]["files"]["text"] == "Describe Only the selected source."
    assert api.reply["elicitation_context"]["files"]["prompt_info"]["id"] == "summary-prompt"
    assert api.reply["prompt_info"]["id"] == "original-prompt"


def test_suggested_file_selection_grounds_inline_prompt_variable_fill(inline_api):
    api = inline_api
    api.open()
    api.card.get_by_role("checkbox", name=re.compile("Suggested report")).check()
    editor = api.card.get_by_role("textbox", name="Additional details for Source files (optional)")
    editor.fill("/Extract company")
    api.card.get_by_role("option", name=re.compile("Extract company")).click()
    fill = api.card.get_by_role("button", name="Find in knowledge", exact=True)
    expect(fill).to_be_enabled()
    fill.click()
    expect(api.card.get_by_role("textbox", name=re.compile("company", re.I))).to_have_value("Contoso")
    assert len(api.knowledge_calls) == 1
    assert api.knowledge_calls[0]["selected_document_ids"] == ["suggested-document"]
    assert api.knowledge_calls[0]["search_all"] is False
    assert api.knowledge_calls[0]["conversation_id"] == CONVERSATION
    api.finish_and_wait()
    assert api.reply["elicitation_response"]["content"]["files"] == ["suggested-document"]
    assert api.reply["elicitation_context"]["files"]["text"] == "Company: Contoso"
    assert api.reply["elicitation_context"]["files"]["prompt_info"]["variables"]["company"] == "Contoso"
    assert api.reply["prompt_info"]["id"] == "original-prompt"


@pytest.mark.parametrize("action", ["decline", "cancel"])
def test_refusal_never_carries_draft_context(inline_api, action):
    api = inline_api
    api.open()
    api.card.get_by_role("checkbox", name=re.compile("Suggested report")).check()
    api.card.get_by_role("textbox", name="Additional details for Source files (optional)").fill("Do not submit these details")
    button = "Decline to answer" if action == "decline" else "Cancel and abandon this request"
    if action == "cancel":
        api.card.get_by_role("button", name=button, exact=True).click()
        expect(api.card).not_to_be_visible()
        assert len(api.plan_calls) == 1
        assert api.page.evaluate(
            """() => {
                const state = window.OrchHarness.stores.orchestration.useOrchestrationStore.getState();
                return Object.keys(state.elicitationDrafts).length === 0
                    && Object.keys(state.activeTurns).length === 0;
            }"""
        )
        return
    with api.page.expect_request(lambda request: request.method == "POST" and "/orchestration/plan" in request.url):
        api.card.get_by_role("button", name=button, exact=True).click()
    assert api.reply["elicitation_response"] == {"action": action, "content": {}}
    assert "elicitation_context" not in api.reply


@pytest.mark.parametrize("width,theme", [(1440, "light"), (390, "dark")])
def test_question_editor_fits_desktop_and_mobile(inline_api, width, theme):
    api = inline_api
    api.page.set_viewport_size({"width": width, "height": 900})
    api.open()
    api.page.evaluate("(dark) => document.documentElement.classList.toggle('dark', dark)", theme == "dark")
    expect(api.card).to_be_visible()
    expect(api.card.get_by_role("button", name="Attach a file", exact=True)).to_be_visible()
    assert api.page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
