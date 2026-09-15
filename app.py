"""
SmartPark - Smart Parking Management System
Flask backend. Every figure returned to the frontend is computed here with
SQL against SQLite - nothing is hardcoded.

Run:
    pip install -r requirements.txt
    python app.py
Then open http://127.0.0.1:5000
"""

import sqlite3
import uuid
from datetime import datetime

from flask import Flask, jsonify, request, render_template, send_from_directory

import database
from database import get_db, init_db, seed_db, now_str

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Business config (backend is the single source of truth for pricing)
# ---------------------------------------------------------------------------
RATES_PER_HOUR = {"BIKE": 10, "CAR": 20, "EV": 25}
PEAK_HOURS = [(8, 11), (17, 20)]   # [start, end) in 24h, backend-configurable
PEAK_MULTIPLIER = 1.5
DEMO_USER_ID = 1  # first user created by the seeder ("Demo User")

VALID_VEHICLE_TYPES = ("CAR", "BIKE", "EV")
VALID_DURATIONS = (30, 60, 120, 180, 240)


def is_peak_hour(dt):
    h = dt.hour
    return any(start <= h < end for start, end in PEAK_HOURS)


def calculate_fee(vehicle_type, duration_minutes, reference_dt):
    rate = RATES_PER_HOUR.get(vehicle_type, RATES_PER_HOUR["CAR"])
    amount = rate * (duration_minutes / 60.0)
    peak = is_peak_hour(reference_dt)
    if peak:
        amount *= PEAK_MULTIPLIER
    return round(amount, 2), peak


def parse_dt(value):
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def error(message, code=400):
    return jsonify({"success": False, "error": message}), code


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@app.route("/")
def landing():
    return render_template("index.html")


@app.route("/app")
def parking_app():
    return render_template("parking.html")


@app.route("/admin")
def admin_app():
    return render_template("admin.html")


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.route("/api/dashboard")
def api_dashboard():
    conn = get_db()
    totals = conn.execute(
        "SELECT status, COUNT(*) c FROM parking_slots GROUP BY status"
    ).fetchall()
    counts = {"AVAILABLE": 0, "OCCUPIED": 0, "RESERVED": 0, "MAINTENANCE": 0}
    for row in totals:
        counts[row["status"]] = row["c"]
    total_slots = sum(counts.values())

    active_session = conn.execute(
        """SELECT ps.*, v.vehicle_number, v.vehicle_type, sl.slot_number, z.name AS zone_name
           FROM parking_sessions ps
           JOIN vehicles v ON v.id = ps.vehicle_id
           JOIN parking_slots sl ON sl.id = ps.slot_id
           JOIN parking_zones z ON z.id = sl.zone_id
           WHERE ps.user_id = ? AND ps.status = 'ACTIVE'
           ORDER BY ps.id DESC LIMIT 1""",
        (DEMO_USER_ID,),
    ).fetchone()

    active_reservation = None
    if not active_session:
        active_reservation = conn.execute(
            """SELECT r.*, v.vehicle_number, v.vehicle_type, sl.slot_number, z.name AS zone_name
               FROM reservations r
               JOIN vehicles v ON v.id = r.vehicle_id
               JOIN parking_slots sl ON sl.id = r.slot_id
               JOIN parking_zones z ON z.id = sl.zone_id
               WHERE r.user_id = ? AND r.status = 'ACTIVE'
               ORDER BY r.id DESC LIMIT 1""",
            (DEMO_USER_ID,),
        ).fetchone()

    conn.close()
    return jsonify({
        "success": True,
        "total_slots": total_slots,
        "available": counts["AVAILABLE"],
        "occupied": counts["OCCUPIED"],
        "reserved": counts["RESERVED"],
        "maintenance": counts["MAINTENANCE"],
        "active_session": dict(active_session) if active_session else None,
        "active_reservation": dict(active_reservation) if active_reservation else None,
    })


# ---------------------------------------------------------------------------
# Zones / Find Parking / Map
# ---------------------------------------------------------------------------

