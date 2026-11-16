# test_v2_admin_version_status.py
"""
Browser regression coverage for the V2 admin version and release status.
Version: 0.261.133
Implemented in: 0.261.126
Separate release check: 0.261.133

Use the built SPA with intercepted APIs, no live settings or GitHub requests.
The release status is its own request, so these tests also prove the settings
render and save while that check is still pending or after it fails.
The shared fixture supports local and Azure Playwright.
"""

import sys
from pathlib import Path

import pytest
from jinja2 import Template
from playwright.sync_api import expect

# Register the shared UI fixture and Azure connection options.
sys.path.insert(0, str(Path(__file__).resolve().parent / 'fixtures'))
from v2_admin_settings import AdminSettingsFixture, ORIGIN, connect_options


pytestmark = pytest.mark.ui
CURRENT = '0.261.126'


@pytest.fixture
def admin_ui(page):
    fixture = AdminSettingsFixture(page)
    fixture.payload['version'] = CURRENT
    fixture.update_payload = {
        'version': CURRENT,
        'update_status': {
            'latest_version': '0.261.127', 'update_available': True,
            'status': 'checked', 'checked_at': '2026-09-21T12:00:00+00:00',
            'attempted_at': '2026-09-21T12:00:00+00:00', 'error': None,
        },
    }
    yield fixture
    fixture.assert_clean()


@pytest.mark.parametrize('width', [390, 1440])
def test_running_version_and_new_release_remain_visible(admin_ui, width):
    admin_ui.open(width=width)
    page = admin_ui.page
    status = page.get_by_role('status', name='Application version')
    expect(status).to_contain_text(f'Version: {CURRENT}')
    expect(status).to_contain_text('New version available: v0.261.127')
    link = status.get_by_role('link', name='View releases')
    expect(link).to_have_attribute('href', 'https://github.com/microsoft/simplechat/releases')
    expect(link).to_have_attribute('rel', 'noopener noreferrer')
    expect(link).to_have_attribute('target', '_blank')
    bounds = status.bounding_box()
    assert bounds and bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= width
    search = page.get_by_role('searchbox', name='Search settings')
    search.fill('no matching setting')
    expect(status).to_be_visible()


@pytest.mark.parametrize('version', [CURRENT, '0.261.125'])
def test_equal_or_older_release_has_no_upgrade_notice(admin_ui, version):
    admin_ui.update_payload['update_status'].update(latest_version=version, update_available=False)
    admin_ui.open()
    status = admin_ui.page.get_by_role('status', name='Application version')
    expect(status).to_contain_text('No newer release found.')
    expect(status.get_by_role('link')).to_have_count(0)


@pytest.mark.parametrize('latest', [None, '0.261.127', '0.261.125'])
def test_failed_checks_never_claim_up_to_date(admin_ui, latest):
    admin_ui.update_payload['update_status'].update(
        latest_version=latest, status='stale' if latest else 'unavailable',
        update_available=latest == '0.261.127',
        error='Unable to check for application updates.',
    )
    admin_ui.open()
    status = admin_ui.page.get_by_role('status', name='Application version')
    expect(status).to_contain_text('Unable to check for application updates.')
    expect(status).not_to_contain_text('No newer release found.')
    if latest:
        expect(status).to_contain_text('may be stale')
    if latest == '0.261.127':
        expect(status).to_contain_text('Last known newer release: v0.261.127')
    page = admin_ui.page
    page.get_by_role('button', name='Hero', exact=False).click()
    page.get_by_label('Hero Title', exact=True).fill('Updated without release service')
    page.get_by_role('button', name='Save changes', exact=True).click()
    expect(page.get_by_role('button', name='Save changes', exact=True)).to_have_count(0)
    assert admin_ui.patches == [{'agents_page_title': 'Updated without release service'}]


