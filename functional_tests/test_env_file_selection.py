# test_env_file_selection.py
#!/usr/bin/env python3
"""
Functional test for selectable SimpleChat dotenv profiles.
Version: 0.250.060
Implemented in: 0.250.060

This test ensures SIMPLECHAT_ENV_FILE can select an alternate dotenv file while
preserving the existing default .env loading behavior when the selector is not set.
"""

import os
import sys
import tempfile
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))

import functions_environment  # noqa: E402


def restore_env_var(name, original_value):
    """Restore an environment variable after a test."""
    if original_value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = original_value


def test_default_dotenv_loading():
    """Validate default load_dotenv() behavior when SIMPLECHAT_ENV_FILE is unset."""
    calls = []
    original_env_value = os.environ.get(functions_environment.SIMPLECHAT_ENV_FILE_VARIABLE)
    original_load_dotenv = functions_environment.load_dotenv

    def fake_load_dotenv(*args, **kwargs):
        calls.append({
            "args": args,
            "kwargs": kwargs,
        })
        return True

    os.environ.pop(functions_environment.SIMPLECHAT_ENV_FILE_VARIABLE, None)
    functions_environment.load_dotenv = fake_load_dotenv

    try:
        result = functions_environment.load_simplechat_dotenv()
    finally:
        functions_environment.load_dotenv = original_load_dotenv
        restore_env_var(functions_environment.SIMPLECHAT_ENV_FILE_VARIABLE, original_env_value)

    assert result["mode"] == "default"
    assert result["path"] is None
    assert result["loaded"] is True
    assert calls == [{"args": (), "kwargs": {}}]


def test_selected_dotenv_loading():
    """Validate selected dotenv file loading when SIMPLECHAT_ENV_FILE is set."""
    calls = []
    original_env_value = os.environ.get(functions_environment.SIMPLECHAT_ENV_FILE_VARIABLE)
    original_load_dotenv = functions_environment.load_dotenv

    def fake_load_dotenv(*args, **kwargs):
        calls.append({
            "args": args,
            "kwargs": kwargs,
        })
        return True

    with tempfile.TemporaryDirectory() as temp_dir:
        selected_env_file = Path(temp_dir) / ".env.simplechatdemo"
        selected_env_file.write_text("SIMPLECHAT_TEST_VALUE=selected\n", encoding="utf-8")
        os.environ[functions_environment.SIMPLECHAT_ENV_FILE_VARIABLE] = str(selected_env_file)
        functions_environment.load_dotenv = fake_load_dotenv

        try:
            result = functions_environment.load_simplechat_dotenv()
        finally:
            functions_environment.load_dotenv = original_load_dotenv
            restore_env_var(functions_environment.SIMPLECHAT_ENV_FILE_VARIABLE, original_env_value)

        assert result["mode"] == "selected"
        assert result["path"] == str(selected_env_file)
        assert result["loaded"] is True
        assert calls == [{"args": (), "kwargs": {"dotenv_path": selected_env_file}}]


def test_missing_selected_dotenv_raises():
    """Validate missing selected dotenv files fail clearly."""
    original_env_value = os.environ.get(functions_environment.SIMPLECHAT_ENV_FILE_VARIABLE)
    with tempfile.TemporaryDirectory() as temp_dir:
        missing_env_file = Path(temp_dir) / ".env.missing"
        os.environ[functions_environment.SIMPLECHAT_ENV_FILE_VARIABLE] = str(missing_env_file)

        try:
            functions_environment.load_simplechat_dotenv()
        except FileNotFoundError as ex:
            assert functions_environment.SIMPLECHAT_ENV_FILE_VARIABLE in str(ex)
            assert str(missing_env_file) in str(ex)
        else:
            raise AssertionError("Expected missing SIMPLECHAT_ENV_FILE target to raise FileNotFoundError.")
        finally:
            restore_env_var(functions_environment.SIMPLECHAT_ENV_FILE_VARIABLE, original_env_value)


if __name__ == "__main__":
    try:
        test_default_dotenv_loading()
        test_selected_dotenv_loading()
        test_missing_selected_dotenv_raises()
        success = True
    except Exception as ex:
        print(f"Selectable SimpleChat dotenv profile test failed: {ex}")
        import traceback

        traceback.print_exc()
        success = False
    sys.exit(0 if success else 1)
