# test_functional_agent_runtime.py
"""
Functional test for agent runtime behavior.
Version: 0.250.007
Implemented in: 0.250.004; browser demo added in 0.250.005; response wait refined in 0.250.007

This test validates a small model endpoint runtime contract and, when enabled
with live demo environment variables, confirms that the authenticated user can
see at least one usable agent in SimpleChat.
"""

import os
import sys
from pathlib import Path

import pytest
import requests

from demo_helpers import (
    ensure_artifact_dir,
    get_demo_base_url,
    get_storage_state_path,
    load_storage_state_cookies,
    new_demo_context,
    wait_for_authenticated_selector,
)


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from model_endpoint_clients import (  # noqa: E402
    MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE,
    ModelEndpointBehavior,
    infer_model_endpoint_protocol,
    normalize_openai_style_base_url,
)


def normalize_search_text(value):
    """Normalize labels so GPT-5.4, GPT54, and GPT 5.4 compare well."""
    return str(value or "").strip().lower().replace(" ", "").replace("-", "").replace("_", "")


def env_flag(name):
    """Return whether an environment flag is enabled."""
    return os.getenv(name, "0").strip().lower() in {"1", "true", "yes"}


def describe_agent(agent):
    """Return a readable one-line summary for live demo output and failures."""
    scope = "global" if agent.get("is_global") else "personal"
    name = agent.get("display_name") or agent.get("name") or agent.get("id") or "Unnamed agent"
    model_hint = agent.get("model_endpoint_id") or agent.get("model_id") or agent.get("azure_openai_gpt_deployment") or "default model"
    return f"{name} ({scope}, {model_hint})"


def test_gpt54_foundry_endpoint_uses_openai_style_protocol():
    """Validate protocol inference for GPT-5.4 on Foundry OpenAI-compatible endpoints."""
    protocol = infer_model_endpoint_protocol(
        provider="new_foundry",
        endpoint="https://example.services.ai.azure.com/openai/v1/chat/completions",
        deployment_name="gpt-5.4",
    )
    assert protocol == MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE


def test_gpt54_endpoint_normalizes_to_openai_v1_base_url():
    """Validate that a GPT-5.4 chat-completions endpoint becomes an OpenAI v1 base URL."""
    normalized_url = normalize_openai_style_base_url(
        "https://example.services.ai.azure.com/openai/v1/chat/completions"
    )
    assert normalized_url == "https://example.services.ai.azure.com/openai/v1/"


def test_gpt54_preserves_reasoning_effort_for_reasoning_model():
    """Validate GPT-5.4 keeps reasoning effort while non-reasoning models ignore it."""
    gpt54_behavior = ModelEndpointBehavior(provider="new_foundry", deployment_name="gpt-5.4")
    assert gpt54_behavior.is_openai_reasoning_model
    assert gpt54_behavior.resolve_reasoning_effort("medium") == "medium"

    gpt4o_behavior = ModelEndpointBehavior(provider="new_foundry", deployment_name="gpt-4o")
    assert not gpt4o_behavior.is_openai_reasoning_model
    assert gpt4o_behavior.resolve_reasoning_effort("medium") == ""


@pytest.mark.skipif(
    os.getenv("SIMPLECHAT_DEMO_FUNCTIONAL_LIVE", "0").strip().lower() not in {"1", "true", "yes"},
    reason="Set SIMPLECHAT_DEMO_FUNCTIONAL_LIVE=1 to query a live SimpleChat environment.",
)
def test_live_authenticated_user_has_agent_available():
    """Optionally verify that the signed-in demo user can see at least one usable agent."""
    base_url = get_demo_base_url()
    storage_state = get_storage_state_path()
    if not storage_state:
        pytest.skip("Set SIMPLECHAT_DEMO_STORAGE_STATE or SIMPLECHAT_UI_STORAGE_STATE for the live functional demo.")

    optional_keyword = os.getenv("SIMPLECHAT_DEMO_AGENT_KEYWORD", "").strip()
    normalized_keyword = normalize_search_text(optional_keyword)
    require_global = env_flag("SIMPLECHAT_DEMO_REQUIRE_GLOBAL_AGENT")

    session = requests.Session()
    session.verify = False
    for cookie in load_storage_state_cookies(storage_state, base_url):
        session.cookies.set(
            cookie.get("name"),
            cookie.get("value"),
            domain=cookie.get("domain"),
            path=cookie.get("path") or "/",
        )

    response = session.get(f"{base_url}/api/user/agents", timeout=30)
    assert response.status_code == 200, f"Expected authenticated agent list, got HTTP {response.status_code}."

    agents = response.json()
    candidate_agents = [agent for agent in agents if not require_global or agent.get("is_global") is True]
    if normalized_keyword:
        candidate_agents = [
            agent for agent in candidate_agents
            if normalized_keyword in normalize_search_text(describe_agent(agent))
        ]

    visible_agents = ", ".join(describe_agent(agent) for agent in agents) or "none"
    expected_parts = []
    if require_global:
        expected_parts.append("global")
    expected_parts.append("agent")
    if optional_keyword:
        expected_parts.append(f"matching '{optional_keyword}'")
    expected_description = " ".join(expected_parts)
    assert candidate_agents, f"Expected at least one visible {expected_description}. Visible agents: {visible_agents}."

    print("Visible agent selected for demo:", describe_agent(candidate_agents[0]))


