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
API_SCOPE=api://37d7a13d-a5b5-48a6-972f-428cbf316bd9/.default (Example only)
API_BASE_URL=<https://web-8000.azurewebsites.us> (Example only)
UPLOAD_DIRECTORY=./test-documents (Example only)
```

## STEP 2: Create a folder repository of files to upload

./test-documents is a sample folder

## STEP 3: Update the map.csv file and add the following columns (Example only)

```csv
folderName, userId, activeGroupOid
folder1, e81deb4e-839d-40e2-b0fc-020a90ec5f60, 496bd544-817a-4eb2-85da-576a0146b106
folder2, e81deb4e-839d-40e2-b0fc-020a90ec5f60, 496bd544-817a-4eb2-85da-576a0146b106
```

## STEP 3: Run main.py script
