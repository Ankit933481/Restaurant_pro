from datetime import timedelta

from flask import Blueprint, jsonify, request

from ..db import db
from ..security import MGMT, require, restaurant, rid
from ..util import (iso, local_day_bounds, local_today, now, parse_date, to_local)

bp = Blueprint("dashboard", __name__)


def bills_between(start, end):
    return db().query("SELECT order_id, paid_at, subtotal, discount, tax, service_charge, total, payment_method "
                      "FROM bills WHERE restaurant_id=? AND paid_at>=? AND paid_at<?", (rid(), start, end))


def top_items(start, end, limit=5):
    return db().query(
        "SELECT oi.name AS name, SUM(oi.quantity) AS quantity, SUM(oi.quantity * oi.unit_price) AS revenue "
        "FROM order_items oi JOIN bills b ON b.order_id=oi.order_id "
        "WHERE b.restaurant_id=? AND b.paid_at>=? AND b.paid_at<? "
        "GROUP BY oi.name ORDER BY quantity DESC, oi.name LIMIT ?", (rid(), start, end, limit))


def totals(rows):
    revenue = sum(r["total"] for r in rows)
    return {"revenue": revenue, "net_sales": sum(r["subtotal"] - r["discount"] for r in rows), "orders": len(rows),
            "tax": sum(r["tax"] for r in rows), "service_charge": sum(r["service_charge"] for r in rows),
            "discounts": sum(r["discount"] for r in rows),
            "avg_order_value": round(revenue / len(rows)) if rows else 0}


def daily_series(rows, first_day, days, off):
    buckets = {(first_day + timedelta(days=i)).isoformat(): {"revenue": 0, "orders": 0} for i in range(days)}
    for r in rows:
        key = to_local(r["paid_at"], off).date().isoformat()
        buckets[key]["revenue"] += r["total"]
        buckets[key]["orders"] += 1
    return [{"label": k, **v} for k, v in buckets.items()]


@bp.get("/dashboard")
@require(*MGMT)
def dashboard():
    off = restaurant()["tz_offset_minutes"]
    today = local_today(off)
    start7, end7 = local_day_bounds(today - timedelta(days=6), off, 7)
    rows7 = bills_between(start7, end7)
    t_start, t_end = local_day_bounds(today, off)
    today_rows = [r for r in rows7 if t_start <= r["paid_at"] < t_end]
    by_status = {s: 0 for s in ("new", "preparing", "ready", "served")}
    for r in db().query("SELECT status, COUNT(*) AS n FROM orders WHERE restaurant_id=? "
                        "AND status IN ('new','preparing','ready','served') GROUP BY status", (rid(),)):
        by_status[r["status"]] = r["n"]
    tbl = {"total": 0, "available": 0, "occupied": 0, "reserved": 0}
    for r in db().query("SELECT status, COUNT(*) AS n FROM dining_tables WHERE restaurant_id=? GROUP BY status", (rid(),)):
        tbl[r["status"]] = r["n"]
        tbl["total"] += r["n"]
    resv = db().one("SELECT COUNT(*) AS n FROM reservations WHERE restaurant_id=? AND status='booked' "
                    "AND reserved_for>=? AND reserved_for<?", (rid(), t_start, t_end))["n"]
    return jsonify(date=today.isoformat(), today=totals(today_rows), active_orders=sum(by_status.values()),
                   orders_by_status=by_status, tables=tbl, reservations_today=resv,
                   last_7_days=daily_series(rows7, today - timedelta(days=6), 7, off),
                   top_items=top_items(t_start, t_end))


@bp.get("/reports/sales")
@require(*MGMT)
def sales_report():
    period = request.args.get("period", "daily")
    if period not in ("daily", "weekly", "monthly"):
        from ..util import invalid
        raise invalid("Invalid input", {"period": "must be daily, weekly or monthly"})
    off = restaurant()["tz_offset_minutes"]
    day = parse_date(request.args["date"]) if request.args.get("date") else local_today(off)
    if period == "daily":
        first, days = day, 1
    elif period == "weekly":
        first, days = day - timedelta(days=6), 7
    else:
        first = day.replace(day=1)
        nxt = (first + timedelta(days=32)).replace(day=1)
        days = (nxt - first).days
    start, end = local_day_bounds(first, off, days)
    rows = bills_between(start, end)
    if period == "daily":
        hours = {f"{h:02d}": {"revenue": 0, "orders": 0} for h in range(24)}
        for r in rows:
            h = f"{to_local(r['paid_at'], off).hour:02d}"
            hours[h]["revenue"] += r["total"]
            hours[h]["orders"] += 1
        series = [{"label": k, **v} for k, v in hours.items()]
    else:
        series = daily_series(rows, first, days, off)
    methods = {}
    for r in rows:
        m = methods.setdefault(r["payment_method"], {"revenue": 0, "orders": 0})
        m["revenue"] += r["total"]
        m["orders"] += 1
    return jsonify(period=period, **{"from": first.isoformat(), "to": (first + timedelta(days=days - 1)).isoformat()},
                   totals=totals(rows), series=series, top_items=top_items(start, end, 10), payment_methods=methods)
