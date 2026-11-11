"""Generates openapi.yaml. Run: python tools/gen_openapi.py  (tests verify it matches the real routes)."""
import os
import yaml

S, I, N, B = "string", "integer", "number", "boolean"
ALL, MG, FL, BI, KI = "any signed-in role", "owner, manager", "owner, manager, cashier, waiter", \
    "owner, manager, cashier", "owner, manager, kitchen"


def obj(**props):
    required = [k[:-1] for k in props if k.endswith("_")]
    properties = {}
    for k, v in props.items():
        k = k.rstrip("_")
        properties[k] = {"type": v} if isinstance(v, str) else v
    schema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


ITEMS = {"type": "array", "items": obj(menu_item_id_=I, quantity_=I, notes=S)}
BILLOPTS = dict(discount_type={"type": S, "enum": ["none", "percent", "amount"]}, discount_value=N)

# (method, path, summary, roles, body-schema or None, success-status)
R = [
    ("post", "/auth/register", "Create a restaurant and its owner account (returns JWT)", "public",
     obj(restaurant_name_=S, name_=S, email_=S, password_=S), 201),
    ("post", "/auth/login", "Sign in (returns JWT)", "public", obj(email_=S, password_=S), 200),
    ("post", "/auth/logout", "Revoke the current token", ALL, None, 200),
    ("get", "/auth/me", "Current user and restaurant summary", ALL, None, 200),
    ("post", "/auth/change-password", "Change own password (signs out other sessions)", ALL,
     obj(current_password_=S, new_password_=S), 200),
    ("get", "/categories", "List menu categories", ALL, None, 200),
    ("post", "/categories", "Create category", MG, obj(name_=S, sort_order=I), 201),
    ("put", "/categories/{cid}", "Update category", MG, obj(name=S, sort_order=I), 200),
    ("delete", "/categories/{cid}", "Delete empty category", MG, None, 204),
    ("get", "/menu-items", "List menu items (filters: category_id, available, q)", ALL, None, 200),
    ("post", "/menu-items", "Create menu item (price in minor units)", MG,
     obj(category_id_=I, name_=S, price_=I, description=S, available=B), 201),
    ("get", "/menu-items/{mid}", "Get menu item", ALL, None, 200),
    ("put", "/menu-items/{mid}", "Update menu item", MG, obj(category_id=I, name=S, price=I, description=S, available=B), 200),
    ("delete", "/menu-items/{mid}", "Delete (or archive, if it appears in past orders) a menu item", MG, None, 204),
    ("get", "/tables", "List tables with active order and next reservation", ALL, None, 200),
    ("post", "/tables", "Create table", MG, obj(label_=S, capacity_=I), 201),
    ("put", "/tables/{tid}", "Update table", MG, obj(label=S, capacity=I), 200),
    ("delete", "/tables/{tid}", "Delete table without history", MG, None, 204),
    ("patch", "/tables/{tid}/status", "Set table status (available, occupied, reserved)", FL,
     obj(status_={"type": S, "enum": ["available", "occupied", "reserved"]}), 200),
    ("get", "/reservations", "List reservations (filters: date, status)", FL, None, 200),
    ("post", "/reservations", "Create reservation (no overlap within 2h, party <= capacity)", FL,
     obj(table_id_=I, customer_name_=S, party_size_=I, reserved_for_={"type": S, "format": "date-time"}, phone=S, notes=S), 201),
    ("put", "/reservations/{resv_id}", "Edit a booked reservation", FL,
     obj(table_id=I, customer_name=S, party_size=I, reserved_for={"type": S, "format": "date-time"}, phone=S, notes=S), 200),
    ("patch", "/reservations/{resv_id}/status", "Seat, cancel or complete a reservation", FL,
     obj(status_={"type": S, "enum": ["seated", "cancelled", "completed"]}), 200),
    ("get", "/orders", "List orders (filters: status, active, table_id, limit, offset)", ALL, None, 200),
    ("post", "/orders", "Create an order (dine_in needs table_id)", FL,
     obj(order_type={"type": S, "enum": ["dine_in", "takeaway"]}, table_id=I, notes=S, items_=ITEMS), 201),
    ("get", "/orders/{oid}", "Get order with items", ALL, None, 200),
    ("post", "/orders/{oid}/items", "Add items to an active order (returns it to the kitchen queue)", FL,
     obj(items_=ITEMS), 200),
    ("patch", "/orders/{oid}/items/{item_id}", "Change quantity/notes of an item (order still 'new')", FL,
     obj(quantity=I, notes=S), 200),
    ("delete", "/orders/{oid}/items/{item_id}", "Remove an item (order still 'new')", FL, None, 200),
    ("patch", "/orders/{oid}/status", "Mark served (after ready) or cancel", FL,
     obj(status_={"type": S, "enum": ["served", "cancelled"]}), 200),
    ("get", "/kitchen/orders", "Kitchen queue: new, preparing and ready orders", KI, None, 200),
    ("patch", "/kitchen/orders/{oid}/status", "Move order new→preparing→ready", KI,
     obj(status_={"type": S, "enum": ["preparing", "ready"]}), 200),
    ("post", "/orders/{oid}/bill/preview", "Calculate totals without paying", BI, obj(**BILLOPTS), 200),
    ("post", "/orders/{oid}/bill", "Create bill and record payment (discounts >20% need manager)", BI,
     obj(payment_method_={"type": S, "enum": ["cash", "card", "upi", "other"]}, amount_tendered=I, **BILLOPTS), 201),
    ("get", "/bills", "List bills (filter: date, limit, offset)", BI, None, 200),
    ("get", "/bills/{bid}", "Get bill with line items", BI, None, 200),
    ("get", "/staff/permissions", "Role/permission matrix", ALL, None, 200),
    ("get", "/staff", "List staff", MG, None, 200),
    ("post", "/staff", "Create staff account (only owner may create owners/managers)", MG,
     obj(name_=S, email_=S, password_=S, role_={"type": S, "enum": ["owner", "manager", "cashier", "waiter", "kitchen"]}), 201),
    ("put", "/staff/{uid}", "Update name/role/active", MG,
     obj(name=S, role={"type": S, "enum": ["owner", "manager", "cashier", "waiter", "kitchen"]}, active=B), 200),
    ("post", "/staff/{uid}/reset-password", "Reset a staff password", MG, obj(new_password_=S), 200),
    ("get", "/settings", "Restaurant settings", ALL, None, 200),
    ("put", "/settings", "Update settings", "owner",
     obj(name=S, address=S, phone=S, currency=S, currency_symbol=S, currency_decimals=I, tax_rate=N,
         service_charge_rate=N, tz_offset_minutes=I), 200),
    ("get", "/dashboard", "Today's KPIs, tables, 7-day revenue, top items", MG, None, 200),
    ("get", "/reports/sales", "Sales report (period=daily|weekly|monthly, date=YYYY-MM-DD)", MG, None, 200),
]

