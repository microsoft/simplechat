# test_v2_orchestration_quiet_activity.py
"""
Real shipped component/controller tests for quiet activity, checking and answer acceptance.
Version: 0.261.416
Implemented in: 0.261.416

Uses production CSS and the existing Python/Azure Playwright connection fixtures.
Only HTTP responses are scripted; the controller, SSE reader, stores and React views
are the shipped modules. No production requests or saved external actions are replayed.
"""

from pathlib import Path

import pytest
from playwright.sync_api import expect

from test_v2_orchestration_plan_editor import (
    HARNESS,
    ORIGIN,
    connect_options,
    editor_assets,
    editor_browser,
    editor_ui,
)
from test_v2_orchestration_recovery import mount_recovery, recovery_ui


pytestmark = pytest.mark.ui


def mount(page, api, component, *, running=False):
    plan = api.add()
    if running:
        plan["status"] = "running"
        plan["approval"]["state"] = "approved"
    page.goto(ORIGIN + HARNESS)
    page.wait_for_function("() => Boolean(window.OrchHarness)")
    for url in api.assets:
        if url.endswith(".css"):
            page.add_style_tag(url=ORIGIN + url)
    page.evaluate(
        """({plan, component, running}) => {
            const H = window.OrchHarness;
            H.reset();
            const S = H.stores.orchestration.useOrchestrationStore.getState();
            H.stores.chat.useChatStore.setState({
                activeConversationId: plan.conversation_id, messagesLoading: false,
                messages: [], conversations: [], streaming: false,
            });
            S.setPlan(plan.conversation_id, plan.turn_id, plan);
            S.setActiveTurn(plan.conversation_id, plan.turn_id);
            S.seedStepRuntime(plan.conversation_id, plan.turn_id, plan);
            S.updateRunRecovery(plan.run_id, { detailLoaded: true, outputs: [] });
            if (running) S.beginRun({
                conversationId: plan.conversation_id, turnId: plan.turn_id,
                planId: plan.plan_id, runId: plan.run_id, startedAt: Date.now(),
            });
            H.mount('mount-a', component, {
                conversationId: plan.conversation_id, turnId: plan.turn_id,
            });
        }""",
        {"plan": plan, "component": component, "running": running},
    )
    return plan


def report(status="checking", *, corrections=0, semantic=True):
    return {
        "version": 2,
        "status": status,
        "corrections": corrections,
        "max_corrections": 2,
        "preparation_status": "prepared",
        "check_kind": "semantic",
        "deterministic_status": "passed",
        "semantic_enabled": semantic,
        "stages": [
            {"id": "prepare", "label": "Prepare answer", "status": "completed"},
            {"id": "format", "label": "Validate required format", "status": "completed"},
            {"id": "semantic", "label": "Review against your request",
             "status": "skipped" if not semantic else
             "failed" if status in ("incomplete", "verification_unavailable") else
             "completed" if status == "complete" else "running"},
        ],
        "reason_code": "private_checker_diagnostic",
        "requirements": [{"requirement": "private_criterion", "status": "met"}],
    }


