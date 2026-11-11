"""Verifies that every *required* property (no default) of each Kotlin response model is present in the
JSON the real backend returns. Run from backend/:  python tools/check_android_contract.py"""
import os, re, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import timedelta
from app import create_app
from app.util import iso, now

MODELS = os.path.join(os.path.dirname(__file__), "..", "..", "android", "app", "src", "main", "java",
                      "com", "restaurantpro", "app", "data", "Models.kt")
src = open(MODELS, encoding="utf-8").read()


def snake(n):
    return re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", n).lower()


def parse_models():
    models = {}
    for m in re.finditer(r"@Serializable data class (\w+)(?:<\w+>)?\((.*?)\)\s*(?:\n|$)", src, re.S):
        name, body = m.group(1), m.group(2)
        params, depth, cur = [], 0, ""
        for ch in body:
            depth += ch in "<(["; depth -= ch in ">)]"
            if ch == "," and depth == 0:
                params.append(cur); cur = ""
            else:
                cur += ch
        params.append(cur)
        req, allp = [], []
        for p in params:
            p = p.strip()
            if not p:
                continue
            p = re.sub(r"@SerialName\(\"(\w+)\"\)\s*", "", p)
            sn = re.search(r"@SerialName\(\"(\w+)\"\)", m.group(2))
            mm = re.match(r"val (\w+)\s*:\s*([^=]+?)\s*(=.*)?$", p, re.S)
            if mm:
                key = "last_7_days" if mm.group(1) == "last7Days" else snake(mm.group(1))
                allp.append(key)
                if not mm.group(3) and not mm.group(2).strip().endswith("?"):
                    req.append(key)
        models[name] = (req, allp)
    return models


models = parse_models()
fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd)
app = create_app({"SECRET_KEY": "k" * 48, "DATABASE_URL": path})
c = app.test_client()
PW = "Passw0rd!x"


def call(method, url, tok=None, js=None):
    r = getattr(c, method)("/api/v1" + url, json=js, headers={"Authorization": f"Bearer {tok}"} if tok else {})
    assert r.status_code < 400, (method, url, r.status_code, r.get_data(as_text=True))
    return r.get_json()


reg = call("post", "/auth/register", js={"restaurant_name": "R", "name": "O", "email": "o@o.co", "password": PW})
t = reg["token"]
cat = call("post", "/categories", t, {"name": "Mains"})
item = call("post", "/menu-items", t, {"category_id": cat["id"], "name": "Pasta", "price": 1000})
tbl = call("post", "/tables", t, {"label": "T1", "capacity": 4})
call("put", "/settings", t, {"tax_rate": 10})
order = call("post", "/orders", t, {"table_id": tbl["id"], "items": [{"menu_item_id": item["id"], "quantity": 2}]})
resv = call("post", "/reservations", t, {"table_id": tbl["id"], "customer_name": "Sam", "party_size": 2,
                                          "reserved_for": iso(now() + timedelta(days=1))})
call("post", "/staff", t, {"name": "W", "email": "w@o.co", "password": PW, "role": "waiter"})
preview = call("post", f"/orders/{order['id']}/bill/preview", t, {})
bill = call("post", f"/orders/{order['id']}/bill", t, {"payment_method": "cash", "amount_tendered": 5000})

checks = [
    ("AuthResponse", reg), ("User", reg["user"]), ("MeResponse", call("get", "/auth/me", t)),
    ("RestaurantInfo", call("get", "/auth/me", t)["restaurant"]),
    ("Category", cat), ("MenuItem", item), ("Category", call("get", "/categories", t)["items"][0]),
    ("DiningTable", call("get", "/tables", t)["items"][0]),
    ("NextReservation", call("get", "/tables", t)["items"][0]["next_reservation"]),
    ("Reservation", resv), ("Order", order), ("Order", call("get", "/orders", t)["items"][0]),
    ("OrderItem", order["items"][0]), ("Order", call("get", f"/orders/{order['id']}", t)),
    ("BillPreview", preview), ("Bill", bill), ("Bill", call("get", f"/bills/{bill['id']}", t)),
    ("Bill", call("get", "/bills", t)["items"][0]), ("OrderItem", bill["items"][0]),
    ("User", call("get", "/staff", t)["items"][0]), ("Settings", call("get", "/settings", t)),
    ("Settings", call("put", "/settings", t, {"name": "R2"})),
    ("PermissionsResponse", call("get", "/staff/permissions", t)),
    ("Dashboard", call("get", "/dashboard", t)), ("DayTotals", call("get", "/dashboard", t)["today"]),
    ("TableCounts", call("get", "/dashboard", t)["tables"]),
    ("SeriesPoint", call("get", "/dashboard", t)["last_7_days"][0]),
    ("TopItem", call("get", "/dashboard", t)["top_items"][0]),
    ("SalesReport", call("get", "/reports/sales?period=weekly", t)),
    ("SeriesPoint", call("get", "/reports/sales?period=daily", t)["series"][0]),
    ("MethodTotals", call("get", "/reports/sales", t)["payment_methods"]["cash"]),
]
# kitchen queue needs a fresh open order
t2 = call("post", "/tables", t, {"label": "T2", "capacity": 2})
o2 = call("post", "/orders", t, {"table_id": t2["id"], "items": [{"menu_item_id": item["id"], "quantity": 1}]})
checks.append(("Order", call("get", "/kitchen/orders", t)["items"][0]))
# last: it revokes the current token
checks.append(("TokenResponse", call("post", "/auth/change-password", t, {"current_password": PW, "new_password": "Another1pass"})))

bad = 0
for name, payload in checks:
    req, allp = models[name]
    missing = [k for k in req if k not in payload]
    if missing:
        bad += 1
        print(f"MISMATCH {name}: required Kotlin fields missing from API response: {missing}")
print(f"checked {len(checks)} responses against {len(models)} Kotlin models; mismatches: {bad}")
os.unlink(path)
sys.exit(1 if bad else 0)
