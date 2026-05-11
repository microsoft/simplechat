### Nanomaterials and Smart Materials

```sql
-- 1. Materials registry
CREATE TABLE Materials (
    MaterialID INT IDENTITY(1,1) PRIMARY KEY,
    Name VARCHAR(150) NOT NULL,
    Type VARCHAR(100) NOT NULL,        -- e.g., Nanostructured, Smart Polymer
    Composition TEXT,                  -- chemical or structural description
    DateCreated DATE DEFAULT GETDATE(),
    Status VARCHAR(50) DEFAULT 'Active'
);

-- 2. Properties catalog
CREATE TABLE Properties (
    PropertyID INT IDENTITY(1,1) PRIMARY KEY,
    Name VARCHAR(100) NOT NULL,        -- e.g., Tensile Strength, Thermal Conductivity
    Unit VARCHAR(20) NOT NULL,         -- e.g., GPa, W/mK
    Description TEXT
);

-- 3. Researchers
CREATE TABLE Researchers (
    ResearcherID INT IDENTITY(1,1) PRIMARY KEY,
    FirstName VARCHAR(100) NOT NULL,
    LastName VARCHAR(100) NOT NULL,
    Affiliation VARCHAR(150),          -- e.g., university or federal lab
    Email VARCHAR(150)
);

-- 4. Experiments
CREATE TABLE Experiments (
    ExperimentID INT IDENTITY(1,1) PRIMARY KEY,
    MaterialID INT NOT NULL,
    ResearcherID INT NOT NULL,
    StartDate DATE,
    EndDate DATE,
    Objective TEXT,
    Status VARCHAR(50) DEFAULT 'Ongoing',
    FOREIGN KEY (MaterialID) REFERENCES Materials(MaterialID),
    FOREIGN KEY (ResearcherID) REFERENCES Researchers(ResearcherID)
);

-- 5. Measurements
CREATE TABLE Measurements (
    MeasurementID BIGINT IDENTITY(1,1) PRIMARY KEY,
    ExperimentID INT NOT NULL,
    PropertyID INT NOT NULL,
    MeasuredValue NUMERIC(12,6) NOT NULL,
    MeasurementTimestamp DATETIME DEFAULT GETDATE(),
    Notes TEXT,
    FOREIGN KEY (ExperimentID) REFERENCES Experiments(ExperimentID),
    FOREIGN KEY (PropertyID) REFERENCES Properties(PropertyID)
);

```

### **Schema Notes**

- **Materials → Experiments → Measurements**:
   Each material can be tested in multiple experiments; experiments record precise measurements for different properties.
- **Researchers ↔ Experiments**:
   Researchers can lead multiple experiments, associating personnel with experimental data.
- Supports tracking **nanomaterials and smart materials**, analyzing **property performance**, and identifying **trends or anomalies** across materials.