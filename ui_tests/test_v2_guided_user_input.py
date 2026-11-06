# test_v2_guided_user_input.py
"""UI tests for one-at-a-time agent questions and one reviewed submission.

Version: 0.261.411
Implemented in: 0.261.411
Drives shipped components and transports with closed local API fixtures.
"""

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "orchestration"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
import harness_build as hb  # noqa: E402
from playwright_connection import connect_options  # noqa: E402, F401


@contextmanager
def input_page(playwright, connection, errors=None):
    hb.ensure_bundle()
    browser = playwright.chromium.connect(**connection) if connection else playwright.chromium.launch()
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    if errors is not None:
        page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        with hb.start_static_server() as base_url:
            response = page.goto(f"{base_url}/{hb.HARNESS_HTML_REL}", wait_until="domcontentloaded")
            if not response or not response.ok:
                raise AssertionError("The question test harness could not be opened.")
            page.wait_for_function('() => Boolean(window.OrchHarness)')
            yield page
    finally:
        context.close()
        browser.close()


SETUP = r"""
() => {
    const H = window.OrchHarness;
    H.reset();
    H.stores.chat.useChatStore.setState({
        activeConversationId: 'conversation', activeConversationKind: 'personal', streaming: false,
    });
    H.stores.bootstrap.useBootstrapStore.setState({data: {user: {id: 'actor'}}});
    const input = {
        id: 'input-one', actor_id: 'actor', revision: 1, conversation_id: 'conversation', conversation_kind: 'personal',
        status: 'pending', agent_name: 'Brief writer',
        question: {
            elicitation_id: 'input-one', revision: 1, turn_id: 'turn', run_id: '', contract_version: 2,
            message: 'A few details are needed to continue.',
            requested_schema: {type: 'object', properties: {
                audience: {type: 'string', title: 'Who is this for?'},
                focus: {type: 'array', items: {type: 'string'}, title: 'What should it emphasize?'},
                format: {type: 'string', enum: ['Brief', 'Full'], title: 'Which format?'},
            }, required: ['audience', 'focus', 'format']},
            ui_hints: {order: ['audience', 'focus', 'format'], pages: [['audience'], ['focus'], ['format']],
                fields: {
                    audience: {input: 'choices', allow_custom: true, choices: [
                        {value: 'Team', label: 'Project team', description: 'The people delivering the work'},
                        {value: 'Leadership', label: 'Leadership'},
                    ]},
                    focus: {input: 'choices', allow_custom: true, choices: [
                        {value: 'Risks', label: 'Risks'}, {value: 'Timeline', label: 'Timeline'},
                    ]},
                }},
        },
    };
    window.__inputCalls = [];
    window.fetch = async (url, options = {}) => {
        const path = String(url);
        const body = options.body ? JSON.parse(options.body) : null;
        window.__inputCalls.push({path, body, headers: options.headers});
        const json = (value) => new Response(JSON.stringify(value), {headers: {'Content-Type': 'application/json'}});
        if (path.includes('/user-input/pending')) return json({requests: [input], csrf_token: 'csrf-fixture'});
        if (path.endsWith('/answer')) return json({input_request: {...input, status: 'answered',
            response: body.response, submission_id: body.submission_id}});
        if (path.endsWith('/continue')) return new Response(
            'data: ' + JSON.stringify({done: true, full_content: 'The brief is ready.', message_id: 'answer'}) + '\n\n',
            {headers: {'Content-Type': 'text/event-stream'}});
        if (path.includes('/messages')) return json([]);
        return json({});
    };
    H.mount('mount-a', 'UserInputCards', {conversationId: 'conversation', conversationKind: 'personal'});
}
"""


