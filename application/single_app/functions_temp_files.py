# functions_temp_files.py
"""Writable scratch locations for short-lived server-side files.

Import-independent on purpose: renderers and download streams use it without
pulling in configuration or Azure clients.
"""

import os


SC_TEMP_FILES_DIR = '/sc-temp-files'


def scratch_file_dir():
    """Return the container's dedicated scratch directory, or None for the platform default.

    Never the process working directory. The container runs as a non-root user, and
    the application code directory is not guaranteed to be writable by that user.
    """
    if os.path.isdir(SC_TEMP_FILES_DIR) and os.access(SC_TEMP_FILES_DIR, os.W_OK | os.X_OK):
        return SC_TEMP_FILES_DIR
    return None
