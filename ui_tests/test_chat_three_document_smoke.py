# test_chat_three_document_smoke.py
"""
Fresh three-source Analyze, saved evidence, downloads, and cross-UI reuse.
Version: 0.261.114
Implemented in: 0.261.114

Real producer, export builders, saved readers, download route, and both browser
renderers run offline. Source/storage I/O and provider responses are deterministic;
this does not claim deployed gpt-4o acceptance or live cross-account verification.
"""

import copy
import csv
import hashlib
import io
import json
import logging
import mimetypes
import os
import re
from pathlib import Path
from urllib.parse import quote, urlsplit

import pytest
from azure.core.exceptions import AzureError, ResourceNotFoundError
from flask import Flask, Response, jsonify, request
from playwright.sync_api import expect
from werkzeug.utils import secure_filename

import test_chat_saved_analysis as shared
from test_chat_saved_analysis import analysis_assets, analysis_client, analysis_ui, connect_options  # noqa: F401
from test_v2_orchestration_plan_editor import make_plan
from test_analyze_backend_saved_integration import runner_namespace
from test_analyze_three_document_smoke import FINDINGS, PASSAGES, PROMPT, source_completion
from test_chat_artifact_download_bytes import load_definitions
from test_saved_analysis_service import ChatSections, read_options, saved
from test_support.document_analysis import USER_ID, FixtureAnalysisClient, document_analysis_runtime, original_document
from content_screening.contracts import ScreeningError


pytestmark = pytest.mark.ui
CONVERSATION = shared.CONVERSATION
EXPLANATION = "Maya Chen already owns the quarterly reviews. This explains the saved finding, not a new source review."


@pytest.fixture
def saved_chat():
    sections = ChatSections()
    state = {"source_allowed": True, "conversation_allowed": True, "resolutions": 0}
    fixture = {
        "state": state, "store": sections, "sources": [], "artifacts": {}, "producer_calls": [],
        "descriptor": {}, "followups": [],
        "message": {"id": "fresh-analysis", "conversation_id": CONVERSATION, "role": "assistant", "content": "", "metadata": {}},
    }

    def authorize(actor, conversation):
        if actor not in (USER_ID, "reader") or conversation != CONVERSATION or not state["conversation_allowed"]:
            raise PermissionError("Not authorized.")
        return {"id": conversation, "user_id": USER_ID}

    def resolve(document_ids, **kwargs):
        state["resolutions"] += 1
        assert set(document_ids) == set(PASSAGES)
        return [{
            **copy.deepcopy(source), "authorization_status": "authorized" if state["source_allowed"] else "unresolved",
        } for source in fixture["sources"]]

    def message_loader(actor, conversation, message_id):
        authorize(actor, conversation)
        if message_id != fixture["message"]["id"]:
            raise LookupError("No saved result.")
        return fixture["message"]

    def produce():
        assert not fixture["producer_calls"], "Only one original-source analysis is allowed."
        documents = {
            name: original_document(name, [passage], scope="group", scope_id="isolated-analysis-qa")
            for name, passage in PASSAGES.items()
        }
        model = FixtureAnalysisClient(source_completion)
        with document_analysis_runtime(documents) as runtime:
            analysis = runtime.producer.run_document_analysis(
                user_id=USER_ID, analysis_prompt=PROMPT, document_ids=list(documents),
                invoke_prompt=model.invoke_prompt, doc_scope="all", window_size=1,
                max_documents=3, max_retries_per_window=0, result_version="analyze-final-v1",
            )
        fixture["producer_calls"].extend(model.calls)
        fixture["sources"] = analysis["analysis_sources"]
        producer = {"kind": "chat", "conversation_id": CONVERSATION, "message_id": "fresh-analysis"}

        def upload(**kwargs):
            content = kwargs["file_content"].encode("utf-8")
            artifact_id = f"fresh-{kwargs['output_format']}"
            fixture["artifacts"][artifact_id] = {
                "content": content, "id": artifact_id, "conversation_id": CONVERSATION, "role": "file",
                "filename": kwargs["file_name"], "file_content_source": "blob",
                "blob_container": "personal-chat", "blob_path": f"{USER_ID}/{CONVERSATION}/generated/{artifact_id}",
                "metadata": {
                    "is_generated_chat_artifact": True,
                    "generated_artifact_output_format": kwargs["output_format"],
                    "generated_artifact_content_sha256": hashlib.sha256(content).hexdigest(),
                    **saved.analysis_artifact_metadata(producer),
                },
            }
            return {"message": {"id": artifact_id, "file_name": kwargs["file_name"]}}

        exports = runner_namespace(upload_generated_analysis_artifact_for_current_user=upload)
        outputs = exports["_maybe_create_document_analysis_generated_artifacts"](
            analysis, PROMPT, conversation_id=CONVERSATION, analysis_producer=producer,
        )
        descriptor = saved.save_chat_analysis(
            {"reply": analysis["reply"], "analysis_result": analysis},
            user_id=USER_ID, conversation_id=CONVERSATION, message_id=producer["message_id"],
            authorize_conversation=authorize, save_result=sections.save, source_resolver=resolve,
        )
        fixture["descriptor"] = descriptor
        fixture["message"] = {
            "id": producer["message_id"], "conversation_id": CONVERSATION, "role": "assistant",
            "content": analysis["analysis_reply"],
            "metadata": {"saved_analysis": descriptor, "generated_analysis_artifacts": outputs["artifacts"]},
        }

    fixture.update(message_loader=message_loader, source_resolver=resolve, produce=produce)
    return fixture


