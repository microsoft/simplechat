# test_chat_math_rendering.py
"""
V1 math rendering with the real chat templates/modules and same-origin API fixtures.
Version: 0.261.047
Implemented in: 0.261.047

Uses Azure Playwright when configured, otherwise local Chromium. No application
backend, model requests, secrets, or signed-in tenant are required.
"""

import json
import mimetypes
import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from azure.identity import DefaultAzureCredential
from azure.mgmt.playwright import PlaywrightMgmtClient
from jinja2 import ChainableUndefined, Environment, FileSystemLoader, Undefined, select_autoescape
from playwright.sync_api import expect
from application.single_app.functions_message_masking import apply_message_mask_action, remove_masked_content


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
ORIGIN = "http://simplechat.test"
pytestmark = pytest.mark.ui


@pytest.fixture(scope="module")
def math_browser(playwright):
    endpoint = os.getenv("AZURE_PLAYWRIGHT_WS_ENDPOINT")
    if not endpoint:
        browser = playwright.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            browser.close()
        return
    with DefaultAzureCredential() as credential:
        with PlaywrightMgmtClient(credential, os.environ["AZURE_SUBSCRIPTION_ID"]) as client:
            workspace = client.playwright_workspaces.get(
                os.environ["AZURE_PLAYWRIGHT_RESOURCE_GROUP"],
                os.environ["AZURE_PLAYWRIGHT_WORKSPACE"],
            )
            if not workspace.id:
                raise RuntimeError("Azure Playwright workspace could not be verified.")
            token = credential.get_token(os.environ["AZURE_PLAYWRIGHT_TOKEN_SCOPE"])
            browser = playwright.chromium.connect(
                endpoint,
                headers={"Authorization": f"Bearer {token.token}"},
                expose_network="<loopback>",
            )
            try:
                yield browser
            finally:
                browser.close()


def _template_json(value, **kwargs):
    def default(item):
        if isinstance(item, Undefined):
            return None
        raise TypeError(f"Unsupported template fixture value: {type(item).__name__}")
    return json.dumps(value, default=default, **kwargs)


def _chat_html():
    environment = Environment(
        loader=FileSystemLoader(APP_ROOT / "templates"),
        autoescape=select_autoescape(),
        undefined=ChainableUndefined,
    )
    environment.policies["json.dumps_function"] = _template_json
    environment.globals["url_for"] = lambda endpoint, **values: (
        f"/static/{values['filename']}" if endpoint == "static" else f"/{endpoint}"
    )
    settings = {"app_title": "Math regression", "enable_enhanced_citations": True}
    return environment.get_template("chats.html").render(
        settings=settings,
        app_settings=settings,
        config={"VERSION": "0.261.047"},
        user_settings={"settings": {}},
        session={"user": {"name": "Math Test", "oid": "math-user"}},
        user_id="math-user",
        user_display_name="Math Test",
        user_groups=[],
        user_visible_public_workspaces=[],
        enable_user_feedback=False,
        enable_enhanced_citations=True,
        enable_document_classification=False,
        enable_multi_model_endpoints=False,
        conversation_contents_drawer_enabled=False,
        active_group_id=None,
        active_group_name="",
        active_public_workspace_id=None,
    )


@pytest.fixture
def math_page(math_browser):
    context = math_browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    errors = []
    external = []
    requests = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    html = _chat_html()

    def route_request(route):
        url = urlsplit(route.request.url)
        requests.append(url.path)
        if f"{url.scheme}://{url.netloc}" != ORIGIN:
            external.append(route.request.url)
            route.abort()
            return
        if url.path.startswith("/static/"):
            asset = (APP_ROOT / unquote(url.path.lstrip("/"))).resolve()
            if not asset.is_relative_to(APP_ROOT) or not asset.is_file():
                route.fulfill(status=404, body="")
                return
            route.fulfill(
                content_type=mimetypes.guess_type(asset.name)[0] or "application/octet-stream",
                body=asset.read_bytes(),
            )
        elif url.path == "/chats":
            route.fulfill(content_type="text/html", body=html)
        elif url.path == "/api/user/settings":
            route.fulfill(json={"settings": {}, "selected_agent": None})
        elif url.path == "/api/get_conversations":
            route.fulfill(json={"conversations": []})
        elif url.path.endswith("/tags"):
            route.fulfill(json={"tags": []})
        elif url.path.endswith("/messages"):
            route.fulfill(json={"messages": []})
        else:
            route.fulfill(json={
                "settings": {}, "documents": [], "groups": [], "agents": [], "models": [],
                "prompts": [], "conversations": [], "notifications": [], "unread_count": 0,
            })

    context.route("**/*", route_request)
    page.goto(f"{ORIGIN}/chats", wait_until="networkidle")
    page.wait_for_function("() => Boolean(window.chatMessages?.appendMessage)")
    page.evaluate("() => { currentConversationId = 'math-conversation'; window.currentConversationId = currentConversationId; }")
    try:
        yield page, errors, external, requests
    finally:
        context.close()


