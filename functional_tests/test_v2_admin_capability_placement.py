#!/usr/bin/env python3
# test_v2_admin_capability_placement.py
"""
Functional test pinning where the V2 admin surface files each capability toggle.
Version: 0.261.047
Implemented in: 0.261.047

Settings that ``admin_settings_fields.py`` does not describe are still shown in the
V2 admin UI, by scanning the settings document for ``enable_*`` booleans and
matching each one to a navigation section that shares its leading word stems
(``buildCapabilityIndex`` in ``AdminSettingsPage.tsx``). That keeps undescribed
groups usable, but it is a guess, and it guessed wrong in ways nobody could see
without opening the page:

  - ``enable_user_workspace`` matched "user" in ``user-agreement-section`` and
    appeared under Appearance > Notices & Agreements.
  - ``enable_external_healthcheck`` and ``enable_no_auth_external_healthcheck``
    matched "external" in ``external-links-section``. ``health-check-section``
    splits into "health" and "check", neither of which matches the single token
    "healthcheck", so the correct home could never win.
  - ``enable_support_latest_feature_documentation_links`` matched "links" in
    ``external-links-section``, which comes first in navigation order and so beat
    the equally-scoring Support and Latest Features sections.
  - ``enable_text_plugin`` matched "text" in ``home-page-text-section`` and
    appeared under Appearance > Branding.

Declaring a field is what takes a key out of that scan. This test holds three
invariants so the misfiling cannot come back:

  1. The Appearance, Chat and Security groups are fully described by the schema, so
     they must receive *no* guessed rows at all. A new undeclared key that lands in
     any of them fails here, and the fix is to declare it in its real section.
  2. The keys that were moved stay declared where they were moved to.
  3. Keys that are not editable settings at all stay suppressed rather than
     declared. ``enable_tabular_processing_plugin`` is the clearest case: it is
     derived from ``enable_enhanced_citations`` and rewritten by ``get_settings``
     on every read, so a switch would appear to save and then revert.

Security was described later and had misfilings of its own. The clearest was
``enable_app_maintenance`` and ``enable_startup_app_maintenance``, which matched
the token "app" in ``app-role-requirements-section`` and so appeared under Security
> Access & Roles, next to Entra role switches they have nothing to do with. Both
are Cosmos maintenance switches and are now declared under
``cosmos-maintenance-section``. ``enable_key_vault_secret_storage`` matched
"storage" in ``data-management-storage-section`` and appeared under Backup &
Recovery, while ``enable_key_vault_secret_expiration_reminders`` matched nothing at
all and fell into "Other capabilities".
"""

import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.nav import ADMIN_NAV
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
SETTINGS_MODULE = APP_ROOT / "functions_settings.py"
RENDERER = REPO_ROOT / "application" / "v2_ui" / "src" / "pages" / "AdminSettingsPage.tsx"

APPEARANCE_GROUP_ID = "appearance"

# Groups whose sections are described by the schema in full. A guessed row landing
# in one of these is a key that was filed by word stems into a group that has a
# real home for everything it owns, which means it is in the wrong place.
FULLY_DESCRIBED_GROUP_IDS = (APPEARANCE_GROUP_ID, "chat", "security", "agents-actions")

