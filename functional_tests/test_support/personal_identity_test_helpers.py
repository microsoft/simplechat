# personal_identity_test_helpers.py
"""Shared request helpers for native personal identity API tests."""

LIST_PATH = "/api/user/identities"


def as_user(env, user_id, roles=("User",)):
    with env.client.session_transaction() as state:
        state["user"] = {"oid": user_id, "roles": list(roles)}


def create_identity(env, *, user_id="owner", credentials=None, **fields):
    as_user(env, user_id)
    response = env.client.post(LIST_PATH, json={
        "name": "Personal credential", "usage_contexts": ["action"],
        "credentials": credentials or {"auth_type": "api_key", "secret": "fixture-only-secret"},
        **fields,
    })
    if response.status_code != 201:
        raise AssertionError(response.get_data(as_text=True))
    return response.get_json()["identity"]