@app.route("/api/zones")
def api_zones():
    conn = get_db()
    zones = conn.execute("SELECT * FROM parking_zones").fetchall()
    result = []
    for z in zones:
        counts = conn.execute(
            "SELECT status, COUNT(*) c FROM parking_slots WHERE zone_id=? GROUP BY status",
            (z["id"],),
        ).fetchall()
        c = {"AVAILABLE": 0, "OCCUPIED": 0, "RESERVED": 0, "MAINTENANCE": 0}
        for row in counts:
            c[row["status"]] = row["c"]
        total = sum(c.values()) or z["total_slots"]
        occupancy_pct = round(((c["OCCUPIED"] + c["RESERVED"]) / total) * 100) if total else 0
        result.append({
            "id": z["id"], "name": z["name"], "location": z["location"],
            "description": z["description"], "total": total,
            "available": c["AVAILABLE"], "occupied": c["OCCUPIED"],
            "reserved": c["RESERVED"], "maintenance": c["MAINTENANCE"],
            "occupancy_pct": occupancy_pct,
        })
    conn.close()
    return jsonify({"success": True, "zones": result})


@app.route("/api/zones/<int:zone_id>/slots")
def api_zone_slots(zone_id):
    conn = get_db()
    slots = conn.execute(
        "SELECT * FROM parking_slots WHERE zone_id=? ORDER BY slot_number", (zone_id,)
    ).fetchall()
    conn.close()
    return jsonify({"success": True, "slots": [dict(s) for s in slots]})


# ---------------------------------------------------------------------------
# Reservations
# ---------------------------------------------------------------------------

@app.route("/api/reservations", methods=["POST"])
def api_create_reservation():
    data = request.get_json(force=True, silent=True) or {}
    slot_id = data.get("slot_id")
    vehicle_number = (data.get("vehicle_number") or "").strip().upper()
    vehicle_type = (data.get("vehicle_type") or "").strip().upper()
    duration = data.get("duration_minutes")

    if not slot_id:
        return error("Slot is required.")
    if not vehicle_number or len(vehicle_number) < 4:
        return error("Please enter a valid vehicle number.")
    if vehicle_type not in VALID_VEHICLE_TYPES:
        return error("Please select a valid vehicle type.")
    try:
        duration = int(duration)
    except (TypeError, ValueError):
        return error("Please select a valid duration.")
    if duration not in VALID_DURATIONS:
        return error("Please select a valid duration.")

    conn = get_db()
    try:
        slot = conn.execute("SELECT * FROM parking_slots WHERE id=?", (slot_id,)).fetchone()
        if not slot:
            return error("Slot not found.", 404)
        if slot["status"] != "AVAILABLE":
            return error("Slot is no longer available.", 409)

        vehicle = conn.execute(
            "SELECT * FROM vehicles WHERE vehicle_number=?", (vehicle_number,)
        ).fetchone()
        if vehicle:
            vehicle_id = vehicle["id"]
            is_ev = 1 if vehicle_type == "EV" else vehicle["is_ev"]
        else:
            is_ev = 1 if vehicle_type == "EV" else 0
            cur = conn.execute(
                "INSERT INTO vehicles (user_id, vehicle_number, vehicle_type, is_ev, created_at) "
                "VALUES (?,?,?,?,?)",
                (DEMO_USER_ID, vehicle_number, vehicle_type, is_ev, now_str()),
            )
            vehicle_id = cur.lastrowid

        now_dt = datetime.now()
        fee, peak = calculate_fee(vehicle_type, duration, now_dt)
        end_dt_str = (now_dt.replace(microsecond=0))
        from datetime import timedelta
        expected_end = now_dt + timedelta(minutes=duration)

        # atomic: only reserve if still AVAILABLE (prevents double booking races)
        cur = conn.execute(
            "UPDATE parking_slots SET status='RESERVED' WHERE id=? AND status='AVAILABLE'",
            (slot_id,),
        )
        if cur.rowcount == 0:
            conn.rollback()
            return error("Slot is no longer available.", 409)

        cur = conn.execute(
            "INSERT INTO reservations (user_id, vehicle_id, slot_id, reservation_time, start_time, "
            "expected_end_time, status, estimated_fee, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (DEMO_USER_ID, vehicle_id, slot_id, now_str(), now_str(),
             expected_end.strftime("%Y-%m-%d %H:%M:%S"), "ACTIVE", fee, now_str()),
        )
        reservation_id = cur.lastrowid
        conn.execute(
            "INSERT INTO parking_events (slot_id, event_type, source, timestamp, description) "
            "VALUES (?,?,?,?,?)",
            (slot_id, "RESERVED", "USER", now_str(), f"Reserved by {vehicle_number}"),
        )
        conn.commit()

        reservation = conn.execute(
            """SELECT r.*, v.vehicle_number, v.vehicle_type, sl.slot_number, z.name AS zone_name
               FROM reservations r
               JOIN vehicles v ON v.id=r.vehicle_id
               JOIN parking_slots sl ON sl.id=r.slot_id
               JOIN parking_zones z ON z.id=sl.zone_id
               WHERE r.id=?""",
            (reservation_id,),
        ).fetchone()
        return jsonify({"success": True, "reservation": dict(reservation), "peak_pricing_applied": peak})
    except sqlite3.Error as e:
        conn.rollback()
        app.logger.error(f"DB error creating reservation: {e}")
        return error("Unable to reserve slot right now. Please try again.", 500)
    finally:
        conn.close()


