# test_v2_orchestration_dependency_plans.py
"""
Real-component tests for version-aware orchestration plans and durable waiting.
Version: 0.261.127
Implemented in: 0.261.127
Refs: microsoft/simplechat#1509

Uses the existing local/Azure Playwright fixture, real React components, production
CSS, stores, SSE client and controller. Only HTTP boundaries are mocked. V2 plan
fixtures follow step_input_specs, _dependency_outputs and InputBinding.to_dict;
they do not admit a render_file capability or invent file lifecycle records.
No model/provider calls or Azure resources are created.

Build: npm --prefix .\\application\\v2_ui run build -- --outDir ..\\..\\ui_tests\\artifacts\\orchestration-plan-editor
Run: python -m pytest .\\ui_tests\\test_v2_orchestration_dependency_plans.py -q
"""

import copy
import re
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

import test_v2_orchestration_plan_editor as editor_tests
import test_v2_orchestration_recovery as recovery_tests
from test_v2_orchestration_plan_editor import (  # noqa: F401
    connect_options,
    editor_assets,
    editor_browser,
    editor_ui,
)


pytestmark = pytest.mark.ui
CONVERSATION = "dependency-chat"
TURN = "dependency-turn"
TITLES = [
    "Gather initial evidence", "Prepare findings", "Gather follow-up evidence",
    "Prepare answer", "Prepare optional notes",
]


def binding(step_id=None, output_name=None, existing_result=None):
    """The complete InputBinding wire object, including its nullable alternatives."""
    return {
        "version": "orchestration-input-binding-v1",
        "step_id": step_id,
        "output_name": output_name,
        "existing_result": existing_result,
    }


def dependency_plan(conversation=CONVERSATION, turn=TURN, mode="manual"):
    plan = editor_tests.make_plan(conversation, turn, mode)
    search_outputs = [
        {"name": "evidence", "kind": "evidence-set-v1"},
        {"name": "sources", "kind": "source-set-v1"},
        {"name": "prepared", "kind": "structured-v1"},
    ]
    specifications = [
        ("gather_first", "document_search", "gather", [], {"query": "Initial evidence"}, {},
         search_outputs),
        ("prepare_findings", "compose", "reason", ["gather_first"], {"instruction": "Prepare complete findings"},
         {"evidence": {"binding": binding("gather_first", "evidence"), "allow_partial": True}},
         [
             {"name": "findings", "kind": "records-v1",
              "columns": [{"name": "finding", "value_type": "string", "nullable": False}]},
             {"name": "context", "kind": "structured-v1",
              "schema": {"type": "object", "properties": {"topic": {"type": "string"}}}},
         ]),
        ("gather_followup", "document_search", "gather", ["prepare_findings"],
         {"query": "Follow-up evidence"}, {}, search_outputs),
        ("prepare_answer", "compose", "reason", ["prepare_findings", "gather_followup"],
         {"instruction": "Prepare the answer"},
         {
             "findings": {"binding": binding("prepare_findings", "findings"), "allow_partial": False},
             "followup": {"binding": binding("gather_followup", "evidence"), "allow_partial": False},
         }, [{"name": "answer", "kind": "markdown-v1"}]),
        ("prepare_notes", "compose", "reason", [], {"instruction": "Prepare optional notes"}, {},
         [{"name": "notes", "kind": "text-v1"}]),
    ]
    plan.update({
        "planner_contract_version": 2,
        "intent": {"summary": "Gather, prepare, gather again, then answer", "complexity": "complex"},
        "inputs": {"documents": [], "web": False, "required_capabilities": []},
        "assumptions": [],
        "validation": {"ok": True, "errors": [], "repairs": []},
        "final_response": binding("prepare_answer", "answer"),
        "steps": [
            {
                "step_id": step_id, "capability_id": capability, "role": role,
                "title": TITLES[index], "rationale": "", "depends_on": dependencies,
                "arguments": arguments, "inputs": inputs, "outputs": copy.deepcopy(outputs),
                "enabled": True, "optional": step_id == "prepare_notes",
                "estimated_cost": "low", "status": "pending",
            }
            for index, (step_id, capability, role, dependencies, arguments, inputs, outputs)
            in enumerate(specifications)
        ],
    })
    plan["outputs"] = [{"kind": "message"}] + [
        {"source_step_id": step["step_id"], **copy.deepcopy(output)}
        for step in plan["steps"] for output in step["outputs"]
    ]
    return plan


