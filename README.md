# SmartPark — Smart Parking Management System

> Evolved from the original PBL project **"Smart Resource Booking & Management System"**
> (Vatsal Sharma, 2427030235, Manipal University Jaipur — Guide: Ms. Harshika Mathur)

A functional full-stack local prototype: Flask + SQLite backend, vanilla HTML/CSS/JS frontend.
Every number shown in the UI (slot counts, occupancy %, revenue, hourly demand, rewards) is
computed live from real SQLite rows — nothing is hardcoded in the frontend.

---

## Problem Statement

Parking availability is difficult to determine in real time, leading to unnecessary searching,
congestion, inefficient utilization of space, and poor parking management.

## Solution

A centralized smart parking platform covering:
- Parking discovery across zones
- Slot reservation with backend-calculated pricing
- Occupancy tracking (live, per zone)
- Parking sessions (start / active timer / exit)
- Simulated demo payments and digital receipts
- Parking history with filtering
- SmartPark Rewards (points ledger)
- Admin dashboard: slot management, revenue, activity log
- A **sensor simulation** layer that mirrors a future real IoT integration

---

## Technology Stack

| Layer     | Technology                          |
|-----------|--------------------------------------|
| Frontend  | HTML5, CSS3, Vanilla JavaScript, Chart.js |
| Backend   | Python 3, Flask                      |
| Database  | SQLite (file: `parking.db`)          |

No React/Node/Docker/cloud services/external paid APIs are used — everything runs locally.

---

## Architecture

```
USER ACTION → FRONTEND (fetch) → FLASK API → SQLite → UPDATED ROWS → FRONTEND RE-RENDERS
```

```
project/
├── app.py                 # Flask app + all API routes + business logic
├── database.py            # Schema (CREATE TABLE ...) + seed data generator
├── requirements.txt
├── parking.db              # created on first run
├── templates/
│   ├── index.html          # PBL presentation / landing page
│   ├── parking.html        # SmartPark user app (Dashboard, Find Parking, My Parking, History, Rewards)
│   └── admin.html          # Admin dashboard
├── static/
│   ├── css/style.css
│   └── js/
│       ├── app.js          # user app logic (all data via fetch())
│       └── admin.js        # admin dashboard logic
└── README.md
```

---

## Database Schema

9 tables, with foreign keys enforced (`PRAGMA foreign_keys = ON`):

- **users** — id, name, email, phone, password_hash (demo auth only), created_at
- **vehicles** — id, user_id → users, vehicle_number, vehicle_type (CAR/BIKE/EV), is_ev, created_at
- **parking_zones** — id, name, location, total_slots, description
- **parking_slots** — id, zone_id → parking_zones, slot_number, slot_type, status
  (AVAILABLE/RESERVED/OCCUPIED/MAINTENANCE), floor, sensor_status
- **reservations** — id, user_id, vehicle_id, slot_id, reservation_time, start_time,
  expected_end_time, status (ACTIVE/CANCELLED/COMPLETED/NO_SHOW), estimated_fee, created_at
- **parking_sessions** — id, reservation_id, user_id, vehicle_id, slot_id, entry_time,
  exit_time, duration_minutes, status (ACTIVE/COMPLETED), final_fee
- **transactions** — id, user_id, session_id, amount, payment_method, payment_status
  (PAID/PENDING/FAILED), transaction_reference, created_at
- **rewards** — id, user_id, points, reason, created_at
- **parking_events** — id, slot_id, event_type, source (USER/ADMIN/SENSOR_SIMULATION/SEED),
  timestamp, description

Seed data (generated once, on first run, with a fixed random seed for reproducibility):
- 3 zones (Zone A – Main Academic Block, Zone B – Library Parking, Zone C – Student Parking), 20 slots each = 60 slots
- Initial mix: 35 AVAILABLE / 20 OCCUPIED / 5 RESERVED (matching the brief exactly)
- 13 users (including the demo user) with realistic Indian vehicle numbers (no real personal data)
- ~6 days of historical parking sessions + transactions + reward records for History/Analytics
- Live `ACTIVE` reservations and sessions backing the seeded RESERVED/OCCUPIED slots

---

## How to Install & Run

1. Install Python 3.10+.
2. Open a terminal in the project folder.
3. `pip install -r requirements.txt`
4. `python app.py`
5. Open **http://127.0.0.1:5000**

The database (`parking.db`) and all seed data are created automatically on first run.

---

## Demo Mode

