## Purpose

This dataset demonstrates **Situational Awareness Reporting** by simulating locations, stations, sensor feeds, PIREPs, hazards, alerts, and maintenance actions. It allows you to showcase how operators, investigators, or dispatchers can monitor real-time hazards, link reports across sources, and ensure corrective actions are tracked against active alerts.

Generate situational awareness reports similar to **NOTAMs** (Notice to Airmen). Track hazards and conditions that directly affect current operations such as wind shear, unreliable navigation aids, pilot reports, bird hazards, and maintenance actions. Enable investigators, operators, or dispatchers to answer questions like what hazards are active now, which stations are unreliable, and whether maintenance is already assigned.

------

## Tables and Relationships

**Locations** – airports, navaids, or general geographic points.
 **Stations** – sensors, radar, ILS, VOR, or IoT devices tied to a location.
 **SensorReadings** – time-series reports from stations (wind shear, vibration, signal strength).
 **Alerts** – NOTAM-like alerts generated from readings, PIREPs, hazards, or rules.
 **PIREPs** – pilot reports (e.g., wind shear, bird strike).
 **Hazards** – structured hazard observations (e.g., bird population spikes).
 **MaintenanceActions** – predictive or corrective maintenance tasks triggered by alerts.
 **WeatherFetchLog** – history of calls to external weather APIs for situational enrichment.
 **AlertLinks** – optional cross-link between alerts and PIREPs, Hazards, or Maintenance.

**Relationships:**

- Locations → Stations → SensorReadings
- SensorReadings → Alerts
- Alerts ↔ PIREPs, Hazards, MaintenanceActions (via AlertLinks)
- Alerts → MaintenanceActions (triggered work orders)
- WeatherFetchLog → Locations

------

## SQL Table Creation Script

```sql
-- 1. Locations
CREATE TABLE Locations (
    LocationID INT IDENTITY(1,1) PRIMARY KEY,
    Name VARCHAR(200),
    FAAIdentifier VARCHAR(20),
    Latitude DECIMAL(9,6) NOT NULL,
    Longitude DECIMAL(9,6) NOT NULL,
    ElevationFeet INT,
    Type VARCHAR(50) -- Airport, VOR, Fix, Airspace
);

-- 2. Stations
CREATE TABLE Stations (
    StationID INT IDENTITY(1,1) PRIMARY KEY,
    LocationID INT NOT NULL REFERENCES Locations(LocationID),
    StationType VARCHAR(100) NOT NULL,  -- Radar, ILS, VOR, IoT
    Identifier VARCHAR(100),
    InstallDate DATE,
    Status VARCHAR(50) DEFAULT 'Active',
    Metadata NVARCHAR(MAX)   -- JSONB equivalent in SQL Server
);

-- 3. SensorReadings
CREATE TABLE SensorReadings (
    ReadingID BIGINT IDENTITY(1,1) PRIMARY KEY,
    StationID INT NOT NULL REFERENCES Stations(StationID),
    ReadingTimestamp DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    SensorType VARCHAR(100),            -- WindShear, Vibration, SignalStrength
    Value DECIMAL(14,6),
    Unit VARCHAR(50),
    RawPayload NVARCHAR(MAX),
    CONSTRAINT sensor_ts_not_future CHECK (ReadingTimestamp <= DATEADD(MINUTE,1,SYSUTCDATETIME()))
);

-- 4. Alerts (NOTAM-like)
CREATE TABLE Alerts (
    AlertID INT IDENTITY(1,1) PRIMARY KEY,
    AlertType VARCHAR(100) NOT NULL,    -- WindShear, SensorFailure, BirdHazard, PIREP
    Title VARCHAR(300) NOT NULL,
    Description NVARCHAR(MAX),
    LocationID INT REFERENCES Locations(LocationID),
    StationID INT REFERENCES Stations(StationID),
    RelatedReadingID BIGINT REFERENCES SensorReadings(ReadingID),
    Severity VARCHAR(20) DEFAULT 'Medium',
    CreatedAt DATETIME2 DEFAULT SYSUTCDATETIME(),
    EffectiveFrom DATETIME2,
    EffectiveTo DATETIME2,
    IsActive BIT DEFAULT 1,
    Source VARCHAR(100),
    Extra NVARCHAR(MAX)
);

-- 5. PIREPs
CREATE TABLE PIREPs (
    PIREPID INT IDENTITY(1,1) PRIMARY KEY,
    ReportTimestamp DATETIME2 NOT NULL,
    ReportingPilot VARCHAR(200),
    AircraftType VARCHAR(100),
    LocationID INT REFERENCES Locations(LocationID),
    AltitudeFeet INT,
    ReportText NVARCHAR(MAX),
    ContainsWindShear BIT DEFAULT 0,
    ContainsBirdStrike BIT DEFAULT 0,
    RawPayload NVARCHAR(MAX)
);

-- 6. Hazards
CREATE TABLE Hazards (
    HazardID INT IDENTITY(1,1) PRIMARY KEY,
    HazardType VARCHAR(100) NOT NULL,   -- BirdPopulation, FOD, Wildlife
    LocationID INT REFERENCES Locations(LocationID),
    ObservationTimestamp DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    Severity VARCHAR(20),
    CountEstimate INT,
    Notes NVARCHAR(MAX),
    ReportSource VARCHAR(100),
    Extra NVARCHAR(MAX)
);

-- 7. MaintenanceActions
CREATE TABLE MaintenanceActions (
    MaintenanceID INT IDENTITY(1,1) PRIMARY KEY,
    StationID INT NOT NULL REFERENCES Stations(StationID),
    TriggerAlertID INT REFERENCES Alerts(AlertID),
    ActionRequested NVARCHAR(MAX) NOT NULL,
    Priority VARCHAR(20) DEFAULT 'Normal',
    AssignedTo VARCHAR(200),
    RequestedAt DATETIME2 DEFAULT SYSUTCDATETIME(),
    PerformedAt DATETIME2,
    Status VARCHAR(50) DEFAULT 'Open',
    Notes NVARCHAR(MAX)
);

-- 8. WeatherFetchLog
CREATE TABLE WeatherFetchLog (
    FetchID BIGINT IDENTITY(1,1) PRIMARY KEY,
    LocationID INT REFERENCES Locations(LocationID),
    FetchTimestamp DATETIME2 DEFAULT SYSUTCDATETIME(),
    Provider VARCHAR(100),
    Summary NVARCHAR(MAX),
    RawResponse NVARCHAR(MAX),
    Success BIT DEFAULT 1
);

-- 9. AlertLinks
CREATE TABLE AlertLinks (
    AlertID INT NOT NULL REFERENCES Alerts(AlertID),
    LinkedType VARCHAR(50) NOT NULL,    -- 'PIREP', 'Hazard', 'Maintenance'
    LinkedID BIGINT NOT NULL,
    PRIMARY KEY (AlertID, LinkedType, LinkedID)
);

```

