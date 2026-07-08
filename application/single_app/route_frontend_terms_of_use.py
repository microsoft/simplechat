# route_frontend_terms_of_use.py

import logging

from config import *
from functions_appinsights import log_event
from functions_terms_of_use import (
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


def register_route_frontend_terms_of_use(bp):
    @bp.route('/terms-of-use', methods=['GET'])
    @swagger_route(security=get_auth_security())
    def terms_of_use():
        settings = get_settings() or {}
        terms_config = get_terms_of_use_config(settings)
        return_url = normalize_terms_of_use_return_path(
            request.args.get('next'),
            fallback=url_for('public_app.index'),
        )

        if not terms_config["enabled"]:
            return redirect(return_url)

        user_id = get_current_user_id()
        if user_id and has_terms_of_use_acceptance(settings, user_id=user_id):
            return redirect(return_url)

        public_settings = sanitize_settings_for_user(settings)
        return render_template(
            'terms_of_use.html',
            app_settings=public_settings,
            terms=terms_config,
            return_url=return_url,
            is_authenticated=bool(user_id),
        )

    @bp.route('/terms-of-use/accept', methods=['POST'])
    @swagger_route(security=get_auth_security())
    def accept_terms_of_use():
        settings = get_settings() or {}
        terms_config = get_terms_of_use_config(settings)
        return_url = normalize_terms_of_use_return_path(
            request.form.get('return_url'),
            fallback=url_for('public_app.index'),
        )

        if not terms_config["enabled"]:
            return redirect(return_url)

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
