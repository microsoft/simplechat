### Air Traffic Management

```sql
-- 1. ControlCenters (regional ATC centers)
CREATE TABLE ControlCenters (
    ControlCenterID INT PRIMARY KEY IDENTITY(1,1),
    Name NVARCHAR(100) NOT NULL,
    Region NVARCHAR(100) NOT NULL,
    Location NVARCHAR(200)
);

-- 2. Controllers (staff at each center)
CREATE TABLE Controllers (
    ControllerID INT PRIMARY KEY IDENTITY(1,1),
    Name NVARCHAR(100) NOT NULL,
    Rank NVARCHAR(50),
    ControlCenterID INT NOT NULL,
    FOREIGN KEY (ControlCenterID) REFERENCES ControlCenters(ControlCenterID)
);

-- 3. Routes (planned flight paths)
CREATE TABLE Routes (
    RouteID INT PRIMARY KEY IDENTITY(1,1),
    RouteCode NVARCHAR(50) NOT NULL UNIQUE,
    Origin NVARCHAR(100) NOT NULL,
    Destination NVARCHAR(100) NOT NULL,
    PlannedDurationMinutes INT
);

-- 4. Flights (real-time tracked flights)
CREATE TABLE Flights (
    FlightID INT PRIMARY KEY IDENTITY(1,1),
    FlightNumber NVARCHAR(20) NOT NULL,
    Airline NVARCHAR(100),
    DepartureTime DATETIME NOT NULL,
    ArrivalTime DATETIME,
    Status NVARCHAR(50) CHECK (Status IN ('Scheduled','En Route','Landed','Cancelled','Diverted')),
    ControllerID INT NOT NULL,
    RouteID INT NOT NULL,
    FOREIGN KEY (ControllerID) REFERENCES Controllers(ControllerID),
    FOREIGN KEY (RouteID) REFERENCES Routes(RouteID)
);

-- 5. Alerts (weather, traffic congestion, or reroutes)
CREATE TABLE Alerts (
    AlertID INT PRIMARY KEY IDENTITY(1,1),
    FlightID INT NOT NULL,
    AlertType NVARCHAR(50) CHECK (AlertType IN ('Weather','Traffic Congestion','Reroute','Emergency')),
    Description NVARCHAR(255),
    Timestamp DATETIME DEFAULT GETDATE(),
    Severity NVARCHAR(20) CHECK (Severity IN ('Low','Medium','High','Critical')),
    FOREIGN KEY (FlightID) REFERENCES Flights(FlightID)
);
```

### **Schema Notes**

- **ControlCenters → Controllers → Flights → Alerts**:
   Each ATC center manages multiple controllers, each controller handles multiple flights, and each flight can generate multiple alerts.
- **Routes ↔ Flights**:
   Each flight follows a planned route; currently one-to-one, but could be extended with a junction table for dynamic rerouting.
- Supports tracking **real-time flight operations**, **controller assignments**, **route planning**, and **alert management** for air traffic control.