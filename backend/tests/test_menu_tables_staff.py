from tests.base import PW, ApiTest


class MenuTests(ApiTest):
    def test_category_and_item_crud(self):
        o = self.register()
        cat = self.call("post", "/categories", o, {"name": "Starters", "sort_order": 1}, 201).get_json()
        self.call("post", "/categories", o, {"name": "Starters"}, 409)
        item = self.call("post", "/menu-items", o, {"category_id": cat["id"], "name": "Salad", "price": 700,
                                                      "description": "Green"}, 201).get_json()
        self.assertTrue(item["available"])
        self.call("put", f"/menu-items/{item['id']}", o, {"price": 800, "available": False}, 200)
        got = self.call("get", f"/menu-items/{item['id']}", o, expect=200).get_json()
        self.assertEqual((got["price"], got["available"], got["name"]), (800, False, "Salad"))
        self.assertEqual(len(self.call("get", "/menu-items?available=true", o, expect=200).get_json()["items"]), 0)
        self.assertEqual(len(self.call("get", "/menu-items?q=sal", o, expect=200).get_json()["items"]), 1)
        self.call("delete", f"/categories/{cat['id']}", o, expect=409)  # still has items
        self.call("delete", f"/menu-items/{item['id']}", o, expect=204)
        self.call("delete", f"/categories/{cat['id']}", o, expect=204)

    def test_validation(self):
        o = self.register()
        cat = self.call("post", "/categories", o, {"name": "A"}, 201).get_json()["id"]
        bad = [{"category_id": cat, "name": "X", "price": -1}, {"category_id": cat, "name": "X", "price": "9"},
               {"category_id": cat, "name": "  ", "price": 1}, {"category_id": 999, "name": "X", "price": 1},
               {"category_id": cat, "price": 1}, {"category_id": cat, "name": "X", "price": True}]
        for payload in bad:
            self.assertIn(self.call("post", "/menu-items", o, payload).status_code, (404, 422), payload)

    def test_used_item_is_archived_not_deleted(self):
        o = self.register()
        ids = self.seed(o)
        k = self.add_staff(o, "kitchen")
        self.place_order(o, ids)
        self.call("delete", f"/menu-items/{ids['pasta']}", o, expect=204)
        names = [i["name"] for i in self.call("get", "/menu-items", o, expect=200).get_json()["items"]]
        self.assertNotIn("Pasta", names)
        order = self.call("get", "/kitchen/orders", k, expect=200).get_json()["items"][0]
        self.assertIn("Pasta", [i["name"] for i in order["items"]])  # history intact


class RoleTests(ApiTest):
    def test_role_matrix(self):
        o = self.register()
        ids = self.seed(o)
        w, c, k, m = (self.add_staff(o, r) for r in ("waiter", "cashier", "kitchen", "manager"))
        # menu writes: only owner/manager
        for tok in (w, c, k):
            self.call("post", "/categories", tok, {"name": "Z"}, 403)
            self.call("put", f"/menu-items/{ids['pasta']}", tok, {"price": 1}, 403)
        self.call("post", "/categories", m, {"name": "Desserts"}, 201)
        # kitchen cannot take orders; waiter cannot use the kitchen board
        self.call("post", "/orders", k, {"table_id": ids["t1"], "items": [{"menu_item_id": ids["pasta"], "quantity": 1}]}, 403)
        self.call("get", "/kitchen/orders", w, expect=403)
        # reports/dashboard/staff list: management only
        for tok in (w, c, k):
            self.call("get", "/dashboard", tok, expect=403)
            self.call("get", "/reports/sales", tok, expect=403)
            self.call("get", "/staff", tok, expect=403)
        self.call("get", "/dashboard", m, expect=200)
        # billing: waiter and kitchen cannot; cashier can read bills
        self.call("get", "/bills", w, expect=403)
        self.call("get", "/bills", c, expect=200)
        # settings: everyone reads, only owner writes
        self.call("get", "/settings", k, expect=200)
        self.call("put", "/settings", m, {"tax_rate": 5}, 403)
        # everyone can read the permission matrix
        self.assertIn("billing", self.call("get", "/staff/permissions", k, expect=200).get_json()["permissions"])