# Where each relocated toggle now lives, and the V1 pane it is mirrored from. The
# pane is checked too, because a schema field with no server-rendered counterpart
# would write a setting the rest of the application never reads.
RELOCATED_CAPABILITIES = {
    "enable_external_healthcheck": ("health-check-section", "logging"),
    "enable_no_auth_external_healthcheck": ("health-check-section", "logging"),
    "enable_support_latest_feature_documentation_links": (
        "user-facing-latest-features-section",
        "user-facing-latest-features",
    ),
    "enable_support_latest_features": ("support-menu-section", "support-menu"),
    "enable_support_menu": ("support-menu-section", "support-menu"),
    "enable_user_workspace": ("personal-workspaces-section", "workspace-types"),
    # Agents & Actions. Before these were declared, enable_semantic_kernel matched
    # no section at all and was filed under "Other capabilities", and the plugin
    # toggles were scattered: enable_text_plugin matched "text" in
    # home-page-text-section, and the rest matched nothing. They now live together
    # in core-plugin-toggles, which is why actions-config no longer declares any.
    "enable_semantic_kernel": ("agents-config", "agents"),
    "enable_agent_template_gallery": ("agent-toggles-card", "agents"),
    "enable_time_plugin": ("core-plugin-toggles", "actions"),
    "enable_http_plugin": ("core-plugin-toggles", "actions"),
    "enable_wait_plugin": ("core-plugin-toggles", "actions"),
    "enable_math_plugin": ("core-plugin-toggles", "actions"),
    "enable_text_plugin": ("core-plugin-toggles", "actions"),
    "enable_default_embedding_model_plugin": ("core-plugin-toggles", "actions"),
    # Declared under Chat, where it is edited. The Actions surface carries a
    # read-only mirror of it, which must not claim the key.
    "enable_fact_memory_plugin": ("fact-memory-section", "chat-experience"),
    # Guessed into the Chat group before the Chat work: "audio", "video" and
    # "file" all reached chat-file-uploads-section, and "enhanced" reached
    # enhanced-citations-section.
    "enable_audio_file_support": ("ai-voice-chat-section", "audio-video"),
    "enable_chat_completion_audio_cues": ("ai-voice-chat-section", "audio-video"),
    "enable_video_file_support": ("video-intelligence-section", "audio-video"),
    "enable_enhanced_extraction": ("document-intelligence-section", "extraction"),
}

# Keys the scan must skip entirely, because they are not settings an
# administrator can change. Declaring one would claim there is something to edit.
EXPECTED_SUPPRESSED_CAPABILITIES = (
    "enable_tabular_processing_plugin",
    "enable_enhanced_citations_mount",
    "enable_mixed_source_chat_search",
    "enable_mixed_source_conversation_continuity",
)

# Relocations with no server-rendered counterpart to check against. Both are
# documented in ``V2_ONLY_FIELDS``, which is what the section assertion below reads
# instead of a pane.
RELOCATED_CAPABILITIES_WITHOUT_V1_FIELD = {
    "enable_app_maintenance": "cosmos-maintenance-section",
    "enable_startup_app_maintenance": "cosmos-maintenance-section",
}

# The rules the ported heuristic depends on. If the renderer stops doing any of
# these, the port below no longer predicts what an administrator sees.
RENDERER_INVARIANTS = (
    ("strips the -section suffix", "replace(/-section$/, '')"),
    ("splits section ids on hyphens", ".split('-')"),
    ("splits capability keys on underscores", ".split('_')"),
    ("ignores tokens of two characters or fewer", "token.length > 2"),
    ("keeps the first section that scores highest", "score > bestScore"),
    ("skips keys that have a declared field", "!declaredKeys.has(key)"),
    ("skips keys the server suppresses", "!suppressedKeys.has(key)"),
)

DEFAULT_SETTING_RE = re.compile(
    r"^\s*'(?P<key>enable_[a-z0-9_]+)'\s*:\s*(?:True|False)\s*,", re.MULTILINE
)

fields_module = import_app_module("admin_settings_fields")


def read_capability_keys():
    """Return the ``enable_*`` booleans the settings document defaults to.

    ``functions_settings`` is one of the modules ``app_stubs`` replaces, because it
    reaches ``config.py`` and a live Cosmos client, so the defaults are read out of
    the source the same way ``scripts/build_docs_inventory.py`` reads them.
    """
    source = SETTINGS_MODULE.read_text(encoding="utf-8")
    keys = sorted({match.group("key") for match in DEFAULT_SETTING_RE.finditer(source)})
    assert keys, "No enable_* defaults were found; the extraction likely broke."
    return keys


def build_sections():
    """Return every navigation section with the tokens the renderer matches on."""
    sections = []
    for group in ADMIN_NAV:
        for tab in group["tabs"]:
            for section in tab["sections"]:
                tokens = {
                    token
                    for token in re.sub(r"-section$", "", section["id"]).split("-")
                    if len(token) > 2
                }
                sections.append(
                    {
                        "group_id": group["id"],
                        "group_label": group["label"],
                        "tab_label": tab["label"],
                        "section_id": section["id"],
                        "tokens": tokens,
                    }
                )
    return sections


