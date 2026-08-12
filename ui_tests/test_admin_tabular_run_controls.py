# test_admin_tabular_run_controls.py
"""
Rendered UI regression for Admin Settings tabular run controls.
Version: 0.250.168
Implemented in: 0.250.168

This test ensures admins can render, change, save, reload, and restore the
large tabular run confirmation and chunk-processing model settings.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
ADMIN_STORAGE_STATE = (
    os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE", "")
    or os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
)
ALLOW_ADMIN_SETTINGS_MUTATION = (
    os.getenv("SIMPLECHAT_UI_ALLOW_ADMIN_SETTINGS_MUTATION", "").strip().lower()
    == "true"
)
UNAVAILABLE_STATUS_CODES = {401, 403, 404}


def _require_ui_environment():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not ADMIN_STORAGE_STATE or not Path(ADMIN_STORAGE_STATE).exists():
        pytest.skip(
            "Set SIMPLECHAT_UI_ADMIN_STORAGE_STATE or SIMPLECHAT_UI_STORAGE_STATE "
            "to a valid authenticated admin Playwright storage state file."
        )
    if not ALLOW_ADMIN_SETTINGS_MUTATION:
        pytest.skip(
            "Set SIMPLECHAT_UI_ALLOW_ADMIN_SETTINGS_MUTATION=true only for an "
            "isolated environment where shared Admin Settings may be changed."
        )


def _open_citations_tab(page):
    citation_tab = page.locator("#citation-tab")
    expect(citation_tab).to_be_visible()
    citation_tab.click()
    expect(page.locator("#citation")).to_be_visible()


def _wait_for_admin_settings_script(page):
    page.wait_for_function(
        "typeof window.isAdminSettingsFormModified === 'function'"
    )


def _load_admin_settings(page, *, allow_unavailable_skip=False):
    response = page.goto(
        f"{BASE_URL}/admin/settings#citation",
        wait_until="domcontentloaded",
    )
    assert response is not None, "Expected a navigation response for Admin Settings."
    if response.status in UNAVAILABLE_STATUS_CODES and allow_unavailable_skip:
        pytest.skip("Admin Settings is unavailable for the configured admin session.")
    assert response.ok, (
        f"Expected Admin Settings to load successfully, got HTTP {response.status}."
    )
    _wait_for_admin_settings_script(page)
    _open_citations_tab(page)


def _reload_admin_settings(page):
    response = page.reload(wait_until="domcontentloaded")
    assert response is not None, "Expected a response when reloading Admin Settings."
    assert response.ok, (
        f"Expected Admin Settings reload to succeed, got HTTP {response.status}."
    )
    _wait_for_admin_settings_script(page)
    _open_citations_tab(page)


def _read_tabular_settings(page):
    return {
        "enable_enhanced_citations": page.locator(
            "#enable_enhanced_citations"
        ).is_checked(),
        "enable_tabular_durable_run_confirmation": page.locator(
            "#enable_tabular_durable_run_confirmation"
        ).is_checked(),
        "tabular_durable_run_confirmation_threshold_rows": page.locator(
            "#tabular_durable_run_confirmation_threshold_rows"
        ).input_value(),
        "tabular_durable_run_confirmation_threshold_batches": page.locator(
            "#tabular_durable_run_confirmation_threshold_batches"
        ).input_value(),
        "tabular_generated_output_chunk_model_mode": page.locator(
            "#tabular_generated_output_chunk_model_mode"
        ).input_value(),
        "tabular_generated_output_chunk_model_deployment": page.locator(
            "#tabular_generated_output_chunk_model_deployment"
        ).input_value(),
    }


def _read_configured_gpt_deployments(page):
    return page.evaluate(
        """() => {
            const deployments = [];
            const appendDeployment = (value) => {
                const deployment = String(value || '').trim();
                if (deployment && !deployments.includes(deployment)) {
                    deployments.push(deployment);
                }
            };

            if (document.getElementById('enable_gpt_apim')?.checked) {
                String(
                    document.getElementById('azure_apim_gpt_deployment')?.value || ''
                )
                    .split(',')
                    .forEach(appendDeployment);
            } else {
                (Array.isArray(window.gptSelected) ? window.gptSelected : [])
                    .forEach((model) => appendDeployment(model?.deploymentName));
                appendDeployment(document.getElementById('gpt_model')?.value);
            }

            return deployments;
        }"""
    )


def _assert_controls_render(page):
    expect(
        page.get_by_role("heading", name="Large Tabular Run Controls")
    ).to_be_visible()
    expect(
        page.get_by_label("Confirm very large row-level runs before starting")
    ).to_be_visible()

    row_threshold = page.get_by_label("Confirmation Row Threshold")
    expect(row_threshold).to_be_visible()
    expect(row_threshold).to_have_attribute("min", "1")
    expect(row_threshold).to_have_attribute("max", "1000000")

    batch_threshold = page.get_by_label("Confirmation Batch Threshold")
    expect(batch_threshold).to_be_visible()
    expect(batch_threshold).to_have_attribute("min", "1")
    expect(batch_threshold).to_have_attribute("max", "100000")

    model_mode = page.get_by_label("Chunk Processing Model")
    expect(model_mode).to_be_visible()
    expect(model_mode.locator('option[value="current"]')).to_have_text(
        "Use the user's selected model"
    )
    expect(model_mode.locator('option[value="configured"]')).to_have_text(
        "Use a configured deployment for chunk work"
    )

    deployment = page.get_by_label("Configured Chunk Model Deployment")
    expect(deployment).to_be_visible()
    expect(deployment).to_have_attribute("maxlength", "120")


def _numeric_alternate(value, maximum):
    current_value = int(value)
    return str(current_value + 1 if current_value < maximum else current_value - 1)


def _build_alternate_settings(original_settings, configured_deployments):
    original_mode = original_settings["tabular_generated_output_chunk_model_mode"]
    assert original_mode in {"current", "configured"}
    original_deployment = original_settings[
        "tabular_generated_output_chunk_model_deployment"
    ]
    deployment = next(
        (
            candidate
            for candidate in configured_deployments
            if candidate != original_deployment
        ),
        None,
    )
    if deployment is None:
        pytest.skip(
            "This persistence test requires an active GPT deployment that differs "
            "from the saved tabular chunk deployment."
        )

    return {
        "enable_enhanced_citations": original_settings[
            "enable_enhanced_citations"
        ],
        "enable_tabular_durable_run_confirmation": not original_settings[
            "enable_tabular_durable_run_confirmation"
        ],
        "tabular_durable_run_confirmation_threshold_rows": _numeric_alternate(
            original_settings["tabular_durable_run_confirmation_threshold_rows"],
            1000000,
        ),
        "tabular_durable_run_confirmation_threshold_batches": _numeric_alternate(
            original_settings["tabular_durable_run_confirmation_threshold_batches"],
            100000,
        ),
        "tabular_generated_output_chunk_model_mode": (
            "configured" if original_mode == "current" else "current"
        ),
        "tabular_generated_output_chunk_model_deployment": deployment,
    }


def _set_checkbox(locator, checked):
    if checked and not locator.is_checked():
        locator.check()
    elif not checked and locator.is_checked():
        locator.uncheck()


def _apply_tabular_settings(page, settings):
    enhanced_citations = page.locator("#enable_enhanced_citations")
    _set_checkbox(enhanced_citations, True)
    expect(page.locator("#enhanced_citation_settings")).to_be_visible()

    _set_checkbox(
        page.locator("#enable_tabular_durable_run_confirmation"),
        settings["enable_tabular_durable_run_confirmation"],
    )
    page.locator("#tabular_durable_run_confirmation_threshold_rows").fill(
        settings["tabular_durable_run_confirmation_threshold_rows"]
    )
    page.locator("#tabular_durable_run_confirmation_threshold_batches").fill(
        settings["tabular_durable_run_confirmation_threshold_batches"]
    )
    page.locator("#tabular_generated_output_chunk_model_mode").select_option(
        settings["tabular_generated_output_chunk_model_mode"]
    )
    page.locator("#tabular_generated_output_chunk_model_deployment").fill(
        settings["tabular_generated_output_chunk_model_deployment"]
    )

    _set_checkbox(
        enhanced_citations,
        settings["enable_enhanced_citations"],
    )


def _assert_tabular_settings(page, expected_settings):
    enhanced_citations = page.locator("#enable_enhanced_citations")
    durable_confirmation = page.locator(
        "#enable_tabular_durable_run_confirmation"
    )

    if expected_settings["enable_enhanced_citations"]:
        expect(enhanced_citations).to_be_checked()
        expect(page.locator("#enhanced_citation_settings")).to_be_visible()
    else:
        expect(enhanced_citations).not_to_be_checked()
        expect(page.locator("#enhanced_citation_settings")).to_be_hidden()

    if expected_settings["enable_tabular_durable_run_confirmation"]:
        expect(durable_confirmation).to_be_checked()
    else:
        expect(durable_confirmation).not_to_be_checked()

    expect(
        page.locator("#tabular_durable_run_confirmation_threshold_rows")
    ).to_have_value(
        expected_settings["tabular_durable_run_confirmation_threshold_rows"]
    )
    expect(
        page.locator("#tabular_durable_run_confirmation_threshold_batches")
    ).to_have_value(
        expected_settings["tabular_durable_run_confirmation_threshold_batches"]
    )
    expect(page.locator("#tabular_generated_output_chunk_model_mode")).to_have_value(
        expected_settings["tabular_generated_output_chunk_model_mode"]
    )
    expect(
        page.locator("#tabular_generated_output_chunk_model_deployment")
    ).to_have_value(
        expected_settings["tabular_generated_output_chunk_model_deployment"]
    )


def _save_admin_settings(page):
    save_button = page.locator("#floating-save-btn")
    expect(save_button).to_be_enabled()
    with page.expect_navigation(wait_until="domcontentloaded") as navigation:
        save_button.click()

    response = navigation.value
    assert response is not None, "Expected Admin Settings form submission to navigate."
    assert response.ok, (
        f"Expected Admin Settings save redirect to succeed, got HTTP {response.status}."
    )
    assert response.request.method == "GET", (
        "Expected Admin Settings to finish the save redirect with a GET request."
    )
    redirected_request = response.request.redirected_from
    while redirected_request is not None and redirected_request.method != "POST":
        redirected_request = redirected_request.redirected_from
    assert redirected_request is not None, (
        "Expected the Admin Settings navigation redirect chain to include the form POST."
    )
    _wait_for_admin_settings_script(page)
    expect(
        page.get_by_text("Admin settings updated successfully.", exact=True)
    ).to_be_visible()


@pytest.mark.ui
def test_admin_tabular_run_controls_persist_after_reload(playwright):
    """Validate rendered tabular run controls save, reload, and restore cleanly."""
    _require_ui_environment()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=ADMIN_STORAGE_STATE,
        viewport={"width": 1440, "height": 1000},
    )
    page = context.new_page()
    original_settings = None
    restore_required = False

    try:
        _load_admin_settings(page, allow_unavailable_skip=True)
        original_settings = _read_tabular_settings(page)
        if page.evaluate("window.enableMultiModelEndpoints === true"):
            pytest.skip(
                "Configured tabular chunk models are not endpoint-aware; run this "
                "persistence test in an isolated legacy direct or APIM environment."
            )
        configured_deployments = _read_configured_gpt_deployments(page)
        alternate_settings = _build_alternate_settings(
            original_settings,
            configured_deployments,
        )

        _set_checkbox(page.locator("#enable_enhanced_citations"), True)
        expect(page.locator("#enhanced_citation_settings")).to_be_visible()
        _assert_controls_render(page)

        _apply_tabular_settings(page, alternate_settings)
        _assert_tabular_settings(page, alternate_settings)

        restore_required = True
        _save_admin_settings(page)
        _open_citations_tab(page)
        _assert_tabular_settings(page, alternate_settings)

        _reload_admin_settings(page)
        _assert_tabular_settings(page, alternate_settings)
    finally:
        if restore_required and original_settings is not None:
            _load_admin_settings(page)
            _apply_tabular_settings(page, original_settings)
            _save_admin_settings(page)
            _reload_admin_settings(page)
            _assert_tabular_settings(page, original_settings)

        context.close()
        browser.close()