class TableTests(ApiTest):
    def test_table_crud_and_status(self):
        o = self.register()
        t = self.call("post", "/tables", o, {"label": "A1", "capacity": 4}, 201).get_json()
        self.call("post", "/tables", o, {"label": "A1", "capacity": 2}, 409)
        self.call("post", "/tables", o, {"label": "A2", "capacity": 0}, 422)
        self.call("put", f"/tables/{t['id']}", o, {"capacity": 6}, 200)
        r = self.call("patch", f"/tables/{t['id']}/status", o, {"status": "reserved"}, 200).get_json()
        self.assertEqual((r["status"], r["capacity"]), ("reserved", 6))
        self.call("patch", f"/tables/{t['id']}/status", o, {"status": "broken"}, 422)
        self.call("delete", f"/tables/{t['id']}", o, expect=204)

    def test_reservations(self):
        o = self.register()
        ids = self.seed(o)
        when = self.future(24)
        base = {"table_id": ids["t2"], "customer_name": "Sam", "party_size": 2, "reserved_for": when}
        r = self.call("post", "/reservations", o, base, 201).get_json()
        self.call("post", "/reservations", o, {**base, "customer_name": "Clash"}, 409)  # same slot
        self.call("post", "/reservations", o, {**base, "party_size": 3}, 422)  # over capacity
        self.call("post", "/reservations", o, {**base, "reserved_for": "2001-01-01T10:00:00Z"}, 422)  # past
        self.call("post", "/reservations", o, {**base, "reserved_for": "tomorrow"}, 422)
        self.call("post", "/reservations", o, {**base, "reserved_for": self.future(30)}, 201)  # different time ok
        tables = self.call("get", "/tables", o, expect=200).get_json()["items"]
        t2 = next(t for t in tables if t["id"] == ids["t2"])
        self.assertEqual(t2["next_reservation"]["customer_name"], "Sam")
        # seat -> occupied, complete -> available
        s = self.call("patch", f"/reservations/{r['id']}/status", o, {"status": "seated"}, 200).get_json()
        self.assertEqual(s["status"], "seated")
        occ = [t for t in self.call("get", "/tables", o, expect=200).get_json()["items"] if t["id"] == ids["t2"]][0]
        self.assertEqual(occ["status"], "occupied")
        self.call("patch", f"/reservations/{r['id']}/status", o, {"status": "cancelled"}, 409)  # invalid transition
        self.call("patch", f"/reservations/{r['id']}/status", o, {"status": "completed"}, 200)
        free = [t for t in self.call("get", "/tables", o, expect=200).get_json()["items"] if t["id"] == ids["t2"]][0]
        self.assertEqual(free["status"], "available")
        self.assertEqual(len(self.call("get", f"/reservations?date={when[:10]}", o, expect=200).get_json()["items"]) >= 1, True)
        self.call("delete", f"/tables/{ids['t2']}", o, expect=409)  # has history


class StaffTests(ApiTest):
    def test_staff_lifecycle(self):
        o = self.register()
        w = self.add_staff(o, "waiter")
        staff = self.call("get", "/staff", o, expect=200).get_json()["items"]
        wid = next(s["id"] for s in staff if s["role"] == "waiter")
        self.call("post", "/staff", o, {"name": "D", "email": "waiter@example.com", "password": PW, "role": "waiter"}, 409)
        self.call("put", f"/staff/{wid}", o, {"role": "cashier"}, 200)
        self.call("get", "/auth/me", w, expect=401)  # role change forces re-login
        w = self.login("waiter@example.com")
        self.call("put", f"/staff/{wid}", o, {"active": False}, 200)
        self.call("get", "/auth/me", w, expect=401)
        self.call("post", "/auth/login", json={"email": "waiter@example.com", "password": PW}, expect=401)
        self.call("put", f"/staff/{wid}", o, {"active": True}, 200)
        w = self.login("waiter@example.com")
        self.call("post", f"/staff/{wid}/reset-password", o, {"new_password": "Reset1234"}, 200)
        self.call("get", "/auth/me", w, expect=401)
        self.login("waiter@example.com", "Reset1234")

    def test_hierarchy_rules(self):
        o = self.register()
        m = self.add_staff(o, "manager")
        self.call("post", "/staff", m, {"name": "X", "email": "x@x.co", "password": PW, "role": "manager"}, 403)
        self.call("post", "/staff", m, {"name": "X", "email": "x@x.co", "password": PW, "role": "owner"}, 403)
        self.call("post", "/staff", m, {"name": "X", "email": "x@x.co", "password": PW, "role": "waiter"}, 201)
        me = self.call("get", "/auth/me", o, expect=200).get_json()["user"]["id"]
        self.call("put", f"/staff/{me}", m, {"active": False}, 403)  # manager cannot touch owner
        self.call("put", f"/staff/{me}", o, {"active": False}, 409)  # cannot deactivate yourself
        self.call("put", f"/staff/{me}", o, {"role": "manager"}, 409)  # nor demote yourself / last owner
        self.call("post", f"/staff/{me}/reset-password", m, {"new_password": "Reset1234"}, 403)
        self.call("post", "/staff", o, {"name": "X", "email": "y@x.co", "password": "weak", "role": "waiter"}, 422)
        self.call("post", "/staff", o, {"name": "X", "email": "y@x.co", "password": PW, "role": "janitor"}, 422)
