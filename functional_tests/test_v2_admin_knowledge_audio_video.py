#!/usr/bin/env python3
# test_v2_admin_knowledge_audio_video.py
"""
Functional test for the Knowledge group's Audio & Video tab in the V2 admin UI.
Version: 0.261.082
Implemented in: 0.261.082

The server-rendered pane puts three unrelated things in one card and orders them
so the shared part is discovered last.

``enable_chat_completion_audio_cues`` plays a short bundled sound when a
response finishes. Its own help text says it does not require Azure Speech
Service, and yet it is the first control in the AI Voice Conversations card,
directly above the Speech resource configuration. It belongs with the other
notification settings.

Three independent capabilities -- audio uploads, voice input, voice responses --
all reveal the same Speech resource block, and the alert explaining that appears
underneath them rather than above. An administrator turning on the second
capability is surprised to find it already configured.

The checks here pin the corrected placement, the shared-resource disclosure, and
the resource-id builder, which is the one place an administrator would otherwise
be retyping a long exact string they have already entered in pieces.
"""

import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.nav import ADMIN_NAV
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
PANES = REPO_ROOT / "application" / "single_app" / "templates" / "admin" / "_panes"
PANE = PANES / "audio-video.html"

AUDIO_VIDEO_SECTIONS = ("video-intelligence-section", "ai-voice-chat-section")

# The three capabilities that share one Speech resource.
SPEECH_CAPABILITIES = (
    "enable_audio_file_support",
    "enable_speech_to_text_input",
    "enable_text_to_speech",
)

fields_module = import_app_module("admin_settings_fields")
evaluate = fields_module.evaluate_dependency

FIELD_NAME_RE = re.compile(r'\sname="([^"]+)"')
JINJA_RE = re.compile(r"\{\{|\{%")


def pane_field_names():
    markup = PANE.read_text(encoding="utf-8")
    return {name for name in FIELD_NAME_RE.findall(markup) if not JINJA_RE.search(name)}


def section_fields(section_id):
    return [
        field
        for declared_section, field in fields_module.iter_fields()
        if declared_section == section_id
    ]


def field_in(section_id, key):
    return next(
        (field for field in section_fields(section_id) if field.get("key") == key), None
    )


def test_the_tab_sections_match_navigation():
    """A field filed under an unknown section id would never render."""
    print("Testing Audio & Video sections against ADMIN_NAV...")

    assert_app_version_at_least("0.261.082")

    nav_sections = {
        section["id"]
        for group in ADMIN_NAV
        if group["id"] == "knowledge"
        for tab in group["tabs"]
        if tab["id"] == "audio-video"
        for section in tab["sections"]
    }

    assert set(AUDIO_VIDEO_SECTIONS) == nav_sections, (
        f"ADMIN_NAV: {sorted(nav_sections)}\n  test: {sorted(AUDIO_VIDEO_SECTIONS)}"
    )
    for section_id in AUDIO_VIDEO_SECTIONS:
        assert section_fields(section_id), f"{section_id} declares no fields."

    print(f"  Both section(s) exist in ADMIN_NAV and are described.")
    return True


def test_the_completion_chime_left_the_voice_section():
    """It plays a local sound and needs no Speech resource at all."""
    print("\nTesting the audio cue relocation...")

    key = "enable_chat_completion_audio_cues"

    owning_sections = [
        section_id
        for section_id, field in fields_module.iter_fields()
        if field.get("key") == key
    ]
    assert owning_sections, f"{key} is not declared anywhere."
    assert len(owning_sections) == 1, (
        f"{key} is declared in more than one section, so it would render twice: "
        f"{owning_sections}"
    )

    section_id = owning_sections[0]
    assert section_id not in AUDIO_VIDEO_SECTIONS, (
        f"{key} is still filed under {section_id}. It plays a bundled local sound "
        "and its own help text says it does not require Azure Speech Service, so "
        "leading the AI Voice Conversations card with it misdescribes both."
    )

    # And it should be somewhere that makes sense: with the other notification
    # settings, under Chat.
    home = next(
        (group["id"], tab["id"])
        for group in ADMIN_NAV
        for tab in group["tabs"]
        for section in tab["sections"]
        if section["id"] == section_id
    )
    assert home == ("chat", "feedback-alerts"), (
        f"{key} moved to {home}, which is not where the other notification "
        "settings live."
    )

    print(f"  {key} is declared under {section_id}.")
    return True


def test_the_shared_speech_resource_is_revealed_by_any_capability():
    """All three capabilities use one resource; each must reveal it."""
    print("\nTesting the shared Speech resource disclosure...")

    endpoint = field_in("ai-voice-chat-section", "speech_service_endpoint")
    assert endpoint, "speech_service_endpoint is not declared."

    dependency = endpoint.get("depends_on")
    assert dependency, "The Speech endpoint is always visible; it should be gated."

    # Off with everything disabled.
    assert not evaluate(dependency, {}.get), (
        "The Speech resource shows with no voice capability enabled."
    )

    # Revealed by each capability independently. Requiring a specific one would
    # leave an administrator unable to configure the feature they turned on.
    for capability in SPEECH_CAPABILITIES:
        state = {key: key == capability for key in SPEECH_CAPABILITIES}
        assert evaluate(dependency, state.get), (
            f"Enabling {capability} alone did not reveal the Speech resource."
        )

    print("  Any one of the three capabilities reveals the shared resource.")
    return True


