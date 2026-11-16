# functions_interaction_csrf.py
"""Session-local CSRF tokens shared by interactive task decisions."""

import secrets

from flask import session


def get_interaction_csrf_token():
    if not session.get("action_credentials_csrf_token"):
        session["action_credentials_csrf_token"] = secrets.token_urlsafe(32)
    return session["action_credentials_csrf_token"]
