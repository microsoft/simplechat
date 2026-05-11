---
layout: showcase-page
title: "Getting Started with Simple Chat"
permalink: /tutorials/getting_started/
menubar: docs_menu
accent: blue
eyebrow: "Tutorial 1"
description: "Deploy the app, enable a workspace, upload one document, and ask the first retrieval-backed question."
hero_icons:
  - bi-rocket-takeoff
  - bi-cloud-arrow-up
  - bi-chat-left-text
hero_pills:
  - First deployment
  - First workspace
  - First grounded conversation
hero_links:
  - label: Deployment reference
    url: /setup_instructions/
    style: primary
  - label: Tutorial index
    url: /tutorials/
    style: secondary
show_nav: true
nav_links:
   next:
      title: Create Your First Agent
      url: /tutorials/first_agent/
---

This tutorial is the shortest useful path into the product. You will deploy Simple Chat, wire the essentials, add one document, and prove the retrieval loop works.

<section class="latest-release-card-grid">
   <article class="latest-release-card">
      <div class="latest-release-card-icon"><i class="bi bi-check2-square"></i></div>
      <h2>You will do</h2>
      <p>Deploy the app, enable a workspace, upload a document, and run a cited conversation against your own content.</p>
   </article>
   <article class="latest-release-card">
      <div class="latest-release-card-icon"><i class="bi bi-list-task"></i></div>
      <h2>You need</h2>
      <p>An Azure subscription with resource permissions, basic Azure familiarity, and a sample document you can safely upload.</p>
   </article>
   <article class="latest-release-card">
      <div class="latest-release-card-icon"><i class="bi bi-arrow-right-circle"></i></div>
      <h2>After this</h2>
      <p>Move on to agents once the base chat and retrieval loop is working end to end.</p>
   </article>
</section>

## Step 1: Deploy Simple Chat

Simple Chat offers multiple deployment options. For getting started, we recommend using the automated deployment:

### Option A: Azure Developer CLI (Recommended for beginners)

The fastest way to get started is with Azure Developer CLI:

1. Install Azure Developer CLI if you haven't already
2. Clone the Simple Chat repository
3. Navigate to the project folder
4. Run the deployment command

```bash
# Clone the repository
git clone https://github.com/microsoft/simplechat.git
cd simplechat

# Deploy with azd
azd up
```

Follow the prompts to select your subscription, region, and provide required configuration.

### Option B: Other Deployment Methods

For more deployment options, see our [deployment reference](../reference/deploy/index.md).

## Step 2: Initial Configuration

After deployment completes:

1. **Open the application** using the URL provided in the deployment output
2. **Sign in** with your Azure Active Directory account
3. **Access Admin Settings** (if you have admin role assigned)

### Configure Basic Settings

In the Admin Settings page:

1. **General Section**: 
   - Set your application title
   - Upload a custom logo (optional)
   
2. **GPT Section**:
   - Verify your Azure OpenAI connection
   - Test the connection using the "Test" button
   - Select your active model deployment

3. **Embeddings Section**:
   - Verify your embeddings endpoint
   - Test the connection

## Step 3: Enable Your First Workspace

1. In Admin Settings, navigate to **Workspaces**
2. Enable **"Your Workspace"** - this allows personal document uploads
3. Click **Save Configuration**

## Step 4: Upload Your First Document

Now let's add some content to work with:

1. **Navigate to "Your Workspace"** from the main menu
2. **Click "Add Documents"**
3. **Select a file** from your computer:
   - Try a PDF with interesting content
   - Word documents work great too
   - Text files are supported
4. **Upload the document** and wait for processing

You'll see the document appear in your workspace with processing status indicators.

## Step 5: Start Your First RAG Conversation

Now for the exciting part - chatting with your document:

1. **Go to "Chat"** from the main menu
2. **Select your workspace** from the workspace dropdown
3. **Ask a question** about your document content

Try questions like:
- "What are the main topics covered in this document?"
- "Can you summarize the key points?"
- "What does the document say about [specific topic]?"

## Step 6: Explore Citations

Notice how Simple Chat provides citations showing where information came from:

- **Standard citations** show which document and chunk
- **Enhanced citations** (if enabled) can link directly to pages

## What You've Accomplished

Congratulations! You've successfully:
✅ Deployed Simple Chat to Azure  
✅ Configured basic settings  
✅ Uploaded your first document  
✅ Had an AI conversation grounded in your data  
✅ Experienced Retrieval-Augmented Generation (RAG)

## Next Steps

Now that you're up and running, explore more features:

- [Create Your First Agent](first_agent) - Build a specialized AI assistant
- [Upload More Documents](uploading_documents) - Build a larger knowledge base
- [Document Classification](classifying_documents) - Organize your content

Or dive into specific tasks with our [how-to guides](../how-to/).

## Troubleshooting

**Document not uploading?**
- Check file size limits in Admin Settings
- Ensure file types are supported
- Look at File Processing Logs (if enabled)

**Can't access admin settings?**
- Verify you have the Admin role assigned in Azure AD
- Check your app registration configuration

**Chat not finding document content?**
- Verify the document finished processing (no error status)
- Try more specific questions
- Check your embeddings configuration

For more help, see our [FAQ](../reference/faqs) or [how-to guides](../how-to/).

---

*Next: [Create Your First Agent](first_agent) →*
