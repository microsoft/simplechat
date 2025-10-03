# Enterprise Software Asset Management

## Purpose

The **Enterprise Software Asset Management (ESAM) database** simulates the full lifecycle of enterprise software assets across procurement, license pools, usage, and requests.

It enables you to demonstrate how administrators can:

- Track **what was purchased** (vendor, product, cost, and quantity).
- Monitor **license allocations and consumption** in real time.
- Determine whether **new license requests** can be fulfilled from existing entitlements or require new purchases.
- Validate that license allocations reconcile with procurement entitlements.
- Identify **shortfalls and cost impacts** when onboarding new users.
- Analyze **volume-based pricing trends** to determine if larger purchases achieve discounts.

This dataset underpins the **ESAM Agent**, providing both structure (for schema reasoning) and realistic sample data (for query execution and reasoning).

------

## Schema Overview

The schema is normalized into five core tables with clear relationships:

1. **Vendors** – Software providers (e.g., Microsoft, Adobe).
2. **Procurements** – Purchase records (what was bought, when, how much, at what cost).
3. **Licenses** – License pools tied to procurements (allocation of purchased entitlements).
4. **Usage** – Deployment/assignment of licenses at the user level.
5. **Requests** – User or departmental requests for additional licenses.

**Relationships**:

- Vendors → Procurements → Licenses
- Licenses → Usage
- Requests ↔ Licenses

------

## SQL Table Creation Script

This script creates the five tables, establishes primary keys, and defines relationships with foreign keys. Note that `Procurements.TotalCost` is a persisted calculated column.

```sql
CREATE TABLE Vendors (
    VendorID INT IDENTITY(1,1) PRIMARY KEY,
    Name VARCHAR(150) NOT NULL,
    ContactEmail VARCHAR(150),
    SupportPhone VARCHAR(50)
);

CREATE TABLE Procurements (
    ProcurementID INT IDENTITY(1,1) PRIMARY KEY,
    VendorID INT NOT NULL,
    ProductName VARCHAR(150) NOT NULL,
    PurchaseDate DATE NOT NULL,
    Quantity INT NOT NULL,
    UnitCost DECIMAL(12,2) NOT NULL,
    TotalCost AS (Quantity * UnitCost) PERSISTED,
    FOREIGN KEY (VendorID) REFERENCES Vendors(VendorID)
);

CREATE TABLE Licenses (
    LicenseID INT IDENTITY(1,1) PRIMARY KEY,
    ProcurementID INT NOT NULL,
    LicenseKey VARCHAR(200),
    TotalQuantity INT NOT NULL,
    ExpirationDate DATE,
    FOREIGN KEY (ProcurementID) REFERENCES Procurements(ProcurementID)
);

CREATE TABLE Usage (
    UsageID INT IDENTITY(1,1) PRIMARY KEY,
    LicenseID INT NOT NULL,
    UserName VARCHAR(150),
    Department VARCHAR(100),
    AssignedDate DATE DEFAULT GETDATE(),
    FOREIGN KEY (LicenseID) REFERENCES Licenses(LicenseID)
);

CREATE TABLE Requests (
    RequestID INT IDENTITY(1,1) PRIMARY KEY,
    LicenseID INT NOT NULL,
    RequestedBy VARCHAR(150),
    Department VARCHAR(100),
    RequestDate DATE DEFAULT GETDATE(),
    QuantityRequested INT NOT NULL,
    Status VARCHAR(50) DEFAULT 'Pending',
    FOREIGN KEY (LicenseID) REFERENCES Licenses(LicenseID)
);
```

------

## Test Data Reset and Population Script

This section **resets all tables** and then **inserts realistic test data** for Vendors, Procurements, Licenses, Usage, and Requests.

The goal is to provide **diverse and realistic records** so the ESAM Agent can demonstrate procurement tracking, license reconciliation, fulfillment logic, and pricing analysis.

### Step 1: Reset All Tables

Ensures a clean slate by deleting all data and reseeding identity columns.

```sql
---------------------------------------------------
-- RESET ALL TABLES (delete + reseed identities)
---------------------------------------------------
DELETE FROM Requests;
DELETE FROM Usage;
DELETE FROM Licenses;
DELETE FROM Procurements;
DELETE FROM Vendors;

DBCC CHECKIDENT ('Requests', RESEED, 0);
DBCC CHECKIDENT ('Usage', RESEED, 0);
DBCC CHECKIDENT ('Licenses', RESEED, 0);
DBCC CHECKIDENT ('Procurements', RESEED, 0);
DBCC CHECKIDENT ('Vendors', RESEED, 0);
```