@app.route("/api/reservations/<int:reservation_id>/cancel", methods=["POST"])
def api_cancel_reservation(reservation_id):
    conn = get_db()
    try:
        res = conn.execute("SELECT * FROM reservations WHERE id=?", (reservation_id,)).fetchone()
        if not res:
            return error("Reservation not found.", 404)
        if res["status"] != "ACTIVE":
            return error("This reservation is no longer active.")

        conn.execute("UPDATE reservations SET status='CANCELLED' WHERE id=?", (reservation_id,))
        conn.execute("UPDATE parking_slots SET status='AVAILABLE' WHERE id=?", (res["slot_id"],))
        conn.execute(
            "INSERT INTO parking_events (slot_id, event_type, source, timestamp, description) VALUES (?,?,?,?,?)",
            (res["slot_id"], "CANCELLED", "USER", now_str(), "Reservation cancelled by user"),
        )
        conn.execute(
            "INSERT INTO rewards (user_id, points, reason, created_at) VALUES (?,?,?,?)",
            (res["user_id"], 5, "Early cancellation", now_str()),
        )
        conn.commit()
        return jsonify({"success": True})
    except sqlite3.Error as e:
        conn.rollback()
        app.logger.error(f"DB error cancelling reservation: {e}")
        return error("Unable to cancel reservation.", 500)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# My Parking - start / current / exit
# ---------------------------------------------------------------------------

@app.route("/api/parking/current")
def api_parking_current():
    conn = get_db()
    session = conn.execute(
        """SELECT ps.*, v.vehicle_number, v.vehicle_type, sl.slot_number, z.name AS zone_name
           FROM parking_sessions ps
           JOIN vehicles v ON v.id=ps.vehicle_id
           JOIN parking_slots sl ON sl.id=ps.slot_id
           JOIN parking_zones z ON z.id=sl.zone_id
           WHERE ps.user_id=? AND ps.status='ACTIVE' ORDER BY ps.id DESC LIMIT 1""",
        (DEMO_USER_ID,),
    ).fetchone()
    reservation = None
    if not session:
        reservation = conn.execute(
            """SELECT r.*, v.vehicle_number, v.vehicle_type, sl.slot_number, z.name AS zone_name
               FROM reservations r
               JOIN vehicles v ON v.id=r.vehicle_id
               JOIN parking_slots sl ON sl.id=r.slot_id
               JOIN parking_zones z ON z.id=sl.zone_id
               WHERE r.user_id=? AND r.status='ACTIVE' ORDER BY r.id DESC LIMIT 1""",
            (DEMO_USER_ID,),
        ).fetchone()
    conn.close()

    current_fee = None
    if session:
        elapsed_min = (datetime.now() - parse_dt(session["entry_time"])).total_seconds() / 60.0
        current_fee, _ = calculate_fee(session["vehicle_type"], max(elapsed_min, 1), parse_dt(session["entry_time"]))

    return jsonify({
        "success": True,
        "session": dict(session) if session else None,
        "reservation": dict(reservation) if reservation else None,
        "current_estimated_fee": current_fee,
    })


