# Demo Questions for the RVA Agent

## 1. Agency Variance with Treasury Context

- Did Customs’ revenue shortfall in April 2025 align with a national spike in refunds?
  - **SQL** → Customs forecast vs. actual
  - **API** → `/income_tax_refunds_issued`
- Explain why the Social Security Administration collections were lower than forecast in May 2025.
  - **SQL** → SSA variance
  - **API** → `/revenue/rcm` and `/income_tax_refunds_issued`

------

## 2. Multi-Agency Variance Analysis

- Summarize agency revenue variances for March 2025 with Treasury refund and revenue context.
  - **SQL** → All agencies in March
  - **API** → Refund + revenue collections
- Compare IRS and CMS revenue forecasts vs. actuals for Q2 2025 and explain differences with Treasury data.
  - **SQL** → IRS + CMS
  - **API** → Refunds and national collections

------

## 3. Variance Report Logging

- Create a variance report for IRS for April 2025 and include national refund trends.
  - **SQL** → IRS forecast vs. actual
  - **API** → Refund surges
  - **Insert** → `VarianceReports` with commentary

------

## 4. Executive Summaries

- Provide a one-paragraph summary of which agencies are under- or over-performing against forecasts this month, with Treasury context.
  - **SQL** → All agencies for current month
  - **API** → National refunds and revenue trends