@pytest.mark.parametrize("mobile,dark", [(False, False), (True, True)])
def test_focus_flow_reviews_all_answers_before_one_submit(mobile, dark, playwright, connect_options):
    errors = []
    with input_page(playwright, connect_options, errors) as page:
        page.set_viewport_size({"width": 390, "height": 844} if mobile else {"width": 1440, "height": 1000})
        page.evaluate("(dark) => document.documentElement.classList.toggle('dark', dark)", dark)
        page.evaluate(SETUP)
        region = page.get_by_role("region", name="Follow-up questions")
        region.wait_for()
        assert region.get_by_role("button", name="Next", exact=True).is_disabled()
        region.get_by_role("radio", name="Write my own", exact=True).check()
        region.get_by_label("Your answer for Who is this for?").fill("Partners")
        region.get_by_role("button", name="Next", exact=True).click()
        region.get_by_role("checkbox", name="Risks", exact=True).check()
        region.get_by_role("checkbox", name="Write my own", exact=True).check()
        region.get_by_label("Your answer for What should it emphasize?").fill("Costs")
        region.get_by_role("button", name="Back", exact=True).click()
        assert region.get_by_label("Your answer for Who is this for?").input_value() == "Partners"
        region.get_by_role("button", name="Next", exact=True).click()
        region.get_by_role("button", name="Next", exact=True).click()
        region.get_by_role("radio", name="Brief", exact=True).check()
        region.get_by_role("button", name="Review answers", exact=True).click()
        assert region.get_by_role("heading", name="Review your answers").count() == 1
        assert "Partners" in region.inner_text() and "Costs" in region.inner_text()
        before = page.evaluate("window.__inputCalls.filter(call => call.body)")
        assert before == [], "step navigation must not send answers or invoke a model"
        region.get_by_role("button", name="Use these answers", exact=True).click()
        page.wait_for_function("() => window.__inputCalls.some(call => call.path.endsWith('/continue'))")
        calls = page.evaluate("window.__inputCalls")
        answers = [call for call in calls if call["path"].endswith("/answer")]
        assert len(answers) == 1
        assert answers[0]["body"]["response"] == {
            "action": "accept", "content": {"audience": "Partners", "focus": ["Risks", "Costs"], "format": "Brief"},
        }
        assert answers[0]["headers"]["X-CSRFToken"] == "csrf-fixture"
        assert not any("/api/chat/stream" in call["path"] for call in calls)
        assert not errors, errors


def test_failed_submission_keeps_review_and_custom_draft(playwright, connect_options):
    with input_page(playwright, connect_options) as page:
        page.evaluate(SETUP)
        page.evaluate("""() => {
            const original = window.fetch;
            window.fetch = (url, options) => String(url).endsWith('/answer')
                ? Promise.resolve(new Response(JSON.stringify({error:'Please retry.'}),
                    {status:503,headers:{'Content-Type':'application/json'}}))
                : original(url, options);
        }""")
        region = page.get_by_role("region", name="Follow-up questions")
        region.get_by_role("radio", name="Write my own", exact=True).check()
        region.get_by_label("Your answer for Who is this for?").fill("Partners")
        region.get_by_role("button", name="Next", exact=True).click()
        region.get_by_role("checkbox", name="Risks", exact=True).check()
        region.get_by_role("button", name="Next", exact=True).click()
        region.get_by_role("radio", name="Brief", exact=True).check()
        region.get_by_role("button", name="Review answers", exact=True).click()
        region.get_by_role("button", name="Use these answers", exact=True).click()
        region.get_by_role("alert").wait_for()
        region.get_by_role("button", name="Edit Who is this for?", exact=True).click()
        assert region.get_by_label("Your answer for Who is this for?").input_value() == "Partners"


def test_required_boolean_has_an_explicit_no_answer(playwright, connect_options):
    with input_page(playwright, connect_options) as page:
        page.evaluate(SETUP)
        page.get_by_role("region", name="Follow-up questions").wait_for()
        page.evaluate("""() => {
            const store = window.OrchHarness.stores.userInput.useUserInputStore.getState();
            const input = store.records['input-one'].request;
            store.accept({...input, revision:2, question:{...input.question, revision:2,
                requested_schema:{type:'object',properties:{appendix:{type:'boolean',title:'Include an appendix?'}},
                    required:['appendix']},
                ui_hints:{order:['appendix'],pages:[['appendix']]},
            }});
        }""")
        region = page.get_by_role("region", name="Follow-up questions")
        assert region.get_by_role("button", name="Review answers", exact=True).is_disabled()
        region.get_by_role("radio", name="No", exact=True).check()
        region.get_by_role("button", name="Review answers", exact=True).click()
        assert region.get_by_text("No", exact=True).count() == 1


