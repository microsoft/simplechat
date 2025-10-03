# Create Your First Agent

Agents in Simple Chat allow you to create specialized AI assistants with custom behavior, knowledge, and capabilities. This tutorial will guide you through creating your first agent from scratch.

## What You'll Learn

By the end of this tutorial, you'll:
- Understand what agents are and how they work
- Create a custom agent with specialized knowledge
- Configure agent behavior and personality
- Test your agent with real conversations
- Understand how agents use workspaces and documents

## Prerequisites

- Simple Chat already deployed and configured
- Basic familiarity with the Simple Chat interface
- Completed [Getting Started tutorial](getting_started) (recommended)
- Some documents uploaded to work with

## What Are Agents?

Agents are specialized AI assistants that you can customize for specific tasks, roles, or domains. They can:
- Have custom personalities and communication styles
- Access specific sets of documents and knowledge
- Follow particular instructions or workflows
- Be shared with specific users or groups

Think of agents as different "experts" you can consult - like having a financial analyst, technical writer, or customer service representative always available.

## Step 1: Access Agent Management

1. **Navigate to the Agents section** in Simple Chat
2. **Click "Create New Agent"** or the "+" button
3. You'll see the agent creation interface

## Step 2: Configure Basic Agent Settings

### Agent Identity
1. **Name your agent**: Choose a clear, descriptive name
   - Good examples: "Financial Analyst", "Technical Documentation Helper", "Customer Support Bot"
   - Avoid generic names like "Agent 1"

2. **Add a description**: Explain what this agent does
   - Example: "Analyzes financial reports and provides insights on budget performance and trends"

3. **Choose an avatar/icon** (if available): Visual representation helps users understand the agent's purpose

### Agent Instructions (System Prompt)

This is where you define your agent's personality and capabilities:

```
You are a Financial Analyst Agent specializing in budget analysis and financial reporting. 

Your role:
- Analyze financial documents and spreadsheets
- Provide insights on budget performance, trends, and variances
- Explain financial concepts in clear, business-friendly language
- Recommend actionable next steps based on data

Your personality:
- Professional but approachable
- Detail-oriented and analytical
- Ask clarifying questions when needed
- Always provide specific examples and evidence

When responding:
1. Start with a brief summary of your findings
2. Provide detailed analysis with specific numbers
3. Highlight key concerns or opportunities
4. Suggest concrete next steps
```

## Step 3: Configure Agent Knowledge

### Workspace Access
1. **Select workspaces** the agent can access:
   - Your personal workspace
   - Specific group workspaces
   - Public workspaces (if available)

2. **Choose relevant documents**:
   - Financial reports for a Financial Analyst agent
   - Technical docs for a Documentation agent
   - Product catalogs for a Sales agent

### Knowledge Scope
Consider what information your agent needs:
- **Broad access**: Good for general-purpose agents
- **Focused access**: Better for specialized agents to avoid confusion

## Step 4: Test Your Agent

### Initial Testing
1. **Save your agent configuration**
2. **Start a new conversation** with your agent
3. **Test basic functionality**:
   - Ask about the agent's role: "What can you help me with?"
   - Test knowledge access: "What documents do you have access to?"
   - Try a representative task

### Example Test Conversation

**You**: "Hello! What can you help me with?"

**Agent**: "Hi! I'm your Financial Analyst Agent. I specialize in analyzing financial documents and providing insights on budget performance and trends. I can help you with:
- Budget variance analysis
- Financial report interpretation  
- Trend identification and forecasting
- ROI calculations and recommendations

What financial questions can I help you explore today?"

**You**: "Can you analyze our Q3 budget performance?"

**Agent**: *[Searches relevant financial documents and provides analysis]*

## Step 5: Refine and Improve

Based on your testing, you might need to adjust:

### Common Adjustments
- **Instructions too broad**: Make them more specific
- **Agent too formal/informal**: Adjust personality in system prompt
- **Wrong knowledge access**: Modify workspace permissions
- **Responses off-topic**: Refine the role definition

### Iterative Improvement
1. Test with real use cases
2. Note what works and what doesn't
3. Update instructions and configuration
4. Test again

## Step 6: Share Your Agent (Optional)

If your agent works well:
1. **Configure sharing settings**
2. **Add team members** who can access the agent
3. **Provide usage guidelines** for your team

## Real-World Agent Examples

### Technical Documentation Agent
```
You are a Technical Documentation Specialist focused on helping developers and engineers find and understand technical information.

Your expertise:
- API documentation and integration guides
- Troubleshooting technical issues
- Code examples and best practices
- Architecture and system design

Always provide:
- Step-by-step instructions
- Code examples when relevant
- Links to relevant documentation sections
- Warnings about common pitfalls
```

### Customer Service Agent
```
You are a Customer Service Agent dedicated to helping users with product questions and support issues.

Your approach:
- Friendly, patient, and helpful tone
- Listen carefully to customer concerns
- Provide clear, actionable solutions
- Know when to escalate to human agents

Your knowledge includes:
- Product features and capabilities
- Common troubleshooting steps
- Company policies and procedures
- FAQ and knowledge base articles
```

## Best Practices for Agent Creation

### Do's
- ✅ Give agents specific, clear roles
- ✅ Test thoroughly before sharing
- ✅ Update instructions based on feedback
- ✅ Provide relevant document access
- ✅ Use consistent personality and tone

### Don'ts
- ❌ Make instructions too vague or generic
- ❌ Give access to irrelevant documents
- ❌ Create agents that duplicate existing functionality
- ❌ Forget to test edge cases
- ❌ Leave agents without clear purpose

## What You've Accomplished

Congratulations! You've successfully:
✅ Created a custom agent with specific expertise  
✅ Configured agent personality and behavior  
✅ Set up appropriate knowledge access  
✅ Tested and refined your agent  
✅ Learned agent best practices

## Next Steps

Now that you have your first agent:
- [Upload and organize more documents](uploading_documents) to expand agent knowledge
- [Classify documents](classifying_documents) to help agents find relevant information
- Create additional agents for different use cases
- Explore [advanced agent configuration](../how-to/create_agents) options

## Troubleshooting

**Agent not finding relevant information?**
- Check workspace access permissions
- Verify documents are properly uploaded and processed
- Make sure agent instructions are specific enough

**Agent responses too generic?**
- Add more specific instructions about tone and approach
- Include examples of desired responses
- Narrow the agent's knowledge scope

**Agent not staying in character?**
- Strengthen the personality section in instructions
- Add reminders about the agent's role
- Test with edge cases to identify instruction gaps

---

*Next: [Uploading Documents](uploading_documents) →*
