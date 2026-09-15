"""
SmartPark - Database layer (SQLite)

This module owns:
  - the SQLite schema (tables, foreign keys, constraints)
  - a get_db() connection helper used by app.py
  - init_db() / seed_db() which create real rows in the database

IMPORTANT: the values generated here are SEED DATA ONLY. They exist so the
application has real rows to query on first run. Every number shown in the
UI (totals, availability, revenue, occupancy %, hourly demand, etc.) is
computed at request time from these rows via SQL in app.py - nothing is
hardcoded on the frontend.
"""

import sqlite3
import random
import uuid
from datetime import datetime, timedelta

DB_PATH = "parking.db"

# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    phone TEXT,
    password_hash TEXT NOT NULL DEFAULT 'demo-no-auth',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vehicles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    vehicle_number TEXT UNIQUE NOT NULL,
    vehicle_type TEXT NOT NULL CHECK (vehicle_type IN ('CAR','BIKE','EV')),
    is_ev INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS parking_zones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    location TEXT,
    total_slots INTEGER NOT NULL DEFAULT 0,
    description TEXT
);

CREATE TABLE IF NOT EXISTS parking_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zone_id INTEGER NOT NULL,
    slot_number TEXT NOT NULL UNIQUE,
    slot_type TEXT NOT NULL DEFAULT 'CAR',
    status TEXT NOT NULL CHECK (status IN ('AVAILABLE','RESERVED','OCCUPIED','MAINTENANCE')) DEFAULT 'AVAILABLE',
    floor INTEGER NOT NULL DEFAULT 1,
    sensor_status TEXT NOT NULL DEFAULT 'OK',
    FOREIGN KEY (zone_id) REFERENCES parking_zones(id)
);

CREATE TABLE IF NOT EXISTS reservations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    vehicle_id INTEGER NOT NULL,
    slot_id INTEGER NOT NULL,
    reservation_time TEXT NOT NULL,
    start_time TEXT,
    expected_end_time TEXT,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE','CANCELLED','COMPLETED','NO_SHOW')) DEFAULT 'ACTIVE',
    estimated_fee REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(id),
    FOREIGN KEY (slot_id) REFERENCES parking_slots(id)
);

CREATE TABLE IF NOT EXISTS parking_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reservation_id INTEGER,
    user_id INTEGER NOT NULL,
    vehicle_id INTEGER NOT NULL,
    slot_id INTEGER NOT NULL,
    entry_time TEXT NOT NULL,
    exit_time TEXT,
    duration_minutes INTEGER,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE','COMPLETED')) DEFAULT 'ACTIVE',
    final_fee REAL,
    FOREIGN KEY (reservation_id) REFERENCES reservations(id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(id),
    FOREIGN KEY (slot_id) REFERENCES parking_slots(id)
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    session_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    payment_method TEXT NOT NULL DEFAULT 'Demo Payment',
    payment_status TEXT NOT NULL CHECK (payment_status IN ('PAID','PENDING','FAILED')) DEFAULT 'PAID',
    transaction_reference TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (session_id) REFERENCES parking_sessions(id)
);

