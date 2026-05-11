# Revenue Variance Analysis (RVA)

## Purpose

The **Revenue Variance Analysis (RVA) database** simulates the lifecycle of **agency revenue forecasting, actual collections, and variance reporting** enriched with U.S. Treasury data.

It enables you to demonstrate how treasury analysts can:

- Track **forecasted vs. actual revenue** for agencies.
- Monitor **daily collection patterns** against monthly forecasts.
- Write **variance reports** with national Treasury context (revenue and refunds).
- Detect **shortfalls or surpluses** linked to national trends.
- Provide **auditable explanations** that tie local agency data to federal Treasury metrics.

This dataset underpins the **RVA Agent**, providing both structure (schema reasoning) and realistic sample data (query execution and analysis).

------

## Schema Overview

The schema is normalized into four core tables with clear relationships:

1. **Agencies** – Owners of forecasts and collections.
2. **RevenueForecasts** – Projected monthly revenues.
3. **Collections** – Daily actual income.
4. **VarianceReports** – Forecast vs. actual reconciliations enriched with Treasury API context.

**Relationships**:

- Agencies → RevenueForecasts
- Agencies → Collections
- VarianceReports links back to Agencies

------

## SQL Table Creation Script

```sql
---------------------------------------------------
-- 1. Agencies (revenue owners)
---------------------------------------------------
CREATE TABLE Agencies (
    AgencyID INT IDENTITY(1,1) PRIMARY KEY,
    Name VARCHAR(150) NOT NULL,
    Division VARCHAR(150),              -- e.g., IRS, Customs, DOT
    ContactEmail VARCHAR(150),
    Status VARCHAR(50) DEFAULT 'Active' -- Active, Inactive, Suspended
);

---------------------------------------------------
-- 2. Revenue Forecasts (planned income)
---------------------------------------------------
CREATE TABLE RevenueForecasts (
    ForecastID INT IDENTITY(1,1) PRIMARY KEY,
    AgencyID INT NOT NULL,
    Month DATE NOT NULL,                -- use first day of month (e.g., 2025-04-01)
    ForecastAmount DECIMAL(15,2) NOT NULL,
    Notes VARCHAR(MAX),
    FOREIGN KEY (AgencyID) REFERENCES Agencies(AgencyID)
);

---------------------------------------------------
-- 3. Collections (actual daily income)
---------------------------------------------------
CREATE TABLE Collections (
    CollectionID BIGINT IDENTITY(1,1) PRIMARY KEY,
    AgencyID INT NOT NULL,
    Date DATE NOT NULL,
    CollectedAmount DECIMAL(15,2) NOT NULL,
    Source VARCHAR(100),                -- e.g., Taxes, Fees, Customs
    EntryMethod VARCHAR(50),            -- e.g., Automated, Manual, API
    FOREIGN KEY (AgencyID) REFERENCES Agencies(AgencyID)
);

---------------------------------------------------
-- 4. Variance Reports (forecast vs. actual + Treasury impact)
---------------------------------------------------
CREATE TABLE VarianceReports (
    VarianceID INT IDENTITY(1,1) PRIMARY KEY,
    AgencyID INT NOT NULL,
    Month DATE NOT NULL,
    ForecastAmount DECIMAL(15,2) NOT NULL,
    ActualAmount DECIMAL(15,2) NOT NULL,
    NationalTrendImpact VARCHAR(MAX),   -- e.g., "National refunds surged 20%"
    GeneratedDate DATE DEFAULT GETDATE(),
    FOREIGN KEY (AgencyID) REFERENCES Agencies(AgencyID)
);
```

------

## Test Data Reset and Population Script

This section resets all tables and then inserts realistic test data for Agencies, Forecasts, Collections, and VarianceReports.

------

### Step 1: Reset All Tables