def test_late_question_from_another_sign_in_is_not_adopted(playwright, connect_options):
    with input_page(playwright, connect_options) as page:
        page.evaluate(SETUP)
        page.get_by_role("region", name="Follow-up questions").wait_for()
        retained = page.evaluate("""() => {
            const store = window.OrchHarness.stores.userInput.useUserInputStore.getState();
            const old = store.records['input-one'].request;
            store.setActor('another-actor');
            store.accept(old);
            return Object.keys(window.OrchHarness.stores.userInput.useUserInputStore.getState().records);
        }""")
        assert retained == []


def test_sign_in_change_during_answer_save_does_not_continue_another_actors_work(playwright, connect_options):
    with input_page(playwright, connect_options) as page:
        page.evaluate(SETUP)
        page.evaluate("""() => {
            const original = window.fetch;
            window.fetch = (url, options) => String(url).endsWith('/answer')
                ? new Promise(resolve => {window.__answerRelease = async () => {
                    const response = await original(url, options);
                    const decode = response.json.bind(response);
                    response.json = async () => {
                        const value = await decode();
                        window.__answerDecoded = true;
                        return value;
                    };
                    resolve(response);
                };})
                : original(url, options);
        }""")
        region = page.get_by_role("region", name="Follow-up questions")
        region.get_by_role("radio", name="Leadership", exact=True).check()
        region.get_by_role("button", name="Next", exact=True).click()
        region.get_by_role("checkbox", name="Risks", exact=True).check()
        region.get_by_role("button", name="Next", exact=True).click()
        region.get_by_role("radio", name="Brief", exact=True).check()
        region.get_by_role("button", name="Review answers", exact=True).click()
        region.get_by_role("button", name="Use these answers", exact=True).click()
        page.wait_for_function("() => Boolean(window.__answerRelease)")
        page.evaluate("""async () => {
            const H = window.OrchHarness;
            H.stores.userInput.useUserInputStore.getState().setActor('another-actor');
            H.stores.bootstrap.useBootstrapStore.setState({data:{user:{id:'another-actor'}}});
            await window.__answerRelease();
        }""")
        page.wait_for_function("() => window.__answerDecoded === true")
        captured = page.evaluate("""() => ({
            records:Object.keys(window.OrchHarness.stores.userInput.useUserInputStore.getState().records),
            continued:window.__inputCalls.some(call => call.path.endsWith('/continue')),
        })""")
        assert captured == {"records": [], "continued": False}


def test_stop_targets_the_saved_input_request_not_a_new_chat_stream(playwright, connect_options):
    with input_page(playwright, connect_options) as page:
        page.evaluate(SETUP)
        page.evaluate("""() => {
            const original = window.fetch;
            window.fetch = (url, options) => {
                if (String(url).endsWith('/continue')) {
                    window.__continueStarted = true;
                    const body = new ReadableStream({start(controller) {
                        options.signal.addEventListener('abort', () => controller.error(new DOMException('Stopped', 'AbortError')));
                    }});
                    return Promise.resolve(new Response(body, {headers:{'Content-Type':'text/event-stream'}}));
                }
                if (String(url).endsWith('/stop')) {
                    window.__stopBody = JSON.parse(options.body);
                    return Promise.resolve(new Response(JSON.stringify({cancel_requested:true,status:'continuing'}),
                        {headers:{'Content-Type':'application/json'}}));
                }
                return original(url, options);
            };
        }""")
        region = page.get_by_role("region", name="Follow-up questions")
        region.get_by_role("radio", name="Leadership", exact=True).check()
        region.get_by_role("button", name="Next", exact=True).click()
        region.get_by_role("checkbox", name="Risks", exact=True).check()
        region.get_by_role("button", name="Next", exact=True).click()
        region.get_by_role("radio", name="Brief", exact=True).check()
        region.get_by_role("button", name="Review answers", exact=True).click()
        region.get_by_role("button", name="Use these answers", exact=True).click()
        page.wait_for_function("() => window.__continueStarted === true")
        page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().stopStreaming()")
        page.wait_for_function("() => Boolean(window.__stopBody)")
        captured = page.evaluate("""() => ({
            stop:window.__stopBody, streamed:window.__inputCalls.some(call => call.path.includes('/api/chat/stream')),
        })""")
        assert captured["stop"]["submission_id"]
        assert not captured["streamed"]