def test_settings_are_usable_while_release_check_is_pending(admin_ui):
    """A slow GitHub check holds up only the banner, never the settings."""
    admin_ui.hold_update_status = True
    admin_ui.open(wait_until='load')
    page = admin_ui.page
    status = page.get_by_role('status', name='Application version')
    expect(status).to_contain_text(f'Version: {CURRENT}')
    expect(status).to_contain_text('Checking for updates...')

    page.get_by_role('button', name='Hero', exact=False).click()
    page.get_by_label('Hero Title', exact=True).fill('Saved while checking for updates')
    page.get_by_role('button', name='Save changes', exact=True).click()
    expect(page.get_by_role('button', name='Save changes', exact=True)).to_have_count(0)
    assert admin_ui.patches == [{'agents_page_title': 'Saved while checking for updates'}]
    # One check for the visit: saving must not start another one.
    assert len(admin_ui.held_update_status) == 1
    expect(status).to_contain_text('Checking for updates...')

    admin_ui.release_update_status()
    expect(status).to_contain_text('New version available: v0.261.127')
    expect(status).not_to_contain_text('Checking for updates...')


def test_release_check_failure_leaves_settings_usable(admin_ui):
    page = admin_ui.page
    page.route('**/api/v2/admin/update-status', lambda route: route.fulfill(
        status=500, json={'error': 'Unable to check for application updates.'},
    ))
    admin_ui.open()
    status = page.get_by_role('status', name='Application version')
    expect(status).to_contain_text(f'Version: {CURRENT}')
    expect(status).to_contain_text('Unable to check for application updates.')
    expect(status).not_to_contain_text('Checking for updates...')
    expect(status).not_to_contain_text('No newer release found.')
    expect(status.get_by_role('link')).to_have_count(0)
    page.get_by_role('button', name='Hero', exact=False).click()
    page.get_by_label('Hero Title', exact=True).fill('Saved without a release check')
    page.get_by_role('button', name='Save changes', exact=True).click()
    expect(page.get_by_role('button', name='Save changes', exact=True)).to_have_count(0)
    assert admin_ui.patches == [{'agents_page_title': 'Saved without a release check'}]
    # The intentionally failed release request is the only expected console error.
    assert admin_ui.errors and all('500' in error for error in admin_ui.errors)
    admin_ui.errors.clear()


def test_settings_failure_keeps_version_and_release_status(admin_ui):
    page = admin_ui.page
    page.route('**/api/v2/admin/settings', lambda route: route.fulfill(
        status=503, json={'error': 'Settings temporarily unavailable.'},
    ))
    page.goto(f'{ORIGIN}/v2/admin', wait_until='networkidle')
    status = page.get_by_role('status', name='Application version')
    expect(status).to_contain_text(f"Version: {admin_ui._bootstrap()['version']}")
    # The release check is a separate request, so a settings failure does not hide it.
    expect(status).to_contain_text('New version available: v0.261.127')
    expect(page.get_by_text('Settings temporarily unavailable.', exact=True)).to_be_visible()
    # The intentionally failed HTTP request is the only expected console error.
    assert all('503' in error for error in admin_ui.errors)
    admin_ui.errors.clear()


@pytest.mark.parametrize('state', ['checked', 'stale', 'unavailable'])
def test_classic_version_markup_uses_shared_status(page, state):
    """Render the actual classic version fragment without a live Flask/Azure app."""
    template_path = (
        Path(__file__).resolve().parents[1] / 'application' / 'single_app'
        / 'templates' / 'admin_settings.html'
    )
    source = template_path.read_text(encoding='utf-8')
    start = source.index('<p class="text-muted d-flex flex-wrap align-items-center gap-2">')
    fragment = source[start:source.index('</p>', start) + len('</p>')]
    latest = '0.261.127' if state != 'unavailable' else None
    html = Template(fragment).render(
        config={'VERSION': CURRENT},
        settings={'release_notifications_registered': False},
        update_available=latest is not None,
        latest_version=latest,
        download_url='https://github.com/microsoft/simplechat/releases',
        update_status={
            'status': state,
            'latest_version': latest,
            'error': None if state == 'checked' else 'Unable to check for application updates.',
        },
    )
    page.set_content(html)
    expect(page.locator('p')).to_contain_text(f'Version: {CURRENT}')
    if state == 'checked':
        expect(page.locator('p')).to_contain_text('New version available')
    else:
        expect(page.get_by_role('status')).to_contain_text('Unable to check for application updates.')
        expect(page.locator('p')).not_to_contain_text('New version available')
    if state == 'stale':
        expect(page.locator('p')).to_contain_text('Last known newer release')
        expect(page.get_by_role('status')).to_contain_text('may be stale')