def _append(page, content, message_id="math-answer", metadata=None):
    page.evaluate(
        """({ content, id, metadata }) => {
            window.chatMessages.appendMessage(
                'AI', content, 'math-test', id, false, [], [], [], null, null,
                { id, role: 'assistant', content, conversation_id: 'math-conversation', metadata },
                false
            );
        }""",
        {"content": content, "id": message_id, "metadata": metadata or {}},
    )
    return page.locator(f'[data-message-id="{message_id}"]')


@pytest.mark.parametrize("width,theme", [(1440, "light"), (390, "dark")])
def test_math_display_history_and_copy(math_page, width, theme):
    page, errors, external, requests = math_page
    page.set_viewport_size({"width": width, "height": 900})
    page.evaluate("(theme) => document.documentElement.dataset.bsTheme = theme", theme)
    assert not any("katex" in request for request in requests)
    content = (
        r"Projection \(x_n=\frac{X_c}{Z_c}\)." "\n\n"
        r"\[\mathbf{X}_c=\begin{bmatrix}X_c \\ Y_c \\ Z_c\end{bmatrix}\]" "\n\n"
        "Costs $5 to $10.\n\n`\\(literal\\)`\n\n```tex\n\\[literal\\]\n```\n\n"
        "| Coordinate | Value |\n| --- | --- |\n| x | 1 |\n\n"
        "(Source: calibration.md, Page: 1) [#calibration_1]"
    )
    message = _append(page, content)
    expect(message.locator(".sc-math[data-math-state='ready']")).to_have_count(2)
    expect(message.locator(".katex-mathml math")).to_have_count(2)
    expect(message.locator(".katex-mathml mfrac")).to_have_count(1)
    expect(message.locator(".katex-mathml mtable mtr")).to_have_count(3)
    expect(message.locator(".katex-html").first).to_have_attribute("aria-hidden", "true")
    expect(message.locator(".sc-math-display")).to_be_visible()
    assert message.locator(".sc-math-display").evaluate(
        "element => element.getBoundingClientRect().width <= element.closest('.message-text').getBoundingClientRect().width + 1"
    )
    expect(message.locator("pre code")).to_have_text(r"\[literal\]" + "\n")
    expect(message.locator(".message-text")).to_contain_text("Costs $5 to $10.")
    expect(message.locator("table")).to_have_count(1)
    expect(message.locator(".message-text a")).not_to_have_count(0)
    copied = message.locator("textarea[id^='copy-md-']").input_value()
    assert r"\(x_n=\frac{X_c}{Z_c}\)" in copied
    assert r"X_c \\ Y_c \\ Z_c" in copied
    assert "scmath:" not in copied
    assert message.locator(".katex").first.evaluate("element => getComputedStyle(element).color") != "rgba(0, 0, 0, 0)"
    page.reload(wait_until="networkidle")
    page.wait_for_function("() => Boolean(window.chatMessages?.appendMessage)")
    reloaded = _append(page, content, "math-reloaded")
    expect(reloaded.locator(".sc-math[data-math-state='ready']")).to_have_count(2)
    assert not errors
    assert not external


