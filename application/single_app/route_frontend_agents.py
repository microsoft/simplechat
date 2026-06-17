# route_frontend_agents.py

import re

from config import *
from functions_authentication import *
from functions_settings import get_settings, sanitize_settings_for_user
from swagger_wrapper import swagger_route, get_auth_security


AGENTS_PAGE_DEFAULTS = {
    'title': 'Find your next AI partner',
    'subtitle': 'Explore specialized agents built to accelerate how you work.',
    'hero_color_mode': 'single',
    'hero_primary_color': '#0f172a',
    'hero_secondary_color': '#1e293b',
    'disclaimer_markdown': '',
    'show_instructions_in_details': True,
}
HEX_COLOR_PATTERN = re.compile(r'^#[0-9a-fA-F]{6}$')


def _normalize_agents_page_text(value, fallback, max_length):
    candidate = str(value or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    if not candidate:
        candidate = fallback
    return candidate[:max_length]


def _normalize_agents_page_color(value, fallback):
    candidate = str(value or '').strip()
    fallback_value = fallback if HEX_COLOR_PATTERN.fullmatch(str(fallback or '')) else '#0f172a'
    return candidate if HEX_COLOR_PATTERN.fullmatch(candidate) else fallback_value


def build_agents_page_config(settings):
    safe_settings = settings if isinstance(settings, dict) else {}
    return {
        'title': _normalize_agents_page_text(
            safe_settings.get('agents_page_title'),
            AGENTS_PAGE_DEFAULTS['title'],
            120,
        ),
        'subtitle': _normalize_agents_page_text(
            safe_settings.get('agents_page_subtitle'),
            AGENTS_PAGE_DEFAULTS['subtitle'],
            240,
        ),
        'hero_color_mode': 'two_tone'
            if str(safe_settings.get('agents_page_hero_color_mode') or '').strip() == 'two_tone'
            else 'single',
        'hero_primary_color': _normalize_agents_page_color(
            safe_settings.get('agents_page_hero_primary_color'),
            AGENTS_PAGE_DEFAULTS['hero_primary_color'],
        ),
        'hero_secondary_color': _normalize_agents_page_color(
            safe_settings.get('agents_page_hero_secondary_color'),
            AGENTS_PAGE_DEFAULTS['hero_secondary_color'],
        ),
        'disclaimer_markdown': _normalize_agents_page_text(
            safe_settings.get('agents_page_disclaimer_markdown'),
            '',
            3000,
        ),
        'show_instructions_in_details': bool(safe_settings.get(
            'agents_page_show_instructions_in_details',
            AGENTS_PAGE_DEFAULTS['show_instructions_in_details'],
        )),
    }


def register_route_frontend_agents(app):
    @app.route('/agents', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_semantic_kernel')
    def agents():
        settings = get_settings()
        public_settings = sanitize_settings_for_user(settings)
        return render_template(
            'agents.html',
            settings=public_settings,
            agents_page_config=build_agents_page_config(public_settings),
        )