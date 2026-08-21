---

layout: page

title: "Upgrading the Application"

description: "Manual setup reference for upgrading the application."

section: "Deploy & Operate"

permalink: /deploy/manual/upgrading-the-application/

menubar: docs_menu

---



[Back to manual setup hub]({{ '/setup_instructions_manual/' | relative_url }})



## Upgrading the Application



This section covers **native Python Azure App Service** upgrades for the manual deployment path.



Before upgrading a native Python deployment, confirm that the App Service Stack Settings Startup command is set correctly and is not blank.



Deploy and run the `application/single_app` folder in App Service.



Use this Startup command:



```bash

python -m gunicorn -c gunicorn.conf.py app:app

```



For a shorter decision guide that also covers container-based upgrades, see [Upgrade Paths]({{ '/guides/upgrade-paths/' | relative_url }}).



Keeping your Simple Chat application up-to-date involves deploying the newer version of the code. Using **Deployment Slots** is the recommended approach for production environments to ensure zero downtime and provide easy rollback capabilities.



![alt text]({{ '/images/admin_settings-upgrade_available_notification.png' | relative_url }})



### Using Deployment Slots (Recommended for Production/Staging)



1. **Create a Deployment Slot**:



   - In your App Service, go to **Deployment** > **Deployment slots**.

   - Click **+ Add Slot**. Give it a name (e.g., staging).

   - Choose to **clone settings** from the production slot initially.

   - This creates a fully functional, independent instance of your app connected to the same App Service Plan.



2. **Deploy New Version to Staging Slot**:



   - Deploy the updated application code (using VS Code deployment or az webapp deploy) specifically targeting the **staging slot**.



   - **VS Code**: When deploying, VS Code will prompt you to select the target slot (production or staging). Choose staging.



   - **Azure CLI**: Add the --slot staging parameter to your az webapp deploy command:



     ```

     az webapp deploy --resource-group <RG_Name> --name <App_Name> --src-path <Zip_Path> --type zip --slot staging

     ```



3. **Test the Staging Slot**:



   - The staging slot has its own unique URL (e.g., https://my-simplechat-app-staging.azurewebsites.net). Access this URL directly.

   - Thoroughly test all application functionality, including new features and critical paths, in the staging environment. This slot typically uses the same backend resources (Cosmos DB, AI Search, etc.) as production unless configured otherwise (e.g., using slot-specific Application Settings).



4. **Swap Staging to Production**:



   - Once confident the new version in staging is stable, go back to **Deployment slots** in the Azure portal.



   - Click the **Swap** button.



   - Configure the swap:



     - **Source**: staging

     - **Target**: production



   - Azure performs a "warm-up" of the staging slot instance before redirecting production traffic to it. The previous production code is simultaneously moved to the staging slot. This swap happens near-instantly from a user perspective.



   - **Azure CLI Swap Command**:



     ```

     az webapp deployment slot swap --resource-group <RG_Name> --name <App_Name> --slot staging --target-slot production

     ```



5. **Monitor and Rollback (If Necessary)**:



   - Monitor the application closely after the swap using Application Insights and user feedback.

   - If critical issues arise, you can perform another **Swap** operation, this time swapping production (which now contains the problematic code) back with staging (which now contains the previous stable code). This provides an immediate rollback.



### Using Direct Deployment to Production (Simpler, for Dev/Test or Low Impact Changes)



You can deploy directly to the production slot using the same VS Code or Azure CLI methods described in the initial deployment section, simply omitting the --slot parameter or choosing the production slot in VS Code.



> [!WARNING]

>

> Deploying directly to production overwrites the live code. This will cause a brief application restart and offers no immediate rollback capability (you would need to redeploy the previous version). This method is generally **not recommended** for production environments or significant updates due to the downtime and risk involved.



### Automate via CI/CD



For mature development practices, set up a Continuous Integration/Continuous Deployment (CI/CD) pipeline using tools like GitHub Actions or Azure DevOps Pipelines. A typical pipeline would:



1. Trigger on code commits/merges to specific branches (e.g., main, release/*).

2. Build the application artifact (e.g., create the zip file).

3. Deploy the artifact to the staging slot.

4. (Optional) Run automated tests against the staging slot.

5. Require manual approval (or automatically trigger based on test results) to perform the swap operation to production.
