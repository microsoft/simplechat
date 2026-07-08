# route_frontend_terms_of_use.py

import logging

from flask import redirect, render_template, request, session, url_for

from functions_appinsights import log_event
from functions_terms_of_use import (
    TERMS_OF_USE_RETURN_PATH_SESSION_KEY,
    get_terms_of_use_config,
    has_terms_of_use_acceptance,
    mark_pre_auth_terms_of_use_acceptance,
    normalize_terms_of_use_return_path,
    record_terms_of_use_acceptance,
    record_terms_of_use_decline,
)
from functions_authentication import get_current_user_id
from functions_settings import get_settings, sanitize_settings_for_user
from swagger_wrapper import get_auth_security, swagger_route


def _store_terms_of_use_return_path(raw_return_path):
    """Store a local-only post-acceptance return path in the server-side session."""
    return_path = normalize_terms_of_use_return_path(
        raw_return_path,
        fallback=url_for('public_app.index'),
    )
    session[TERMS_OF_USE_RETURN_PATH_SESSION_KEY] = return_path
    session.modified = True
    return return_path


def _pop_terms_of_use_return_path():
    """Resolve and clear the local-only return path saved during the interstitial GET."""
    return_path = normalize_terms_of_use_return_path(
        session.pop(TERMS_OF_USE_RETURN_PATH_SESSION_KEY, None),
        fallback=url_for('public_app.index'),
    )
    session.modified = True
    return return_path


def register_route_frontend_terms_of_use(bp):
    @bp.route('/terms-of-use', methods=['GET'])
    @swagger_route(security=get_auth_security())
    def terms_of_use():
        settings = get_settings() or {}
        terms_config = get_terms_of_use_config(settings)
        _store_terms_of_use_return_path(request.args.get('next'))

        if not terms_config["enabled"]:
            return redirect(url_for('public_app.index'))

        user_id = get_current_user_id()
        if user_id and has_terms_of_use_acceptance(settings, user_id=user_id):
            return redirect(url_for('public_app.index'))

        public_settings = sanitize_settings_for_user(settings)
        return render_template(
            'terms_of_use.html',
            app_settings=public_settings,
            terms=terms_config,
            is_authenticated=bool(user_id),
        )

    @bp.route('/terms-of-use/accept', methods=['POST'])
    @swagger_route(security=get_auth_security())
    def accept_terms_of_use():
        settings = get_settings() or {}
        terms_config = get_terms_of_use_config(settings)
        return_url = _pop_terms_of_use_return_path()

        if not terms_config["enabled"]:
            return redirect(url_for('public_app.index'))

        user_id = get_current_user_id()
        if user_id:
            record_terms_of_use_acceptance(
                user_id=user_id,
                settings=settings,
                source="post_auth",
            )
            return redirect(return_url)

        mark_pre_auth_terms_of_use_acceptance(settings)
        return redirect(url_for('frontend_authentication.login'))

    @bp.route('/terms-of-use/decline', methods=['POST'])
    @swagger_route(security=get_auth_security())
    def decline_terms_of_use():
        settings = get_settings() or {}
        terms_config = get_terms_of_use_config(settings)
        user_id = get_current_user_id()

        if user_id:
            try:
                record_terms_of_use_decline(
                    user_id=user_id,
                    settings=settings,
                    source="post_auth",
                )
            except Exception as decline_log_error:
                log_event(
                    "[TermsOfUse] Decline audit logging failed.",
                    extra={
                        "user_id": user_id,
                        "error": str(decline_log_error),
                    },
                    level=logging.ERROR,
                    exceptionTraceback=True,
                )

        redirect_url = terms_config["decline_redirect_url"]
        session.clear()
        return redirect(redirect_url)