@pytest.mark.ui
@pytest.mark.skipif(
    os.getenv("SIMPLECHAT_DEMO_SHOW_BROWSER", "0").strip().lower() not in {"1", "true", "yes"},
    reason="Set SIMPLECHAT_DEMO_SHOW_BROWSER=1 to open a headed browser for the live demo.",
)
def test_live_browser_shows_agent_picker(playwright):
    """Open a headed browser, select an agent, send a message, and show the response."""
    base_url = get_demo_base_url()
    pause_ms = int(os.getenv("SIMPLECHAT_DEMO_BROWSER_PAUSE_MS", "15000"))
    post_response_pause_ms = int(os.getenv("SIMPLECHAT_DEMO_POST_RESPONSE_PAUSE_MS", "10000"))
    response_timeout_ms = int(os.getenv("SIMPLECHAT_DEMO_AGENT_RESPONSE_TIMEOUT_MS", "240000"))
    browser_agent_keyword = os.getenv("SIMPLECHAT_DEMO_BROWSER_AGENT_KEYWORD", "Simple Chat")
    prompt = os.getenv(
        "SIMPLECHAT_DEMO_AGENT_PROMPT",
        "Demo test: do not search documents or workspaces. Reply exactly: Simple Chat agent demo response.",
    )
    expected_response_text = os.getenv("SIMPLECHAT_DEMO_EXPECTED_RESPONSE_TEXT", "Simple Chat agent demo response")
    artifact_dir = ensure_artifact_dir()
    browser, context = new_demo_context(playwright)
    page = context.new_page()
    conversation_id = None
    trace_path = artifact_dir / "demo_functional_agent_browser_trace.zip"
    screenshot_path = artifact_dir / "demo_functional_agent_browser_failure.png"
    context.tracing.start(screenshots=True, snapshots=True, sources=True)

    try:
        page.goto(f"{base_url}/chats", wait_until="domcontentloaded", timeout=60000)
        wait_for_authenticated_selector(page, "#user-input", "the live browser agent demo")

        agent_response = context.request.get(f"{base_url}/api/user/agents", timeout=30000)
        assert agent_response.ok, f"Expected authenticated agent API call to succeed, got HTTP {agent_response.status}."
        agents = agent_response.json()
        assert agents, "Expected at least one visible agent for the authenticated demo user."
        print("Visible agents in browser demo:")
        for agent in agents:
            print(" -", describe_agent(agent))

        enable_agents_button = page.locator("#enable-agents-btn")
        if enable_agents_button.is_visible(timeout=10000):
            is_enabled = "active" in (enable_agents_button.get_attribute("class") or "").split()
            if not is_enabled:
                enable_agents_button.click()

        page.locator("#agent-select-container").wait_for(state="visible", timeout=30000)
        page.wait_for_function(
            """
            () => {
                const select = document.querySelector('#agent-select');
                return Boolean(select && Array.from(select.options).some((option) => !option.disabled && option.value));
            }
            """,
            timeout=30000,
        )

        with page.expect_response(
            lambda response: response.request.method in {"POST", "PUT"}
            and response.url.endswith("/api/user/settings/selected_agent"),
            timeout=30000,
        ):
            selected_agent_label = page.evaluate(
                """
                (keywordValue) => {
                    const select = document.querySelector('#agent-select');
                    const keyword = String(keywordValue || '').toLowerCase();
                    const options = Array.from(select.options).filter((item) => !item.disabled && item.value);
                    const option = options.find((item) => {
                        const label = [item.textContent, item.dataset.displayName, item.dataset.name, item.value]
                            .join(' ')
                            .toLowerCase();
                        return keyword && label.includes(keyword);
                    }) || options[0];
                    select.value = option.value;
                    select.dispatchEvent(new Event('change', { bubbles: true }));
                    return option.textContent || option.dataset.displayName || option.dataset.name || option.value;
                }
                """,
                browser_agent_keyword,
            )
        print("Selected agent in browser demo:", selected_agent_label)

        agent_button = page.locator("#agent-dropdown-button")
        agent_button.click()
        page.locator("#agent-dropdown-menu").wait_for(state="visible", timeout=10000)
        page.screenshot(path=artifact_dir / "demo_functional_agent_picker.png", full_page=True)
        page.keyboard.press("Escape")

        page.evaluate(
            """
            () => {
                const workspaceButton = document.querySelector('#search-documents-btn');
                if (workspaceButton && workspaceButton.classList.contains('active')) {
                    workspaceButton.click();
                }
            }
            """
        )

        previous_ai_message_count = page.locator(".ai-message .message-text").count()

        page.locator("#user-input").fill(prompt)
        page.locator("#send-btn").click()
        page.screenshot(path=artifact_dir / "demo_functional_agent_message_sent.png", full_page=True)

        page.wait_for_function(
            """
            ({ previousCount, expectedText }) => {
                const messages = Array.from(document.querySelectorAll('.ai-message .message-text'));
                if (messages.length <= previousCount) {
                    return false;
                }
                const element = messages[messages.length - 1];
                const text = (element.textContent || '').trim();
                const normalizedText = text.toLowerCase();
                const normalizedExpectedText = String(expectedText || '').trim().toLowerCase();
                const messageElement = element.closest('.ai-message');
                return Boolean(
                    text
                    && !text.includes('Streaming...')
                    && !text.includes('Reconnecting')
                    && !normalizedText.startsWith('thinking')
                    && !normalizedText.startsWith('checking content safety')
                    && !normalizedText.startsWith('preparing')
                    && !normalizedText.startsWith('processing')
                    && !normalizedText.startsWith('connecting')
                    && !normalizedText.startsWith('searching public workspace documents')
                    && !normalizedText.startsWith('searching all workspace documents')
                    && !normalizedText.startsWith('searching all workspaces')
                    && !normalizedText.startsWith('searching workspace documents')
                    && !normalizedText.startsWith('searching documents')
                    && text.length >= 20
                    && (!normalizedExpectedText || normalizedText.includes(normalizedExpectedText))
                    && messageElement
                    && !messageElement.querySelector('.streaming-cursor, .spinner-border')
                );
            }
            """,
            arg={"previousCount": previous_ai_message_count, "expectedText": expected_response_text},
            timeout=response_timeout_ms,
        )

        assistant_text = (page.locator(".ai-message .message-text").last.text_content() or "").strip()
        assert assistant_text, "Expected an assistant response after sending the demo agent prompt."
        if expected_response_text:
            assert expected_response_text.lower() in assistant_text.lower(), (
                f"Expected assistant response to contain '{expected_response_text}', got: {assistant_text[:500]}"
            )
        print("Agent response preview:", assistant_text[:500])
        page.screenshot(path=artifact_dir / "demo_functional_agent_response.png", full_page=True)

        if post_response_pause_ms > 0:
            print(
                f"Streaming is complete. Keeping browser open for {post_response_pause_ms} ms "
                "so the presenter can click around."
            )
            page.wait_for_timeout(post_response_pause_ms)

        conversation_id = page.evaluate(
            """
            () => window.chatConversations?.getCurrentConversationId?.()
                || window.currentConversationId
                || null
            """
        )

        if pause_ms > 0:
            print(f"Final browser hold: keeping browser open for {pause_ms} ms before cleanup.")
            page.wait_for_timeout(pause_ms)
    except Exception:
        page.screenshot(path=screenshot_path, full_page=True)
        raise
    finally:
        if conversation_id:
            try:
                context.request.delete(f"{base_url}/api/conversations/{conversation_id}", timeout=30000)
            except Exception:
                pass
        context.tracing.stop(path=trace_path)
        context.close()
        browser.close()