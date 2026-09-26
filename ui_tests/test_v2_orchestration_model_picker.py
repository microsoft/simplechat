# test_v2_orchestration_model_picker.py
"""
Browser regressions for the Orchestrate model picker's placement and remembered choice.
Version: 0.261.137
Implemented in: 0.261.137

In Orchestrate the model picker used to jump out above the input, and its Auto choice lived
only in component state, so leaving the chat or opening a new one reset it to a specific model.
It now sits in the normal model picker's slot under Manual controls, defaults to Auto wherever a
connected model can be chosen per step, and is saved to the account. The normal chat model is
remembered the same way instead of snapping back to the model loaded at startup.

Drives the real Composer, router and settings store over the approval-persistence HTTP fixture,
whose settings persist across remounts and fresh browser contexts. Planning requests are captured
and answered with a pending fixture plan; no model or tool runs.

Run: python -m pytest ui_tests/test_v2_orchestration_model_picker.py -q
"""

import copy
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

# Appended, not prepended: the approval-persistence UI fixtures below share their module name
# with a functional test, and this directory's copy is the one wanted.
sys.path.append(str(Path(__file__).resolve().parents[1] / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_v2_orchestration_approval_persistence import (  # noqa: E402, F401
    approval_assets, approval_browser, approval_ui, connect_options,
    CHAT_PATH, PLAN_PATH, mount, message_box, send_button, settings_response,
)

pytestmark = pytest.mark.ui

PICKER_TITLE = "Auto chooses by task, then admin priority and favorites. A specific model stays pinned."
AUTO = "Auto - choose per step"
ROUTING = "orchestrationModelRouting"
PINNED = "orchestrationPreferredModelId"
MODEL_FIELDS = {"model_deployment", "model_id", "model_endpoint_id", "model_provider", "reasoning_effort"}


def catalog_model(key, label, model_id, endpoint_id, *, routable=True):
    model = {
        "selection_key": key, "display_name": label, "deployment_name": model_id,
        "model_id": model_id, "endpoint_id": endpoint_id, "provider": "aoai",
    }
    if routable:
        model.update({
            "profile": {"id": f"profile-{model_id}", "archived": False, "tasks": {"general": "suitable"}},
            "capabilities": {"processesText": True, "generatesText": True},
            "auto_routing_available": True,
        })
    return model


WRITER = catalog_model("global::east:writer", "Writer", "writer", "east")
SUMMARY = catalog_model("global::west:summary", "Summary", "summary", "west")


def configure(api, *, models=(WRITER, SUMMARY), orchestration=True, manual_controls=True,
              approval_override=True):
    models = [copy.deepcopy(model) for model in models]
    api.bootstrap["features"]["enable_chat_orchestration"] = orchestration
    api.bootstrap["catalogs"].update(models=models, initial_model_selection=copy.deepcopy(models[0]))
    api.bootstrap["orchestration"].update(
        show_manual_controls=manual_controls, allow_user_approval_override=approval_override,
    )


def picker(page):
    return page.locator(f'[title="{PICKER_TITLE}"]')


def open_manual(page):
    page.get_by_title("Manual controls", exact=True).click()
    expect(picker(page)).to_be_visible()


def choose(page, label):
    with page.expect_response(settings_response):
        picker(page).click()
        page.get_by_role("option", name=label, exact=True).click()
    expect(picker(page)).to_contain_text(label)


def leave_and_return(page):
    page.get_by_role("link", name="Leave chat", exact=True).click()
    expect(page.get_by_text("Away from chat", exact=True)).to_be_visible()
    page.get_by_role("link", name="Return to chat", exact=True).click()
    expect(message_box(page)).to_be_visible()


def send(page, path=PLAN_PATH, text="Plan the requested work."):
    message_box(page).fill(text)
    with page.expect_response(lambda response: urlsplit(response.url).path == path):
        send_button(page).click()


def test_implementation_version():
    assert_app_version_at_least("0.261.137")


@pytest.mark.parametrize("width", [1440, 390])
def test_picker_lives_under_manual_controls_not_above_the_input(approval_ui, width):
    open_page, api = approval_ui
    configure(api)
    page = open_page(width)
    mount(page, api)

    expect(page.get_by_title("Orchestrate", exact=True)).to_have_attribute("aria-pressed", "true")
    expect(picker(page)).to_have_count(0)
    expect(page.get_by_text(AUTO, exact=True)).to_have_count(0)
    open_manual(page)
    expect(picker(page)).to_contain_text(AUTO)
    # The old picker sat above the input. The new one is in the toolbar underneath it.
    assert picker(page).bounding_box()["y"] > message_box(page).bounding_box()["y"]
    picker(page).click()
    options = page.get_by_role("listbox", name="Orchestration model options").get_by_role("option")
    expect(options).to_have_text([AUTO, "Writer", "Summary"])
    page.keyboard.press("Escape")
    page.get_by_title("Manual controls", exact=True).click()
    expect(picker(page)).to_have_count(0)


def test_auto_is_the_default_and_survives_leaving_the_chat(approval_ui):
    open_page, api = approval_ui
    configure(api)
    page = open_page()
    mount(page, api)
    open_manual(page)
    expect(picker(page)).to_contain_text(AUTO)

    choose(page, "Writer")
    assert api.settings[ROUTING] == "manual" and api.settings[PINNED] == WRITER["selection_key"]
    choose(page, AUTO)
    assert api.settings[ROUTING] == "auto"
    assert api.settings["darkModeEnabled"] is True

    leave_and_return(page)
    open_manual(page)
    expect(picker(page)).to_contain_text(AUTO)
    send(page)
    assert api.plans[-1]["model_routing"] == "auto"
    assert not set(api.plans[-1]) & MODEL_FIELDS

    choose(page, "Summary")
    leave_and_return(page)
    open_manual(page)
    expect(picker(page)).to_contain_text("Summary")
    send(page)
    assert "model_routing" not in api.plans[-1]
    assert api.plans[-1]["model_id"] == "summary" and api.plans[-1]["model_endpoint_id"] == "west"


def test_choice_is_restored_after_a_reload_and_in_a_fresh_browser_context(approval_ui):
    open_page, api = approval_ui
    configure(api)
    page = open_page()
    mount(page, api)
    open_manual(page)
    choose(page, "Summary")
    for current in (page, open_page(390)):
        mount(current, api)
        open_manual(current)
        expect(picker(current)).to_contain_text("Summary")


def unrated(model):
    """A profiled model with no rating for general answering."""
    model = copy.deepcopy(model)
    model["profile"]["tasks"] = {"summarization": "strong"}
    return model


@pytest.mark.parametrize("models", [
    pytest.param((
        catalog_model("global::east:writer", "Writer", "writer", "east", routable=False),
        catalog_model("global::west:summary", "Summary", "summary", "west", routable=False),
    ), id="no-catalog-profile"),
    pytest.param((unrated(WRITER), unrated(SUMMARY)), id="no-general-rating"),
])
def test_auto_is_not_offered_without_a_routable_model(approval_ui, models):
    open_page, api = approval_ui
    configure(api, models=models)
    page = open_page()
    mount(page, api)
    open_manual(page)
    expect(picker(page)).to_contain_text("Writer")
    picker(page).click()
    options = page.get_by_role("listbox", name="Orchestration model options").get_by_role("option")
    expect(options).to_have_text(["Writer", "Summary"])
    page.keyboard.press("Escape")
    send(page)
    assert "model_routing" not in api.plans[-1]
    assert api.plans[-1]["model_id"] == "writer"


def test_hidden_manual_controls_use_auto_and_ignore_a_saved_pin(approval_ui):
    open_page, api = approval_ui
    configure(api, manual_controls=False)
    api.settings.update({ROUTING: "manual", PINNED: SUMMARY["selection_key"]})
    page = open_page()
    mount(page, api)
    expect(page.get_by_title("Manual controls", exact=True)).to_have_count(0)
    expect(picker(page)).to_have_count(0)
    send(page)
    assert api.plans[-1]["model_routing"] == "auto"
    assert not set(api.plans[-1]) & MODEL_FIELDS


def test_an_orchestrate_pin_leaves_the_normal_chat_model_alone(approval_ui):
    open_page, api = approval_ui
    configure(api)
    page = open_page()
    mount(page, api)
    open_manual(page)
    choose(page, "Summary")
    page.get_by_title("Orchestrate", exact=True).click()
    normal = page.get_by_role("button", name="Writer", exact=True)
    expect(normal).to_be_visible()
    expect(picker(page)).to_have_count(0)
    normal.click()
    options = page.get_by_role("listbox", name="Model options").get_by_role("option")
    expect(options).to_have_text(["Writer", "Summary"])
    page.keyboard.press("Escape")
    send(page, CHAT_PATH, "A normal chat message.")
    assert api.chats[-1]["model_id"] == "writer"
    assert "model_routing" not in api.chats[-1]
    page.get_by_title("Orchestrate", exact=True).click()
    # The disclosure keeps the state it had, so the pinned model is showing again at once.
    expect(page.get_by_title("Manual controls", exact=True)).to_have_attribute("aria-expanded", "true")
    expect(picker(page)).to_contain_text("Summary")


def test_the_normal_chat_model_survives_leaving_the_chat(approval_ui):
    open_page, api = approval_ui
    configure(api, orchestration=False)
    page = open_page()
    mount(page, api)
    with page.expect_response(settings_response):
        page.get_by_role("button", name="Writer", exact=True).click()
        page.get_by_role("listbox", name="Model options").get_by_role("option", name="Summary", exact=True).click()
    assert api.settings["preferredModelId"] == SUMMARY["selection_key"]
    # The bootstrap still names Writer, as it would until the page next reloads it.
    assert api.bootstrap["catalogs"]["initial_model_selection"]["selection_key"] == WRITER["selection_key"]
    leave_and_return(page)
    expect(page.get_by_role("button", name="Summary", exact=True)).to_be_visible()
    send(page, CHAT_PATH, "Use the model I chose.")
    assert api.chats[-1]["model_id"] == "summary"


def test_sending_waits_for_a_saved_pin_to_load(approval_ui):
    open_page, api = approval_ui
    configure(api, approval_override=False)
    api.settings.update({ROUTING: "manual", PINNED: SUMMARY["selection_key"]})
    api.hold_reads = True
    page = open_page()
    mount(page, api)
    message_box(page).fill("Plan with my pinned model.")
    expect(send_button(page)).to_be_disabled()
    expect(page.get_by_role("status").filter(
        has_text="Loading your model preference before orchestration can start",
    )).to_be_visible()
    api.release_reads()
    expect(send_button(page)).to_be_enabled()
    with page.expect_response(lambda response: urlsplit(response.url).path == PLAN_PATH):
        send_button(page).click()
    assert api.plans[-1]["model_id"] == "summary" and "model_routing" not in api.plans[-1]
