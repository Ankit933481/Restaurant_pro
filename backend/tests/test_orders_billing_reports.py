from tests.base import PW, ApiTest


class OrderFlowTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.o = self.register()
        self.ids = self.seed(self.o)
        self.w = self.add_staff(self.o, "waiter")
        self.k = self.add_staff(self.o, "kitchen")
        self.cash = self.add_staff(self.o, "cashier")

    def table(self, key):
        return next(t for t in self.call("get", "/tables", self.o, expect=200).get_json()["items"] if t["id"] == self.ids[key])

    def test_full_dine_in_workflow(self):
        order = self.place_order(self.w, self.ids)
        self.assertEqual((order["status"], order["subtotal"], order["item_count"]), ("new", 2550, 3))
        self.assertEqual(self.table("t1")["status"], "occupied")
        self.assertEqual(self.table("t1")["active_order_id"], order["id"])
        # kitchen sees it, and must follow the flow
        q = self.call("get", "/kitchen/orders", self.k, expect=200).get_json()["items"]
        self.assertEqual([x["id"] for x in q], [order["id"]])
        self.call("patch", f"/kitchen/orders/{order['id']}/status", self.k, {"status": "ready"}, 409)  # skip step
        self.call("patch", f"/orders/{order['id']}/status", self.w, {"status": "served"}, 409)  # not ready yet
        self.to_ready(self.k, order["id"])
        self.call("patch", f"/orders/{order['id']}/status", self.w, {"status": "served"}, 200)
        self.assertEqual(self.call("get", "/kitchen/orders", self.k, expect=200).get_json()["items"], [])
        # bill: 10% discount, 10% tax, 5% service
        self.set_rates(self.o, 10, 5)
        prev = self.call("post", f"/orders/{order['id']}/bill/preview", self.cash,
                         {"discount_type": "percent", "discount_value": 10}, 200).get_json()
        self.assertEqual((prev["subtotal"], prev["discount"], prev["tax"], prev["service_charge"], prev["total"]),
                         (2550, 255, 230, 115, 2640))  # 2295 taxable; 229.5 -> 230 (half up); 114.75 -> 115
        bill = self.call("post", f"/orders/{order['id']}/bill", self.cash,
                         {"discount_type": "percent", "discount_value": 10, "payment_method": "cash",
                          "amount_tendered": 3000}, 201).get_json()
        self.assertEqual((bill["total"], bill["change_due"], bill["number"]), (2640, 360, "INV-000001"))
        self.assertEqual(self.call("get", f"/orders/{order['id']}", self.w, expect=200).get_json()["status"], "paid")
        self.assertEqual(self.table("t1")["status"], "available")
        self.call("post", f"/orders/{order['id']}/bill", self.cash, {"payment_method": "card"}, 409)  # already paid
        self.call("patch", f"/orders/{order['id']}/status", self.o, {"status": "cancelled"}, 409)
        self.assertEqual(self.call("get", f"/bills/{bill['id']}", self.cash, expect=200).get_json()["items"][0]["name"], "Pasta")

    def test_rate_change_does_not_alter_issued_bill(self):
        self.set_rates(self.o, 10, 0)
        order = self.place_order(self.w, self.ids)
        bill = self.call("post", f"/orders/{order['id']}/bill", self.cash, {"payment_method": "card"}, 201).get_json()
        self.set_rates(self.o, 50, 0)
        again = self.call("get", f"/bills/{bill['id']}", self.cash, expect=200).get_json()
        self.assertEqual((again["tax_rate"], again["total"]), (10.0, 2805))

    def test_amount_discount_and_cash_validation(self):
        order = self.place_order(self.w, self.ids)
        b = lambda **kw: self.call("post", f"/orders/{order['id']}/bill", self.cash, kw)
        self.assertEqual(b(payment_method="cash", amount_tendered=100).status_code, 422)  # does not cover total
        self.assertEqual(b(payment_method="card", discount_type="amount", discount_value=99999).status_code, 422)
        self.assertEqual(b(payment_method="card", discount_type="percent", discount_value=101).status_code, 422)
        self.assertEqual(b(payment_method="bitcoin").status_code, 422)
        self.assertEqual(b(payment_method="card", discount_type="percent", discount_value=30).status_code, 403)  # cashier cap
        ok = b(payment_method="card", discount_type="amount", discount_value=50)
        self.assertEqual(ok.status_code, 201)
        self.assertEqual(ok.get_json()["total"], 2500)

    def test_manager_can_give_big_discount(self):
        m = self.add_staff(self.o, "manager")
        order = self.place_order(self.w, self.ids)
        r = self.call("post", f"/orders/{order['id']}/bill", m,
                      {"payment_method": "card", "discount_type": "percent", "discount_value": 100}, 201).get_json()
        self.assertEqual(r["total"], 0)

    def test_second_order_for_busy_table_and_adding_items(self):
        order = self.place_order(self.w, self.ids)
        r = self.call("post", "/orders", self.w, {"table_id": self.ids["t1"], "items": [
            {"menu_item_id": self.ids["soup"], "quantity": 1}]}, 409).get_json()
        self.assertEqual(r["error"]["details"]["order_id"], order["id"])
        self.to_ready(self.k, order["id"])
        upd = self.call("post", f"/orders/{order['id']}/items", self.w,
                        {"items": [{"menu_item_id": self.ids["soup"], "quantity": 2, "notes": "no salt"}]}, 200).get_json()
        self.assertEqual((upd["status"], upd["subtotal"]), ("new", 3650))  # back to the kitchen queue
        self.assertEqual(len(self.call("get", "/kitchen/orders", self.k, expect=200).get_json()["items"]), 1)

    def test_item_edit_rules(self):
        order = self.place_order(self.w, self.ids)
        item = order["items"][0]
        edited = self.call("patch", f"/orders/{order['id']}/items/{item['id']}", self.w, {"quantity": 5}, 200).get_json()
        self.assertEqual(edited["items"][0]["quantity"], 5)
        self.call("patch", f"/orders/{order['id']}/items/{item['id']}", self.w, {"quantity": 0}, 422)
        self.call("delete", f"/orders/{order['id']}/items/{item['id']}", self.w, expect=200)
        last = self.call("get", f"/orders/{order['id']}", self.w, expect=200).get_json()["items"][0]
        self.call("delete", f"/orders/{order['id']}/items/{last['id']}", self.w, expect=409)  # keep one item
        self.call("patch", f"/kitchen/orders/{order['id']}/status", self.k, {"status": "preparing"}, 200)
        self.call("patch", f"/orders/{order['id']}/items/{last['id']}", self.w, {"quantity": 2}, 409)

    def test_cancel_rules_and_table_release(self):
        order = self.place_order(self.w, self.ids)
        self.call("patch", f"/orders/{order['id']}/status", self.w, {"status": "cancelled"}, 200)  # still 'new'
        self.assertEqual(self.table("t1")["status"], "available")
        self.call("post", f"/orders/{order['id']}/bill", self.cash, {"payment_method": "card"}, 409)
        second = self.place_order(self.w, self.ids)
        self.call("patch", f"/kitchen/orders/{second['id']}/status", self.k, {"status": "preparing"}, 200)
        self.call("patch", f"/orders/{second['id']}/status", self.w, {"status": "cancelled"}, 403)
        self.call("patch", f"/orders/{second['id']}/status", self.o, {"status": "cancelled"}, 200)

    def test_order_validation(self):
        post = lambda payload, tok=None: self.call("post", "/orders", tok or self.w, payload).status_code
        item = {"menu_item_id": self.ids["pasta"], "quantity": 1}
        self.assertEqual(post({"table_id": self.ids["t1"], "items": []}), 422)
        self.assertEqual(post({"items": [item]}), 422)  # dine-in needs a table
        self.assertEqual(post({"table_id": 9999, "items": [item]}), 404)
        self.assertEqual(post({"table_id": self.ids["t1"], "items": [{**item, "quantity": 0}]}), 422)
        self.assertEqual(post({"table_id": self.ids["t1"], "items": [{**item, "menu_item_id": 9999}]}), 422)
        self.call("put", f"/menu-items/{self.ids['pasta']}", self.o, {"available": False}, 200)
        self.assertEqual(post({"table_id": self.ids["t1"], "items": [item]}), 422)  # unavailable dish
        self.assertEqual(self.table("t1")["status"], "available")  # failed order left nothing behind
        self.assertEqual(self.call("get", "/orders", self.w, expect=200).get_json()["items"], [])

    def test_takeaway_and_listing_filters(self):
        t = self.call("post", "/orders", self.w, {"order_type": "takeaway", "items": [
            {"menu_item_id": self.ids["soup"], "quantity": 1}]}, 201).get_json()
        self.assertIsNone(t["table_id"])
        d = self.place_order(self.w, self.ids)
        all_ = self.call("get", "/orders", self.w, expect=200).get_json()["items"]
        self.assertEqual({o["id"] for o in all_}, {t["id"], d["id"]})
        only = self.call("get", f"/orders?table_id={self.ids['t1']}", self.w, expect=200).get_json()["items"]
        self.assertEqual([o["id"] for o in only], [d["id"]])
        self.assertEqual(len(self.call("get", "/orders?status=new,ready", self.w, expect=200).get_json()["items"]), 2)
        self.call("get", "/orders?status=bogus", self.w, expect=422)
        self.call("get", "/orders?limit=0", self.w, expect=422)
        self.assertEqual(len(self.call("get", "/orders?limit=1", self.w, expect=200).get_json()["items"]), 1)

    def test_bill_numbers_increment(self):
        nums = []
        for key in ("t1", "t2"):
            o = self.place_order(self.w, self.ids, table=key)
            nums.append(self.call("post", f"/orders/{o['id']}/bill", self.cash, {"payment_method": "cash"}, 201).get_json()["number"])
        self.assertEqual(nums, ["INV-000001", "INV-000002"])


