from flask import Blueprint, g, jsonify, request

from ..db import db
from ..security import ALL, FLOOR, MGMT, require, rid
from ..services import ACTIVE, release_table_if_idle, set_order_status
from ..util import ApiError, body, conflict, forbidden, invalid, not_found, now_iso, page_args, validate

bp = Blueprint("orders", __name__)
STATUSES = ("new", "preparing", "ready", "served", "paid", "cancelled")

ITEM_SPEC = {
    "menu_item_id": {"type": int, "required": True},
    "quantity": {"type": int, "required": True, "min": 1, "max": 99},
    "notes": {"max_len": 200, "default": ""},
}


def fetch_order(oid):
    o = db().one("SELECT o.*, t.label AS table_label FROM orders o LEFT JOIN dining_tables t ON t.id=o.table_id "
                 "WHERE o.id=? AND o.restaurant_id=?", (oid, rid()))
    if not o:
        raise not_found("Order")
    return o


def fetch_items(oid):
    return db().query("SELECT id, menu_item_id, name, unit_price, quantity, notes FROM order_items "
                      "WHERE order_id=? ORDER BY id", (oid,))


def order_out(o, items, detail=True):
    out = {"id": o["id"], "table_id": o["table_id"], "table_label": o["table_label"], "order_type": o["order_type"],
           "status": o["status"], "notes": o["notes"], "waiter_id": o["waiter_id"], "created_at": o["created_at"],
           "updated_at": o["updated_at"], "item_count": sum(i["quantity"] for i in items),
           "subtotal": sum(i["unit_price"] * i["quantity"] for i in items)}
    if detail:
        out["items"] = items
        bill = db().one("SELECT id FROM bills WHERE order_id=?", (o["id"],))
        out["bill_id"] = bill["id"] if bill else None
    return out


def add_items(oid, raw_items):
    if not isinstance(raw_items, list) or not raw_items:
        raise invalid("Invalid input", {"items": "must be a non-empty list"})
    if len(raw_items) > 100:
        raise invalid("Invalid input", {"items": "at most 100 entries per request"})
    for idx, raw in enumerate(raw_items):
        try:
            it = validate(raw, ITEM_SPEC)
        except ApiError as e:
            raise invalid("Invalid input", {f"items[{idx}]": e.details or e.message})
        m = db().one("SELECT * FROM menu_items WHERE id=? AND restaurant_id=? AND archived=0",
                     (it["menu_item_id"], rid()))
        if not m:
            raise invalid("Invalid input", {f"items[{idx}]": "menu item not found"})
        if not m["available"]:
            raise invalid("Invalid input", {f"items[{idx}]": f"'{m['name']}' is currently unavailable"})
        db().insert("INSERT INTO order_items(order_id,menu_item_id,name,unit_price,quantity,notes) VALUES (?,?,?,?,?,?)",
                    (oid, m["id"], m["name"], m["price"], it["quantity"], it["notes"]))


@bp.get("/orders")
@require()
def list_orders():
    limit, offset = page_args()
    sql, params = ("SELECT o.*, t.label AS table_label FROM orders o LEFT JOIN dining_tables t ON t.id=o.table_id "
                   "WHERE o.restaurant_id=?"), [rid()]
    if request.args.get("status"):
        wanted = request.args["status"].split(",")
        if any(s not in STATUSES for s in wanted):
            raise invalid("Invalid input", {"status": "unknown status"})
        sql += " AND o.status IN (" + ",".join("?" * len(wanted)) + ")"
        params += wanted
    if request.args.get("active") == "true":
        sql += " AND o.status IN ('new','preparing','ready','served')"
    if request.args.get("table_id", "").isdigit():
        sql += " AND o.table_id=?"
        params.append(int(request.args["table_id"]))
    sql += " ORDER BY o.created_at DESC, o.id DESC LIMIT ? OFFSET ?"
    rows = db().query(sql, params + [limit, offset])
    items_by_order = {}
    if rows:
        ids = [r["id"] for r in rows]
        for it in db().query("SELECT order_id, unit_price, quantity FROM order_items WHERE order_id IN ("
                             + ",".join("?" * len(ids)) + ")", ids):
            items_by_order.setdefault(it["order_id"], []).append(it)
    return jsonify(items=[order_out(r, items_by_order.get(r["id"], []), detail=False) for r in rows],
                   limit=limit, offset=offset)


