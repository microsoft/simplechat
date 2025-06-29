# Bulkloader

The Bulkloader application is a command-line utility designed to streamline the process of uploading large batches of files into your system. By leveraging a mapping CSV file, it allows administrators or power users to efficiently associate folders of files with specific users and groups, automating what would otherwise be a time-consuming manual process. This tool is especially useful for initial data migrations, onboarding new users with pre-existing documents, or synchronizing large repositories of files into the platform.

```python
pip freeze > requirements.txt
pip install -r requirements.txt
```

## STEP 1: .env file

Rename a example.env file to .env and update variables.

## STEP 2: Create a folder repository of files to upload

## STEP 3: Update the map.csv file and add the following columns (Example only)

```csv
folderName, userId, activeGroupOid
folder1, e81deb4e-839d-40e2-b0fc-020a90ec5f60, 496bd544-817a-4eb2-85da-576a0146b106
folder2, e81deb4e-839d-40e2-b0fc-020a90ec5f60, 496bd544-817a-4eb2-85da-576a0146b106
```

## STEP 3: Run main.py script
