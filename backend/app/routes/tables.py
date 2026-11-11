from datetime import timedelta

from flask import Blueprint, jsonify, request

from ..db import db, update_row
from ..security import FLOOR, MGMT, require, restaurant, rid
from ..services import release_table_if_idle
from ..util import (ApiError, body, conflict, invalid, iso, local_day_bounds, not_found, now, now_iso,
                    parse_date, parse_iso, validate)

bp = Blueprint("tables", __name__)
TABLE_STATUS = ("available", "occupied", "reserved")
RESV_GAP = timedelta(minutes=120)


def get_table(tid):
    t = db().one("SELECT * FROM dining_tables WHERE id=? AND restaurant_id=?", (tid, rid()))
    if not t:
        raise not_found("Table")
    return t


@bp.get("/tables")
@require()
def list_tables():
    tables = db().query("SELECT * FROM dining_tables WHERE restaurant_id=? ORDER BY label", (rid(),))
    active = {r["table_id"]: r["id"] for r in db().query(
        "SELECT id, table_id FROM orders WHERE restaurant_id=? AND table_id IS NOT NULL "
        "AND status IN ('new','preparing','ready','served')", (rid(),))}
    upcoming = {}
    for r in db().query(
            "SELECT id, table_id, customer_name, reserved_for FROM reservations WHERE restaurant_id=? "
            "AND status='booked' AND reserved_for>=? ORDER BY reserved_for DESC",
            (rid(), iso(now() - timedelta(minutes=30)))):
        upcoming[r["table_id"]] = {"id": r["id"], "customer_name": r["customer_name"], "reserved_for": r["reserved_for"]}
    return jsonify(items=[{**t, "active_order_id": active.get(t["id"]), "next_reservation": upcoming.get(t["id"])}
                          for t in tables])


TABLE_SPEC = {"label": {"required": True, "max_len": 40}, "capacity": {"type": int, "required": True, "min": 1, "max": 50}}


@bp.post("/tables")
@require(*MGMT)
def create_table():
    d = validate(body(), TABLE_SPEC)
    tid = db().insert("INSERT INTO dining_tables(restaurant_id,label,capacity) VALUES (?,?,?)",
                      (rid(), d["label"], d["capacity"]), conflict="A table with this label already exists")
    return jsonify(get_table(tid)), 201


@bp.put("/tables/<int:tid>")
@require(*MGMT)
def update_table(tid):
    get_table(tid)
    d = validate(body(), {k: {kk: vv for kk, vv in v.items() if kk != "required"} for k, v in TABLE_SPEC.items()})
    if "label" in d and not d["label"]:
        raise invalid("Invalid input", {"label": "must not be empty"})
    update_row("dining_tables", tid, rid(), d)
    return jsonify(get_table(tid))


@bp.delete("/tables/<int:tid>")
@require(*MGMT)
def delete_table(tid):
    get_table(tid)
    if db().one("SELECT id FROM orders WHERE table_id=? LIMIT 1", (tid,)) or \
            db().one("SELECT id FROM reservations WHERE table_id=? LIMIT 1", (tid,)):
        raise conflict("Table has order or reservation history and cannot be deleted")
    db().execute("DELETE FROM dining_tables WHERE id=? AND restaurant_id=?", (tid, rid()))
    return "", 204


@bp.patch("/tables/<int:tid>/status")
@require(*FLOOR)
def set_table_status(tid):
    t = get_table(tid)
    d = validate(body(), {"status": {"required": True, "choices": TABLE_STATUS}})
    if d["status"] != "occupied" and db().one(
            "SELECT id FROM orders WHERE table_id=? AND status IN ('new','preparing','ready','served') LIMIT 1", (tid,)):
        raise conflict("Table has an active order; settle or cancel it first")
    update_row("dining_tables", tid, rid(), {"status": d["status"]})
    return jsonify(get_table(tid))


# ---- reservations -------------------------------------------------------------------------------

def resv_out(r):
    return {k: r[k] for k in ("id", "table_id", "table_label", "customer_name", "phone", "party_size",
                              "reserved_for", "status", "notes")}


def get_resv(rid_):
    r = db().one("SELECT r.*, t.label AS table_label FROM reservations r JOIN dining_tables t ON t.id=r.table_id "
                 "WHERE r.id=? AND r.restaurant_id=?", (rid_, rid()))
    if not r:
        raise not_found("Reservation")
    return r