class FreshAnalysisApi(shared.AnalysisApi):
    def __init__(self, backend, css):
        super().__init__(backend, css)
        self.messages = []
        self.plan_body = None
        self.download_client = self.build_download_client()

    def build_download_client(self):
        def authorize_artifact(actor, conversation, message_id):
            self.fixture["message_loader"](actor, conversation, self.fixture["message"]["id"])
            artifact = self.fixture["artifacts"][message_id]
            saved.authorize_analysis_artifact(
                actor, artifact, parents_loader=lambda *args: [self.fixture["message"]],
                result_reader=lambda user, context: saved.load_saved_analysis(user, context, **read_options(self.fixture)),
            )
            return copy.deepcopy(artifact)

        def download(container, path):
            assert container == "personal-chat"
            return next(item["content"] for item in self.fixture["artifacts"].values() if item["blob_path"] == path)

        namespace = {
            "hashlib": hashlib, "logging": logging, "mimetypes": mimetypes, "os": os, "quote": quote,
            "Response": Response, "jsonify": jsonify, "request": request, "secure_filename": secure_filename,
            "AzureError": AzureError, "ResourceNotFoundError": ResourceNotFoundError,
            "ScreeningError": ScreeningError,
            "_get_authorized_chat_artifact_message": authorize_artifact,
            "download_blob_content": download, "get_current_user_id": lambda: "reader",
            "log_event": lambda *args, **kwargs: None,
        }
        load_definitions("route_enhanced_citations.py", {
            "_resolve_generated_artifact_file_name", "_normalize_response_file_name",
            "_build_content_disposition", "_serve_chat_artifact_download", "download_chat_artifact",
        }, namespace)
        app = Flask("fresh-analysis-download")
        app.add_url_rule("/api/chat_artifacts/download", view_func=namespace["download_chat_artifact"])
        return app.test_client()

    def stream(self, route, *, replay=False):
        body = route.request.post_data_json if route.request.post_data else {}
        if body.get("analysis_result_context"):
            context = body["analysis_result_context"]
            payload, _ = saved.load_saved_analysis_input("reader", context, **read_options(self.fixture))
            data = json.loads(payload)
            assert len(data["records"]) == 4 and data["original_sources_reanalyzed"] is False
            self.fixture["followups"].append(context)
            message = {
                "id": "fresh-explanation", "conversation_id": CONVERSATION, "role": "assistant",
                "content": EXPLANATION, "metadata": {"analysis_result_contexts": [context]},
            }
        else:
            self.fixture["produce"]()
            message = copy.deepcopy(self.fixture["message"])
            self.message = message
        self.messages.append(message)
        event = {
            "done": True, "conversation_id": CONVERSATION, "message_id": message["id"],
            "full_content": message["content"], "metadata": message["metadata"],
        }
        if urlsplit(route.request.url).path.endswith("/orchestration/run"):
            event.update(type="orchestration_done", run_id="fresh-run", turn_id=self.plan_body["turn_id"],
                         status="completed", outcome="completed", message_saved=True)
        frames = [{"content": message["content"]}, event]
        route.fulfill(content_type="text/event-stream", body="".join(f"data: {json.dumps(frame)}\n\n" for frame in frames))

    def handle(self, route):
        path = urlsplit(route.request.url).path
        body = route.request.post_data_json if route.request.post_data else None
        if path == "/api/v2/orchestration/plan":
            self.plan_body = body
            assert body["message"] == PROMPT
            assert set(body["selected_document_ids"]) == set(PASSAGES)
            assert body["approval_mode"] == "manual"
            assert "document_search" not in body["required_capabilities"]
            plan = make_plan(CONVERSATION, body["turn_id"])
            plan["run_id"] = "fresh-run"
            plan["intent"]["summary"] = "Analyze the three selected documents."
            plan["inputs"]["documents"] = [
                {"document_id": name, "display_name": name.title(), "selected_by_user": True} for name in PASSAGES
            ]
            plan["steps"] = [{
                "step_id": "analyze", "capability_id": "document_analyze", "title": "Analyze three documents",
                "arguments": {"document_ids": list(PASSAGES), "analysis_prompt": PROMPT},
                "phase": "knowledge", "enabled": True, "status": "pending",
            }, {
                "step_id": "respond", "capability_id": "respond", "title": "Explain accepted findings",
                "arguments": {}, "phase": "reasoning", "enabled": True, "status": "pending", "depends_on": ["analyze"],
            }]
            event = {"type": "orchestration_plan", "plan": plan, "done": True}
            route.fulfill(content_type="text/event-stream", body=f"data: {json.dumps(event)}\n\n")
            return
        if path == "/api/v2/orchestration/run":
            self.requests.append({"path": path, "method": "POST", "body": body})
            self.stream(route)
            return
        if path == "/api/group_documents":
            route.fulfill(json={"documents": [
                {"id": name, "title": name.title(), "file_name": f"{name}.txt", "status": "completed",
                 "group_id": "isolated-analysis-qa"}
                for name in PASSAGES
            ], "total_count": 3})
            return
        if path == "/api/chat_artifacts/download":
            parsed = urlsplit(route.request.url)
            response = self.download_client.get(parsed.path + "?" + parsed.query)
            route.fulfill(status=response.status_code, headers=dict(response.headers), body=response.data)
            return
        if path == "/api/chat/document-action/stream":
            assert body["message"] == PROMPT
            self.requests.append({"path": path, "method": "POST", "body": body})
            self.stream(route)
            return
        super().handle(route)


