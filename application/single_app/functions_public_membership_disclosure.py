# functions_public_membership_disclosure.py
"""What each viewer may see of a public workspace's members, decided on the server.

Classic showed every member's email to every member. The M10A decision tightens
this (decision 18, the M7A "never disclose what a role mustn't see" rule): only the
Owner and Admins see members' email addresses, and a DocumentManager viewer sees
names and roles but not emails.

The redaction is applied here, on the server, before a member list leaves the
route, so it can never be undone on the client. It is a behaviour change from
classic, and is deliberate.

``project_member_rows(rows, viewer_role)`` returns fresh rows: for an Owner or Admin
viewer every field is kept; for any other viewer each row's ``email`` is blanked.
Only ``email`` is withheld; a member's ``userId``, ``displayName``, ``role`` and
``member_actions`` are the names and roles the decision keeps visible. The input
rows are never mutated.

This module is pure: it reads only the values it is given.
"""

PUBLIC_MEMBERSHIP_EMAIL_VIEWER_ROLES = ("Owner", "Admin")


def viewer_may_see_member_emails(viewer_role):
    """Whether a viewer holding ``viewer_role`` may see members' email addresses."""
    return viewer_role in PUBLIC_MEMBERSHIP_EMAIL_VIEWER_ROLES


def project_member_rows(rows, viewer_role):
    """Return copies of ``rows`` with each email withheld unless the viewer may see it."""
    keep_emails = viewer_may_see_member_emails(viewer_role)
    projected = []
    for row in rows:
        copy = dict(row)
        if not keep_emails:
            copy["email"] = ""
        projected.append(copy)
    return projected


__all__ = [
    "PUBLIC_MEMBERSHIP_EMAIL_VIEWER_ROLES",
    "project_member_rows",
    "viewer_may_see_member_emails",
]