------

### Step 2: Vendors (20 rows)

Populates the **Vendors** table with well-known enterprise software providers.

```sql
---------------------------------------------------
-- Vendors (20 rows) with real-like names
---------------------------------------------------
INSERT INTO Vendors (Name, ContactEmail, SupportPhone)
VALUES
('Microsoft', 'support@microsoft.com', '+1-800-642-7676'),
('Adobe', 'support@adobe.com', '+1-800-833-6687'),
('Oracle', 'support@oracle.com', '+1-800-633-0738'),
('SAP', 'support@sap.com', '+1-800-872-1727'),
('Salesforce', 'support@salesforce.com', '+1-800-667-6389'),
('Atlassian', 'support@atlassian.com', '+1-844-588-8475'),
('VMware', 'support@vmware.com', '+1-877-486-9273'),
('IBM', 'support@ibm.com', '+1-800-426-4968'),
('Google', 'support@google.com', '+1-855-836-3987'),
('Amazon AWS', 'support@amazon.com', '+1-888-280-4331'),
('Slack', 'support@slack.com', '+1-844-752-7425'),
('Zoom', 'support@zoom.com', '+1-888-799-9666'),
('ServiceNow', 'support@servicenow.com', '+1-800-861-8260'),
('HubSpot', 'support@hubspot.com', '+1-888-482-7768'),
('Cisco', 'support@cisco.com', '+1-800-553-6387'),
('Dropbox', 'support@dropbox.com', '+1-888-717-7726'),
('Asana', 'support@asana.com', '+1-855-727-6262'),
('GitHub', 'support@github.com', '+1-877-844-4825'),
('Box', 'support@box.com', '+1-877-729-4269'),
('Zendesk', 'support@zendesk.com', '+1-888-670-4887');
```

------

### Step 3: Procurements (50 rows with volume-based pricing)

Simulates purchase records with **volume discounts**. Larger purchase quantities yield lower per-unit costs.

```sql
---------------------------------------------------
-- Procurements (50 rows) with volume-based pricing
---------------------------------------------------
WITH ProductList AS (
    SELECT VendorID, Name AS VendorName FROM Vendors
)
INSERT INTO Procurements (VendorID, ProductName, PurchaseDate, Quantity, UnitCost)
SELECT TOP (50)
    v.VendorID,
    CASE v.Name
        WHEN 'Microsoft' THEN 'Office 365'
        WHEN 'Adobe' THEN 'Photoshop'
        WHEN 'Oracle' THEN 'Database Enterprise'
        WHEN 'SAP' THEN 'SAP S/4HANA'
        WHEN 'Salesforce' THEN 'Sales Cloud'
        WHEN 'Atlassian' THEN 'Jira Software'
        WHEN 'VMware' THEN 'vSphere'
        WHEN 'IBM' THEN 'Watson AI'
        WHEN 'Google' THEN 'Workspace'
        WHEN 'Amazon AWS' THEN 'EC2'
        WHEN 'Slack' THEN 'Slack Standard'
        WHEN 'Zoom' THEN 'Zoom Pro'
        WHEN 'ServiceNow' THEN 'ITSM'
        WHEN 'HubSpot' THEN 'Marketing Hub'
        WHEN 'Cisco' THEN 'WebEx'
        WHEN 'Dropbox' THEN 'Dropbox Business'
        WHEN 'Asana' THEN 'Asana Premium'
        WHEN 'GitHub' THEN 'GitHub Enterprise'
        WHEN 'Box' THEN 'Box Enterprise'
        WHEN 'Zendesk' THEN 'Zendesk Suite'
    END,
    DATEADD(DAY, -ROW_NUMBER() OVER (ORDER BY (SELECT NULL)), GETDATE()),
    -- Random quantity per procurement
    (ABS(CHECKSUM(NEWID())) % 200) + 10,
    -- Volume cost break: lower unit cost for larger purchases
    CASE 
        WHEN (ABS(CHECKSUM(NEWID())) % 200) + 10 < 50 THEN CAST(100 + (ABS(CHECKSUM(NEWID())) % 50) AS DECIMAL(12,2))
        WHEN (ABS(CHECKSUM(NEWID())) % 200) + 10 < 100 THEN CAST(90 + (ABS(CHECKSUM(NEWID())) % 40) AS DECIMAL(12,2))
        WHEN (ABS(CHECKSUM(NEWID())) % 200) + 10 < 150 THEN CAST(80 + (ABS(CHECKSUM(NEWID())) % 30) AS DECIMAL(12,2))
        ELSE CAST(70 + (ABS(CHECKSUM(NEWID())) % 20) AS DECIMAL(12,2))
    END
FROM Vendors v
CROSS JOIN (SELECT TOP (3) ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS x FROM sys.objects) AS t;
```