@pytest.fixture
def analysis_api_factory():
    return FreshAnalysisApi


def assert_findings(ui):
    region = shared.result(ui)
    expect(region).to_be_visible()
    region.locator("summary").filter(has_text="Findings and limitations").click()
    expect(region).to_contain_text("Showing 1–4 of 4 records")
    expect(region).to_contain_text("3 of 3 sources")
    for entries in FINDINGS.values():
        for _, values in entries:
            expect(region).to_contain_text(values["explanation"])
    region.locator("summary").filter(has_text="Evidence for finding").first.click()
    expect(region.get_by_role("blockquote").first).to_be_visible()
    assert "end_chunk_sequence" not in ui.page.locator("body").inner_text()
    return region


def test_new_three_source_result_reloads_in_both_uis_and_reuses_saved_findings(analysis_ui):
    ui = analysis_ui
    ui.mount(history=False, orchestration=ui.renderer == "v2")
    if ui.renderer == "v2":
        ui.page.evaluate("""() => {
            const S = window.OrchHarness.stores.bootstrap.useBootstrapStore;
            S.setState(state => ({data: {...state.data,
                features: {...state.data.features, enable_group_workspaces: true},
                scope: {...state.data.scope, groups: [{id: 'isolated-analysis-qa', name: 'Analyze QA'}]},
            }}));
        }""")
        ui.page.get_by_title("Manual controls", exact=True).click()
        ui.page.get_by_title("Documents", exact=True).click()
        for name in PASSAGES:
            ui.page.get_by_role("button", name=re.compile(f"^{name.title()}")).and_(
                ui.page.locator("button[aria-pressed]")
            ).click()
        ui.page.get_by_role("button", name="Done", exact=True).click()
        ui.page.get_by_role("textbox", name="Message", exact=True).fill(PROMPT)
        ui.page.get_by_role("button", name="Send message", exact=True).click()
        expect(ui.page.get_by_role("button", name="Approve and run the plan").first).to_be_visible()
        ui.page.get_by_role("button", name="Approve and run the plan").first.click()
    else:
        ui.page.get_by_label("Document action", exact=True).select_option("analyze")
        ui.page.evaluate("""(spec) => {
            return import('/static/js/chat/chat-streaming.js').then(module =>
                module.sendMessageWithStreaming({
                    message: spec.prompt, conversation_id: spec.conversation,
                    document_action: {type: 'analyze', document_ids: spec.documents},
                    selected_document_ids: spec.documents, model_deployment: 'gpt-4o',
                }, null, spec.conversation));
        }""", {"prompt": PROMPT, "conversation": CONVERSATION, "documents": list(PASSAGES)})
    assert_findings(ui)
    assert len(ui.api.fixture["producer_calls"]) == 3
    if ui.renderer == "v2":
        assert ui.api.plan_body["active_group_id"] == "isolated-analysis-qa"
    original_context = saved.saved_analysis_context(ui.api.fixture["descriptor"])
    for renderer in (ui.renderer, "classic" if ui.renderer == "v2" else "v2"):
        ui.renderer = renderer
        ui.mount(renderer_override=renderer)
        region = assert_findings(ui)
        ui.page.locator("summary").filter(has_text="Downloads").click()
        for output_format in ("csv", "md"):
            artifact = ui.api.fixture["artifacts"][f"fresh-{output_format}"]
            label = f"Download {artifact['filename']}" if renderer == "classic" else f"Download {output_format.upper()}"
            with ui.page.expect_download() as downloaded:
                ui.page.get_by_role("button", name=label, exact=True).click()
            content = Path(downloaded.value.path()).read_bytes()
            assert content == artifact["content"]
            if output_format == "csv":
                rows = list(csv.DictReader(io.StringIO(content.decode("utf-8"))))
                assert len(rows) == 4
        region.get_by_role("button", name="Ask about this analysis", exact=True).click()
        draft = ui.page.get_by_role("textbox", name="Message", exact=True)
        draft.fill("Explain the existing governance control.")
        draft.press("Enter")
        expect(ui.page.get_by_text(EXPLANATION, exact=True).filter(visible=True).first).to_be_visible()
        assert ui.api.fixture["followups"][-1] == original_context
    assert len(ui.api.fixture["producer_calls"]) == 3
    assert len(ui.api.fixture["followups"]) == 2
