# Simple Chat - Bulk Uploader

Tool used to assist users with the bulk loading of documents into a group for use within Simple Chat application.

```python
pip freeze > requirements.txt
pip install -r requirements.txt
```

## STEP 1: Create a Service Principal for bulk upload
- You will need a Service Principal (app registration) and password for bulk upload authentication.
- Use the Client ID and Password in the .env (described below).
- The bulk upload Service Principal will need the ExternalAPI app role (which is a app role on the app service app registration)

## STEP 2: Disable the App Service Authentication
- Temporarily disable the App Service Authentication during the bulk file upload.

## STEP 3: .env file

Create a .env file to put environment variables in.

### .env file format

```markup
AUTHORITY_URL=<https://login.microsoftonline.us>
AZURE_TENANT_ID=[YOUR TENANT ID]
AZURE_CLIENT_ID=[YOUR CLIENT ID]
AZURE_CLIENT_SECRET=[YOUR SECRET]
API_SCOPE=api://37d7a13d-a5b5-48a6-972f-428cbf316bd9/.default (Example only)
API_BASE_URL=<https://web-8000.azurewebsites.us> (Example only)
UPLOAD_DIRECTORY=./test-documents (Example only)
```

## STEP 4: Create a folder repository of files to upload

./test-documents is a sample folder

## STEP 5: Update the map.csv file and add the following columns (Example only)

```csv
folderName, userId, activeGroupOid
folder1, e81deb4e-839d-40e2-b0fc-020a90ec5f60, 496bd544-817a-4eb2-85da-576a0146b106
folder2, e81deb4e-839d-40e2-b0fc-020a90ec5f60, 496bd544-817a-4eb2-85da-576a0146b106
```

## STEP 6: Run main.py script


## STEP 7: Run main.py script