------

### Step 4: Licenses (500 rows, split allocations)

Distributes procurement entitlements into **license pools** (1–5 splits per procurement). Ensures the sum of license splits equals the procurement quantity.

```sql
---------------------------------------------------
-- Licenses (500 rows)
---------------------------------------------------
;WITH LicenseSplits AS (
    SELECT 
        p.ProcurementID,
        p.Quantity,
        ABS(CHECKSUM(NEWID())) % 5 + 1 AS NumSplits
    FROM Procurements p
),
SplitCTE AS (
    SELECT 
        ls.ProcurementID,
        ls.Quantity,
        ls.NumSplits,
        t.rn,
        ABS(CHECKSUM(NEWID())) % 100 + 1 AS Weight
    FROM LicenseSplits ls
    CROSS APPLY (
        SELECT TOP (ls.NumSplits) ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS rn
        FROM sys.objects
    ) t
),
WeightedSplits AS (
    SELECT 
        s.ProcurementID,
        s.rn,
        CAST(ROUND(1.0 * s.Weight / SUM(s.Weight) OVER (PARTITION BY s.ProcurementID) * s.Quantity, 0) AS INT) AS SplitQuantity,
        DATEADD(DAY, (ABS(CHECKSUM(NEWID())) % 730), GETDATE()) AS ExpirationDate
    FROM SplitCTE s
)
INSERT INTO Licenses (ProcurementID, LicenseKey, TotalQuantity, ExpirationDate)
SELECT 
    ws.ProcurementID,
    NULL,
    CASE WHEN ws.SplitQuantity = 0 THEN 1 ELSE ws.SplitQuantity END,
    ws.ExpirationDate
FROM WeightedSplits ws;
```

------

### Step 5: Usage (2000 rows)

Simulates real license assignments across users and departments.

```sql
---------------------------------------------------
-- Usage (2000 rows)
---------------------------------------------------
INSERT INTO Usage (LicenseID, UserName, Department, AssignedDate)
SELECT TOP (2000)
    l.LicenseID,
    CONCAT('user', ROW_NUMBER() OVER (ORDER BY (SELECT NULL))),
    CASE (ABS(CHECKSUM(NEWID())) % 5)
        WHEN 0 THEN 'Engineering'
        WHEN 1 THEN 'Finance'
        WHEN 2 THEN 'Marketing'
        WHEN 3 THEN 'HR'
        ELSE 'IT'
    END,
    DATEADD(DAY, -(ABS(CHECKSUM(NEWID())) % 365), GETDATE())
FROM Licenses l
CROSS JOIN (SELECT TOP (5) ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS x FROM sys.objects) AS t;
```

------

### Step 6: Requests (500 rows)

Simulates license requests with varied statuses.

```sql
---------------------------------------------------
-- Requests (500 rows)
---------------------------------------------------
INSERT INTO Requests (LicenseID, RequestedBy, Department, RequestDate, QuantityRequested, Status)
SELECT TOP (500)
    l.LicenseID,
    CONCAT('req_user', ROW_NUMBER() OVER (ORDER BY (SELECT NULL))),
    CASE (ABS(CHECKSUM(NEWID())) % 5)
        WHEN 0 THEN 'Engineering'
        WHEN 1 THEN 'Finance'
        WHEN 2 THEN 'Marketing'
        WHEN 3 THEN 'HR'
        ELSE 'IT'
    END,
    DATEADD(DAY, -(ABS(CHECKSUM(NEWID())) % 180), GETDATE()),
    (ABS(CHECKSUM(NEWID())) % 20) + 1,
    CASE (ABS(CHECKSUM(NEWID())) % 3)
        WHEN 0 THEN 'Pending'
        WHEN 1 THEN 'Approved'
        ELSE 'Fulfilled'
    END
FROM Licenses l
CROSS JOIN (SELECT TOP (2) ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS x FROM sys.objects) AS t;
```

------

## Why This Matters

Together, these scripts create a **realistic, self-contained ESAM dataset**. The ESAM Agent can now:

- Query procurement history.
- Calculate license availability.
- Validate procurement-to-license reconciliation.
- Answer whether new requests can be fulfilled.
- Estimate costs for onboarding scenarios.
- Detect volume discounts in pricing.