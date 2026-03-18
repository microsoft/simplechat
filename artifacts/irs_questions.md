# IRS/Treasury Workbook Agent Test Questions

These prompts are ordered from basic workbook validation to more realistic customer-service and compliance scenarios. They are designed to help test whether an AI agent can read the workbook, connect related tabs, explain findings clearly, and behave like a useful customer-facing assistant.

## 1. Basic Workbook Overview

"Summarize this workbook for me. What worksheets does it contain, what does each worksheet represent, and how are they related?"

Purpose: Confirms the agent can identify the workbook structure and explain the high-level data model.

## 2. Single Taxpayer Lookup

"Find taxpayer `TP000123`. Show their profile, tax return summary, and any related W-2, 1099, payment, refund, notice, audit, or installment agreement records."

Purpose: Tests simple key-based retrieval across all linked tabs.

## 3. Return-to-Refund Explanation

"For return `RET000123`, explain why the taxpayer received a refund or owes a balance. Use the fields in the workbook to walk me through the calculation in plain English."

Purpose: Verifies the agent can interpret tax return fields and produce a customer-friendly explanation.

## 4. Employer and Wage Cross-Check

"Pick one taxpayer with at least one W-2 and tell me whether their taxpayer wages, return amounts, and W-2 wages look consistent. If something looks off, explain why."

Purpose: Checks whether the agent can compare values across related worksheets and surface discrepancies.

## 5. Payment Posting Scenario

"Show me a taxpayer who made estimated payments. Explain when the payments were made, whether they posted successfully, and how they affected the final return outcome."

Purpose: Tests timeline reasoning and the agent's ability to connect payment activity to balances due or refunds.

## 6. Refund Customer Support Scenario

"Act like a support agent. A taxpayer says, 'My refund is smaller than I expected.' Use one refund claim record to explain the likely reason, including offsets, reviews, or disbursement details, in a calm customer-service tone."

Purpose: Simulates a realistic customer experience and checks whether the agent can translate data into a support-style answer.

## 7. Notice Resolution Scenario

"Find a taxpayer who received an IRS notice. Explain what triggered the notice, what amount was requested, whether the taxpayer responded, and what the current resolution status is."

Purpose: Tests case tracking across returns, notices, and related audit or collections signals.

## 8. Audit Readiness Scenario

"Identify a taxpayer with an audit record and summarize the full case history: why the return may have been selected, what changes were proposed, whether penalties or interest were assessed, and whether the case is still open."

Purpose: Validates multi-step reasoning on more complex compliance workflows.

## 9. Installment Agreement Risk Scenario

"Find a taxpayer with an installment agreement and assess the risk that they may default. Use balance, monthly payment, missed payments, status, and risk indicators to justify your answer."

Purpose: Tests whether the agent can combine multiple fields into a practical risk assessment.

## 10. End-to-End Customer Journey

"Choose one taxpayer who has records in as many worksheets as possible and tell their full story from filing through payments, refund or balance outcome, notices, audit activity, and any installment agreement. Then suggest what a customer support agent should say as the next best action."

Purpose: This is the most complete scenario. It tests cross-tab reasoning, summarization quality, prioritization, and customer-facing guidance.

## Optional Scoring Rubric

You can score your agent on each question using these checks:

- Did it reference the correct worksheet relationships?
- Did it use the right IDs and linked records?
- Did it explain the result clearly and accurately?
- Did it avoid inventing facts not present in the workbook?
- Did it respond in a way that sounds useful for a real customer or analyst?