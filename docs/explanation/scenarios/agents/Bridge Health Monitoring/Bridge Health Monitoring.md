### Bridge Health Monitoring

```sql
-- 1. Bridges registry
CREATE TABLE Bridges (
    BridgeID SERIAL PRIMARY KEY,
    Name VARCHAR(150) NOT NULL,
    Location VARCHAR(255) NOT NULL,
    YearBuilt INT,
    Material VARCHAR(100),
    Status VARCHAR(50) DEFAULT 'Active'
);

-- 2. Sensors attached to bridges
CREATE TABLE Sensors (
    SensorID SERIAL PRIMARY KEY,
    BridgeID INT NOT NULL,
    SensorType VARCHAR(100) NOT NULL,  -- e.g., Strain Gauge, Accelerometer, Weather
    InstallDate DATE NOT NULL,
    Status VARCHAR(50) DEFAULT 'Active',
    FOREIGN KEY (BridgeID) REFERENCES Bridges(BridgeID)
);

-- 3. Sensor readings (IoT data points)
CREATE TABLE SensorReadings (
    ReadingID BIGSERIAL PRIMARY KEY,
    SensorID INT NOT NULL,
    ReadingTimestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    Value NUMERIC(12,4) NOT NULL,      -- e.g., vibration, strain
    Unit VARCHAR(20),                  -- e.g., psi, g-force, Celsius
    FOREIGN KEY (SensorID) REFERENCES Sensors(SensorID)
);

-- 4. Alerts triggered by abnormal readings
CREATE TABLE Alerts (
    AlertID SERIAL PRIMARY KEY,
    ReadingID BIGINT NOT NULL,
    AlertType VARCHAR(100) NOT NULL,   -- e.g., Threshold Breach, Sensor Failure
    Severity VARCHAR(20) NOT NULL,     -- Low, Medium, High, Critical
    CreatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    Resolved BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (ReadingID) REFERENCES SensorReadings(ReadingID)
);

-- 5. Maintenance actions linked to alerts
CREATE TABLE Maintenance (
    MaintenanceID SERIAL PRIMARY KEY,
    AlertID INT NOT NULL,
    ActionTaken VARCHAR(255) NOT NULL,
    PerformedBy VARCHAR(150),          -- e.g., engineer or company
    PerformedDate DATE,
    Notes TEXT,
    FOREIGN KEY (AlertID) REFERENCES Alerts(AlertID)
);
```

### **Schema Notes**

- **Bridges → Sensors**: Each bridge can have multiple sensors monitoring its structural health.
- **Sensors → SensorReadings**: Sensors generate time-series IoT data for analysis.
- **SensorReadings → Alerts**: Readings outside thresholds trigger alerts.
- **Alerts → Maintenance**: Each alert can generate one or more maintenance actions.
- Supports **real-time monitoring of bridge health**, **alerting for critical conditions**, and **tracking maintenance actions** for FAA/DOT infrastructure.