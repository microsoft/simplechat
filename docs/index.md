# Simple Chat Documentation

Welcome to the Simple Chat Application documentation. This documentation is organized following the [Diátaxis framework](https://diataxis.fr/) to help you find exactly what you need, when you need it.

## Quick Start

New to Simple Chat? Start here:
- [Getting Started Tutorial](tutorials/getting_started) - Your first steps with Simple Chat
- [Deploy Simple Chat](reference/deploy/) - Choose your deployment method

## Documentation Structure

Our documentation is organized into four types to serve different needs:

### 📚 [Tutorials](tutorials/) - *Learn by doing*
**Learning-oriented lessons that get you started**

Perfect when you're new to Simple Chat and want to learn through guided, hands-on experiences.

- [Getting Started](tutorials/getting_started) - Set up and run your first chat
- [Create Your First Agent](tutorials/first_agent) - Build a custom AI agent
- [Upload and Use Documents](tutorials/uploading_documents) - Work with your own data
- [Classify Documents](tutorials/classifying_documents) - Organize your content

### 🎯 [How-to Guides](how-to/) - *Solve specific problems*
**Goal-oriented directions for common tasks**

Use these when you have a specific goal and need step-by-step instructions.

- [Add Documents](how-to/add_documents) - Upload and manage your files
- [Create Custom Agents](how-to/create_agents) - Build specialized AI assistants
- [Scale on Azure](how-to/scaling_on_azure) - Handle increased load and usage
- [Use Managed Identity](how-to/use_managed_identity) - Secure Azure integration
- [Enterprise Networking](how-to/enterprise_networking) - Configure for enterprise environments

### 📖 [Reference](reference/) - *Look up information*
**Information-oriented technical descriptions**

Use these when you need precise, factual information about Simple Chat's features and configuration.

- [Admin Configuration](reference/admin_configuration) - Complete admin settings reference
- [API Reference](reference/api_reference) - Programmatic interface documentation
- [Features](reference/features) - Complete feature catalog
- **Deployment Options:**
  - [Azure Developer CLI](reference/deploy/azd-cli_deploy)
  - [Bicep Templates](reference/deploy/bicep_deploy)
  - [Terraform](reference/deploy/terraform_deploy)
  - [Manual Deployment](reference/deploy/manual_deploy)

### 💡 [Explanation](explanation/) - *Understand concepts*
**Understanding-oriented discussions of key topics**

Use these when you need to understand the "why" behind Simple Chat's design and architecture.

- [Architecture](explanation/architecture) - System design and components
- [Design Principles](explanation/design_principles) - Philosophy behind Simple Chat
- [Feature Guidance](explanation/feature_guidance) - When and how to use features
- **Scenarios:**
  - [Agent Examples](explanation/scenarios/agents/) - Real-world agent use cases
  - [Workspace Examples](explanation/scenarios/workspaces/) - Organization patterns
- **Version History:**
  - [Features by Version](explanation/features/) - Feature evolution
  - [Fixes by Version](explanation/fixes/) - Bug fix history

---

## What is Simple Chat?

The **Simple Chat Application** is a comprehensive, web-based platform designed to facilitate secure and context-aware interactions with generative AI models, specifically leveraging **Azure OpenAI**. Its central feature is **Retrieval-Augmented Generation (RAG)**, which significantly enhances AI interactions by allowing users to ground conversations in their own data.

### Key Capabilities

- **💬 AI Chat**: Interact with Azure OpenAI's GPT models
- **📁 Document Integration**: Upload and chat with your documents using RAG
- **👥 Group Collaboration**: Share knowledge across teams and workspaces
- **🔒 Enterprise Security**: Azure AD integration with role-based access control
- **🎨 Customization**: Optional features like image generation, content safety, and more

### Getting Help

- **New users**: Start with [tutorials](tutorials/)
- **Specific tasks**: Check [how-to guides](how-to/)
- **Configuration details**: See [reference](reference/)
- **Understanding concepts**: Read [explanation](explanation/)

---

*This documentation follows the [Diátaxis framework](https://diataxis.fr/) for systematic technical documentation.*