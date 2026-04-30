---
layout: showcase-page
title: "Document Classification Tutorial"
permalink: /tutorials/classifying_documents/
menubar: docs_menu
accent: emerald
eyebrow: "Tutorial 4"
description: "Build a classification scheme that helps users organize content, filter retrieval, and support real workflows instead of just adding labels for decoration."
hero_icons:
  - bi-tags
  - bi-funnel
  - bi-grid-3x3-gap
hero_pills:
  - Better organization
  - Better filtering
  - Better context for AI responses
hero_links:
  - label: Tutorial index
    url: /tutorials/
    style: primary
  - label: Admin configuration
    url: /admin_configuration/
    style: secondary
show_nav: true
nav_links:
   prev:
      title: Uploading and Managing Documents
      url: /tutorials/uploading_documents/
   next:
      title: How-to Guides
      url: /how-to/
---

Classification works when the categories reflect how your organization actually handles content. This tutorial focuses on making the labels operational, not decorative.

<section class="latest-release-card-grid">
   <article class="latest-release-card">
      <div class="latest-release-card-icon"><i class="bi bi-list-check"></i></div>
      <h2>Plan the scheme</h2>
      <p>Choose categories that match departments, document types, sensitivity, or project flows your users already recognize.</p>
   </article>
   <article class="latest-release-card">
      <div class="latest-release-card-icon"><i class="bi bi-sliders"></i></div>
      <h2>Configure and apply</h2>
      <p>Enable classification as an admin, expose the categories to users, and make classification part of the upload flow.</p>
   </article>
   <article class="latest-release-card">
      <div class="latest-release-card-icon"><i class="bi bi-chat-quote"></i></div>
      <h2>Use the context</h2>
      <p>Once documents are classified, filtering, search, routing, and chat context become more predictable and more useful.</p>
   </article>
</section>

## What Is Document Classification?

Document classification allows you to tag documents with categories that indicate their type, purpose, sensitivity level, or department. Think of it like adding colored labels to file folders.

### Benefits of Classification

**Better Organization**:
- Visual organization with color coding
- Easy filtering and searching
- Clear document purposes

**Improved Workflows**:
- Route documents to appropriate teams
- Implement approval processes
- Support compliance requirements

**Enhanced AI Responses**:
- AI can understand document context better
- More relevant search results
- Better citation context

## Step 1: Plan Your Classification Scheme

Before setting up classifications, plan what categories you need:

### Common Classification Types

**By Department**:
- 🏢 HR Documents (Purple)
- 💰 Finance (Blue) 
- 🔧 IT/Technical (Green)
- 📈 Marketing (Orange)
- 🏛️ Legal (Red)

**By Document Type**:
- 📋 Policies & Procedures (Blue)
- 📊 Reports & Analytics (Green)
- 📝 Meeting Notes (Yellow)
- 📄 Contracts (Red)
- 🎓 Training Materials (Purple)

**By Sensitivity Level**:
- 🔒 Confidential (Red)
- ⚠️ Internal Use (Yellow)
- 📢 Public (Green)
- 👥 Team Only (Blue)

**By Project/Initiative**:
- 🚀 Project Alpha (Blue)
- 📱 Mobile App Dev (Green)
- 🌐 Website Redesign (Orange)
- 📊 Data Migration (Purple)

### Planning Questions
- What document types do you work with most?
- How do people currently organize files?
- What workflows need document routing?
- What compliance requirements exist?

## Step 2: Configure Classifications (Admin)

As an admin, you'll set up the classification options:

### Access Admin Settings
1. **Navigate to Admin Settings**
2. **Find the "Workspaces" section**
3. **Locate "Document Classification" settings**

### Create Classification Categories
1. **Enable Document Classification** if not already active
2. **Add classification types**:
   - Enter category name (e.g., "Financial Reports")
   - Choose color for visual identification
   - Add description (optional but helpful)
3. **Save configuration**

### Example Configuration

```
Classification Categories:
├── 📊 Financial Reports (Blue)
├── 📋 HR Policies (Purple)  
├── 🔧 Technical Docs (Green)
├── 📈 Marketing Materials (Orange)
├── 📄 Legal Documents (Red)
└── 📝 Meeting Notes (Yellow)
```

### Best Practices for Setup
- **Start simple**: Begin with 4-6 main categories
- **Use clear names**: Avoid ambiguous terms
- **Choose distinct colors**: Make visual differences obvious  
- **Get team input**: Involve users in category selection
- **Plan for growth**: Categories can be added later

## Step 3: Apply Classifications During Upload

Now let's use classifications when uploading documents:

### Upload with Classification
1. **Start normal upload process**
2. **Select documents** to upload
3. **Choose classification** from dropdown menu
4. **Complete upload** as usual

The classification will be applied to all documents in that upload batch.