@bp.post("/orders")
@require(*FLOOR)
def create_order():
    data = body()
    d = validate(data, {
        "order_type": {"choices": ("dine_in", "takeaway"), "default": "dine_in"},
        "table_id": {"type": int}, "notes": {"max_len": 500, "default": ""},
        "items": {"type": list, "required": True, "min_items": 1, "max_items": 100},
    })
    table_id = None
    if d["order_type"] == "dine_in":
        if "table_id" not in d:
            raise invalid("Invalid input", {"table_id": "is required for dine-in orders"})
        t = db().one("SELECT * FROM dining_tables WHERE id=? AND restaurant_id=?", (d["table_id"], rid()))
        if not t:
            raise not_found("Table")
        existing = db().one("SELECT id FROM orders WHERE table_id=? AND restaurant_id=? "
                            "AND status IN ('new','preparing','ready','served')", (t["id"], rid()))
        if existing:
            raise conflict("Table already has an active order; add items to it instead",
                           {"order_id": existing["id"]})
        table_id = t["id"]
    ts = now_iso()
    oid = db().insert("INSERT INTO orders(restaurant_id,table_id,waiter_id,order_type,notes,created_at,updated_at) "
                      "VALUES (?,?,?,?,?,?,?)", (rid(), table_id, g.user["id"], d["order_type"], d["notes"], ts, ts))
    add_items(oid, d["items"])
    if table_id:
        db().execute("UPDATE dining_tables SET status='occupied' WHERE id=? AND restaurant_id=?", (table_id, rid()))
    return jsonify(order_out(fetch_order(oid), fetch_items(oid))), 201


@bp.get("/orders/<int:oid>")
@require()
def read_order(oid):
    return jsonify(order_out(fetch_order(oid), fetch_items(oid)))


def require_active(o):
    if o["status"] not in ACTIVE:
        raise conflict(f"Order is {o['status']} and can no longer be changed")


@bp.post("/orders/<int:oid>/items")
@require(*FLOOR)
def append_items(oid):
    o = fetch_order(oid)
    require_active(o)
    add_items(oid, body().get("items"))
    if o["status"] in ("ready", "served"):
        set_order_status(oid, rid(), "new")  # kitchen must see the new dishes
    else:
        set_order_status(oid, rid(), o["status"])
    return jsonify(order_out(fetch_order(oid), fetch_items(oid)))


def editable_item(oid, item_id):
    o = fetch_order(oid)
    if o["status"] != "new":
        raise conflict("Order is already being prepared; changes must go through the kitchen")
    it = db().one("SELECT * FROM order_items WHERE id=? AND order_id=?", (item_id, oid))
    if not it:
        raise not_found("Order item")
    return o, it


@bp.patch("/orders/<int:oid>/items/<int:item_id>")
@require(*FLOOR)
def update_item(oid, item_id):
    editable_item(oid, item_id)
    d = validate(body(), {"quantity": {"type": int, "min": 1, "max": 99}, "notes": {"max_len": 200}})
    if d:
        cols = ", ".join(f"{k}=?" for k in d)
        db().execute(f"UPDATE order_items SET {cols} WHERE id=? AND order_id=?", (*d.values(), item_id, oid))
        set_order_status(oid, rid(), "new")
    return jsonify(order_out(fetch_order(oid), fetch_items(oid)))


@bp.delete("/orders/<int:oid>/items/<int:item_id>")
@require(*FLOOR)
def delete_item(oid, item_id):
    editable_item(oid, item_id)
    if len(fetch_items(oid)) == 1:
        raise conflict("An order must keep at least one item; cancel the order instead")
    db().execute("DELETE FROM order_items WHERE id=? AND order_id=?", (item_id, oid))
    set_order_status(oid, rid(), "new")
    return jsonify(order_out(fetch_order(oid), fetch_items(oid)))


@bp.patch("/orders/<int:oid>/status")
@require(*FLOOR)
def change_status(oid):
    o = fetch_order(oid)
    d = validate(body(), {"status": {"required": True, "choices": ("served", "cancelled")}})
    require_active(o)
    if d["status"] == "served":
        if o["status"] != "ready":
            raise conflict("Only orders marked ready by the kitchen can be served")
    elif o["status"] != "new" and g.user["role"] not in MGMT:
        raise forbidden("Only a manager or owner can cancel an order once the kitchen has started it")
    set_order_status(oid, rid(), d["status"])
    if d["status"] == "cancelled":
        release_table_if_idle(o["table_id"], rid())
    return jsonify(order_out(fetch_order(oid), fetch_items(oid)))