def seed_editor(api, plan):
    api.add(plan["conversation_id"], plan["turn_id"], plan["approval"]["mode"])
    editor = api.editors[plan["conversation_id"]]
    editor["plan"] = copy.deepcopy(plan)
    editor["history"] = [api.history(plan, "original", "As planned")]
    api.records[plan["run_id"]] = copy.deepcopy(plan)


def mount_editor(page, api, plan=None):
    plan = plan or dependency_plan()
    seed_editor(api, plan)
    editor_tests.mount(page, api, plan["conversation_id"], plan["turn_id"])
    return plan


def mount_run_view(page, api, plan=None, **props):
    plan = mount_editor(page, api, plan)
    page.evaluate(
        """(spec) => {
            const H = window.OrchHarness;
            H.unmount('mount-a');
            H.mount('mount-a', 'OrchestrationRunView', spec);
        }""",
        {"conversationId": plan["conversation_id"], "turnId": plan["turn_id"], **props},
    )
    return page.locator("#mount-a")


def plan_state(page):
    return editor_tests.state(page, CONVERSATION, TURN)


@pytest.mark.parametrize("width", [1440, 390])
def test_interleaved_roles_keep_actual_order_and_accessible_bindings(editor_ui, width):
    page, api = editor_ui
    page.set_viewport_size({"width": width, "height": 900})
    view = mount_run_view(page, api)
    expect(view.locator("h3")).to_have_text(["Gather", "Reason", "Gather", "Reason"])
    expect(view.locator("[data-step-id]")).to_have_count(5)
    rendered = view.locator("[data-step-id]").evaluate_all(
        "(steps) => steps.map(step => step.getAttribute('aria-label'))"
    )
    assert rendered == [f"Step {index + 1}: {title}" for index, title in enumerate(TITLES)]
    expect(view.get_by_role("region", name="Result bindings for Prepare answer")).to_contain_text(
        "Output findings from Prepare findings (records-v1). Complete results required."
    )
    expect(view.get_by_label("Final chat response binding")).to_contain_text(
        "Output answer from Prepare answer (markdown-v1)"
    )
    expect(view.get_by_text("Server file format reference", exact=True)).to_have_count(0)
    expect(view.get_by_role("link")).to_have_count(0)
    overflow = page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth")
    assert not overflow


@pytest.mark.parametrize("width", [1440, 390])
@pytest.mark.parametrize("version", [None, 1])
def test_legacy_plan_is_not_reclassified_by_current_role_descriptors(editor_ui, version, width):
    page, api = editor_ui
    page.set_viewport_size({"width": width, "height": 900})
    plan = editor_tests.make_plan(CONVERSATION, TURN)
    if version is None:
        plan.pop("planner_contract_version", None)
    else:
        plan["planner_contract_version"] = version
    plan["steps"][0].update(capability_id="document_analyze", phase="knowledge", role="reason")
    view = mount_run_view(page, api, plan)
    page.evaluate("""() => {
        const store = window.OrchHarness.stores.bootstrap.useBootstrapStore;
        store.setState({ data: { ...store.getState().data, orchestration: {
            enabled: true, capabilities: [{id: 'document_analyze', phase: 'output', role: 'reason'}],
        } } });
    }""")
    expect(view.locator("h3")).to_have_text(["Gathering knowledge", "Reasoning"])
    expect(view.get_by_role("heading", name="Named outputs", exact=True)).to_have_count(0)
    normalized = plan_state(page)["plan"]
    assert normalized["planner_contract_version"] == 1
    assert "role" not in normalized["steps"][0]
    assert "outputs" not in normalized["steps"][0]