def place_capability(key, sections):
    """Port of ``buildCapabilityIndex``: the section a guessed key is filed under.

    Returns ``None`` when nothing matched, which the renderer collects under
    "Other capabilities".
    """
    key_tokens = [
        token for token in key[len("enable_"):].split("_") if len(token) > 2
    ]

    best = None
    best_score = 0
    for section in sections:
        score = sum(1 for token in key_tokens if token in section["tokens"])
        # Strictly greater, so the first section reaching a score keeps it. That
        # tie-break is why navigation order decided three of the misfilings.
        if score > best_score:
            best_score = score
            best = section
    return best


def test_ported_heuristic_still_matches_the_renderer():
    """A rewritten renderer would leave this test asserting the wrong thing."""
    print("Testing the ported heuristic against AdminSettingsPage.tsx...")

    assert_app_version_at_least("0.261.059")

    assert RENDERER.is_file(), f"Missing the V2 admin renderer: {RENDERER}"
    source = RENDERER.read_text(encoding="utf-8")

    missing = [
        description
        for description, fragment in RENDERER_INVARIANTS
        if fragment not in source
    ]

    assert not missing, (
        "The V2 capability fallback no longer works the way this test models it, so "
        "its placement assertions are no longer meaningful. Re-read "
        "buildCapabilityIndex and update place_capability to match:\n  "
        + "\n  ".join(missing)
    )

    print(f"  All {len(RENDERER_INVARIANTS)} heuristic rule(s) still hold.")
    return True


def test_described_groups_receive_no_guessed_capabilities():
    """A fully described group has a real home for everything it owns."""
    print("\nTesting that no guessed capability lands in a fully described group...")

    declared = fields_module.get_declared_setting_keys()
    suppressed = set(fields_module.get_suppressed_capability_keys())
    sections = build_sections()
    described_sections = {
        section["section_id"]: section
        for section in sections
        if section["group_id"] in FULLY_DESCRIBED_GROUP_IDS
    }

    misfiled = []
    guessed = 0
    for key in read_capability_keys():
        if key in declared or key in suppressed:
            continue
        guessed += 1
        placement = place_capability(key, sections)
        if placement and placement["section_id"] in described_sections:
            misfiled.append(
                f"{key} -> {placement['group_label']} > {placement['tab_label']} "
                f"> {placement['section_id']}"
            )

    assert not misfiled, (
        "These settings have no declared field, so the V2 admin UI guessed a home "
        "for them and put them in a group that is described in full, where they do "
        "not belong. Declare each one in admin_settings_fields.py under the section "
        "it really lives in, or suppress it if it is not an editable setting:\n  "
        + "\n  ".join(misfiled)
    )

    print(
        f"  {guessed} guessed capability row(s), none of them in "
        f"{', '.join(FULLY_DESCRIBED_GROUP_IDS)}."
    )
    return True


def test_non_editable_capabilities_are_suppressed_not_declared():
    """A switch over a derived value appears to save and then reverts."""
    print("\nTesting the suppressed capability declarations...")

    suppressed = set(fields_module.get_suppressed_capability_keys())
    # A read-only mirror is not an editable declaration. It reports a derived
    # value and names what computes it, which is more use to an administrator
    # than the key being absent entirely, and it cannot be saved: the schema
    # rejects a write to a readonly field.
    editable = {
        field["key"]
        for _section_id, field in fields_module.iter_fields()
        if field.get("key") and not field.get("readonly")
    }

    problems = []
    for key in EXPECTED_SUPPRESSED_CAPABILITIES:
        if key not in suppressed:
            problems.append(
                f"{key}: not suppressed, so the fallback scan will draw a switch for it"
            )
        if key in editable:
            problems.append(
                f"{key}: declared as an editable field, but it is not an editable setting"
            )

    # Every suppression must carry a written reason, so a key cannot be hidden
    # from administrators without saying why.
    unexplained = sorted(
        key
        for key, reason in fields_module.SUPPRESSED_CAPABILITY_KEYS.items()
        if not str(reason or "").strip()
    )
    problems.extend(f"{key}: suppressed with no reason recorded" for key in unexplained)

    assert not problems, (
        "The suppressed capability list is wrong:\n  " + "\n  ".join(problems)
    )

    print(f"  All {len(EXPECTED_SUPPRESSED_CAPABILITIES)} suppression(s) hold.")
    return True