@pytest.mark.parametrize("width,dark", [(1440, False), (390, True)])
def test_quiet_activity_has_light_steps_and_honest_checking(editor_ui, width, dark):
    page, api = editor_ui
    page.set_viewport_size({"width": width, "height": 900})
    plan = mount(page, api, "OrchestrationPlanCard", running=True)
    page.evaluate("(dark) => document.documentElement.classList.toggle('dark', dark)", dark)
    page.evaluate(
        """({plan, report}) => {
            const S = window.OrchHarness.stores.orchestration.useOrchestrationStore.getState();
            S.updateStepStatus(plan.conversation_id, plan.turn_id, 'read', { status: 'completed' });
            S.updateStepStatus(plan.conversation_id, plan.turn_id, 'answer', {
                status: 'running', task_completeness: report,
            });
        }""",
        {"plan": plan, "report": report()},
    )
    activity = page.get_by_test_id("quiet-activity")
    expect(activity.get_by_role("status")).to_have_text("Checking answer")
    expect(activity.get_by_text("private_criterion")).to_have_count(0)
    expect(activity.get_by_text("private_checker_diagnostic")).to_have_count(0)
    expect(activity.get_by_role("button", name="Stop execution")).to_have_count(0)
    expect(activity.get_by_text("Answer prepared — Completed")).not_to_be_visible()
    activity.locator("summary").click()
    expect(activity.get_by_text("Answer prepared — Completed")).to_be_visible()
    expect(activity.locator('[data-check-stage="format"]')).to_have_text("Validate required format — Completed")
    for status, corrections, text in [
        ("correcting", 1, "Adjusting answer"),
        ("checking", 1, "Checking again"),
        ("verification_unavailable", 1, "Checking couldn't finish"),
    ]:
        page.evaluate(
            """({plan, report}) => window.OrchHarness.stores.orchestration.useOrchestrationStore
                .getState().updateStepStatus(plan.conversation_id, plan.turn_id, 'answer',
                    { status: 'running', task_completeness: report })""",
            {"plan": plan, "report": report(status, corrections=corrections)},
        )
        expect(activity.get_by_role("status")).to_have_text(text)
        expect(activity.get_by_text("Answer prepared — Completed")).to_be_visible()
    geometry = activity.evaluate(
        """(element) => ({border: getComputedStyle(element).borderTopWidth,
            overflow: document.documentElement.scrollWidth > innerWidth})"""
    )
    assert geometry == {"border": "0px", "overflow": False}
    page.emulate_media(reduced_motion="reduce")
    assert activity.locator("svg").first.evaluate("(element) => getComputedStyle(element).animationName") == "none"
    artifacts = Path(__file__).resolve().parent / "artifacts" / "quiet-activity"
    artifacts.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(artifacts / f"activity-{width}-{'dark' if dark else 'light'}.png"))


def test_policy_selector_obtains_hold_and_projects_only_optional_review(editor_ui):
    page, api = editor_ui
    plan = mount(page, api, "OrchestrationRunView")
    choice = page.get_by_role("combobox", name="Semantic review for Write the comparison")
    expect(choice).to_have_value("auto")
    expect(page.get_by_text("Validate required format — Planned")).to_be_visible()
    choice.select_option("off")
    expect(choice).to_have_value("off")
    state = page.evaluate(
        """({conversation_id,turn_id}) => {
            const S = window.OrchHarness.stores.orchestration.useOrchestrationStore.getState();
            const edits = window.OrchHarness.stores.orchestration.selectEdits(S, conversation_id, turn_id);
            const plan = window.OrchHarness.stores.orchestration.selectPlan(S, conversation_id, turn_id);
            return {edits, held: Boolean(plan.edit_version), mode: plan.approval.mode,
                projected: window.OrchHarness.plan.applyPlanEdits(plan, edits)};
        }""", plan
    )
    assert state["held"] and state["mode"] == "manual"
    assert state["edits"]["semantic_review"] == {"answer": "off"}
    answer = next(step for step in state["projected"]["steps"] if step["step_id"] == "answer")
    assert answer["arguments"]["semantic_review"] == "off"
    expect(page.get_by_text("Validate required format — Planned")).to_be_visible()
    expect(page.get_by_text("Semantic review off — Planned")).to_be_visible()
    page.evaluate(
        """(plan) => {
            const S = window.OrchHarness.stores.orchestration.useOrchestrationStore.getState();
            S.setPlan(plan.conversation_id, plan.turn_id, {...plan, status:'running',
                approval: {...plan.approval, state:'approved'}});
        }""", plan
    )
    expect(choice).to_be_disabled()


def test_failed_hold_never_applies_policy_or_restarts_timer(editor_ui):
    page, api = editor_ui
    api.hold_response = "error"
    plan = mount(page, api, "OrchestrationRunView")
    page.get_by_role("combobox", name="Semantic review for Write the comparison").select_option("off")
    page.wait_for_function(
        """() => Object.values(window.OrchHarness.stores.orchestration.useOrchestrationStore
            .getState().planEditors).some(editor => editor.blocked)"""
    )
    edits = page.evaluate(
        """(plan) => window.OrchHarness.stores.orchestration.selectEdits(
            window.OrchHarness.stores.orchestration.useOrchestrationStore.getState(),
            plan.conversation_id, plan.turn_id)""", plan
    )
    assert not edits.get("semantic_review")
    assert not api.calls("/run")