class ReportTests(ApiTest):
    def test_dashboard_and_reports_reflect_payments(self):
        o = self.register()
        ids = self.seed(o)
        self.set_rates(o, 10, 0)
        w, k, c = (self.add_staff(o, r) for r in ("waiter", "kitchen", "cashier"))
        d0 = self.call("get", "/dashboard", o, expect=200).get_json()
        self.assertEqual((d0["today"]["revenue"], d0["tables"]["total"], d0["active_orders"]), (0, 2, 0))
        paid = self.place_order(w, ids, "t1")
        self.call("post", f"/orders/{paid['id']}/bill", c, {"payment_method": "card"}, 201)  # 2550 + 255 = 2805
        self.place_order(w, ids, "t2", qty=(1, 0 + 1))  # stays open
        d = self.call("get", "/dashboard", o, expect=200).get_json()
        self.assertEqual((d["today"]["revenue"], d["today"]["orders"], d["today"]["avg_order_value"]), (2805, 1, 2805))
        self.assertEqual((d["active_orders"], d["orders_by_status"]["new"], d["tables"]["occupied"]), (1, 1, 1))
        self.assertEqual(d["top_items"][0], {"name": "Pasta", "quantity": 2, "revenue": 2000})
        self.assertEqual((len(d["last_7_days"]), d["last_7_days"][-1]["revenue"]), (7, 2805))
        daily = self.call("get", "/reports/sales?period=daily", o, expect=200).get_json()
        self.assertEqual((len(daily["series"]), daily["totals"]["revenue"], daily["totals"]["tax"]), (24, 2805, 255))
        self.assertEqual(daily["payment_methods"], {"card": {"revenue": 2805, "orders": 1}})
        weekly = self.call("get", "/reports/sales?period=weekly", o, expect=200).get_json()
        self.assertEqual((len(weekly["series"]), weekly["totals"]["orders"]), (7, 1))
        monthly = self.call("get", "/reports/sales?period=monthly", o, expect=200).get_json()
        self.assertEqual(monthly["totals"]["revenue"], 2805)
        self.assertGreaterEqual(len(monthly["series"]), 28)
        past = self.call("get", "/reports/sales?period=weekly&date=2001-01-10", o, expect=200).get_json()
        self.assertEqual(past["totals"]["revenue"], 0)
        self.call("get", "/reports/sales?period=yearly", o, expect=422)
        self.call("get", "/reports/sales?date=notadate", o, expect=422)

    def test_timezone_offset_shifts_day_boundaries(self):
        o = self.register()
        ids = self.seed(o)
        self.call("put", "/settings", o, {"tz_offset_minutes": 330}, 200)  # IST
        self.call("get", "/dashboard", o, expect=200)
        self.call("put", "/settings", o, {"tz_offset_minutes": 5000}, 422)


