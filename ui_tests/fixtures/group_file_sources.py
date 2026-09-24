# group_file_sources.py
"""
Closed M5B group file source HTTP fixtures for the real production V2 SPA.
Version: 0.261.147
Implemented in: 0.261.147

The fixture serves the immutable `/api/groups/<group_id>/file-sources[...]` family
and the `/api/groups/<group_id>/file-source-options` route, and injects the
`file_source_management` context hint that gates create plus the per-row
`source_actions` projection that gates edit, sync, delete and test. It never permits
a personal-scope read: the shared base fixture records any `/api/user/*`, personal
`/api/file-sync/personal/*` request, or `?agent_scope=personal` request from a group
page as unexpected rather than answering it, so a group file source surface that
leaked into personal reads would fail the run. It never falls back to personal
behaviour: file source reads use the same manager roles as writes -- Owner, Admin and
DocumentManager -- so an ordinary member is refused with 403 on every file source
route, which the section renders as its unavailable Classic hand-off rather than a
personal file-sync read.

group-a is a manager workspace carrying three file sources: a fully editable SMB
share whose stored password proves masking survives an edit, a withheld one whose
empty `source_actions` hides every row control, and one bound to a reusable group
identity so the list row shows the identity name and the options picker offers it.
group-a also carries a File Sync identity so the options `eligible_identity_ids`
surface it. group-b is an ordinary member: file sources are manager-only, so its
section is unavailable and its file source routes answer 403. Writes carry
`expected_config_revision` in the JSON body, secrets stay masked server-side, and the
delete body carries the documents choice with its counts.
"""

import pytest

from ui_tests.fixtures.group_workspace import (  # noqa: F401
    GroupWorkspaceFixture, group_file_source, group_identity,
)


EDITABLE_SOURCE_ID = "group-a-editable-source"
WITHHELD_SOURCE_ID = "group-a-withheld-source"
IDENTITY_SOURCE_ID = "group-a-identity-source"
FILE_SYNC_IDENTITY_ID = "group-a-file-sync-identity"


class GroupFileSourcesFixture(GroupWorkspaceFixture):
    """A small scripted file source boundary; no live File Sync engine, no live Key Vault."""

    def __init__(self, page):
        super().__init__(page)
        self.active_group = "group-a"
        # group-a: a manager workspace. Recomputing the context from the same Owner policy carries the
        # full file_source_management hint, exactly like the identity fixture recomputes its policy.
        self.set_file_source_policy("group-a", role="Owner", status="active")
        # A File Sync identity so the options picker offers a reusable credential and the
        # identity-bound source's list row can name it. It is appended to the base identities rather
        # than reseeded, so the base action-usage identity is left intact.
        self.native_identities.setdefault("group-a", []).insert(0, group_identity(
            "group-a", FILE_SYNC_IDENTITY_ID, "Archive file share account",
            usage=("file_sync",), auth_type="username_password", secret_stored=True,
            username="svc-archive", domain="CORP", source_types=["smb", "generic"],
        ))
        self.native_identity_revisions[("group-a", FILE_SYNC_IDENTITY_ID)] = 1
        self._seed_file_sources("group-a", [
            # Fully editable: an inline stored secret proves an edit keeps it masked, and its
            # source_actions carry every operation so a manager reaches every control.
            group_file_source("group-a", EDITABLE_SOURCE_ID, "Quarterly reports share",
                              source_type="smb", auth_type="username_password",
                              username="svc-reports", domain="CORP", secret_stored=True,
                              connection={"unc_path": "\\\\files.example.test\\reports"}),
            # Withheld: the workspace advertises the operations, but this row's empty source_actions
            # hide edit, sync and delete. An explicit defensive case, kept so the per-row gate is
            # proven, not merely the workspace-level hint.
            group_file_source("group-a", WITHHELD_SOURCE_ID, "Locked archive share",
                              source_type="smb", secret_stored=True, actions=()),
            # Bound to a reusable group identity: the list row shows the identity name and the editor
            # opens in identity mode.
            group_file_source("group-a", IDENTITY_SOURCE_ID, "Shared drive via identity",
                              source_type="smb", identity_id=FILE_SYNC_IDENTITY_ID,
                              identity_name="Archive file share account", secret_stored=False,
                              connection={"unc_path": "\\\\files.example.test\\shared"}),
        ])
        # group-b: an ordinary member. File sources are manager-only, so the section is unavailable
        # and every file source route answers 403. The base already seeds one source for it and
        # models the member role; the seeded row is never served, which is exactly the unavailable
        # path the section must take rather than reading a personal file source.
        self.set_file_source_policy("group-b", role="User", status="active")


@pytest.fixture
def group_file_sources_ui(page):
    fixture = GroupFileSourcesFixture(page)
    yield fixture
    fixture.assert_clean()
