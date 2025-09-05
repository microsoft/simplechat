### Financial Mismanagement Investigations

```sql
-- 1. Departments (funding recipients)
CREATE TABLE Departments (
    DepartmentID SERIAL PRIMARY KEY,
    Name VARCHAR(150) NOT NULL,
    Agency VARCHAR(150),            -- e.g., DOT, FAA, NIH
    BudgetAllocated NUMERIC(15,2), -- total budget
    Status VARCHAR(50) DEFAULT 'Active'
);

-- 2. Transactions (budget items, expenditures)
CREATE TABLE Transactions (
    TransactionID BIGSERIAL PRIMARY KEY,
    DepartmentID INT NOT NULL,
    TransactionDate DATE NOT NULL,
    Amount NUMERIC(12,2) NOT NULL,
    Description TEXT,
    TransactionType VARCHAR(50),    -- e.g., Expense, Grant, Purchase
    FOREIGN KEY (DepartmentID) REFERENCES Departments(DepartmentID)
);

-- 3. Investigations (review of suspicious transactions)
CREATE TABLE Investigations (
    InvestigationID SERIAL PRIMARY KEY,
    TransactionID BIGINT NOT NULL,
    InvestigatorID INT NOT NULL,
    StartDate DATE DEFAULT CURRENT_DATE,
    EndDate DATE,
    Status VARCHAR(50) DEFAULT 'Ongoing', -- e.g., Ongoing, Closed
    Objective TEXT,
    FOREIGN KEY (TransactionID) REFERENCES Transactions(TransactionID),
    FOREIGN KEY (InvestigatorID) REFERENCES Investigators(InvestigatorID)
);

-- 4. Investigators (assigned personnel)
CREATE TABLE Investigators (
    InvestigatorID SERIAL PRIMARY KEY,
    FirstName VARCHAR(100) NOT NULL,
    LastName VARCHAR(100) NOT NULL,
    Agency VARCHAR(150),              -- e.g., OIG, DOJ
    Email VARCHAR(150)
);

-- 5. Findings (discrepancies, recommendations)
CREATE TABLE Findings (
    FindingID SERIAL PRIMARY KEY,
    InvestigationID INT NOT NULL,
    FindingDate DATE DEFAULT CURRENT_DATE,
    Description TEXT NOT NULL,
    Severity VARCHAR(20),             -- Low, Medium, High, Critical
    ActionRecommended TEXT,
    FOREIGN KEY (InvestigationID) REFERENCES Investigations(InvestigationID)
);
```

### **Schema Notes**

- **Departments → Transactions → Investigations → Findings**:
   Each department has multiple transactions; suspicious transactions can trigger investigations, and investigations produce findings.
- **Investigators ↔ Investigations**:
   Each investigator can be assigned to multiple investigations.