@app.route("/api/parking/start", methods=["POST"])
def api_parking_start():
    data = request.get_json(force=True, silent=True) or {}
    reservation_id = data.get("reservation_id")
    conn = get_db()
    try:
        res = conn.execute("SELECT * FROM reservations WHERE id=?", (reservation_id,)).fetchone()
        if not res:
            return error("Reservation not found.", 404)
        if res["status"] != "ACTIVE":
            return error("This reservation cannot be started.")
        slot = conn.execute("SELECT * FROM parking_slots WHERE id=?", (res["slot_id"],)).fetchone()
        if not slot or slot["status"] != "RESERVED":
            return error("Slot is not in a reserved state.", 409)

        cur = conn.execute(
            "UPDATE parking_slots SET status='OCCUPIED' WHERE id=? AND status='RESERVED'",
            (res["slot_id"],),
        )
        if cur.rowcount == 0:
            conn.rollback()
            return error("Unable to start parking - slot state changed.", 409)

        cur = conn.execute(
            "INSERT INTO parking_sessions (reservation_id, user_id, vehicle_id, slot_id, entry_time, status) "
            "VALUES (?,?,?,?,?,?)",
            (res["id"], res["user_id"], res["vehicle_id"], res["slot_id"], now_str(), "ACTIVE"),
        )
        session_id = cur.lastrowid
        conn.execute(
            "INSERT INTO parking_events (slot_id, event_type, source, timestamp, description) VALUES (?,?,?,?,?)",
            (res["slot_id"], "ENTRY", "USER", now_str(), "Parking started"),
        )
        conn.commit()

        session = conn.execute(
            """SELECT ps.*, v.vehicle_number, v.vehicle_type, sl.slot_number, z.name AS zone_name
               FROM parking_sessions ps
               JOIN vehicles v ON v.id=ps.vehicle_id
               JOIN parking_slots sl ON sl.id=ps.slot_id
               JOIN parking_zones z ON z.id=sl.zone_id
               WHERE ps.id=?""",
            (session_id,),
        ).fetchone()
        return jsonify({"success": True, "session": dict(session)})
    except sqlite3.Error as e:
        conn.rollback()
        app.logger.error(f"DB error starting parking: {e}")
        return error("Unable to start parking right now.", 500)
    finally:
        conn.close()


