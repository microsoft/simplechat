# ReadMe.md

```python
pip freeze > requirements.txt
pip install -r requirements.txt
```

## STEP 1: .env file

Create a .env file to put environment variables in.

### .env file format

```markup
AUTHORITY_URL=<https://login.microsoftonline.us>
AZURE_TENANT_ID=[YOUR TENANT ID]
AZURE_CLIENT_ID=[YOUR CLIENT ID]
AZURE_CLIENT_SECRET=[YOUR SECRET]
API_SCOPE=api://37d7a13d-a5b5-48a6-972f-428cbf316bd9/.default (Example only-From App Registration)
API_BASE_URL=<https://web-8000.azurewebsites.us> (Example only)
USER_ID=457f0fcb-b0b4-4b12-b55c-d4f116a7e111 (OBJECT ID OF USER FROM ENTRA)
```

## STEP 2: TBD