def test_math_streaming_and_existing_masks(math_page):
    page, errors, external, _ = math_page
    content = r"Before \(x^2\) after."
    message = _append(page, r"Before \(x", "math-stream")
    expect(message.locator(".katex")).to_have_count(0)
    page.evaluate(
        """async (content) => {
            const streaming = await import('/static/js/chat/chat-streaming.js');
            streaming.updateStreamingMessage('math-stream', content);
        }""", content,
    )
    expect(message.locator(".sc-math[data-math-state='ready']")).to_have_count(1)
    saved = _append(page, content, "math-masked", {
        "masked_ranges": [{"start": 13, "end": 18, "display_start": 13, "display_end": 18, "text": "after", "id": "mask-1"}],
    })
    expect(saved.locator(".masked-content")).to_have_text("after")
    expect(saved.locator(".sc-math[data-math-state='ready']")).to_have_count(1)
    result = page.evaluate(
        """async () => {
            const { getMathAwareSelection } = await import('/static/js/chat/chat-math.js');
            const text = document.querySelector('[data-message-id="math-masked"] .message-text');
            const selected = text.querySelector('.masked-content').firstChild;
            const range = document.createRange();
            range.selectNodeContents(selected);
            return getMathAwareSelection(text, range);
        }"""
    )
    assert result == {"start": 13, "end": 18, "text": "after", "sourceText": "after"}
    equation_selection = page.evaluate(
        """async () => {
            const { getMathAwareSelection } = await import('/static/js/chat/chat-math.js');
            const text = document.querySelector('[data-message-id="math-masked"] .message-text');
            const glyph = text.querySelector('.katex-html .mord');
            const range = document.createRange();
            range.selectNodeContents(glyph);
            return getMathAwareSelection(text, range);
        }"""
    )
    assert equation_selection == {"start": 7, "end": 12, "text": "(x^2)", "sourceText": r"\(x^2\)"}
    page.evaluate(
        """() => window.chatMessages.applyMaskedState(
            document.querySelector('[data-message-id="math-masked"]'),
            { masked_ranges: [{ start: 7, end: 12, display_start: 7, display_end: 12, text: '(x^2)', id: 'mask-2' }] }
        )"""
    )
    expect(saved.locator(".masked-content")).to_have_text("(x^2)")
    expect(saved.locator(".katex")).to_have_count(0)
    page.evaluate(
        """() => window.chatMessages.applyMaskedState(
            document.querySelector('[data-message-id="math-masked"]'), { masked_ranges: [] }
        )"""
    )
    expect(saved.locator(".katex")).to_have_count(1)
    page.evaluate("() => window.chatMessages.applySearchHighlight('x')")
    expect(saved.locator(".sc-math .search-highlight")).to_have_count(0)
    expect(saved.locator(".katex-mathml math")).to_have_count(1)
    assert not errors
    assert not external


def test_math_untrusted_input_and_failed_asset_retry(math_page):
    page, errors, external, _ = math_page
    page.route("**/vendor/katex-0.18.4/katex.min.js", lambda route: route.abort())
    failed = _append(page, r"\[x^2\]", "math-failed")
    expect(failed.locator(".sc-math-error")).to_have_text(" [Math unavailable]")
    page.unroute("**/vendor/katex-0.18.4/katex.min.js")
    content = (
        r"\[\frac{1}{2}\]" "\n\n"
        r"\[\frac{1}{\]" "\n\n"
        r"\[\notARealCommand{x}\]" "\n\n"
        r"\[\href{javascript:alert(1)}{click}\]" "\n\n"
        r"\[\includegraphics{https://example.invalid/image.png}\]" "\n\n"
        r"\[\text{<img src=x onerror=alert(1)>}\]"
    )
    message = _append(page, content, "math-retry")
    expect(message.locator(".sc-math[data-math-state='ready']")).not_to_have_count(0)
    expect(message.locator(".sc-math-error")).not_to_have_count(0)
    expect(message.locator(".sc-math img, .sc-math a, .sc-math script, .sc-math [onerror]")).to_have_count(0)
    assert not errors
    assert not external


@pytest.mark.parametrize("ending", ["complete", "stopped", "error"])
def test_math_stream_lifecycle(math_page, ending):
    page, errors, external, requests = math_page
    content = r"Projection \[x_n=\frac{X_c}{Z_c}\]"
    final = {
        "done": True,
        "full_content": content,
        "conversation_id": "math-conversation",
        "conversation_title": "Math",
        "message_id": "math-completed",
    }
    if ending == "stopped":
        final.update(cancelled=True, message_persisted=False)
    elif ending == "error":
        final = {"error": "Fixture stream interruption", "partial_content": content}
    events = [{"content": content[:15]}, {"content": content[15:]}, final]
    payload = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
    page.route(
        "**/api/chat/stream",
        lambda route: route.fulfill(content_type="text/event-stream", body=payload),
    )
    page.evaluate(
        """async () => {
            const streaming = await import('/static/js/chat/chat-streaming.js');
            await streaming.sendMessageWithStreaming(
                { message: 'Show projection', conversation_id: 'math-conversation' },
                null, 'math-conversation', { allowRecovery: false }
            );
        }"""
    )
    expect(page.locator(".sc-math[data-math-state='ready']")).to_have_count(1)
    if ending == "stopped":
        expect(page.locator(".stream-stopped-banner")).to_contain_text("Stopped by you.")
    elif ending == "error":
        expect(page.locator(".message-text .alert-warning")).to_contain_text("Fixture stream interruption")
    else:
        expect(page.locator('[data-message-id="math-completed"] .katex')).to_have_count(1)
    assert requests.count("/static/vendor/katex-0.18.4/katex.min.js") == 1
    assert not errors
    assert not external