CREATE TABLE IF NOT EXISTS rewards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    points INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS parking_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slot_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('USER','ADMIN','SENSOR_SIMULATION','SEED')),
    timestamp TEXT NOT NULL,
    description TEXT,
    FOREIGN KEY (slot_id) REFERENCES parking_slots(id)
);
"""


def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def _table_has_rows(conn, table):
    return conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"] > 0


def seed_db(force=False):
    """Populate the database with realistic seed data. Safe to call every
    startup: it only seeds if the users table is empty, unless force=True
    (used by the admin 'Reset Demo Data' action)."""
    conn = get_db()

    if force:
        for t in ["parking_events", "rewards", "transactions", "parking_sessions",
                  "reservations", "vehicles", "parking_slots", "parking_zones", "users"]:
            conn.execute(f"DELETE FROM {t}")
        conn.execute("DELETE FROM sqlite_sequence")
        conn.commit()
    elif _table_has_rows(conn, "users"):
        conn.close()
        return  # already seeded

    rng = random.Random(42)  # fixed seed -> reproducible demo data
    now = datetime.now()

    # ---------------- Users ----------------
    demo_names = [
        ("Demo User", "demo@smartpark.local", "9999900000"),
        ("Aarav Sharma", "aarav.sharma@example.com", "9812300001"),
        ("Diya Verma", "diya.verma@example.com", "9812300002"),
        ("Kabir Singh", "kabir.singh@example.com", "9812300003"),
        ("Ananya Gupta", "ananya.gupta@example.com", "9812300004"),
        ("Vivaan Mehta", "vivaan.mehta@example.com", "9812300005"),
        ("Ishita Rathore", "ishita.rathore@example.com", "9812300006"),
        ("Rohan Kapoor", "rohan.kapoor@example.com", "9812300007"),
        ("Saanvi Joshi", "saanvi.joshi@example.com", "9812300008"),
        ("Aditya Nair", "aditya.nair@example.com", "9812300009"),
        ("Meera Iyer", "meera.iyer@example.com", "9812300010"),
        ("Arjun Malhotra", "arjun.malhotra@example.com", "9812300011"),
        ("Kavya Reddy", "kavya.reddy@example.com", "9812300012"),
    ]
    user_ids = []
    for name, email, phone in demo_names:
        cur = conn.execute(
            "INSERT INTO users (name, email, phone, password_hash, created_at) VALUES (?,?,?,?,?)",
            (name, email, phone, "demo-no-auth", now_str()),
        )
        user_ids.append(cur.lastrowid)
    demo_user_id = user_ids[0]

    # ---------------- Vehicles ----------------
    plate_prefixes = ["RJ14", "RJ45", "DL01", "DL08", "HR26", "UP14"]
    vehicle_type_choices = [("CAR", 0), ("BIKE", 0), ("EV", 1)]
    vehicle_ids = {}  # user_id -> [vehicle_id,...]
    used_plates = set()

    def gen_plate():
        while True:
            prefix = rng.choice(plate_prefixes)
            letters = "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(2))
            digits = rng.randint(1000, 9999)
            plate = f"{prefix}{letters}{digits}"
            if plate not in used_plates:
                used_plates.add(plate)
                return plate

    # Demo user gets a fixed, presentable vehicle
    demo_plate = "RJ14XX1234"
    used_plates.add(demo_plate)
    cur = conn.execute(
        "INSERT INTO vehicles (user_id, vehicle_number, vehicle_type, is_ev, created_at) VALUES (?,?,?,?,?)",
        (demo_user_id, demo_plate, "CAR", 0, now_str()),
    )
    vehicle_ids[demo_user_id] = [cur.lastrowid]

    for uid in user_ids[1:]:
        n_vehicles = rng.choice([1, 1, 1, 2])
        vehicle_ids[uid] = []
        for _ in range(n_vehicles):
            vtype, is_ev = rng.choice(vehicle_type_choices)
            plate = gen_plate()
            cur = conn.execute(
                "INSERT INTO vehicles (user_id, vehicle_number, vehicle_type, is_ev, created_at) VALUES (?,?,?,?,?)",
                (uid, plate, vtype, is_ev, now_str()),
            )
            vehicle_ids[uid].append(cur.lastrowid)

    # ---------------- Zones & Slots ----------------
    zones = [
        ("Zone A", "Main Academic Block", 20, "Parking adjacent to the main academic block"),
        ("Zone B", "Library Parking", 20, "Parking behind the central library"),
        ("Zone C", "Student Parking", 20, "Open student parking ground"),
    ]
    zone_ids = []
    for name, location, total, desc in zones:
        cur = conn.execute(
            "INSERT INTO parking_zones (name, location, total_slots, description) VALUES (?,?,?,?)",
            (name, location, total, desc),
        )
        zone_ids.append(cur.lastrowid)

    # target initial mix across the whole lot: 35 available / 20 occupied / 5 reserved (of 60)
    zone_letters = ["A", "B", "C"]
    zone_mix = [
        {"AVAILABLE": 12, "OCCUPIED": 7, "RESERVED": 1},
        {"AVAILABLE": 12, "OCCUPIED": 6, "RESERVED": 2},
        {"AVAILABLE": 11, "OCCUPIED": 7, "RESERVED": 2},
    ]

    slot_ids_by_status = {"AVAILABLE": [], "OCCUPIED": [], "RESERVED": []}
    slot_zone_map = {}
    slot_number_to_id = {}

    for zi, zone_id in enumerate(zone_ids):
        letter = zone_letters[zi]
        mix = zone_mix[zi]
        statuses = (["AVAILABLE"] * mix["AVAILABLE"] + ["OCCUPIED"] * mix["OCCUPIED"]
                    + ["RESERVED"] * mix["RESERVED"])
        rng.shuffle(statuses)
        for i in range(20):
            slot_number = f"{letter}{i+1:02d}"
            status = statuses[i]
            floor = 1 if i < 10 else 2
            cur = conn.execute(
                "INSERT INTO parking_slots (zone_id, slot_number, slot_type, status, floor, sensor_status) "
                "VALUES (?,?,?,?,?,?)",
                (zone_id, slot_number, "CAR", status, floor, "OK"),
            )
            slot_id = cur.lastrowid
            slot_ids_by_status[status].append(slot_id)
            slot_zone_map[slot_id] = zone_id
            slot_number_to_id[slot_number] = slot_id

    # a couple of slots under maintenance for realism (kept out of the 60 count example)
    for slot_number in [f"{zone_letters[0]}05"]:
        pass  # keep demo numbers exactly matching the spec (35/20/5 of 60); no maintenance slots

    RATES = {"BIKE": 10, "CAR": 20, "EV": 25}

    def fee_for(vtype, minutes, start_dt):
        rate = RATES.get(vtype, 20)
        hours = minutes / 60.0
        amount = rate * hours
        if is_peak(start_dt):
            amount *= 1.5
        return round(amount, 2)

    def is_peak(dt):
        return dt.hour in (8, 9, 10, 17, 18, 19)

    # ---------------- Active reservations for RESERVED slots ----------------
    other_user_ids = user_ids[1:]
    for slot_id in slot_ids_by_status["RESERVED"]:
        uid = rng.choice(other_user_ids)
        vid = rng.choice(vehicle_ids[uid])
        vtype = conn.execute("SELECT vehicle_type FROM vehicles WHERE id=?", (vid,)).fetchone()["vehicle_type"]
        made = now - timedelta(minutes=rng.randint(2, 25))
        duration = rng.choice([30, 60, 120])
        end = made + timedelta(minutes=duration)
        est_fee = fee_for(vtype, duration, made)
        conn.execute(
            "INSERT INTO reservations (user_id, vehicle_id, slot_id, reservation_time, start_time, "
            "expected_end_time, status, estimated_fee, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (uid, vid, slot_id, made.strftime("%Y-%m-%d %H:%M:%S"), made.strftime("%Y-%m-%d %H:%M:%S"),
             end.strftime("%Y-%m-%d %H:%M:%S"), "ACTIVE", est_fee, made.strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.execute(
            "INSERT INTO parking_events (slot_id, event_type, source, timestamp, description) VALUES (?,?,?,?,?)",
            (slot_id, "RESERVED", "SEED", made.strftime("%Y-%m-%d %H:%M:%S"), "Seed reservation created"),
        )

    # ---------------- Active sessions for OCCUPIED slots ----------------
    for slot_id in slot_ids_by_status["OCCUPIED"]:
        uid = rng.choice(other_user_ids)
        vid = rng.choice(vehicle_ids[uid])
        vtype = conn.execute("SELECT vehicle_type FROM vehicles WHERE id=?", (vid,)).fetchone()["vehicle_type"]
        entry = now - timedelta(minutes=rng.randint(15, 180))
        conn.execute(
            "INSERT INTO parking_sessions (reservation_id, user_id, vehicle_id, slot_id, entry_time, "
            "status) VALUES (?,?,?,?,?,?)",
            (None, uid, vid, slot_id, entry.strftime("%Y-%m-%d %H:%M:%S"), "ACTIVE"),
        )
        conn.execute(
            "INSERT INTO parking_events (slot_id, event_type, source, timestamp, description) VALUES (?,?,?,?,?)",
            (slot_id, "OCCUPIED", "SEED", entry.strftime("%Y-%m-%d %H:%M:%S"), "Seed vehicle parked"),
        )

    # ---------------- Historical completed sessions (for History / Analytics) ----------------
    all_slot_ids = list(slot_zone_map.keys())
    for day_offset in range(6, 0, -1):
        day = now - timedelta(days=day_offset)
        n_sessions = rng.randint(10, 16)
        for _ in range(n_sessions):
            uid = rng.choice(user_ids)  # include demo user occasionally
            vid = rng.choice(vehicle_ids[uid])
            vtype = conn.execute("SELECT vehicle_type FROM vehicles WHERE id=?", (vid,)).fetchone()["vehicle_type"]
            slot_id = rng.choice(all_slot_ids)
            hour = rng.choices(
                population=list(range(6, 23)),
                weights=[1, 2, 3, 5, 6, 4, 3, 3, 4, 5, 6, 7, 6, 5, 4, 3, 2],
            )[0]
            entry = day.replace(hour=hour, minute=rng.randint(0, 59), second=0, microsecond=0)
            duration = rng.choice([30, 45, 60, 90, 120, 150, 180])
            exit_dt = entry + timedelta(minutes=duration)
            final_fee = fee_for(vtype, duration, entry)

            cur = conn.execute(
                "INSERT INTO parking_sessions (reservation_id, user_id, vehicle_id, slot_id, entry_time, "
                "exit_time, duration_minutes, status, final_fee) VALUES (?,?,?,?,?,?,?,?,?)",
                (None, uid, vid, slot_id, entry.strftime("%Y-%m-%d %H:%M:%S"),
                 exit_dt.strftime("%Y-%m-%d %H:%M:%S"), duration, "COMPLETED", final_fee),
            )
            session_id = cur.lastrowid
            ref = f"TXN-{uuid.uuid4().hex[:10].upper()}"
            conn.execute(
                "INSERT INTO transactions (user_id, session_id, amount, payment_method, payment_status, "
                "transaction_reference, created_at) VALUES (?,?,?,?,?,?,?)",
                (uid, session_id, final_fee, "Demo Payment", "PAID", ref, exit_dt.strftime("%Y-%m-%d %H:%M:%S")),
            )
            conn.execute(
                "INSERT INTO parking_events (slot_id, event_type, source, timestamp, description) VALUES (?,?,?,?,?)",
                (slot_id, "ENTRY", "SEED", entry.strftime("%Y-%m-%d %H:%M:%S"), "Historical demo entry"),
            )
            conn.execute(
                "INSERT INTO parking_events (slot_id, event_type, source, timestamp, description) VALUES (?,?,?,?,?)",
                (slot_id, "EXIT", "SEED", exit_dt.strftime("%Y-%m-%d %H:%M:%S"), "Historical demo exit"),
            )
            conn.execute(
                "INSERT INTO rewards (user_id, points, reason, created_at) VALUES (?,?,?,?)",
                (uid, 10, "On-time exit", exit_dt.strftime("%Y-%m-%d %H:%M:%S")),
            )

    # a couple of no-shows / cancellations for realistic reward history
    for uid in rng.sample(other_user_ids, 3):
        vid = rng.choice(vehicle_ids[uid])
        slot_id = rng.choice(all_slot_ids)
        made = now - timedelta(days=rng.randint(1, 5), hours=rng.randint(1, 10))
        conn.execute(
            "INSERT INTO reservations (user_id, vehicle_id, slot_id, reservation_time, start_time, "
            "expected_end_time, status, estimated_fee, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (uid, vid, slot_id, made.strftime("%Y-%m-%d %H:%M:%S"), made.strftime("%Y-%m-%d %H:%M:%S"),
             (made + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"), "NO_SHOW", 20.0,
             made.strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.execute(
            "INSERT INTO rewards (user_id, points, reason, created_at) VALUES (?,?,?,?)",
            (uid, -15, "No-show", made.strftime("%Y-%m-%d %H:%M:%S")),
        )

    conn.commit()
    conn.close()
