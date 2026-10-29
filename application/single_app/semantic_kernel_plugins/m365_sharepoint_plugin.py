# m365_sharepoint_plugin.py
"""Delegated SPO document-library retrieval and conversation evidence."""

import functions_m365_retrieval as retrieval


class M365SharePointPlugin(retrieval.M365FilePlugin):
    ACTION_TYPE = "m365_sharepoint"