def test_math_does_not_break_other_visualizations(math_page):
    page, errors, external, _ = math_page
    chart = {
        "version": 1, "chartType": "bar", "kind": "bar", "title": "Coordinates",
        "data": {"labels": ["x", "y"], "datasets": [{"label": "Value", "data": [1, 2]}]},
    }
    proposal = {"version": 1, "visualId": "math-image", "title": "Projection", "prompt": r"Draw \(x\)."}
    message = _append(
        page,
        r"\[x^2\]" + "\n\n```simplechart\n" + json.dumps(chart)
        + "\n```\n\n```simpleimage\n" + json.dumps(proposal) + "\n```\n",
        "math-with-visuals",
    )
    expect(message.locator(".katex")).to_have_count(1)
    expect(message.locator(".sc-inline-chart canvas")).to_be_visible()
    expect(message.locator(".sc-inline-image-proposal")).to_be_visible()
    assert not errors
    assert not external


def test_math_mask_request_resolves_to_stored_tex(math_page):
    page, errors, external, _ = math_page
    content = r"Before \(\frac{1}{2}\) after."
    stored = {"id": "math-mask-request", "content": content, "metadata": {}}
    payloads = []

    def mask_request(route):
        payload = route.request.post_data_json
        payloads.append(payload)
        apply_message_mask_action(
            stored, payload["action"], payload.get("selection"), "math-user", "Math Test"
        )
        route.fulfill(json={
            "message": stored,
            "masked": stored["metadata"].get("masked", False),
            "masked_ranges": stored["metadata"].get("masked_ranges", []),
        })

    page.route("**/mask", mask_request)
    message = _append(page, content, stored["id"])
    expect(message.locator(".katex")).to_have_count(1)
    page.evaluate(
        """() => {
            const message = document.querySelector('[data-message-id="math-mask-request"]');
            const range = document.createRange();
            range.selectNodeContents(message.querySelector('.katex-html .mord'));
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            message.querySelector('.mask-add-btn').click();
        }"""
    )
    expect(message.locator(".masked-content")).to_contain_text(r"\frac{1}{2}")
    assert len(payloads) == 1
    assert payloads[0]["selection"]["text"] == r"\(\frac{1}{2}\)"
    assert remove_masked_content(content, stored["metadata"]["masked_ranges"]) == "Before  after."
    expect(message.locator(".katex")).to_have_count(0)
    assert not errors
    assert not external


def test_wide_equation_scrolls_without_clipping_first_terms(math_page):
    page, errors, external, _ = math_page
    page.set_viewport_size({"width": 390, "height": 844})
    message = _append(page, r"\[" + "+".join(f"x_{{{index}}}" for index in range(60)) + r"\]", "math-wide")
    expect(message.locator(".sc-math[data-math-state='ready']")).to_have_count(1)
    geometry = message.locator(".sc-math-display").evaluate(
        """element => {
            const bounds = element.getBoundingClientRect();
            const terms = element.querySelector('.katex-html').getBoundingClientRect();
            return {
                width: bounds.width, contentWidth: element.scrollWidth,
                left: bounds.left, termsLeft: terms.left,
                parentWidth: element.closest('.message-text').getBoundingClientRect().width,
                overflow: getComputedStyle(element).overflowX
            };
        }"""
    )
    assert geometry["overflow"] == "auto"
    assert geometry["contentWidth"] > geometry["width"]
    assert geometry["width"] <= geometry["parentWidth"] + 1
    assert geometry["termsLeft"] >= geometry["left"] - 1
    assert not errors
    assert not external
