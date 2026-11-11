from flask import Blueprint, jsonify

from ..db import db
from ..security import KITCHEN, require, rid
from ..services import set_order_status
from ..util import body, conflict, now, parse_iso, validate
from .orders import fetch_items, fetch_order, order_out

bp = Blueprint("kitchen", __name__)
FLOW = {"new": ("preparing",), "preparing": ("ready",), "ready": ("preparing",)}


@bp.get("/kitchen/orders")
@require(*KITCHEN)
def queue():
    rows = db().query(
        "SELECT o.*, t.label AS table_label FROM orders o LEFT JOIN dining_tables t ON t.id=o.table_id "
        "WHERE o.restaurant_id=? AND o.status IN ('new','preparing','ready') ORDER BY o.created_at, o.id", (rid(),))
    out = []
    for r in rows:
        o = order_out(r, fetch_items(r["id"]))
        o["minutes_waiting"] = int((now() - parse_iso(r["created_at"])).total_seconds() // 60)
        out.append(o)
    return jsonify(items=out)


@bp.patch("/kitchen/orders/<int:oid>/status")
@require(*KITCHEN)
def advance(oid):
    o = fetch_order(oid)
    d = validate(body(), {"status": {"required": True, "choices": ("preparing", "ready")}})
    if d["status"] not in FLOW.get(o["status"], ()):
        raise conflict(f"Cannot move an order from {o['status']} to {d['status']}")
    set_order_status(oid, rid(), d["status"])
    return jsonify(order_out(fetch_order(oid), fetch_items(oid)))
