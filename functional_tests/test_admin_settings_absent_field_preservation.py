#!/usr/bin/env python3
# test_admin_settings_absent_field_preservation.py
"""
Functional test that the admin save cannot zero a setting nobody can edit.
Version: 0.261.059
Implemented in: 0.261.059

The server-rendered admin page submits one big form and the save handler reads
every value out of it by name. When a setting is written from ``form_data`` but
no template renders an input for it, ``form_data.get(name, '')`` returns the
literal default on every save -- so the stored value is silently overwritten,
for any unrelated reason, with no error anywhere.

This has bitten twice:

``number_of_historical_messages_to_summarize`` and the two summarize switches
    Read by ``route_backend_chats.py`` but never rendered, so every save reset
    them to off and 10. Fixed by adding the controls.

``office_docs_key``, ``video_files_key``, ``audio_files_key``
    Azure Storage account keys. ``office_docs_key`` is passed straight to
    ``generate_blob_sas`` as ``account_key=`` for Enhanced Citations file
    access, and ``route_frontend_chats.py`` returns a 500 when it is empty, so
    zeroing it breaks citation downloads after the first admin save. There is
    still no input for these, so they are preserved from the stored settings
    instead.

The check below is the general one: any settings key the save handler reads from
the form with a *literal* default must either have an input in the composed
template, or fall back to the stored value.
"""

import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.templates import read_admin_settings_template
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
SAVE_HANDLER = REPO_ROOT / "application" / "single_app" / "route_frontend_admin_settings.py"

# `'some_key': form_data.get('some_key', <default>)` -- the shape that silently
# resets. A default that is anything other than a literal '' or "" is reading a
# fallback, which is the fix, so only the literal-empty form is matched.
RESET_SHAPE_RE = re.compile(
    r"""^\s*['"](?P<key>[a-z0-9_]+)['"]\s*:\s*form_data\.get\(\s*"""
    r"""['"](?P<field>[a-z0-9_]+)['"]\s*,\s*(?P<default>''|"")\s*\)""",
    re.MULTILINE,
)

FIELD_NAME_RE = re.compile(r'\sname="([^"]+)"')
TEMPLATED = re.compile(r"\{\{|\{%")

# Keys written with a literal '' default whose form field does not exist, with the
# reason each is recorded rather than fixed. An entry here is a decision, not an
# oversight, and the staleness check below stops one outliving its setting.
KNOWN_UNBACKED_FORM_READS = {
    "web_search_foundry_notes": (
        "Free-text notes on the Azure AI Foundry web search config. No template or "
        "script renders it and nothing reads it back, so there is no value to lose. "
        "Recorded rather than fixed because it belongs to the Web Search settings, "
        "not the Chat work that added this check."
    ),
}


def submitted_field_names():
    """Every literal form field name the composed admin template submits."""
    markup = read_admin_settings_template()
    return {
        name for name in FIELD_NAME_RE.findall(markup) if not TEMPLATED.search(name)
    }


def test_no_setting_is_reset_by_a_form_it_cannot_be_edited_in():
    """A key read from an input that does not exist is zeroed on every save."""
    print("Testing that the admin save cannot zero an uneditable setting...")

    assert_app_version_at_least("0.261.059")

    assert SAVE_HANDLER.is_file(), f"Missing the admin save handler: {SAVE_HANDLER}"
    source = SAVE_HANDLER.read_text(encoding="utf-8")

    rendered = submitted_field_names()
    assert rendered, "No form field names were found; the extraction likely broke."

    offenders = []
    checked = 0
    for match in RESET_SHAPE_RE.finditer(source):
        key = match.group("key")
        field = match.group("field")
        checked += 1

        if field in rendered or field in KNOWN_UNBACKED_FORM_READS:
            continue

        offenders.append(
            f"{key}: read from form field {field!r}, which no template renders"
        )

    assert not offenders, (
        "These settings are written from a form field that does not exist, so "
        "form_data.get returns the empty default and every admin save overwrites "
        "the stored value. Either render an input, or fall back to the stored "
        "setting as the neighbouring fields do:\n  " + "\n  ".join(sorted(offenders))
    )

    assert checked, "No form reads were inspected; the extraction likely broke."
    print(f"  {checked} literal-default form read(s), all backed by a real input.")
    return True


def test_storage_account_keys_fall_back_to_the_stored_value():
    """These have no input at all, so only a stored fallback preserves them."""
    print("\nTesting the storage account key fallbacks...")

    source = SAVE_HANDLER.read_text(encoding="utf-8")

    missing = [
        key
        for key in ("office_docs_key", "video_files_key", "audio_files_key")
        if not re.search(
            rf"""['"]{key}['"]\s*:\s*form_data\.get\(\s*['"]{key}['"]\s*,\s*"""
            rf"""settings\.get\(\s*['"]{key}['"]""",
            source,
        )
    ]

    assert not missing, (
        "These storage account keys no longer fall back to the stored value, so "
        "an admin save zeroes them. office_docs_key is passed to generate_blob_sas "
        "as account_key= for Enhanced Citations, and an empty value returns a 500 "
        "on every citation download:\n  " + "\n  ".join(missing)
    )

    print("  All 3 storage account key(s) preserve the stored value.")
    return True


def test_known_unbacked_reads_are_still_real():
    """An exemption that outlives its setting hides the next instance of this bug."""
    print("\nTesting the known unbacked form read list...")

    source = SAVE_HANDLER.read_text(encoding="utf-8")
    rendered = submitted_field_names()

    problems = []
    for field, reason in KNOWN_UNBACKED_FORM_READS.items():
        if f"'{field}'" not in source:
            problems.append(f"{field}: the save handler no longer reads it")
        if field in rendered:
            problems.append(
                f"{field}: a template now renders it, so the exemption is obsolete"
            )
        if not str(reason or "").strip():
            problems.append(f"{field}: recorded with no reason")

    assert not problems, (
        "The known unbacked form read list is stale:\n  " + "\n  ".join(problems)
    )

    print(f"  {len(KNOWN_UNBACKED_FORM_READS)} recorded read(s), all still real.")
    return True


if __name__ == "__main__":
    tests = [
        test_no_setting_is_reset_by_a_form_it_cannot_be_edited_in,
        test_storage_account_keys_fall_back_to_the_stored_value,
        test_known_unbacked_reads_are_still_real,
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