def seed_question(page):
    page.evaluate(
        """() => {
            const H = window.OrchHarness;
            H.reset();
            const S = H.stores.orchestration.useOrchestrationStore.getState();
            const elicitation = { elicitation_id:'question-1', turn_id:'question-turn', revision:3,
                message:'Which topic?', requested_schema:{type:'object',
                    properties:{topic:{type:'string',title:'Topic'}},required:['topic']},
                ui_hints:{pages:[['topic']],order:['topic']} };
            H.stores.chat.useChatStore.setState({ activeConversationId:'question-chat', messages:[],
                conversations:[], messagesLoading:false, streaming:false });
            S.setElicitation('question-chat','question-turn',elicitation);
            S.setActiveTurn('question-chat','question-turn');
            H.mount('mount-a','ElicitationCard',{conversationId:'question-chat',turnId:'question-turn'});
            const encoder = new TextEncoder();
            window.__answerCalls=[];
            window.fetch = async (url, options={}) => {
                if (String(url).includes('/api/v2/orchestration/plan')) {
                    window.__answerBody=JSON.parse(options.body);
                    window.__answerCalls.push(window.__answerBody);
                    return new Response(new ReadableStream({ start(controller) {
                        window.__emitAnswerEvent = event => controller.enqueue(encoder.encode(
                            'data: '+JSON.stringify(event)+'\\n\\n'));
                        window.__endAnswerStream = () => controller.close();
                    }}),{headers:{'Content-Type':'text/event-stream'}});
                }
                return new Response(JSON.stringify({error:'Saved status unavailable'}),{status:503,
                    headers:{'Content-Type':'application/json'}});
            };
        }"""
    )


def submit_answer(page):
    page.get_by_role("textbox", name="Topic", exact=True).fill("Preserved topic")
    page.get_by_role("button", name="Review answers", exact=True).click()
    page.get_by_role("button", name="Use these answers", exact=True).click()
    page.wait_for_function("() => Boolean(window.__emitAnswerEvent)")


@pytest.mark.parametrize("admission", [False, True])
def test_answer_collapses_then_retires_on_matching_durable_ack(editor_ui, admission):
    page, api = editor_ui
    mount(page, api, "ElicitationCard")
    seed_question(page)
    submit_answer(page)
    expect(page.get_by_test_id("elicitation-submission")).to_have_text("Submitting your answers…")
    expect(page.get_by_role("textbox", name="Topic", exact=True)).to_have_count(0)
    assert page.evaluate("() => document.activeElement.dataset.testid") == "elicitation-submission"
    page.evaluate(
        """() => window.__emitAnswerEvent({type:'orchestration_elicitation_accepted',
            conversation_id:'question-chat',turn_id:'question-turn',elicitation_id:'question-1',
            elicitation_revision:2,elicitation_submission_id:window.__answerBody.elicitation_submission_id})"""
    )
    expect(page.get_by_test_id("elicitation-submission")).to_be_visible()
    page.evaluate(
        """() => window.__emitAnswerEvent({type:'user_message_persisted',
            conversation_id:'question-chat',turn_id:'question-turn',user_message_id:'stale-question',
            server_managed:true,planning_submission_id:'stale-submission'})"""
    )
    expect(page.get_by_test_id("elicitation-submission")).to_be_visible()
    page.evaluate(
        """(admission) => window.__emitAnswerEvent(admission
            ? {type:'user_message_persisted', conversation_id:'question-chat',turn_id:'question-turn',
                user_message_id:'saved-question',server_managed:true,
                planning_submission_id:window.__answerBody.elicitation_submission_id}
            : {type:'orchestration_elicitation_accepted',
                conversation_id:'question-chat',turn_id:'question-turn',elicitation_id:'question-1',
                elicitation_revision:3,elicitation_submission_id:window.__answerBody.elicitation_submission_id})""",
        admission,
    )
    expect(page.get_by_test_id("elicitation-submission")).to_have_count(0)
    draft = page.evaluate(
        """() => Object.values(window.OrchHarness.stores.orchestration.useOrchestrationStore
            .getState().elicitationDrafts)[0]"""
    )
    assert draft["accepted"] is True and draft["editors"]["topic"]["text"] == "Preserved topic"
    assert len(page.evaluate("() => window.__answerCalls")) == 1
    page.evaluate("() => window.__endAnswerStream()")