There is no login screen — the app runs as a single **Demo User** (seeded with vehicle
`RJ14XX1234`), so the whole flow (reserve → start → exit → receipt → rewards) can be
demonstrated immediately without setting up authentication.

---

## Pricing (backend-configured, in `app.py`)

| Vehicle | Rate/hour |
|---------|-----------|
| Bike    | ₹10       |
| Car     | ₹20       |
| EV      | ₹25       |

Peak hours: 08:00–11:00 and 17:00–20:00 → **1.5×** multiplier. All fees are calculated
server-side (`calculate_fee()` in `app.py`); the frontend only shows a live *preview* before
confirming — the authoritative amount always comes back from the API response.

---

## Main API Endpoints

```
GET    /api/dashboard                 Dashboard KPIs + current session/reservation
GET    /api/zones                     Zones with live counts + occupancy %
GET    /api/zones/<id>/slots          Slot map for a zone
POST   /api/reservations              Create a reservation (AVAILABLE → RESERVED)
POST   /api/reservations/<id>/cancel  Cancel an active reservation
GET    /api/parking/current           Active session/reservation for the demo user
POST   /api/parking/start             RESERVED → OCCUPIED, creates a parking session
POST   /api/parking/exit              Ends session, creates transaction + receipt
GET    /api/parking/history           Filterable transaction/session history
GET    /api/rewards                   Reward points + history
GET    /api/admin/dashboard           Admin KPIs incl. today's revenue/vehicles
GET    /api/admin/activity            Recent parking_events log
GET    /api/admin/hourly-demand       Hourly session counts (for the demand chart)
POST   /api/admin/slots               Add a new slot
PATCH  /api/admin/slots/<id>          Set slot to AVAILABLE/MAINTENANCE (warns on OCCUPIED override)
POST   /api/admin/reset-demo          Re-seed the database (requires confirm:true)
POST   /api/sensor/detect             Simulated sensor: AVAILABLE → OCCUPIED
POST   /api/sensor/exit               Simulated sensor: OCCUPIED → AVAILABLE
GET    /api/config                    Exposes rates/peak-hours to the frontend (read-only)
```

---

## 5-Minute Demo Flow

1. Open `/` → click **Launch SmartPark**.
2. **Dashboard** loads live totals from SQLite.
3. **Find Parking** → pick Zone A → click an AVAILABLE slot (e.g. A03).
4. Enter a vehicle number, pick **2 hours** → see the backend-calculated estimated fee → **Confirm Reservation**.
   Slot flips AVAILABLE → RESERVED in the database and on the map.
5. **My Parking** → **Start Parking** → slot flips RESERVED → OCCUPIED, a session starts, a live timer runs off the real `entry_time`.
6. **Exit Parking** → backend computes actual duration + final fee, creates a `transactions` row, shows the receipt.
7. **History** → the completed session appears with its real transaction reference.
8. **Admin Dashboard** → occupancy, available count and today's revenue have all changed; the activity log shows every step.
9. **Sensor Simulation** (Admin) → type a slot number → **VEHICLE DETECTED** / **VEHICLE EXIT** → watch the slot and event log update from a simulated sensor source.

## IoT / Future Scope

Every slot carries a `sensor_status` field and every state change is logged in `parking_events`
with a `source` of `USER`, `ADMIN`, `SENSOR_SIMULATION`, or `SEED`. The Admin panel's
"Prototype Sensor Simulation" section demonstrates this pipeline end-to-end. **No physical
hardware is connected** — the simulation exists purely to prove the data model and API shape
that a real IoT sensor (e.g. an ultrasonic/IR sensor per bay reporting to `/api/sensor/detect`
and `/api/sensor/exit`) could call directly in a future deployment.

Other future scope: real payment gateway integration (currently a labelled "Demo Payment"
stored in `transactions`), proper user authentication, license-plate recognition at entry/exit
barriers, and predictive demand forecasting from the `parking_events` history.

---

## Known Limitations

- Single demo user, no real authentication (by design, for a fast demo).
- Real-time updates use polling (dashboard/admin refresh every ~15–20s, plus refresh-after-action), not WebSockets.
- Sensor simulation is a manual trigger, not connected to real hardware.
- Peak pricing is a flat multiplier applied once per booking based on the start hour, not a per-minute split across a peak/off-peak boundary.

---

## Academic Details

Department of Computer Science and Engineering, Manipal University Jaipur
Presented By: Vatsal Sharma (2427030235) · Project Guide: Ms. Harshika Mathur