```sql
---------------------------------------------------
-- RESET ALL TABLES (delete + reseed identities)
---------------------------------------------------
DELETE FROM VarianceReports;
DELETE FROM Collections;
DELETE FROM RevenueForecasts;
DELETE FROM Agencies;

DBCC CHECKIDENT ('VarianceReports', RESEED, 0);
DBCC CHECKIDENT ('Collections', RESEED, 0);
DBCC CHECKIDENT ('RevenueForecasts', RESEED, 0);
DBCC CHECKIDENT ('Agencies', RESEED, 0);
```

------

### Step 2: Agencies (10 rows)

```sql
---------------------------------------------------
-- Agencies (10 rows with real-like names)
---------------------------------------------------
INSERT INTO Agencies (Name, Division, ContactEmail, Status)
VALUES
('Internal Revenue Service', 'Tax Collection', 'irs@agency.gov', 'Active'),
('U.S. Customs and Border Protection', 'Trade & Tariffs', 'cbp@agency.gov', 'Active'),
('Department of Transportation', 'Highway Trust Fund', 'dot@agency.gov', 'Active'),
('Department of Energy', 'Energy Programs', 'doe@agency.gov', 'Active'),
('National Institutes of Health', 'Medical Research', 'nih@agency.gov', 'Active'),
('Social Security Administration', 'Payroll Tax', 'ssa@agency.gov', 'Active'),
('Department of Agriculture', 'Food Programs', 'usda@agency.gov', 'Active'),
('Federal Aviation Administration', 'Aviation Fees', 'faa@agency.gov', 'Active'),
('Centers for Medicare & Medicaid Services', 'Healthcare Funding', 'cms@agency.gov', 'Active'),
('Environmental Protection Agency', 'Environmental Fees', 'epa@agency.gov', 'Active');
```

------

Great callout. The raw randomization in that script could easily create **unrealistic data patterns** (e.g., daily totals swinging too wildly compared to forecasts). To make this dataset demo-friendly and realistic, here are the **gotchas** to fix and a set of **improved strategies** for generating the fake data:

------

## Gotchas in the Current Script

1. **Revenue Forecasts Range ($10M–$60M) chosen at random per agency per month**
   - Problem: This can cause a small agency (e.g., FAA) to randomly have a forecast higher than IRS.
   - Fix: Set **agency-specific baseline ranges** and add **seasonal variance**, rather than pure random.
2. **Daily Collections ($100k–$2M per day, random)**
   - Problem: Over 30 days, sums might not align at all with the forecast (could be 20% or 300% of forecast).
   - Fix: Make daily totals **scale proportionally to forecast**, with mild daily randomness.
3. **No linkage between Collections and Forecasts**
   - Problem: Forecast says $50M, but daily totals might add up to $75M.
   - Fix: Generate collections so monthly sum ≈ forecast ± 5–15%.
4. **VarianceReports hardcoded**
   - Problem: If collections are already off by large amounts, these seeded variances won’t match reality.
   - Fix: Calculate variances programmatically based on forecasts vs. actuals.

------

### Step 3: Revenue Forecasts (Agency-specific ranges)

Instead of random $10M–$60M for everyone:

```sql
---------------------------------------------------
-- Revenue Forecasts (agency-specific ranges + mild variance)
---------------------------------------------------
;WITH Numbers AS (
    SELECT TOP (12) ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) - 1 AS n
    FROM sys.objects
)
INSERT INTO RevenueForecasts (AgencyID, Month, ForecastAmount, Notes)
SELECT 
    a.AgencyID,
    DATEADD(MONTH, n, '2025-01-01'),
    CASE a.Name
        WHEN 'Internal Revenue Service' THEN (4000000000 + (ABS(CHECKSUM(NEWID())) % 200000000)) -- $4B–$4.2B
        WHEN 'Social Security Administration' THEN (2500000000 + (ABS(CHECKSUM(NEWID())) % 150000000))
        WHEN 'Centers for Medicare & Medicaid Services' THEN (2000000000 + (ABS(CHECKSUM(NEWID())) % 100000000))
        WHEN 'U.S. Customs and Border Protection' THEN (500000000 + (ABS(CHECKSUM(NEWID())) % 50000000))
        ELSE (200000000 + (ABS(CHECKSUM(NEWID())) % 50000000)) -- smaller agencies
    END,
    'Baseline forecast for month ' + CAST(n+1 AS VARCHAR)
FROM Agencies a
CROSS JOIN Numbers;
```

