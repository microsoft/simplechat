# functions_environment.py
"""Environment profile loading helpers for SimpleChat."""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


SIMPLECHAT_ENV_FILE_VARIABLE = "SIMPLECHAT_ENV_FILE"


def resolve_simplechat_env_file(raw_path: Optional[str]) -> Optional[Path]:
    """Resolve the optional selected dotenv file path."""
    selected_path = str(raw_path or "").strip()
    if not selected_path:
        return None

    expanded_path = os.path.expandvars(os.path.expanduser(selected_path))
    return Path(expanded_path)


def load_simplechat_dotenv():
    """Load SimpleChat environment variables from the selected dotenv profile."""
    selected_env_file = resolve_simplechat_env_file(os.getenv(SIMPLECHAT_ENV_FILE_VARIABLE))
    if selected_env_file is None:
        return {
            "mode": "default",
            "path": None,
            "loaded": load_dotenv(),
        }

    if not selected_env_file.exists():
        raise FileNotFoundError(
            f"{SIMPLECHAT_ENV_FILE_VARIABLE} points to a dotenv file that does not exist: {selected_env_file}"
        )
    if not selected_env_file.is_file():
        raise ValueError(f"{SIMPLECHAT_ENV_FILE_VARIABLE} must point to a file: {selected_env_file}")

    return {
        "mode": "selected",
        "path": str(selected_env_file),
        "loaded": load_dotenv(dotenv_path=selected_env_file),
    }