@pytest.mark.parametrize("width", [1440, 390])
def test_legacy_step_with_unknown_phase_remains_visible_without_current_capability(editor_ui, width):
    page, api = editor_ui
    page.set_viewport_size({"width": width, "height": 900})
    plan = editor_tests.make_plan(CONVERSATION, TURN)
    plan["planner_contract_version"] = 1
    plan["steps"].append({
        "step_id": "historical-step", "capability_id": "retired-capability",
        "title": "Historical step", "phase": "retired-phase",
        "arguments": {}, "depends_on": [], "status": "completed", "enabled": True,
    })
    view = mount_run_view(page, api, plan)
    expect(view.locator("[data-step-id]")).to_have_count(len(plan["steps"]))
    historical = view.locator("[data-step-id='historical-step']")
    expect(historical).to_be_visible()
    expect(historical).to_have_attribute("aria-label", f"Step {len(plan['steps'])}: Historical step")
    expect(view.locator("h3")).to_have_text(["Gathering knowledge", "Reasoning"])


@pytest.mark.parametrize("width", [1440, 390])
def test_plan_panel_names_the_planner_answer_basis_visuals_and_optional_inputs(editor_ui, width):
    """Version 0.261.134: who planned the work, what the answer may rely on, and optional inputs."""
    page, api = editor_ui
    page.set_viewport_size({"width": width, "height": 900})
    plan = dependency_plan()
    plan["planner"] = {"label": "gpt-5.4", "source": "selected"}
    plan["model_routing"] = "auto"
    answer = plan["steps"][3]
    answer["arguments"].update(
        knowledge_basis="sources_and_general_knowledge", visuals=["chart", "image_proposal"],
    )
    answer["inputs"]["followup"]["optional"] = True
    view = mount_run_view(page, api, plan)

    expect(view.get_by_test_id("orchestration-plan-planner")).to_have_text(
        "Planned by gpt-5.4 (the model you selected); each step uses its own Auto-routed model"
    )
    step = view.locator("[data-step-id='prepare_answer']")
    expect(step).to_contain_text("Gathered sources, plus general knowledge for stable facts")
    expect(step).to_contain_text("Chart, Image proposals")
    bindings = view.get_by_role("region", name="Result bindings for Prepare answer")
    expect(bindings).to_contain_text(
        "Optional: if it cannot be gathered, the answer continues from general knowledge and says so."
    )
    expect(bindings).to_contain_text("Output findings from Prepare findings (records-v1). Complete results required.")
    overflow = page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth")
    assert not overflow


def test_plans_without_a_recorded_planner_show_no_planner_line(editor_ui):
    page, api = editor_ui
    view = mount_run_view(page, api)
    expect(view.get_by_test_id("orchestration-plan-planner")).to_have_count(0)


def test_untrusted_producer_titles_and_column_names_remain_text(editor_ui):
    page, api = editor_ui
    plan = dependency_plan()
    unsafe_name = "<img src=x onerror=window.orchestrationNameExecuted=true>"
    plan["steps"][1]["title"] = unsafe_name
    plan["steps"][1]["outputs"][0]["columns"][0]["name"] = unsafe_name
    view = mount_run_view(page, api, plan)
    expect(view.get_by_role("region", name="Result bindings for Prepare answer")).to_contain_text(unsafe_name)
    expect(view.locator("[data-step-id='prepare_findings']")).to_contain_text(unsafe_name)
    expect(view.locator("img, script")).to_have_count(0)
    executed = page.evaluate("() => Boolean(window.orchestrationNameExecuted)")
    assert not executed
    names = plan_state(page)["plan"]["steps"][1]["outputs"][0]["columns"]
    assert names[0]["name"] == unsafe_name


