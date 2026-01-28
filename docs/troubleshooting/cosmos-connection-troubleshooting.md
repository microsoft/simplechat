## FAQ: Cosmos DB Resource Not Found and Authorization Errors

### What do these errors look like?

Common log messages include:

* `CosmosResourceNotFoundError: Resource Not Found`
* `CosmosHttpResponseError: (Forbidden) Request cannot be authorized by AAD token in data plane`

These typically appear during application startup when Simple Chat attempts to read or create Cosmos DB containers.

---

### What is the most common cause?

The most common cause is that the application is configured to use Managed Identity for Cosmos DB access, but the Managed Identity has not been granted Cosmos data plane permissions.

Without data plane role assignments, the app can authenticate but cannot create or read containers. This results in Resource Not Found or Forbidden errors.

---

### How do I quickly verify whether this is a permissions issue?

Switch the application temporarily to use the Cosmos primary key instead of Managed Identity.

1. Add an environment variable
   `AZURE_COSMOS_KEY`
   with the Cosmos DB primary key value.

2. Stop and start the App Service.

3. Wait four to eight minutes for configuration propagation.

If the application connects successfully after this change, the issue is confirmed to be Managed Identity permissions.

---

### How do I properly configure Managed Identity permissions?

Run the permissions setup script included with Simple Chat:

```
/deployers/bicep/CosmosDB-post-deploy-perms.sh
```

This script grants the App Service Managed Identity the required Cosmos DB data plane roles, including container creation permissions.

After running the script, remove the `AZURE_COSMOS_KEY` variable and restart the App Service to return to Managed Identity authentication.

---

### Could this be a networking issue instead of permissions?

Yes. Resource Not Found errors can also occur if the application cannot reach Cosmos DB over the network. Common networking causes include:

* Cosmos DB firewall enabled without allowing the App Service outbound IPs
* Private Endpoints enabled with incorrect DNS resolution
* VNet integration misconfigured on the App Service

If switching to the Cosmos key does not resolve the issue, inspect network connectivity next.

---

### Why does the error mention "Resource Not Found" when the container exists?

When using AAD authentication without proper data plane access, Cosmos DB returns a Resource Not Found response even if the container exists. This is a known behavior to prevent information disclosure.

---

### Why does this usually appear on first deployment?

On first deployment, Simple Chat attempts to create required containers automatically. Container creation requires additional data plane permissions. If Managed Identity permissions were not assigned yet, container creation fails and produces these errors.

---

### What is the recommended deployment order?

1. Deploy Cosmos DB.
2. Deploy App Service with Managed Identity enabled.
3. Run `CosmosDB-post-deploy-perms.sh`.
4. Restart the App Service.

Following this order avoids both Resource Not Found and Forbidden errors.

---

### Where can I learn more about Cosmos native RBAC?

Microsoft documentation:
[https://aka.ms/cosmos-native-rbac](https://aka.ms/cosmos-native-rbac)