paths = {}
for method, path, summary, roles, schema, status in R:
    op = {"summary": summary, "description": f"Allowed roles: {roles}.", "tags": [path.split("/")[1]],
          "responses": {str(status): {"description": "Success"}, "default": {"$ref": "#/components/responses/Error"}}}
    if roles == "public":
        op["security"] = []
    if schema:
        op["requestBody"] = {"required": True, "content": {"application/json": {"schema": schema}}}
    params = [p for p in path.replace("{", "|{").split("|") if p.startswith("{")]
    op["parameters"] = [{"name": p.split("}")[0][1:], "in": "path", "required": True, "schema": {"type": I}} for p in params]
    if not op["parameters"]:
        del op["parameters"]
    paths.setdefault(path, {})[method] = op

spec = {
    "openapi": "3.0.3",
    "info": {"title": "Restaurant Management API", "version": "1.0.0",
             "description": "Multi-tenant REST API. All money values are integers in minor units (cents). "
                            "Timestamps are UTC ISO-8601. Errors: {\"error\": {\"code\", \"message\", \"details\"}}."},
    "servers": [{"url": "/api/v1"}],
    "security": [{"bearerAuth": []}],
    "paths": paths,
    "components": {
        "securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}},
        "responses": {"Error": {"description": "Error", "content": {"application/json": {"schema": obj(
            error=obj(code=S, message=S, details={"type": "object"}))}}}},
    },
}
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "openapi.yaml")
with open(out, "w", encoding="utf-8") as f:
    yaml.safe_dump(spec, f, sort_keys=False, allow_unicode=True)
print("wrote", out, len(R), "operations")