def test_required_producer_cannot_be_silently_disabled_and_leaf_edit_is_reversible(editor_ui):
    page, api = editor_ui
    view = mount_run_view(page, api)
    producer = view.locator("[data-step-id='prepare_findings']")
    checkbox = producer.get_by_role("checkbox", name=re.compile("^Run Prepare findings"))
    expect(checkbox).to_be_disabled()
    expect(checkbox).to_have_accessible_name(re.compile(
        "Required by: Gather follow-up evidence; Prepare answer"
    ))
    answer = view.locator("[data-step-id='prepare_answer']")
    expect(answer.get_by_role("checkbox")).to_be_disabled()
    expect(answer).to_contain_text("Final chat response")

    notes = view.locator("[data-step-id='prepare_notes']").get_by_role("checkbox")
    notes.focus()
    notes.press("Space")
    expect(notes).not_to_be_checked()
    narrowed = plan_state(page)
    assert narrowed["edits"]["disabled_step_ids"] == ["prepare_notes"]
    assert narrowed["plan"]["steps"][3]["inputs"]["findings"]["binding"] == binding("prepare_findings", "findings")
    assert narrowed["plan"]["steps"][4]["outputs"] == [{"name": "notes", "kind": "text-v1"}]
    notes.press("Space")
    expect(notes).to_be_checked()

    page.evaluate("""(spec) => {
        const S = window.OrchHarness.stores.orchestration;
        const current = S.useOrchestrationStore.getState();
        const plan = S.selectPlan(current, spec.conversation, spec.turn);
        current.disableStep(spec.conversation, spec.turn, plan.steps[1]);
    }""", {"conversation": CONVERSATION, "turn": TURN})
    protected = plan_state(page)
    assert protected["edits"]["disabled_step_ids"] == []
    assert protected["plan"]["final_response"] == binding("prepare_answer", "answer")


def test_invalid_saved_overlay_identifies_consumers_and_blocks_execution(editor_ui):
    page, api = editor_ui
    view = mount_run_view(page, api)
    page.evaluate("""(spec) => {
        const H = window.OrchHarness, key = spec.conversation + '\\u0000' + spec.turn;
        H.stores.orchestration.useOrchestrationStore.setState({
            edits: {[key]: {disabled_step_ids: ['prepare_findings'], removed_document_ids: {}}},
        });
        H.mount('mount-b', 'OrchestrationPlanCard', {
            conversationId: spec.conversation, turnId: spec.turn,
        });
    }""", {"conversation": CONVERSATION, "turn": TURN})
    expect(view.get_by_role("alert")).to_contain_text("Prepare answer, input findings requires Prepare findings")
    expect(page.locator("#mount-b").get_by_role("button", name="Approve and run the plan")).to_be_disabled()
    page.evaluate("(spec) => window.OrchHarness.controller.approveAndRunPlan(spec)",
                  {"conversationId": CONVERSATION, "turnId": TURN})
    assert not api.calls("/run")
    producer = view.locator("[data-step-id='prepare_findings']").get_by_role("checkbox")
    expect(producer).to_be_enabled()
    producer.focus()
    producer.press("Space")
    expect(view.get_by_role("alert")).to_have_count(0)
    expect(page.locator("#mount-b").get_by_role("button", name="Approve and run the plan")).to_be_enabled()


def test_normalization_preserves_named_contract_and_server_order(editor_ui):
    page, api = editor_ui
    plan = dependency_plan()
    plan["steps"][3]["inputs"]["snapshot"] = {"binding": binding(existing_result="approved_snapshot")}
    mount_run_view(page, api, plan)
    normalized = plan_state(page)["plan"]
    for original, received in zip(plan["steps"], normalized["steps"]):
        assert original["outputs"] == received["outputs"]
        assert original["depends_on"] == received["depends_on"]
    assert normalized["steps"][3]["inputs"]["snapshot"]["binding"] == binding(existing_result="approved_snapshot")
    assert normalized["final_response"] == plan["final_response"]
    # Even a skipped consumer retains its edge in the actual server validator.
    result = page.evaluate("""(raw) => {
        const P = window.OrchHarness.plan;
        const plan = P.normalizePlan(raw);
        plan.steps[3].enabled = false;
        return {
            explanation: P.stepDisableExplanation(plan, 'gather_followup'),
            order: P.orderStepsForDisplay([plan.steps[4], ...plan.steps.slice(0, 4)], 2)
                .map(step => step.step_id),
        };
    }""", plan)
    assert "Prepare answer" in result["explanation"]
    assert result["order"] == ["prepare_notes", "gather_first", "prepare_findings", "gather_followup", "prepare_answer"]


