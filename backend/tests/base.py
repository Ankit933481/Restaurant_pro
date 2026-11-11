import os
import tempfile
import unittest
from datetime import timedelta

from app import create_app
from app.security import reset_throttle
from app.util import iso, now

PW = "Passw0rd!x"


class ApiTest(unittest.TestCase):
    def setUp(self):
        reset_throttle()
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.app = create_app({"SECRET_KEY": "k" * 48, "DATABASE_URL": self.path, "TESTING": True})
        self.c = self.app.test_client()

    def tearDown(self):
        os.unlink(self.path)

    # -- helpers ------------------------------------------------------------------
    def call(self, method, url, token=None, json=None, expect=None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        r = getattr(self.c, method)("/api/v1" + url, json=json, headers=headers)
        if expect is not None:
            self.assertEqual(r.status_code, expect, f"{method.upper()} {url} -> {r.status_code} {r.get_data(as_text=True)}")
        return r

    def register(self, name="Bistro", email="owner@example.com"):
        r = self.call("post", "/auth/register", json={"restaurant_name": name, "name": "Olivia Owner",
                                                      "email": email, "password": PW}, expect=201)
        return r.get_json()["token"]

    def login(self, email, password=PW):
        return self.call("post", "/auth/login", json={"email": email, "password": password}, expect=200).get_json()["token"]

    def add_staff(self, owner, role, email=None):
        email = email or f"{role}@example.com"
        self.call("post", "/staff", owner, {"name": role.title(), "email": email, "password": PW, "role": role}, 201)
        return self.login(email)

    def seed(self, owner):
        """Category + two items + two tables. Returns ids."""
        cat = self.call("post", "/categories", owner, {"name": "Mains"}, 201).get_json()["id"]
        pasta = self.call("post", "/menu-items", owner, {"category_id": cat, "name": "Pasta", "price": 1000}, 201).get_json()["id"]
        soup = self.call("post", "/menu-items", owner, {"category_id": cat, "name": "Soup", "price": 550}, 201).get_json()["id"]
        t1 = self.call("post", "/tables", owner, {"label": "T1", "capacity": 4}, 201).get_json()["id"]
        t2 = self.call("post", "/tables", owner, {"label": "T2", "capacity": 2}, 201).get_json()["id"]
        return dict(cat=cat, pasta=pasta, soup=soup, t1=t1, t2=t2)

    def set_rates(self, owner, tax=10, service=5):
        self.call("put", "/settings", owner, {"tax_rate": tax, "service_charge_rate": service}, 200)

    def place_order(self, token, ids, table="t1", qty=(2, 1)):
        return self.call("post", "/orders", token, {"table_id": ids[table], "items": [
            {"menu_item_id": ids["pasta"], "quantity": qty[0]}, {"menu_item_id": ids["soup"], "quantity": qty[1]}]}, 201).get_json()

    def to_ready(self, kitchen, oid):
        self.call("patch", f"/kitchen/orders/{oid}/status", kitchen, {"status": "preparing"}, 200)
        self.call("patch", f"/kitchen/orders/{oid}/status", kitchen, {"status": "ready"}, 200)

    @staticmethod
    def future(hours=24):
        return iso(now() + timedelta(hours=hours))
