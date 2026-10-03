#!/usr/bin/env python3
"""
Functional test for V2 inline media players, image cards and agent-posted group messages.
Version: 0.261.222
Implemented in: 0.261.222

This test ensures that:
  - links to audio and video files in chat markdown render as inline players (the logic is run in
    Node by test_v2_inline_media_logic.mjs), and markdown images render as captioned cards;
  - the markdown renderer stays XSS-safe: no raw HTML, the default URL transform, and every
    rendered href or media source passes through a scheme check;
  - messages an agent posts through add_conversation_message are marked as agent-authored
    markdown on both the personal and the shared path, and only those render as markdown;
  - CSP_MEDIA_SRC_ORIGINS adds only bare https origins to media-src and cannot inject directives.
"""

import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"
V2_SRC = ROOT / "application" / "v2_ui" / "src"
CHAT_DIR = V2_SRC / "components" / "chat"

sys.path.insert(0, str(ROOT / "functional_tests"))
sys.path.insert(0, str(APP_DIR))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

IMPLEMENTED_IN = "0.261.222"


def _read(path):
    return path.read_text(encoding="utf-8")


def test_csp_media_origins_accept_only_bare_https_origins():
    """Only https origins reach media-src; anything that could widen the policy is rejected."""
    print("Testing CSP media origin validation...")
    from csp_media_sources import build_media_src_directive, parse_csp_media_origins

    accepted, rejected = parse_csp_media_origins(
        "https://media.example.com, https://*.env-abc.westus3.azurecontainerapps.io "
        "https://media.example.com/ HTTPS://Clips.Example.org:8443"
    )
    assert accepted == [
        "https://media.example.com",
        "https://*.env-abc.westus3.azurecontainerapps.io",
        "https://clips.example.org:8443",
    ], accepted
    assert rejected == [], rejected

    hostile = [
        "http://media.example.com",
        "https://media.example.com/path",
        "*",
        "https://*",
        "https://*.com.",
        "'unsafe-inline'",
        "data:",
        "https://media.example.com;script-src",
        "https://media.example.com:99999",
        "https://localhost",
        "javascript:alert(1)",
    ]
    for value in hostile:
        accepted, rejected = parse_csp_media_origins(value)
        assert accepted == [], f"{value!r} must not be accepted"
        assert rejected, f"{value!r} must be reported as rejected"

    accepted, _ = parse_csp_media_origins('["https://a.example.com", "https://a.example.com", "https://b.example.com"]')
    assert accepted == ["https://a.example.com", "https://b.example.com"]
    assert parse_csp_media_origins("") == ([], [])
    assert build_media_src_directive([]) == "media-src 'self' blob:"
    assert build_media_src_directive(["https://a.example.com"]) == "media-src 'self' blob: https://a.example.com"
    print("CSP media origin validation passed!")


def test_config_builds_media_src_from_the_validated_setting():
    """config.py reads CSP_MEDIA_SRC_ORIGINS through the validator and keeps every other directive."""
    print("Testing the Content-Security-Policy wiring...")
    config = _read(APP_DIR / "config.py")
    assert "parse_csp_media_origins(os.getenv('CSP_MEDIA_SRC_ORIGINS', ''))" in config
    assert "MEDIA_SRC_DIRECTIVE = build_media_src_directive(CSP_MEDIA_SRC_ORIGINS)" in config
    policy = re.search(r"'Content-Security-Policy':\s*\((.*?)\)\s*\n\s*\}", config, re.DOTALL)
    assert policy, "Content-Security-Policy not found in config.py"
    policy_text = policy.group(1)
    assert 'f"{MEDIA_SRC_DIRECTIVE}; "' in policy_text
    assert "\"media-src 'self' blob:; \"" not in policy_text, "media-src must come from the validated directive"
    for directive in ("default-src 'self'", "script-src 'self'", "font-src 'self'", "object-src 'none'"):
        assert directive in policy_text, f"CSP must still contain {directive!r}"
    print("Content-Security-Policy wiring passed!")


def test_agent_posted_messages_are_marked_on_both_paths():
    """Personal and shared messages posted through the action carry the agent-markdown marker."""
    print("Testing the agent-posted message marker...")
    source = _read(APP_DIR / "functions_simplechat_operations.py")
    tree = ast.parse(source)
    marker = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(target, "id", "") == "AGENT_POSTED_MESSAGE_METADATA" for target in node.targets):
            marker = ast.literal_eval(node.value)
    assert marker == {"posted_via": "agent_action", "content_format": "markdown"}, marker

    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "add_conversation_message_for_current_user")
    calls = {
        get_name(call.func): call
        for call in ast.walk(function)
        if isinstance(call, ast.Call) and get_name(call.func) in ("_persist_personal_conversation_message", "persist_collaboration_message")
    }
    assert set(calls) == {"_persist_personal_conversation_message", "persist_collaboration_message"}, calls
    for name, call in calls.items():
        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        assert getattr(keywords.get("extra_metadata"), "id", "") == "AGENT_POSTED_MESSAGE_METADATA", f"{name} must pass the marker"

    persist = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_persist_personal_conversation_message")
    assert "extra_metadata" in [arg.arg for arg in persist.args.args]
    assert 'message_doc["metadata"].update(extra_metadata)' in ast.get_source_segment(source, persist)

    shared = _read(V2_SRC / "lib" / "sharedMessage.ts")
    assert "metadata?.posted_via === 'agent_action'" in shared
    assert "metadata?.content_format === 'markdown'" in shared
    assert "message?.role === 'user'" in shared
    print("Agent-posted message marker passed!")