def test_v2_editor_revision_and_stale_approval_preserve_bindings(editor_ui):
    page, api = editor_ui
    original = mount_editor(page, api)
    dialog = editor_tests.open_editor(page)
    expect(dialog.get_by_role("region", name="Plan preview").locator("h3").filter(
        has_text=re.compile("^(Gather|Reason)$")
    )).to_have_text(["Gather", "Reason", "Gather", "Reason"])
    editor_tests.ask(page, "Focus on verified findings")
    editor_tests.wait_revision(page, 1, CONVERSATION, TURN)
    revised = plan_state(page)
    assert revised["plan"]["final_response"] == original["final_response"]
    assert revised["plan"]["steps"][3]["inputs"] == original["steps"][3]["inputs"]
    assert api.calls("/revisions")[-1]["body"]["expected_version"]

    editor = api.editors[CONVERSATION]
    api.publish(editor, "A concurrent revision")
    dialog.get_by_role("button", name="Run saved revision").click()
    editor_tests.wait_revision(page, 2, CONVERSATION, TURN)
    expect(page.get_by_role("alert")).to_contain_text("Approval refused: plan_changed")
    assert not api.successful_runs
    current = plan_state(page)
    assert current["plan"]["steps"][1]["outputs"] == original["steps"][1]["outputs"]
    assert current["plan"]["edit_version"] == editor["version"]
    dialog = editor_tests.open_editor(page)
    dialog.get_by_role("button", name="Close the plan editor").click()
    expect(page.get_by_role("button", name="Edit the plan", exact=True).first).to_be_focused()