### Classification Selection
- **Match content to category**: Choose the most appropriate classification
- **Consider primary purpose**: What's the main use of this document?
- **Think about audience**: Who primarily uses this document type?
- **Be consistent**: Use the same classification for similar documents

## Step 4: Manage Classified Documents

### View by Classification
1. **Go to document workspace**
2. **Use classification filter** to see documents by category
3. **Visual indicators** show classification colors
4. **Sort and search** within classifications

### Change Classifications
If you need to reclassify documents:
1. **Select document** in workspace
2. **Edit document properties**
3. **Choose new classification**
4. **Save changes**

### Batch Operations
For multiple documents:
1. **Select multiple documents** (if supported)
2. **Apply classification** to entire selection
3. **Confirm changes**

## Step 5: Use Classifications in Workflows

### Search and Discovery
Classifications improve how you find documents:

**Filter by type**:
- "Show me all financial reports"
- "Display only HR policies"
- "Find technical documentation"

**Search within categories**:
- Search for specific content within a classification
- Combine keywords with document types
- Use visual cues to identify relevant content

### AI Chat Integration
Classifications provide context to AI responses:

**Better responses**: AI understands document context
**Relevant citations**: Citations include classification information
**Workflow awareness**: AI can suggest appropriate next steps

### Example Chat Interactions

**Classification-aware questions**:
- "What financial policies apply to expense reporting?"
- "Summarize all technical documentation about the API"
- "What do the meeting notes say about the project timeline?"

**Cross-classification analysis**:
- "Compare financial and operational data from last quarter"
- "How do HR policies align with legal requirements?"

## Step 6: Advanced Classification Workflows

### Approval Processes
Use classifications to route documents:
- Financial documents → Finance team review
- Policy updates → Legal approval
- Technical specs → Engineering validation

### Compliance Management
Track sensitive documents:
- Confidential documents get special handling
- Public documents can be shared freely
- Internal documents stay within organization

### Project Organization
Group project-related content:
- All Project Alpha documents in one view
- Timeline tracking across document types
- Resource allocation by project classification

## Real-World Examples

### Legal Firm Classification
```
Document Types:
├── ⚖️ Case Files (Red)
├── 📄 Contracts (Blue)
├── 📋 Legal Briefs (Green)
├── 📊 Billing Records (Yellow)
└── 📝 Client Communications (Purple)
```

### Healthcare Organization
```
Document Types:  
├── 🏥 Patient Records (Red - Confidential)
├── 📋 Policies & Procedures (Blue)
├── 🎓 Training Materials (Green)
├── 📊 Quality Reports (Yellow)
└── 📄 Compliance Docs (Purple)
```

### Software Company
```
Document Types:
├── 💻 Technical Specifications (Blue)
├── 📱 Product Requirements (Green)
├── 🐛 Bug Reports (Orange)
├── 📊 Performance Reports (Yellow)
└── 📝 Meeting Notes (Purple)
```

## Best Practices

### Classification Strategy
- ✅ Keep categories focused and distinct
- ✅ Train users on classification guidelines
- ✅ Review and refine categories regularly
- ✅ Document classification criteria
- ✅ Use consistent naming conventions

### Implementation
- ✅ Start with pilot group before rollout
- ✅ Create classification guidelines document  
- ✅ Monitor usage and adjust categories
- ✅ Get feedback from users regularly
- ✅ Integrate with existing workflows

### Maintenance
- ✅ Regular cleanup of misclassified documents
- ✅ Update categories as needs evolve
- ✅ Train new users on classification system
- ✅ Monitor for unused categories
- ✅ Document classification decisions

## Troubleshooting

### Classification Not Available
**Missing admin setup**:
- Verify classification is enabled in admin settings
- Check that categories are properly configured
- Ensure user has appropriate permissions

**Categories not showing**:
- Refresh browser/clear cache
- Check admin settings for category visibility
- Verify configuration was saved properly

### Wrong Classifications Applied
**Batch misclassification**:
- Use document management to reclassify
- Consider if categories need refinement
- Update classification guidelines

**Inconsistent usage**:
- Provide user training on classification criteria
- Create clearer category descriptions
- Consider simplifying classification scheme

### Performance Issues
**Slow filtering**:
- Large numbers of documents may slow filtering
- Consider archiving old documents
- Check system performance and scaling

## What You've Accomplished

Congratulations! You've successfully:
✅ Planned an effective classification scheme  
✅ Configured document classifications as admin  
✅ Applied classifications to uploaded documents  
✅ Used classifications for organization and discovery  
✅ Integrated classifications into workflows

## Next Steps

Now that you have document classification working:
- Create [specialized agents](first_agent) that work with specific document classifications
- Explore [advanced document management](../how-to/add_documents) techniques
- Set up [group workspaces](../how-to/group_management) with classification workflows
- Learn about [enhanced citations](../how-to/enhanced_citations) that show classification context

---

*Tutorial series complete! Ready for [how-to guides](../how-to/) →*