------

## Example Use Cases

1. **What active NOTAM-like alerts exist for my airport?**
    Query `Alerts` joined with `Locations` where `IsActive = TRUE`.
2. **Which stations are degraded and have open maintenance?**
    Query `Stations` left-joined with `MaintenanceActions` where `Status <> 'Completed'`.
3. **What PIREPs in the last 24 hours reported wind shear near my location?**
    Filter `PIREPs` by `ContainsWindShear = TRUE` and `ReportTimestamp >= NOW() - 1 day`.
4. **Are there elevated bird populations in the last 6 hours?**
    Query `Hazards` where `HazardType = 'BirdPopulation'` and `CountEstimate > threshold`.
5. **When was the last weather API call for this airport, and what did it report?**
    Query `WeatherFetchLog` by `LocationID` ordered by `FetchTimestamp DESC`.

### Recommended example queries

1. Active NOTAM-like alerts for my current location (by FAA identifier):

```
SELECT a.AlertID, a.Title, a.Description, a.Severity, a.CreatedAt
FROM Alerts a
JOIN Locations l ON a.LocationID = l.LocationID
WHERE l.FAAIdentifier = 'KXYZ' AND a.IsActive = TRUE
ORDER BY a.Severity DESC, a.CreatedAt DESC;
```

1. Recent sensor-derived wind shear alerts within last 30 minutes:

```
SELECT a.AlertID, a.Title, sr.ReadingTimestamp, sr.Value, sr.Unit, s.Identifier AS StationIdentifier
FROM Alerts a
JOIN SensorReadings sr ON a.RelatedReadingID = sr.ReadingID
JOIN Stations s ON sr.StationID = s.StationID
WHERE a.AlertType = 'WindShear' AND sr.ReadingTimestamp >= now() - INTERVAL '30 minutes'
ORDER BY sr.ReadingTimestamp DESC;
```

1. Identify VHF omnidirectional range station showing degraded signal and any open maintenance:

```
SELECT s.StationID, s.Identifier, s.Status, m.MaintenanceID, m.Status AS MaintStatus, m.AssignedTo
FROM Stations s
LEFT JOIN MaintenanceActions m ON s.StationID = m.StationID AND m.Status <> 'Completed'
WHERE s.StationType = 'VOR' AND s.Status IN ('Degraded', 'Offline');
```

1. PIREPs that mention wind shear near a location in the last 24 hours:

```
SELECT p.PIREPID, p.ReportTimestamp, p.ReportingPilot, p.ReportText
FROM PIREPs p
JOIN Locations l ON p.LocationID = l.LocationID
WHERE p.ContainsWindShear = TRUE
  AND p.ReportTimestamp >= now() - INTERVAL '24 hours'
  AND l.FAAIdentifier = 'KXYZ';
```

1. Bird hazard threshold check to create an alert if count exceeds threshold T (example logic you would implement in app):

```
-- Example: find recent bird observations above threshold for operator to create an alert
SELECT h.HazardID, h.ObservationTimestamp, h.CountEstimate, l.Name, l.FAAIdentifier
FROM Hazards h
JOIN Locations l ON h.LocationID = l.LocationID
WHERE h.HazardType = 'BirdPopulation'
  AND h.CountEstimate > 50
  AND h.ObservationTimestamp >= now() - INTERVAL '6 hours';
```

### Notes and integration tips

- Use `SensorReadings.RawPayload` and `WeatherFetchLog.RawResponse` to store full API or sensor messages for forensic purposes while keeping parsed fields for fast queries.
- Predictive maintenance workflows typically run analysis jobs over `SensorReadings` to detect trends. When a rule triggers, create an `Alerts` row and link it to `MaintenanceActions`.
- For performance, create time-partitioning or retention policies on `SensorReadings` and `WeatherFetchLog` if you ingest high-frequency data.
- Keep PII handling policies in mind for `ReportingPilot` and any personnel fields in OIG or FAA contexts.

If you want, I can:
 • Produce sample insert statements with realistic examples (radar wind shear reading, a VOR reporting degraded signal, a PIREP noting wind shear, a bird hazard).
 • Add a stored procedure or job SQL that converts qualifying sensor readings into alerts and optionally opens maintenance tickets.