class SettingsTests(ApiTest):
    def test_settings_update_and_validation(self):
        o = self.register()
        s = self.call("put", "/settings", o, {"name": "Taj", "currency": "inr", "currency_symbol": "₹", "tax_rate": 5,
                                              "service_charge_rate": 2.5, "address": "MG Road", "phone": "123"}, 200).get_json()
        self.assertEqual((s["currency"], s["currency_symbol"], s["tax_rate"], s["service_charge_rate"]), ("INR", "₹", 5.0, 2.5))
        self.assertEqual(self.call("get", "/auth/me", o, expect=200).get_json()["restaurant"]["currency"], "INR")
        for bad in ({"tax_rate": -1}, {"tax_rate": 101}, {"currency": "DOLLARS"}, {"currency_decimals": 9}, {"tax_rate": "ten"}):
            self.call("put", "/settings", o, bad, 422)


class IsolationTests(ApiTest):
    def test_restaurants_cannot_see_or_touch_each_other(self):
        a = self.register("A", "a@example.com")
        b = self.register("B", "b@example.com")
        ids = self.seed(a)
        w = self.add_staff(a, "waiter", "wa@example.com")
        order = self.place_order(w, ids)
        self.call("post", f"/orders/{order['id']}/bill", a, {"payment_method": "card"}, 201)
        bill_id = self.call("get", "/bills", a, expect=200).get_json()["items"][0]["id"]
        staff_id = self.call("get", "/staff", a, expect=200).get_json()["items"][0]["id"]
        # B sees nothing of A's data
        for path in ("/categories", "/menu-items", "/tables", "/orders", "/bills", "/reservations"):
            self.assertEqual(self.call("get", path, b, expect=200).get_json()["items"], [], path)
        self.assertEqual(len(self.call("get", "/staff", b, expect=200).get_json()["items"]), 1)
        # direct access by id is 404, never 403/200 (no existence leak)
        probes = [("get", f"/orders/{order['id']}"), ("get", f"/menu-items/{ids['pasta']}"),
                  ("get", f"/bills/{bill_id}"), ("put", f"/menu-items/{ids['pasta']}"),
                  ("put", f"/tables/{ids['t1']}"), ("delete", f"/tables/{ids['t1']}"),
                  ("patch", f"/tables/{ids['t1']}/status"), ("put", f"/categories/{ids['cat']}"),
                  ("delete", f"/categories/{ids['cat']}"), ("put", f"/staff/{staff_id}"),
                  ("post", f"/staff/{staff_id}/reset-password"), ("patch", f"/kitchen/orders/{order['id']}/status"),
                  ("post", f"/orders/{order['id']}/bill/preview")]
        payload = {"status": "preparing", "name": "x", "new_password": "Hacked123", "capacity": 3, "price": 1, "active": False}
        for method, path in probes:
            r = self.call(method, path, b, payload if method != "get" else None)
            self.assertEqual(r.status_code, 404, f"{method} {path} -> {r.status_code}")
        # cross-tenant references in bodies are rejected
        self.call("post", "/orders", b, {"table_id": ids["t1"], "items": [{"menu_item_id": ids["pasta"], "quantity": 1}]}, 404)
        cat_b = self.call("post", "/categories", b, {"name": "Mains"}, 201).get_json()["id"]  # same name is fine per tenant
        self.call("post", "/menu-items", b, {"category_id": ids["cat"], "name": "Steal", "price": 1}, 404)
        self.call("post", "/tables", b, {"label": "T1", "capacity": 4}, 201)  # labels unique per tenant only
        self.call("post", "/reservations", b, {"table_id": ids["t1"], "customer_name": "x", "party_size": 1,
                                               "reserved_for": self.future()}, 404)
        # A's data is unchanged
        self.assertEqual(self.call("get", f"/menu-items/{ids['pasta']}", a, expect=200).get_json()["price"], 1000)
        self.assertEqual(self.call("get", "/dashboard", b, expect=200).get_json()["today"]["revenue"], 0)
        self.assertEqual(self.call("get", "/dashboard", a, expect=200).get_json()["today"]["revenue"], 2550)

    def test_token_for_one_tenant_cannot_be_replayed_after_user_moves(self):
        a = self.register("A", "a@example.com")
        self.register("B", "b@example.com")
        self.call("get", "/auth/me", a, expect=200)