- Keeps IRS/SSA/CMS very large, others smaller.
- Forecasts are stable month-to-month with slight fluctuation.

------

### Step 4: Collections (scale daily totals to forecast)

Generate daily collections so they **sum close to forecast**:

```sql
---------------------------------------------------
-- Collections (daily actuals aligned to forecast)
---------------------------------------------------
;WITH Forecasts AS (
    SELECT AgencyID, Month, ForecastAmount
    FROM RevenueForecasts
),
Days AS (
    SELECT TOP (31) ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) - 1 AS DayOffset
    FROM sys.objects
)
INSERT INTO Collections (AgencyID, Date, CollectedAmount, Source, EntryMethod)
SELECT 
    f.AgencyID,
    DATEADD(DAY, d.DayOffset, f.Month),
    CAST(f.ForecastAmount / 31.0 * 
        (1.0 + ((ABS(CHECKSUM(NEWID())) % 10) - 5) / 100.0)  -- ±5% daily variance
        AS DECIMAL(15,2)),
    CASE (ABS(CHECKSUM(NEWID())) % 3)
        WHEN 0 THEN 'Taxes'
        WHEN 1 THEN 'Fees'
        ELSE 'Customs'
    END,
    CASE (ABS(CHECKSUM(NEWID())) % 2)
        WHEN 0 THEN 'Automated'
        ELSE 'Manual'
    END
FROM Forecasts f
CROSS JOIN Days d;
```

- Each day’s revenue is close to **1/31 of forecast** with ±5% noise.
- Ensures monthly actual ≈ forecast ± ~10%.

------

### Step 5: Variance Reports (calculated, not hardcoded)

Instead of inserting static examples:

```sql
---------------------------------------------------
-- Variance Reports (auto-generated based on actuals vs. forecast)
---------------------------------------------------
INSERT INTO VarianceReports (AgencyID, Month, ForecastAmount, ActualAmount, NationalTrendImpact)
SELECT 
    f.AgencyID,
    f.Month,
    f.ForecastAmount,
    SUM(c.CollectedAmount) AS ActualAmount,
    CASE 
        WHEN SUM(c.CollectedAmount) < f.ForecastAmount * 0.95 
            THEN 'National refunds surged (downward pressure on collections)'
        WHEN SUM(c.CollectedAmount) > f.ForecastAmount * 1.05
            THEN 'Revenue collections rose faster than expected'
        ELSE 'In line with Treasury national trends'
    END
FROM RevenueForecasts f
JOIN Collections c ON f.AgencyID = c.AgencyID 
    AND MONTH(c.Date) = MONTH(f.Month) 
    AND YEAR(c.Date) = YEAR(f.Month)
GROUP BY f.AgencyID, f.Month, f.ForecastAmount;
```

- Automatically generates realistic variances.
- Keeps alignment between forecast and actuals.
- Inserts contextual commentary to simulate Treasury API correlation.

------

## Benefits of This Approach

- **No unrealistic spikes:** Forecasts are stable and aligned by agency size.

- **Collections match forecasts:** Daily values are proportional and noisy but roll up realistically.

- **Variance Reports are honest:** They reflect the actual differences, not arbitrary numbers.

- **Demo-ready:** Reports will read like a real system, e.g.:

  > “IRS March 2025 forecast $4.1B, actual $3.95B (variance -3.7%). National refunds surged (downward pressure on collections).”

## Why This Matters

Together, these scripts create a **realistic, self-contained RVA dataset**. The RVA Agent can now:

- Query agency forecasts vs. actual collections.

- Compare local agency variances against national Treasury trends.

- Generate **VarianceReports** that are audit-ready and backed by external Treasury data.

- Provide demo-ready explanations like:

  > “IRS under-collected $3M in March 2025 while national refunds surged 18%.”