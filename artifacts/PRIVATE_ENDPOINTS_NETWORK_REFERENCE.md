# Private Endpoint Diagram Reference

Version: **0.261.333**. Deployer: **1.0.34**. Related issue: [#1765](https://github.com/microsoft/simplechat/issues/1765).

Use the [Commercial tables](../docs/guides/enterprise-networking.md#networking-in-azure-commercial) and [Government tables](../docs/guides/enterprise-networking.md#networking-in-azure-government) alongside the Visio sources in this directory. Each section separates fresh script-created networks from the compact existing-network design, with address/usable counts and delegation.

## Fresh Deployment in Either Cloud

Private networking must be enabled, with no existing VNet/subnet IDs supplied.

| Network/Subnet | Address space | Addresses | Azure-usable | Delegation / Notes |
|---|---|---:|---:|---|
| **VNet** | **`10.0.0.0/21`** | **2048** | - | Automatically created |
| `AppServiceIntegration` | `10.0.0.0/24` | 256 | 251 | `Microsoft.Web/serverFarms`; outbound |
| `PrivateEndpoints` | `10.0.2.0/24` | 256 | 251 | All created endpoints, including optional AMPLS |
| **Unallocated** | **`10.0.1.0/24`, `10.0.3.0/24`, `10.0.4.0/22`** | **1536** | - | Future subnets |

## Compact Existing-Network Reference

| Network/Subnet | Address space | Addresses | Azure-usable | Delegation / Notes |
|---|---|---:|---:|---|
| **VNet** | **`10.42.0.0/24`** | **256** | - | Enterprise reference, not script default |
| `snet-app-outbound` | `10.42.0.0/26` | 64 | 59 | `Microsoft.Web/serverFarms` |
| `snet-platform-pe` | `10.42.0.64/26` | 64 | 59 | ACR, Key Vault, optional AMPLS |
| `snet-data-pe` | `10.42.0.128/27` | 32 | 27 | Cosmos, Blob, optional Redis |
| `snet-ai-pe` | `10.42.0.160/27` | 32 | 27 | Supported AI private endpoints |
| `snet-app-inbound-pe` | `10.42.0.192/28` | 16 | 11 | App inbound endpoint |
| **Unallocated** | **`10.42.0.208-10.42.0.255`** | **48** | - | Future growth |

The current scripts accept one integration and one shared endpoint subnet. Existing-network reuse does not automatically distribute endpoints into the reference subnets; segmented placement needs IaC customization or enterprise network tooling. Draw PaaS services outside the VNet and endpoint NICs inside; draw DNS zone links to the VNet rather than nesting zones inside subnets.

Commercial can use Managed Redis and supported Video Indexer private endpoints. Government uses classic Redis and has no Video Indexer PE in the deployed API profile. Both can opt into AMPLS. See the guide's cloud DNS/AMPLS matrix for exact labels. The Visio files remain user-owned and must be updated deliberately to match the selected layout.
