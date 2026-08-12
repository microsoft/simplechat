# Selectable Environment Files

## Header Information

**Feature**: Selectable SimpleChat dotenv profiles  
**Overview**: SimpleChat can load an alternate dotenv file for local development when `SIMPLECHAT_ENV_FILE` is set, while preserving the existing default `.env` behavior when it is not set.  
**Implemented in version**: **0.250.060**  
**Dependencies**: `python-dotenv`, `application\single_app\functions_environment.py`, `application\single_app\config.py`

## Technical Specifications

### Architecture Overview

SimpleChat now centralizes dotenv profile loading in `functions_environment.py`.

At startup, `config.py` calls `load_simplechat_dotenv()` before reading application settings:

1. If `SIMPLECHAT_ENV_FILE` is not set, SimpleChat runs the existing `load_dotenv()` behavior.
2. If `SIMPLECHAT_ENV_FILE` is set, SimpleChat validates that the selected path exists and is a file.
3. The selected file is loaded with `load_dotenv(dotenv_path=...)`.
4. The default `.env` file is not loaded when a selected profile is supplied.

`python-dotenv` keeps the existing precedence behavior: environment variables already present in the process are not overwritten unless the application explicitly changes that behavior in the future.

### Configuration Options

| Setting | Required | Purpose |
| --- | --- | --- |
| `SIMPLECHAT_ENV_FILE` | No | Absolute or relative path to the dotenv profile to load instead of the default `.env`. |

### File Structure

| File | Purpose |
| --- | --- |
| `application\single_app\functions_environment.py` | Dotenv profile selection and validation. |
| `application\single_app\config.py` | Calls the profile loader before reading environment-backed settings. |
| `.gitignore` | Ignores `.env` and `.env.*` local profile files while allowing `.env.example`. |
| `functional_tests\test_env_file_selection.py` | Regression coverage for default, selected, and missing profile behavior. |

## Usage Instructions

### Default Behavior

If no selector is set, continue using the existing `.env` workflow:

```powershell
cd C:\Repos\simplechatmsft
python application\single_app\app.py
```

### Named Local Profiles

Keep local profiles out of source control. For example:

```text
C:\Repos\simplechatmsft\.env
C:\Repos\simplechatmsft\.env.mag
C:\Repos\simplechatmsft\.env.simplechatdemo
```

or outside the repo:

```text
C:\Users\<alias>\.simplechat\env\mag.env
C:\Users\<alias>\.simplechat\env\simplechatdemo.env
```

Start SimpleChat with a selected profile:

```powershell
$env:SIMPLECHAT_ENV_FILE = "C:\Repos\simplechatmsft\.env.simplechatdemo"
python application\single_app\app.py
```

Switch back to the default `.env` behavior:

```powershell
Remove-Item Env:\SIMPLECHAT_ENV_FILE
python application\single_app\app.py
```

### Safety Notes

- Do not commit `.env`, `.env.*`, or exported App Service settings.
- Prefer fake or non-production values for local testing whenever possible.
- If `SIMPLECHAT_ENV_FILE` points to a missing file, startup fails clearly instead of silently falling back to another tenant profile.

## Testing and Validation

### Test Coverage

`functional_tests\test_env_file_selection.py` validates:

- Default `load_dotenv()` behavior when `SIMPLECHAT_ENV_FILE` is unset.
- Selected dotenv profile loading when `SIMPLECHAT_ENV_FILE` is set.
- Clear `FileNotFoundError` behavior for missing selected profiles.

### Known Limitations

- `SIMPLECHAT_ENV_FILE` selects a local process dotenv profile only; it does not change Azure App Service configuration.
- Existing process-level environment variables still take precedence over dotenv values according to `python-dotenv` defaults.
