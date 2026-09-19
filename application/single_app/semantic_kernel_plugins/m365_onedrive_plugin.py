# m365_onedrive_plugin.py
"""Delegated OneDrive file retrieval and conversation evidence."""

import functions_m365_retrieval as retrieval


class M365OneDrivePlugin(retrieval.M365FilePlugin):
    ACTION_TYPE = "m365_onedrive"