def test_suppressed_capabilities_are_real_settings_keys():
    """A suppression for a key that no longer exists hides nothing and misleads."""
    print("\nTesting that suppressed keys still exist in the settings document...")

    capability_keys = set(read_capability_keys())
    stale = sorted(
        key
        for key in fields_module.SUPPRESSED_CAPABILITY_KEYS
        if key not in capability_keys
    )

    assert not stale, (
        "These keys are suppressed but no longer appear in the settings defaults. "
        "Remove the suppression so it does not outlive the setting it describes:\n  "
        + "\n  ".join(stale)
    )

    print(f"  All {len(fields_module.SUPPRESSED_CAPABILITY_KEYS)} suppressed key(s) exist.")
    return True


def test_relocated_capabilities_are_declared_where_they_belong():
    """Undeclaring one of these silently returns it to the group it was guessed into."""
    print("\nTesting the relocated capability declarations...")

    declared_sections = {}
    for section_id, field in fields_module.iter_fields():
        key = field.get("key")
        if not key:
            continue
        # A key may also be declared as a read-only mirror in another section.
        # The writable declaration is the one that owns the setting, so a mirror
        # never displaces it here.
        existing = declared_sections.get(key)
        if existing and existing[1].get("readonly") is not True and field.get("readonly"):
            continue
        declared_sections[key] = (section_id, field)

    expected_sections = {
        key: section for key, (section, _pane) in RELOCATED_CAPABILITIES.items()
    }
    expected_sections.update(RELOCATED_CAPABILITIES_WITHOUT_V1_FIELD)

    problems = []
    for key, expected_section in expected_sections.items():
        entry = declared_sections.get(key)
        if entry is None:
            problems.append(f"{key}: not declared at all")
            continue
        section_id, field = entry
        if section_id != expected_section:
            problems.append(
                f"{key}: declared under {section_id!r}, expected {expected_section!r}"
            )
        if field.get("type") != "switch":
            problems.append(f"{key}: declared as {field.get('type')!r}, expected 'switch'")

    assert not problems, (
        "These capabilities were moved out of the group that guessed them by "
        "declaring them. Changing that undoes the move:\n  " + "\n  ".join(problems)
    )

    print(f"  All {len(expected_sections)} relocated capability declaration(s) hold.")
    return True


def test_v2_only_relocations_are_documented():
    """A field V1 has no control for must say why, not just appear."""
    print("\nTesting that V2-only relocations are recorded...")

    undocumented = sorted(
        key
        for key in RELOCATED_CAPABILITIES_WITHOUT_V1_FIELD
        if not fields_module.V2_ONLY_FIELDS.get(key)
    )

    assert not undocumented, (
        "These settings are declared in the schema but have no server-rendered "
        "control, so V2 is deliberately ahead of V1. Record the reason in "
        "V2_ONLY_FIELDS in admin_settings_fields.py:\n  " + "\n  ".join(undocumented)
    )

    print(
        f"  All {len(RELOCATED_CAPABILITIES_WITHOUT_V1_FIELD)} V2-only relocation(s) "
        "are documented."
    )
    return True


def test_relocated_capabilities_exist_in_their_v1_panes():
    """A declared field with no V1 counterpart would save a setting nothing reads."""
    print("\nTesting the relocated capabilities against their V1 panes...")

    panes_dir = APP_ROOT / "templates" / "admin" / "_panes"

    missing = []
    for key, (_section, pane_id) in RELOCATED_CAPABILITIES.items():
        pane_path = panes_dir / f"{pane_id}.html"
        if not pane_path.is_file():
            missing.append(f"{key}: pane {pane_path.name} does not exist")
            continue
        if f'name="{key}"' not in pane_path.read_text(encoding="utf-8"):
            missing.append(f"{key}: no name=\"{key}\" field in {pane_path.name}")

    assert not missing, (
        "These relocated capabilities do not exist in the server-rendered pane "
        "they were mirrored from:\n  " + "\n  ".join(missing)
    )

    print(f"  All {len(RELOCATED_CAPABILITIES)} capability field(s) exist in V1.")
    return True


if __name__ == "__main__":
    tests = [
        test_ported_heuristic_still_matches_the_renderer,
        test_described_groups_receive_no_guessed_capabilities,
        test_non_editable_capabilities_are_suppressed_not_declared,
        test_suppressed_capabilities_are_real_settings_keys,
        test_relocated_capabilities_are_declared_where_they_belong,
        test_v2_only_relocations_are_documented,
        test_relocated_capabilities_exist_in_their_v1_panes,
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