def get_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def test_only_agent_posted_user_messages_render_as_markdown():
    """MessageList renders agent-posted messages with the markdown renderer and leaves typed ones as text."""
    print("Testing message rendering...")
    message_list = _read(CHAT_DIR / "MessageList.tsx")
    assert "const agentPosted = isAgentPostedMessage(message);" in message_list
    branch = message_list.index("agentPosted ? (")
    plain = message_list.index('<p className="text-[15px] leading-relaxed whitespace-pre-wrap">')
    assert branch < plain, "the agent-posted branch must be checked before the plain-text user branch"
    assert "<AssistantMarkdown\n                                content={message.content}\n                                masks={masks.ranges}" in message_list
    assert "alignRight && !agentPosted" in message_list, "agent-posted messages use the neutral bubble"
    print("Message rendering passed!")


def test_markdown_renderer_wires_inline_media_safely():
    """Audio and video links become players, images become cards, and the renderer stays XSS-safe."""
    print("Testing the markdown renderer...")
    markdown = _read(CHAT_DIR / "AssistantMarkdown.tsx")
    for component in ("InlineAudioPlayer", "InlineVideoCard", "InlineImageCard"):
        assert f"import {{ {component} }} from './{component}';" in markdown, component
    assert "a: ({ href, children, node, ...props }) =>" in markdown
    assert "const kind = inlineMediaKind(href);" in markdown
    assert "<a href={safeMarkdownHref(href)} {...props}>" in markdown
    assert "img: ({ src, alt }) => <InlineImageCard src={src} alt={alt} />" in markdown
    assert "from 'rehype-raw'" not in markdown, "raw HTML must stay off"
    assert "allowDangerousHtml" not in markdown and "urlTransform=" not in markdown, "keep react-markdown's default URL transform"

    player = _read(CHAT_DIR / "InlineAudioPlayer.tsx")
    for control in ("Pause", "Play", "Square", "VolumeX", "Volume2", "ChevronDown", "PLAYBACK_RATES", "claimPlayback(audio)", "aria-expanded"):
        assert control in player, f"audio player is missing {control}"
    assert player.count('type="range"') == 2, "the player needs a seek slider and a volume slider"
    assert "audio.currentTime = 0" in player, "stop must rewind as well as pause"
    assert "<InlineMediaFallback kind=\"audio\"" in player

    video = _read(CHAT_DIR / "InlineVideoCard.tsx")
    assert "controls" in video and "playsInline" in video and "claimPlayback(event.currentTarget)" in video

    for name in ("InlineAudioPlayer.tsx", "InlineVideoCard.tsx", "InlineMediaFallback.tsx"):
        text = _read(CHAT_DIR / name)
        elements = list(re.finditer(r"<(a|audio|video)\b[^>]*?\b(href|src)=\{([^}]*)\}", text, re.S))
        assert elements, f"{name}: expected a link or media element"
        for match in elements:
            assert "safeMediaUrl(" in match.group(3), f"{name}: <{match.group(1)} {match.group(2)}> must pass through safeMediaUrl"
        assert "dangerouslySetInnerHTML" not in text

    image_card = _read(CHAT_DIR / "InlineImageCard.tsx")
    assert "resolveImageSource(src)" in image_card and "createPortal(" in image_card
    print("Markdown renderer passed!")


def test_inline_media_helpers_behave():
    """Run the real TypeScript helpers in Node."""
    print("Testing inline media helpers in Node...")
    subprocess.run(["node", str(ROOT / "functional_tests" / "test_v2_inline_media_logic.mjs")], cwd=ROOT, check=True)
    print("Inline media helpers passed!")


def test_version_was_incremented():
    assert_app_version_at_least(IMPLEMENTED_IN)


if __name__ == "__main__":
    tests = [
        test_csp_media_origins_accept_only_bare_https_origins,
        test_config_builds_media_src_from_the_validated_setting,
        test_agent_posted_messages_are_marked_on_both_paths,
        test_only_agent_posted_user_messages_render_as_markdown,
        test_markdown_renderer_wires_inline_media_safely,
        test_inline_media_helpers_behave,
        test_version_was_incremented,
    ]
    failures = 0
    for test in tests:
        try:
            test()
        except Exception as exc:  # noqa: BLE001 - report every failing check
            failures += 1
            print(f"FAILED {test.__name__}: {exc}")
    print(f"{len(tests) - failures}/{len(tests)} tests passed")
    sys.exit(1 if failures else 0)