def test_rejected_answer_restores_complete_draft_and_uncertain_blocks_resend(editor_ui):
    page, api = editor_ui
    mount(page, api, "ElicitationCard")
    seed_question(page)
    submit_answer(page)
    page.evaluate(
        """() => window.__emitAnswerEvent({error:'Topic was rejected',
            code:'invalid_elicitation_response'})"""
    )
    expect(page.get_by_role("button", name="Use these answers", exact=True)).to_be_visible()
    page.get_by_role("button", name="Back", exact=True).click()
    expect(page.get_by_role("textbox", name="Topic", exact=True)).to_have_value("Preserved topic")
    page.get_by_role("button", name="Review answers", exact=True).click()
    page.get_by_role("button", name="Use these answers", exact=True).click()
    page.wait_for_function("() => window.__answerCalls.length === 2")
    page.evaluate("() => window.__endAnswerStream()")
    expect(page.get_by_test_id("elicitation-submission")).to_contain_text("Confirming your answers")
    expect(page.get_by_role("button", name="Check saved status")).to_be_visible()
    draft = page.evaluate(
        """() => Object.values(window.OrchHarness.stores.orchestration.useOrchestrationStore
            .getState().elicitationDrafts)[0]"""
    )
    assert draft["uncertain"] is True and draft["editors"]["topic"]["text"] == "Preserved topic"
    assert len(page.evaluate("() => window.__answerCalls")) == 2


def test_check_report_hydration_retains_history_and_rejects_stale_candidates(editor_ui):
    page, api = editor_ui
    plan = mount(page, api, "OrchestrationRunView", running=True)
    latest = report("complete", corrections=1)
    for stage in latest["stages"]:
        stage["candidate_revision"] = 2
        stage["owner_step_id"] = "answer"
    old = report("checking")
    for stage in old["stages"]:
        stage["candidate_revision"] = 1
        stage["owner_step_id"] = "answer"
    page.evaluate(
        """({plan,latest,old}) => {
            const S = window.OrchHarness.stores.orchestration.useOrchestrationStore.getState();
            S.updateStepStatus(plan.conversation_id,plan.turn_id,'answer',
                {status:'running',task_completeness:latest});
            S.updateStepStatus(plan.conversation_id,plan.turn_id,'answer',{task_completeness:old});
        }""", {"plan": plan, "latest": latest, "old": old}
    )
    expect(page.get_by_text("Answer checking: Reviewed after adjustment")).to_be_visible()
    expect(page.locator('[data-check-stage="semantic"]').first).to_contain_text("Completed")
    page.evaluate(
        """(plan) => {
            const S = window.OrchHarness.stores.orchestration.useOrchestrationStore.getState();
            S.updateStepStatus(plan.conversation_id,plan.turn_id,'read',
                {task_completeness:{version:1,status:'complete',corrections:0,requirements:[]}});
        }""", plan
    )
    page.get_by_text("Answer checking: Review complete", exact=True).click()
    expect(page.get_by_text("Detailed stage history was not saved for this report.")).to_be_visible()


@pytest.mark.parametrize("check_only", [False, True])
def test_check_recovery_deduplicates_failure_and_never_invents_retry_scope(recovery_ui, check_only):
    page, api = recovery_ui
    api.failure = {"code": "completeness_unavailable",
                   "message": "I couldn't finish checking the answer. Your progress is saved."}
    api.finish(api.plan["run_id"])
    api.records[api.plan["run_id"]]["recovery"]["retry_scope"] = "check" if check_only else "step"
    mount_recovery(page, api, saved=True)
    notice = page.locator('section[aria-label="Orchestration recovery"]')
    expect(page.get_by_text(api.failure["message"], exact=True)).to_have_count(2)
    # One visible notice, one retained historical diagnostic under explicit Run details.
    expect(page.get_by_text(api.failure["message"], exact=True).first).to_be_visible()
    expect(page.get_by_text(api.failure["message"], exact=True).last).not_to_be_visible()
    expect(notice.get_by_role("button", name="Retry check" if check_only else "Retry from failed step")).to_be_enabled()
    expect(notice.get_by_role("button", name="Stop execution")).to_have_count(0)
    expect(notice.get_by_text("Reuse saved results:", exact=False)).not_to_be_visible()
    notice.locator("summary", has_text="Run details").click()
    expect(notice.get_by_text("Reuse saved results:", exact=False)).to_be_visible()
    assert not api.calls("/retry") and not api.calls("/run")
