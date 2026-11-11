from flask import Blueprint, jsonify, request

from ..db import db, update_row
from ..security import MGMT, require, rid
from ..util import ApiError, body, conflict, invalid, not_found, now_iso, validate

bp = Blueprint("menu", __name__)


def cat_out(c):
    return {"id": c["id"], "name": c["name"], "sort_order": c["sort_order"], "item_count": c.get("item_count", 0)}


def item_out(m):
    return {"id": m["id"], "category_id": m["category_id"], "category_name": m.get("category_name"),
            "name": m["name"], "description": m["description"], "price": m["price"],
            "available": bool(m["available"])}


def get_category(cid):
    c = db().one("SELECT * FROM categories WHERE id=? AND restaurant_id=?", (cid, rid()))
    if not c:
        raise not_found("Category")
    return c


def get_item(mid):
    m = db().one("SELECT m.*, c.name AS category_name FROM menu_items m JOIN categories c ON c.id=m.category_id "
                 "WHERE m.id=? AND m.restaurant_id=? AND m.archived=0", (mid, rid()))
    if not m:
        raise not_found("Menu item")
    return m


@bp.get("/categories")
@require()
def list_categories():
    rows = db().query(
        "SELECT c.*, (SELECT COUNT(*) FROM menu_items m WHERE m.category_id=c.id AND m.archived=0) AS item_count "
        "FROM categories c WHERE c.restaurant_id=? ORDER BY c.sort_order, c.name", (rid(),))
    return jsonify(items=[cat_out(r) for r in rows])


CAT_SPEC = {"name": {"required": True, "max_len": 80}, "sort_order": {"type": int, "min": 0, "max": 10000}}


@bp.post("/categories")
@require(*MGMT)
def create_category():
    d = validate(body(), {**CAT_SPEC, "sort_order": {**CAT_SPEC["sort_order"], "default": 0}})
    cid = db().insert("INSERT INTO categories(restaurant_id,name,sort_order) VALUES (?,?,?)",
                      (rid(), d["name"], d["sort_order"]), conflict="A category with this name already exists")
    return jsonify(cat_out(get_category(cid))), 201


@bp.put("/categories/<int:cid>")
@require(*MGMT)
def update_category(cid):
    get_category(cid)
    d = validate(body(), {**CAT_SPEC, "name": {"max_len": 80}})
    if "name" in d and not d["name"]:
        raise invalid("Invalid input", {"name": "must not be empty"})
    try:
        update_row("categories", cid, rid(), d)
    except ApiError:
        raise conflict("A category with this name already exists")
    return jsonify(cat_out(get_category(cid)))


@bp.delete("/categories/<int:cid>")
@require(*MGMT)
def delete_category(cid):
    get_category(cid)
    n = db().one("SELECT COUNT(*) AS n FROM menu_items WHERE category_id=? AND restaurant_id=?", (cid, rid()))["n"]
    if n:
        raise conflict("Category still contains menu items; move or delete them first")
    db().execute("DELETE FROM categories WHERE id=? AND restaurant_id=?", (cid, rid()))
    return "", 204


@bp.get("/menu-items")
@require()
def list_items():
    sql = ("SELECT m.*, c.name AS category_name FROM menu_items m JOIN categories c ON c.id=m.category_id "
           "WHERE m.restaurant_id=? AND m.archived=0")
    params = [rid()]
    if request.args.get("category_id"):
        sql += " AND m.category_id=?"
        params.append(int(request.args["category_id"]) if request.args["category_id"].isdigit() else -1)
    if request.args.get("available") in ("true", "false"):
        sql += " AND m.available=?"
        params.append(1 if request.args["available"] == "true" else 0)
    if request.args.get("q"):
        sql += " AND LOWER(m.name) LIKE ?"
        params.append("%" + request.args["q"].lower() + "%")
    sql += " ORDER BY c.sort_order, c.name, m.name"
    return jsonify(items=[item_out(r) for r in db().query(sql, params)])


ITEM_SPEC = {
    "category_id": {"type": int, "required": True},
    "name": {"required": True, "max_len": 120},
    "description": {"max_len": 500, "default": ""},
    "price": {"type": int, "required": True, "min": 0, "max": 100_000_000},
    "available": {"type": bool, "default": True},
}


@bp.post("/menu-items")
@require(*MGMT)
def create_item():
    d = validate(body(), ITEM_SPEC)
    get_category(d["category_id"])
    mid = db().insert(
        "INSERT INTO menu_items(restaurant_id,category_id,name,description,price,available,created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (rid(), d["category_id"], d["name"], d["description"], d["price"], int(d["available"]), now_iso()))
    return jsonify(item_out(get_item(mid))), 201


@bp.get("/menu-items/<int:mid>")
@require()
def read_item(mid):
    return jsonify(item_out(get_item(mid)))


@bp.put("/menu-items/<int:mid>")
@require(*MGMT)
def update_item(mid):
    get_item(mid)
    spec = {k: {kk: vv for kk, vv in v.items() if kk not in ("required", "default")} for k, v in ITEM_SPEC.items()}
    d = validate(body(), spec)
    if "name" in d and not d["name"]:
        raise invalid("Invalid input", {"name": "must not be empty"})
    if "category_id" in d:
        get_category(d["category_id"])
    if "available" in d:
        d["available"] = int(d["available"])
    update_row("menu_items", mid, rid(), d)
    return jsonify(item_out(get_item(mid)))


@bp.delete("/menu-items/<int:mid>")
@require(*MGMT)
def delete_item(mid):
    get_item(mid)
    used = db().one("SELECT COUNT(*) AS n FROM order_items WHERE menu_item_id=?", (mid,))["n"]
    if used:  # keep history intact: archive instead of hard delete
        db().execute("UPDATE menu_items SET archived=1, available=0 WHERE id=? AND restaurant_id=?", (mid, rid()))
    else:
        db().execute("DELETE FROM menu_items WHERE id=? AND restaurant_id=?", (mid, rid()))
    return "", 204