@app.route("/api/parking/exit", methods=["POST"])
def api_parking_exit():
    data = request.get_json(force=True, silent=True) or {}
    session_id = data.get("session_id")
    conn = get_db()
    try:
        session = conn.execute("SELECT * FROM parking_sessions WHERE id=?", (session_id,)).fetchone()
        if not session:
            return error("Active parking session not found.", 404)
        if session["status"] != "ACTIVE":
            return error("This session has already ended.")

        vehicle = conn.execute("SELECT * FROM vehicles WHERE id=?", (session["vehicle_id"],)).fetchone()
        entry_dt = parse_dt(session["entry_time"])
        exit_dt = datetime.now()
        duration_minutes = max(1, round((exit_dt - entry_dt).total_seconds() / 60.0))
        final_fee, peak = calculate_fee(vehicle["vehicle_type"], duration_minutes, entry_dt)

        conn.execute(
            "UPDATE parking_sessions SET exit_time=?, duration_minutes=?, status='COMPLETED', final_fee=? "
            "WHERE id=?",
            (exit_dt.strftime("%Y-%m-%d %H:%M:%S"), duration_minutes, final_fee, session_id),
        )
        if session["reservation_id"]:
            conn.execute("UPDATE reservations SET status='COMPLETED' WHERE id=?", (session["reservation_id"],))
        conn.execute("UPDATE parking_slots SET status='AVAILABLE' WHERE id=?", (session["slot_id"],))

        ref = f"TXN-{uuid.uuid4().hex[:10].upper()}"
        cur = conn.execute(
            "INSERT INTO transactions (user_id, session_id, amount, payment_method, payment_status, "
            "transaction_reference, created_at) VALUES (?,?,?,?,?,?,?)",
            (session["user_id"], session_id, final_fee, "Demo Payment", "PAID", ref,
             exit_dt.strftime("%Y-%m-%d %H:%M:%S")),
        )
        transaction_id = cur.lastrowid

        conn.execute(
            "INSERT INTO rewards (user_id, points, reason, created_at) VALUES (?,?,?,?)",
            (session["user_id"], 10, "On-time exit", exit_dt.strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.execute(
            "INSERT INTO parking_events (slot_id, event_type, source, timestamp, description) VALUES (?,?,?,?,?)",
            (session["slot_id"], "EXIT", "USER", exit_dt.strftime("%Y-%m-%d %H:%M:%S"), "Parking session ended"),
        )
        conn.commit()

        zone = conn.execute(
            "SELECT z.name FROM parking_zones z JOIN parking_slots s ON s.zone_id=z.id WHERE s.id=?",
            (session["slot_id"],),
        ).fetchone()
        slot = conn.execute("SELECT slot_number FROM parking_slots WHERE id=?", (session["slot_id"],)).fetchone()

        receipt = {
            "transaction_reference": ref,
            "vehicle_number": vehicle["vehicle_number"],
            "zone_name": zone["name"] if zone else "",
            "slot_number": slot["slot_number"] if slot else "",
            "entry_time": session["entry_time"],
            "exit_time": exit_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_minutes": duration_minutes,
            "rate_per_hour": RATES_PER_HOUR.get(vehicle["vehicle_type"]),
            "peak_multiplier_applied": PEAK_MULTIPLIER if peak else 1,
            "final_amount": final_fee,
            "payment_status": "PAID",
            "payment_method": "Demo Payment",
        }
        return jsonify({"success": True, "receipt": receipt})
    except sqlite3.Error as e:
        conn.rollback()
        app.logger.error(f"DB error exiting parking: {e}")
        return error("Unable to process exit right now.", 500)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

@app.route("/api/parking/history")
def api_parking_history():
    vehicle = request.args.get("vehicle", "").strip()
    zone = request.args.get("zone", "").strip()
    date = request.args.get("date", "").strip()
    status = request.args.get("status", "").strip()

    query = """
        SELECT t.id AS transaction_id, t.transaction_reference, t.amount, t.payment_status, t.created_at,
               ps.entry_time, ps.exit_time, ps.duration_minutes, ps.status AS session_status,
               v.vehicle_number, z.name AS zone_name, sl.slot_number
        FROM transactions t
        JOIN parking_sessions ps ON ps.id = t.session_id
        JOIN vehicles v ON v.id = ps.vehicle_id
        JOIN parking_slots sl ON sl.id = ps.slot_id
        JOIN parking_zones z ON z.id = sl.zone_id
        WHERE t.user_id = ?
    """
    params = [DEMO_USER_ID]
    if vehicle:
        query += " AND v.vehicle_number LIKE ?"
        params.append(f"%{vehicle}%")
    if zone:
        query += " AND z.name LIKE ?"
        params.append(f"%{zone}%")
    if date:
        query += " AND date(ps.entry_time) = ?"
        params.append(date)
    if status:
        query += " AND t.payment_status = ?"
        params.append(status)
    query += " ORDER BY t.id DESC LIMIT 200"

    conn = get_db()
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return jsonify({"success": True, "history": [dict(r) for r in rows]})


# ---------------------------------------------------------------------------
# Rewards
# ---------------------------------------------------------------------------

@app.route("/api/rewards")
def api_rewards():
    conn = get_db()
    total = conn.execute(
        "SELECT COALESCE(SUM(points),0) t FROM rewards WHERE user_id=?", (DEMO_USER_ID,)
    ).fetchone()["t"]
    history = conn.execute(
        "SELECT * FROM rewards WHERE user_id=? ORDER BY id DESC LIMIT 50", (DEMO_USER_ID,)
    ).fetchall()
    conn.close()
    return jsonify({"success": True, "total_points": total, "history": [dict(h) for h in history]})


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

@app.route("/api/admin/dashboard")
def api_admin_dashboard():
    conn = get_db()
    totals = conn.execute("SELECT status, COUNT(*) c FROM parking_slots GROUP BY status").fetchall()
    counts = {"AVAILABLE": 0, "OCCUPIED": 0, "RESERVED": 0, "MAINTENANCE": 0}
    for row in totals:
        counts[row["status"]] = row["c"]

    today_vehicles = conn.execute(
        "SELECT COUNT(DISTINCT vehicle_id) c FROM parking_sessions WHERE date(entry_time) = date('now','localtime')"
    ).fetchone()["c"]
    today_revenue = conn.execute(
        "SELECT COALESCE(SUM(amount),0) s FROM transactions "
        "WHERE payment_status='PAID' AND date(created_at) = date('now','localtime')"
    ).fetchone()["s"]
    total_revenue = conn.execute(
        "SELECT COALESCE(SUM(amount),0) s FROM transactions WHERE payment_status='PAID'"
    ).fetchone()["s"]

    conn.close()
    return jsonify({
        "success": True,
        "total_slots": sum(counts.values()),
        "available": counts["AVAILABLE"],
        "occupied": counts["OCCUPIED"],
        "reserved": counts["RESERVED"],
        "maintenance": counts["MAINTENANCE"],
        "today_vehicles": today_vehicles,
        "today_revenue": round(today_revenue, 2),
        "total_revenue": round(total_revenue, 2),
    })


@app.route("/api/admin/activity")
def api_admin_activity():
    conn = get_db()
    rows = conn.execute(
        """SELECT pe.*, sl.slot_number, z.name AS zone_name
           FROM parking_events pe
           JOIN parking_slots sl ON sl.id = pe.slot_id
           JOIN parking_zones z ON z.id = sl.zone_id
           ORDER BY pe.id DESC LIMIT 40"""
    ).fetchall()
    conn.close()
    return jsonify({"success": True, "activity": [dict(r) for r in rows]})


@app.route("/api/admin/hourly-demand")
def api_admin_hourly_demand():
    conn = get_db()
    rows = conn.execute(
        "SELECT strftime('%H', entry_time) hr, COUNT(*) c FROM parking_sessions GROUP BY hr"
    ).fetchall()
    conn.close()
    counts = [0] * 24
    for r in rows:
        counts[int(r["hr"])] = r["c"]
    return jsonify({"success": True, "labels": [f"{h:02d}:00" for h in range(24)], "counts": counts})


@app.route("/api/admin/slots", methods=["POST"])
def api_admin_add_slot():
    data = request.get_json(force=True, silent=True) or {}
    zone_id = data.get("zone_id")
    slot_number = (data.get("slot_number") or "").strip().upper()
    slot_type = (data.get("slot_type") or "CAR").strip().upper()
    floor = data.get("floor", 1)

    if not zone_id or not slot_number:
        return error("Zone and slot number are required.")

    conn = get_db()
    try:
        zone = conn.execute("SELECT * FROM parking_zones WHERE id=?", (zone_id,)).fetchone()
        if not zone:
            return error("Zone not found.", 404)
        existing = conn.execute("SELECT id FROM parking_slots WHERE slot_number=?", (slot_number,)).fetchone()
        if existing:
            return error("A slot with this number already exists.", 409)

        conn.execute(
            "INSERT INTO parking_slots (zone_id, slot_number, slot_type, status, floor, sensor_status) "
            "VALUES (?,?,?,?,?,?)",
            (zone_id, slot_number, slot_type, "AVAILABLE", floor, "OK"),
        )
        conn.execute(
            "UPDATE parking_zones SET total_slots = total_slots + 1 WHERE id=?", (zone_id,)
        )
        conn.commit()
        return jsonify({"success": True})
    except sqlite3.Error as e:
        conn.rollback()
        app.logger.error(f"DB error adding slot: {e}")
        return error("Unable to add slot.", 500)
    finally:
        conn.close()


@app.route("/api/admin/slots/<int:slot_id>", methods=["PATCH"])
def api_admin_update_slot(slot_id):
    data = request.get_json(force=True, silent=True) or {}
    new_status = (data.get("status") or "").strip().upper()
    confirm = bool(data.get("confirm"))

    if new_status not in ("AVAILABLE", "MAINTENANCE"):
        return error("Admin can only set a slot to AVAILABLE or MAINTENANCE.")

    conn = get_db()
    try:
        slot = conn.execute("SELECT * FROM parking_slots WHERE id=?", (slot_id,)).fetchone()
        if not slot:
            return error("Slot not found.", 404)

        if slot["status"] == "OCCUPIED" and new_status == "AVAILABLE" and not confirm:
            return jsonify({
                "success": False,
                "requires_confirmation": True,
                "error": "This slot is currently OCCUPIED. Forcing it to AVAILABLE will not close the "
                         "active session. Confirm to override.",
            }), 409

        conn.execute("UPDATE parking_slots SET status=? WHERE id=?", (new_status, slot_id))
        conn.execute(
            "INSERT INTO parking_events (slot_id, event_type, source, timestamp, description) VALUES (?,?,?,?,?)",
            (slot_id, new_status, "ADMIN", now_str(), f"Admin set slot to {new_status}"),
        )
        conn.commit()
        return jsonify({"success": True})
    except sqlite3.Error as e:
        conn.rollback()
        app.logger.error(f"DB error updating slot: {e}")
        return error("Unable to update slot.", 500)
    finally:
        conn.close()


@app.route("/api/admin/reset-demo", methods=["POST"])
def api_admin_reset_demo():
    data = request.get_json(force=True, silent=True) or {}
    if not data.get("confirm"):
        return error("Confirmation required to reset demo data.")
    seed_db(force=True)
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Sensor simulation
# ---------------------------------------------------------------------------

@app.route("/api/sensor/detect", methods=["POST"])
def api_sensor_detect():
    data = request.get_json(force=True, silent=True) or {}
    slot_id = data.get("slot_id")
    conn = get_db()
    try:
        slot = conn.execute("SELECT * FROM parking_slots WHERE id=?", (slot_id,)).fetchone()
        if not slot:
            return error("Slot not found.", 404)
        if slot["status"] != "AVAILABLE":
            return error(f"Slot is currently {slot['status']}; sensor cannot mark it occupied.", 409)

        conn.execute("UPDATE parking_slots SET status='OCCUPIED', sensor_status='VEHICLE_DETECTED' WHERE id=?",
                     (slot_id,))
        conn.execute(
            "INSERT INTO parking_events (slot_id, event_type, source, timestamp, description) VALUES (?,?,?,?,?)",
            (slot_id, "OCCUPIED", "SENSOR_SIMULATION", now_str(), "Vehicle detected (simulated sensor)"),
        )
        conn.commit()
        return jsonify({"success": True})
    except sqlite3.Error as e:
        conn.rollback()
        app.logger.error(f"DB error in sensor detect: {e}")
        return error("Unable to simulate detection.", 500)
    finally:
        conn.close()


@app.route("/api/sensor/exit", methods=["POST"])
def api_sensor_exit():
    data = request.get_json(force=True, silent=True) or {}
    slot_id = data.get("slot_id")
    conn = get_db()
    try:
        slot = conn.execute("SELECT * FROM parking_slots WHERE id=?", (slot_id,)).fetchone()
        if not slot:
            return error("Slot not found.", 404)
        if slot["status"] != "OCCUPIED":
            return error(f"Slot is currently {slot['status']}; sensor cannot mark it vacated.", 409)

        conn.execute("UPDATE parking_slots SET status='AVAILABLE', sensor_status='OK' WHERE id=?", (slot_id,))
        conn.execute(
            "INSERT INTO parking_events (slot_id, event_type, source, timestamp, description) VALUES (?,?,?,?,?)",
            (slot_id, "AVAILABLE", "SENSOR_SIMULATION", now_str(), "Vehicle exit (simulated sensor)"),
        )
        conn.commit()
        return jsonify({"success": True})
    except sqlite3.Error as e:
        conn.rollback()
        app.logger.error(f"DB error in sensor exit: {e}")
        return error("Unable to simulate exit.", 500)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Config exposed to frontend (read-only, still computed/stored on backend)
# ---------------------------------------------------------------------------

@app.route("/api/config")
def api_config():
    return jsonify({
        "success": True,
        "rates_per_hour": RATES_PER_HOUR,
        "peak_hours": PEAK_HOURS,
        "peak_multiplier": PEAK_MULTIPLIER,
        "valid_durations": VALID_DURATIONS,
        "demo_user_id": DEMO_USER_ID,
    })


@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "error": "Not found"}), 404
    return e


@app.errorhandler(500)
def server_error(e):
    app.logger.error(f"Unhandled error: {e}")
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "error": "Something went wrong on the server."}), 500
    return e


if __name__ == "__main__":
    init_db()
    seed_db()
    app.run(debug=True, port=5000)