def test_format_reference_only_uses_explicit_server_catalog(editor_ui):
    page, api = editor_ui
    # One descriptor from the shared catalog, not a second format/profile implementation.
    catalog = [{
        "format_id": "csv", "aliases": ["csv"], "file_extension": "csv",
        "media_type": "text/csv; charset=utf-8", "renderer_version": 1,
        "profiles": [{
            "profile": "tabular_records_v1", "source_kinds": ["records"],
            "required_options": ["columns"], "supported_options": ["columns"], "requires_complete": True,
            "options_schema": {"type": "object", "properties": {"columns": {
                "type": "array", "minItems": 1, "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            }}, "required": ["columns"], "additionalProperties": False},
            "input_schema": {"type": "array", "items": {"type": "object"}},
        }],
        "streaming": True, "rich_media": False, "dependencies": ["jsonschema"],
        "default_limits": {"max_records": 1000000}, "max_output_bytes_required": True,
        "failure_codes": [], "validation_failures_retryable": False, "retryable_failure_codes": [],
    }]
    view = mount_run_view(page, api, exportCatalog=catalog)
    reference = view.get_by_text("Server file format reference", exact=True)
    reference.focus()
    reference.press("Enter")
    expect(view.get_by_text("csv (.csv)", exact=True)).to_be_visible()
    expect(view.get_by_text("Profile: tabular_records_v1", exact=True)).to_be_visible()
    expect(view.get_by_text("Required options: columns", exact=True)).to_be_visible()
    expect(view.get_by_role("combobox")).to_have_count(0)
    expect(view.get_by_role("link")).to_have_count(0)
    expect(view.get_by_text("xlsx (.xlsx)", exact=True)).to_have_count(0)


@pytest.mark.parametrize("width", [1440, 390])
@pytest.mark.parametrize("with_options", [False, True])
def test_explicit_file_specification_is_readonly_intent_not_a_download(editor_ui, width, with_options):
    page, api = editor_ui
    page.set_viewport_size({"width": width, "height": 900})
    preview = dependency_plan()
    output_format = "csv" if with_options else "txt"
    profile = "tabular_records_v1" if with_options else "prepared_text_v1"
    source_step = "prepare_findings" if with_options else "prepare_notes"
    output_name = "findings" if with_options else "notes"
    producer = next(step for step in preview["steps"] if step["step_id"] == source_step)
    declared_output = next(output for output in producer["outputs"] if output["name"] == output_name)
    file_name = f"findings <img onerror=window.orchestrationNameExecuted=true>.{output_format}"
    arguments = {"file_name": file_name, "output_format": output_format, "profile": profile}
    if with_options:
        arguments["options"] = {"columns": ["finding"]}
    # A recorded specification is not capability admission or a committed receipt.
    preview["validation"] = {"ok": False, "errors": ["Render route admission is not available."], "repairs": []}
    preview["steps"].append({
        "step_id": "file_preview", "capability_id": "render_file", "role": "render",
        "title": "Requested findings file", "rationale": "", "depends_on": [source_step],
        "arguments": arguments,
        "inputs": {"source": {"binding": binding(source_step, output_name), "allow_partial": False}},
        "outputs": [], "enabled": True, "optional": False, "estimated_cost": "low", "status": "pending",
    })
    view = mount_run_view(page, api, preview, previewPlan=preview, previewRuntime={
        "file_preview": {"status": "running", "summary": ""},
    }, exportCatalog=[])
    expect(view.get_by_text("The server did not advertise file formats for this plan.", exact=True)).to_be_visible()
    expect(view.get_by_role("button", name="Load server file format reference", exact=True)).to_have_count(0)
    specification = view.get_by_role("region", name="Planned file for Requested findings file")
    expect(specification.get_by_text(file_name, exact=True)).to_be_visible()
    expect(specification.get_by_text(output_format, exact=True)).to_be_visible()
    expect(specification.get_by_text(profile, exact=True)).to_be_visible()
    expect(specification).to_contain_text(
        f"source: Output {output_name} from {producer['title']} ({declared_output['kind']})"
    )
    if with_options:
        expect(specification).to_contain_text('["finding"]')
    normalized = plan_state(page)["plan"]
    rendered_step = normalized["steps"][-1]
    assert rendered_step["arguments"] == arguments
    assert ("options" in rendered_step["arguments"]) is with_options
    assert rendered_step["inputs"] == preview["steps"][-1]["inputs"]
    assert rendered_step["outputs"] == []
    assert normalized["final_response"] == preview["final_response"]
    expect(specification).to_contain_text("Requested output, not a completed download.")
    expect(view.locator("[data-step-id='file_preview']").get_by_text("Rendering", exact=True)).to_be_visible()
    expect(view.get_by_role("link")).to_have_count(0)
    expect(view.get_by_role("checkbox")).to_have_count(0)
    expect(view.locator("img, script")).to_have_count(0)
    executed = page.evaluate("() => Boolean(window.orchestrationNameExecuted)")
    assert not executed
    overflow = page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth")
    assert not overflow
    assert not api.calls("/run")
    assert not api.calls("/retry")
    assert not api.calls("/export-catalog")


class DependencyRecoveryApi(recovery_tests.RecoveryApi):
    """Existing run reads with a native wait, no retry route or file-result fiction."""

    def __init__(self, assets):
        super().__init__(assets)
        self.plan = dependency_plan(recovery_tests.CONVERSATION, recovery_tests.TURN)
        self.records = {}
        self.steps = {}
        record = self.add_record(self.plan)
        record["plan_summary"]["step_count"] = len(self.plan["steps"])
        self.stream_mode = "waiting"

    def wait_for_results(self, run_id):
        record = self.records[run_id]
        record.update(status="waiting", outcome="waiting", started_at="2026-09-21T19:00:00Z")
        record["plan"]["status"] = "waiting"
        record["plan_summary"]["status"] = "waiting"
        self.steps[run_id] = [
            {
                "step_id": step["step_id"], "step_index": index, "title": step["title"],
                "capability_id": step["capability_id"],
                "status": "completed" if index in (0, 4) else "waiting",
                "summary": "Saved results" if index in (0, 4) else "Waiting for required results.",
            }
            for index, step in enumerate(self.plan["steps"])
        ]

    def complete(self, run_id):
        record = self.records[run_id]
        record.update(
            status="completed", outcome="completed", finalization_status="saved", message_saved=True,
            completed_at="2026-09-21T19:01:00Z", assistant_message_id=f"answer-{run_id}",
        )
        record["plan"]["status"] = "completed"
        record["plan_summary"]["status"] = "completed"
        for step in self.steps[run_id]:
            step.update(status="completed", summary="Saved results")
        self.messages.append({
            "id": record["assistant_message_id"], "conversation_id": recovery_tests.CONVERSATION,
            "role": "assistant", "content": "The saved computation is ready.",
            "metadata": {"orchestration": {
                "run_id": run_id, "outcome": "completed", "attempt_index": 1,
                "finalization_status": "saved", "message_saved": True,
            }},
        })

    def handle(self, route):
        if urlsplit(route.request.url).path == editor_tests.RUN:
            body = route.request.post_data_json
            self.requests.append({"path": editor_tests.RUN, "method": route.request.method, "body": body})
            self.wait_for_results(body["run_id"])
            events = [{"type": "orchestration_step", **step} for step in self.steps[body["run_id"]]]
            if self.stream_mode != "transport":
                terminal = {
                    "type": "orchestration_done", "done": True, "status": "waiting", "outcome": "waiting",
                    "run_id": body["run_id"], "turn_id": recovery_tests.TURN, "attempt_index": 1,
                }
                if self.stream_mode == "legacy_done":
                    terminal.pop("status")
                    terminal.pop("outcome")
                events.append(terminal)
            self.stream(route, events)
            return
        super().handle(route)


@pytest.fixture
def dependency_recovery_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    api = DependencyRecoveryApi(editor_assets)
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: api.errors.append(str(error)))
    try:
        yield page, api
    finally:
        api.release()
        context.close()
        assert not api.errors, api.errors


@pytest.mark.parametrize("stream_mode", ["waiting", "transport", "legacy_done"])
def test_waiting_survives_stream_loss_reload_and_same_attempt_completion(dependency_recovery_ui, stream_mode):
    page, api = dependency_recovery_ui
    api.stream_mode = stream_mode
    recovery_tests.mount_recovery(page, api)
    page.get_by_role("button", name="Approve and run the plan").click()
    expect(page.get_by_role("status").filter(has_text=re.compile("^Waiting for required results")).first).to_be_visible()
    expect(page.get_by_role("button", name="Retry from failed step")).to_have_count(0)
    expect(page.get_by_role("button", name="Run prepared retry")).to_have_count(0)
    state = recovery_tests.main_state(page)
    assert list(state["inFlight"]) == [api.plan["run_id"]]
    assert not state["history"]
    assert not any(message.get("metadata", {}).get("orchestration", {}).get("outcome") == "completed"
                   for message in state["messages"])

    page.get_by_role("button", name="Review the running plan").click()
    drawer = page.get_by_role("complementary", name="Review drawer")
    expect(drawer.locator("[data-step-id='prepare_findings']")).to_contain_text("waiting")
    drawer.get_by_role("tab", name="Map", exact=True).click()
    expect(drawer.get_by_text("Waiting for results", exact=True)).to_be_visible()
    expect(drawer.get_by_text(re.compile(r"\d+ artifacts?"))).to_have_count(0)

    recovery_tests.mount_recovery(page, api, saved=True)
    expect(page.get_by_role("status").filter(has_text=re.compile("^Waiting for required results")).first).to_be_visible()
    page.evaluate("(spec) => window.OrchHarness.controller.approveAndRunPlan(spec)", {
        "conversationId": recovery_tests.CONVERSATION, "turnId": recovery_tests.TURN,
    })
    assert len(api.calls("/run")) == 1
    assert not api.calls("/retry")
    restored = recovery_tests.main_state(page)
    assert list(restored["inFlight"]) == [api.plan["run_id"]]

    api.complete(api.plan["run_id"])
    page.get_by_role("button", name="Check saved status").first.click()
    expect(page.get_by_text("The saved computation is ready.", exact=True)).to_be_visible()
    finished = recovery_tests.main_state(page)
    assert not finished["inFlight"]
    assert finished["history"][recovery_tests.CONVERSATION][0]["status"] == "completed"
    assert len(api.calls("/run")) == 1
    assert not api.calls("/retry")


def test_waiting_is_not_retryable_even_with_stale_recovery_metadata(dependency_recovery_ui):
    page, api = dependency_recovery_ui
    run_id = api.plan["run_id"]
    api.wait_for_results(run_id)
    api.records[run_id]["recovery"] = api.recovery(run_id)
    recovery_tests.mount_recovery(page, api, saved=True)
    expect(page.get_by_role("status").filter(has_text=re.compile("^Waiting for required results")).first).to_be_visible()
    expect(page.get_by_role("button", name="Retry from failed step")).to_have_count(0)
    # Exercise the controller's read-time check independently of the visible button gate.
    page.evaluate("""async (spec) => {
        const H = window.OrchHarness;
        H.stores.orchestration.useOrchestrationStore.getState().releaseRunAttempt(spec.runId);
        await H.controller.retryOrchestrationRun(spec.conversationId, spec.runId);
    }""", {"runId": run_id, "conversationId": recovery_tests.CONVERSATION})
    assert not api.calls("/retry")
    assert not api.calls("/run")


def test_partial_step_status_is_preserved_on_hydration(dependency_recovery_ui):
    page, api = dependency_recovery_ui
    api.wait_for_results(api.plan["run_id"])
    api.steps[api.plan["run_id"]][0]["status"] = "partial"
    recovery_tests.mount_recovery(page, api, saved=True)
    expect(page.get_by_role("status").filter(has_text=re.compile("^Waiting for required results")).first).to_be_visible()
    page.get_by_role("button", name="Review the running plan").click()
    drawer = page.get_by_role("complementary", name="Review drawer")
    expect(drawer.locator("[data-step-id='gather_first']")).to_contain_text("partial")
    expect(drawer.get_by_role("checkbox")).to_have_count(0)
    assert not api.calls("/run")


def test_map_does_not_replace_an_older_run_with_the_current_turns_plan(dependency_recovery_ui):
    page, api = dependency_recovery_ui
    old = editor_tests.make_plan(recovery_tests.CONVERSATION, recovery_tests.TURN)
    old.update(run_id="earlier-run", plan_id="earlier-plan", status="completed")
    old["intent"]["summary"] = "Earlier saved answer"
    old["steps"] = [{
        "step_id": "earlier-answer", "capability_id": "respond", "title": "Earlier answer step",
        "phase": "reasoning", "arguments": {}, "status": "completed",
    }]
    record = api.add_record(old)
    record.update(
        status="completed", outcome="completed", completed_at="2026-09-20T19:00:00Z",
        finalization_status="saved", message_saved=True,
    )
    record["plan_summary"]["step_count"] = 1
    api.steps[old["run_id"]] = [{
        "step_id": "earlier-answer", "step_index": 0, "status": "completed", "title": "Earlier answer step",
    }]
    api.wait_for_results(api.plan["run_id"])
    recovery_tests.mount_recovery(page, api, saved=True)
    expect(page.get_by_role("status").filter(has_text=re.compile("^Waiting for required results")).first).to_be_visible()
    page.get_by_role("button", name="Review the running plan").click()
    drawer = page.get_by_role("complementary", name="Review drawer")
    drawer.get_by_role("tab", name="Map", exact=True).click()
    old_row = drawer.get_by_role("listitem").filter(
        has=page.get_by_role("button", name="Earlier saved answer", exact=True)
    )
    old_row.get_by_role("button", name="Expand steps").click()
    expect(old_row.get_by_text("Earlier answer step", exact=True)).to_be_visible()
    expect(old_row.get_by_text(TITLES[0], exact=True)).to_have_count(0)
    old_row.get_by_role("button", name="Earlier saved answer", exact=True).click()
    expect(drawer.get_by_text("Earlier answer step", exact=True)).to_be_visible()
    expect(drawer.get_by_role("heading", name="Reasoning", exact=True)).to_be_visible()
    current = editor_tests.state(page, recovery_tests.CONVERSATION, recovery_tests.TURN)
    assert current["plan"]["run_id"] == api.plan["run_id"]
    assert current["plan"]["planner_contract_version"] == 2
    assert not api.calls("/run")
