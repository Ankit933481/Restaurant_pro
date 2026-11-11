from flask import Blueprint, g, jsonify, request

from ..db import db
from ..security import BILLING, MGMT, require, restaurant, rid
from ..services import ACTIVE, release_table_if_idle, set_order_status
from ..util import (ApiError, body, conflict, forbidden, invalid, local_day_bounds, not_found, now_iso, page_args,
                    parse_date, pct, validate)
from .orders import fetch_items, fetch_order

bp = Blueprint("billing", __name__)
MAX_CASHIER_DISCOUNT_PCT = 20

BILL_SPEC = {
    "discount_type": {"choices": ("none", "percent", "amount"), "default": "none"},
    "discount_value": {"type": float, "min": 0, "default": 0.0},
}


def compute(items, rest, dtype, dvalue):
    subtotal = sum(i["unit_price"] * i["quantity"] for i in items)
    if dtype == "percent":
        if dvalue > 100:
            raise invalid("Invalid input", {"discount_value": "percentage must be <= 100"})
        discount = pct(subtotal, dvalue)
    elif dtype == "amount":
        if dvalue != int(dvalue):
            raise invalid("Invalid input", {"discount_value": "amount must be a whole number of minor units"})
        discount = int(dvalue)
        if discount > subtotal:
            raise invalid("Invalid input", {"discount_value": "discount cannot exceed the subtotal"})
    else:
        discount = 0
    taxable = subtotal - discount
    tax, service = pct(taxable, rest["tax_rate"]), pct(taxable, rest["service_charge_rate"])
    return {"subtotal": subtotal, "discount_type": dtype, "discount_value": dvalue if dtype != "none" else 0.0,
            "discount": discount, "tax_rate": rest["tax_rate"], "tax": tax,
            "service_rate": rest["service_charge_rate"], "service_charge": service,
            "total": taxable + tax + service}


def billable(oid):
    o = fetch_order(oid)
    if o["status"] not in ACTIVE:
        raise conflict(f"Order is {o['status']} and cannot be billed")
    items = fetch_items(oid)
    if not items:
        raise conflict("Order has no items")
    return o, items


def check_discount_authority(calc):
    if calc["subtotal"] and calc["discount"] * 100 > MAX_CASHIER_DISCOUNT_PCT * calc["subtotal"] \
            and g.user["role"] not in MGMT:
        raise forbidden(f"Discounts above {MAX_CASHIER_DISCOUNT_PCT}% need a manager or owner")


@bp.post("/orders/<int:oid>/bill/preview")
@require(*BILLING)
def preview(oid):
    o, items = billable(oid)
    d = validate(request.get_json(silent=True) or {}, BILL_SPEC)
    calc = compute(items, restaurant(), d["discount_type"], d["discount_value"])
    return jsonify(order_id=oid, items=items, **calc)


def bill_out(b, items=None):
    out = {k: b[k] for k in ("id", "order_id", "number", "subtotal", "discount_type", "discount_value", "discount",
                             "tax_rate", "tax", "service_rate", "service_charge", "total", "payment_method",
                             "amount_tendered", "change_due", "paid_at", "created_by")}
    if items is not None:
        out["items"] = items
    return out


@bp.post("/orders/<int:oid>/bill")
@require(*BILLING)
def pay(oid):
    o, items = billable(oid)
    d = validate(body(), {**BILL_SPEC,
                          "payment_method": {"required": True, "choices": ("cash", "card", "upi", "other")},
                          "amount_tendered": {"type": int, "min": 0}})
    calc = compute(items, restaurant(), d["discount_type"], d["discount_value"])
    check_discount_authority(calc)
    tendered, change = calc["total"], 0
    if d["payment_method"] == "cash" and "amount_tendered" in d:
        if d["amount_tendered"] < calc["total"]:
            raise invalid("Invalid input", {"amount_tendered": f"must cover the total ({calc['total']})"})
        tendered, change = d["amount_tendered"], d["amount_tendered"] - calc["total"]
    seq = (db().one("SELECT COALESCE(MAX(seq),0) AS m FROM bills WHERE restaurant_id=?", (rid(),))["m"]) + 1
    bill_id = db().insert(
        "INSERT INTO bills(restaurant_id,order_id,seq,number,subtotal,discount_type,discount_value,discount,tax_rate,"
        "tax,service_rate,service_charge,total,payment_method,amount_tendered,change_due,paid_at,created_by) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (rid(), oid, seq, f"INV-{seq:06d}", calc["subtotal"], calc["discount_type"], calc["discount_value"],
         calc["discount"], calc["tax_rate"], calc["tax"], calc["service_rate"], calc["service_charge"], calc["total"],
         d["payment_method"], tendered, change, now_iso(), g.user["id"]),
        conflict="Order was just billed or another bill was issued at the same moment; retry")
    set_order_status(oid, rid(), "paid")
    release_table_if_idle(o["table_id"], rid())
    b = db().one("SELECT * FROM bills WHERE id=?", (bill_id,))
    return jsonify(bill_out(b, items)), 201


@bp.get("/bills")
@require(*BILLING)
def list_bills():
    limit, offset = page_args()
    sql, params = "SELECT * FROM bills WHERE restaurant_id=?", [rid()]
    if request.args.get("date"):
        start, end = local_day_bounds(parse_date(request.args["date"]), restaurant()["tz_offset_minutes"])
        sql += " AND paid_at>=? AND paid_at<?"
        params += [start, end]
    rows = db().query(sql + " ORDER BY paid_at DESC, id DESC LIMIT ? OFFSET ?", params + [limit, offset])
    return jsonify(items=[bill_out(b) for b in rows], limit=limit, offset=offset)


@bp.get("/bills/<int:bid>")
@require(*BILLING)
def read_bill(bid):
    b = db().one("SELECT * FROM bills WHERE id=? AND restaurant_id=?", (bid, rid()))
    if not b:
        raise not_found("Bill")
    return jsonify(bill_out(b, fetch_items(b["order_id"])))