def test_the_speech_resource_is_declared_before_the_capabilities():
    """V1 explains the sharing in an alert placed under the toggles."""
    print("\nTesting Speech resource ordering...")

    order = [
        field.get("key") or field.get("component") or field.get("status_source")
        for field in section_fields("ai-voice-chat-section")
    ]

    endpoint = order.index("speech_service_endpoint")
    for capability in SPEECH_CAPABILITIES:
        assert endpoint < order.index(capability), (
            f"{capability} is declared before the Speech resource it depends on.\n"
            f"  order: {order}"
        )

    print("  The shared resource is stated before the capabilities that use it.")
    return True


def test_the_speech_key_is_a_secret_and_gated_on_key_auth():
    """A credential rendered as plain text is a credential handed to the browser."""
    print("\nTesting the Speech credential...")

    key_field = field_in("ai-voice-chat-section", "speech_service_key")
    assert key_field, "speech_service_key is not declared."
    assert key_field["type"] == "secret", key_field["type"]

    enabled = {"enable_audio_file_support": True}

    assert evaluate(
        key_field["depends_on"],
        {**enabled, "speech_service_authentication_type": "key"}.get,
    ), "The key should show for key authentication."

    assert not evaluate(
        key_field["depends_on"],
        {**enabled, "speech_service_authentication_type": "managed_identity"}.get,
    ), "The key should be hidden for managed identity."

    # And hidden entirely when no capability is on, even under key auth.
    assert not evaluate(
        key_field["depends_on"], {"speech_service_authentication_type": "key"}.get
    ), "The key showed with no voice capability enabled."

    assert "speech_service_key" in fields_module.get_secret_storage_paths(), (
        "speech_service_key is not reported for redaction."
    )

    print("  The Speech key is a secret, shown only where it applies.")
    return True


def test_the_resource_id_builder_is_wired_to_its_sources():
    """A builder whose sources do not exist can never build anything."""
    print("\nTesting the resource id builder...")

    builder = field_in("ai-voice-chat-section", "speech_service_resource_id")
    assert builder, "speech_service_resource_id is not declared."
    assert builder["component"] == "resource-id-builder", builder

    template = builder.get("builder_template") or ""
    sources = builder.get("builder_sources") or {}
    assert template and sources, "The builder declares no template or sources."

    declared = fields_module.get_declared_setting_keys()
    placeholders = set(re.findall(r"\{(\w+)\}", template))

    assert placeholders == set(sources), (
        "Every template placeholder needs a source and vice versa.\n"
        f"  template: {sorted(placeholders)}\n  sources: {sorted(sources)}"
    )

    for placeholder, key in sources.items():
        assert key in declared, (
            f"The builder reads {key!r} for {placeholder!r}, which is not a "
            "declared field, so it would always be blank."
        )

    print(f"  The builder reads {len(sources)} declared source field(s).")
    return True


def test_video_indexer_leads_with_its_connection():
    """Account details are useless without the endpoint they are read against."""
    print("\nTesting Video Indexer ordering...")

    fields = section_fields("video-intelligence-section")
    groups = [(field.get("group") or {}).get("id") for field in fields]

    capability = [field for field in fields if field.get("role") == "capability"]
    assert len(capability) == 1, "Video Indexer should name one capability switch."

    connection_positions = [i for i, group in enumerate(groups) if group == "connection"]
    advanced_positions = [i for i, group in enumerate(groups) if group == "advanced"]
    assert connection_positions and advanced_positions, groups
    assert max(connection_positions) < min(advanced_positions), (
        f"Advanced settings are interleaved with the connection.\n  groups: {groups}"
    )

    custom = field_in("video-intelligence-section", "video_indexer_endpoint")
    assert custom, "video_indexer_endpoint is not declared."
    assert custom.get("required"), (
        "The Video Indexer endpoint should be required, or a section with no "
        "endpoint would read as configured."
    )

    print("  Video Indexer states its connection before its advanced settings.")
    return True


def test_every_v1_field_is_claimed():
    """A V1 field with no V2 equivalent is invisible in the new UI."""
    print("\nTesting that V1 Audio & Video fields are claimed...")

    claimed = fields_module.get_legacy_field_names()
    documented = set(fields_module.LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT)

    missing = sorted(pane_field_names() - claimed - documented)

    assert not missing, (
        "These fields exist in the server-rendered Audio & Video pane but are "
        "not described in admin_settings_fields.py:\n  " + "\n  ".join(missing)
    )

    print(f"  All {len(pane_field_names())} V1 field(s) are claimed.")
    return True


def test_the_schema_invents_nothing():
    """A schema key with no V1 counterpart would save a setting nothing reads."""
    print("\nTesting that the schema invents no Audio & Video fields...")

    v1_names = pane_field_names()

    invented = []
    for section_id in AUDIO_VIDEO_SECTIONS:
        for field in section_fields(section_id):
            key = field.get("key")
            if not key:
                continue
            legacy = fields_module.LEGACY_FIELD_NAMES.get(key, [key])
            if not any(name in v1_names for name in legacy):
                invented.append(f"{section_id}.{key}")

    assert not invented, (
        "These schema fields have no matching field in the V1 pane:\n  "
        + "\n  ".join(invented)
    )

    print("  Every declared field maps back to a V1 field.")
    return True


if __name__ == "__main__":
    tests = [
        test_the_tab_sections_match_navigation,
        test_the_completion_chime_left_the_voice_section,
        test_the_shared_speech_resource_is_revealed_by_any_capability,
        test_the_speech_resource_is_declared_before_the_capabilities,
        test_the_speech_key_is_a_secret_and_gated_on_key_auth,
        test_the_resource_id_builder_is_wired_to_its_sources,
        test_video_indexer_leads_with_its_connection,
        test_every_v1_field_is_claimed,
        test_the_schema_invents_nothing,
    ]

    results = []
    for test in tests:
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