def check_slot(table_id, when, ignore_id=None):
    lo, hi = iso(when - RESV_GAP + timedelta(seconds=1)), iso(when + RESV_GAP)
    clash = db().one(
        "SELECT id FROM reservations WHERE table_id=? AND restaurant_id=? AND status IN ('booked','seated') "
        "AND reserved_for>=? AND reserved_for<? AND id<>?", (table_id, rid(), lo, hi, ignore_id or -1))
    if clash:
        raise conflict("Table is already reserved within 2 hours of that time", {"reservation_id": clash["id"]})


RESV_SPEC = {
    "table_id": {"type": int, "required": True},
    "customer_name": {"required": True, "max_len": 120},
    "phone": {"max_len": 30, "default": ""},
    "party_size": {"type": int, "required": True, "min": 1, "max": 50},
    "reserved_for": {"required": True, "max_len": 40},
    "notes": {"max_len": 500, "default": ""},
}


def check_not_past(when):
    if when < now() - timedelta(minutes=5):
        raise invalid("Invalid input", {"reserved_for": "must not be in the past"})


@bp.get("/reservations")
@require(*FLOOR)
def list_reservations():
    sql, params = ("SELECT r.*, t.label AS table_label FROM reservations r JOIN dining_tables t ON t.id=r.table_id "
                   "WHERE r.restaurant_id=?"), [rid()]
    if request.args.get("date"):
        start, end = local_day_bounds(parse_date(request.args["date"]), restaurant()["tz_offset_minutes"])
        sql += " AND r.reserved_for>=? AND r.reserved_for<?"
        params += [start, end]
    else:
        sql += " AND r.reserved_for>=?"
        params.append(iso(now() - timedelta(hours=2)))
    if request.args.get("status"):
        sql += " AND r.status=?"
        params.append(request.args["status"])
    sql += " ORDER BY r.reserved_for LIMIT 200"
    return jsonify(items=[resv_out(r) for r in db().query(sql, params)])


@bp.post("/reservations")
@require(*FLOOR)
def create_reservation():
    d = validate(body(), RESV_SPEC)
    t = get_table(d["table_id"])
    if d["party_size"] > t["capacity"]:
        raise invalid("Invalid input", {"party_size": f"exceeds table capacity ({t['capacity']})"})
    when = parse_iso(d["reserved_for"], "reserved_for")
    check_not_past(when)
    check_slot(t["id"], when)
    new_id = db().insert(
        "INSERT INTO reservations(restaurant_id,table_id,customer_name,phone,party_size,reserved_for,notes,created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (rid(), t["id"], d["customer_name"], d["phone"], d["party_size"], iso(when), d["notes"], now_iso()))
    return jsonify(resv_out(get_resv(new_id))), 201


@bp.put("/reservations/<int:resv_id>")
@require(*FLOOR)
def update_reservation(resv_id):
    r = get_resv(resv_id)
    if r["status"] != "booked":
        raise conflict("Only booked reservations can be edited")
    spec = {k: {kk: vv for kk, vv in v.items() if kk not in ("required", "default")} for k, v in RESV_SPEC.items()}
    d = validate(body(), spec)
    table = get_table(d.get("table_id", r["table_id"]))
    if d.get("party_size", r["party_size"]) > table["capacity"]:
        raise invalid("Invalid input", {"party_size": f"exceeds table capacity ({table['capacity']})"})
    if "reserved_for" in d:
        when = parse_iso(d["reserved_for"], "reserved_for")
        check_not_past(when)
        d["reserved_for"] = iso(when)
    else:
        when = parse_iso(r["reserved_for"])
    check_slot(table["id"], when, resv_id)
    update_row("reservations", resv_id, rid(), d)
    return jsonify(resv_out(get_resv(resv_id)))


RESV_FLOW = {"booked": ("seated", "cancelled"), "seated": ("completed",)}


@bp.patch("/reservations/<int:resv_id>/status")
@require(*FLOOR)
def reservation_status(resv_id):
    r = get_resv(resv_id)
    d = validate(body(), {"status": {"required": True, "choices": ("seated", "cancelled", "completed")}})
    if d["status"] not in RESV_FLOW.get(r["status"], ()):
        raise conflict(f"Cannot change a {r['status']} reservation to {d['status']}")
    update_row("reservations", resv_id, rid(), {"status": d["status"]})
    if d["status"] == "seated":
        update_row("dining_tables", r["table_id"], rid(), {"status": "occupied"})
    else:
        t = get_table(r["table_id"])
        if t["status"] == "reserved" and d["status"] == "cancelled":
            update_row("dining_tables", t["id"], rid(), {"status": "available"})
        release_table_if_idle(r["table_id"], rid())
    return jsonify(resv_out(get_resv(resv_id)))
