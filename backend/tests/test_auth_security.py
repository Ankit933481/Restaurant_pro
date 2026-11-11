import time
import jwt
from tests.base import PW, ApiTest


class AuthTests(ApiTest):
    def test_register_login_me_logout_revokes_token(self):
        token = self.register()
        me = self.call("get", "/auth/me", token, expect=200).get_json()
        self.assertEqual(me["user"]["role"], "owner")
        self.assertEqual(me["restaurant"]["currency"], "USD")
        t2 = self.login("OWNER@example.com")  # email is case-insensitive
        self.call("post", "/auth/logout", t2, expect=200)
        self.call("get", "/auth/me", t2, expect=401)
        self.call("get", "/auth/me", token, expect=200)  # other session unaffected

    def test_registration_validation(self):
        base = {"restaurant_name": "R", "name": "N", "email": "a@b.co", "password": PW}
        self.call("post", "/auth/register", json={**base, "password": "short1"}, expect=422)
        self.call("post", "/auth/register", json={**base, "password": "allletters"}, expect=422)
        self.call("post", "/auth/register", json={**base, "password": "12345678"}, expect=422)
        self.call("post", "/auth/register", json={**base, "email": "nope"}, expect=422)
        self.call("post", "/auth/register", json={"name": "N"}, expect=422)
        self.register(email="dup@example.com")
        self.call("post", "/auth/register", json={**base, "email": "dup@example.com"}, expect=409)

    def test_bad_login_and_lockout(self):
        self.register()
        for _ in range(5):
            self.call("post", "/auth/login", json={"email": "owner@example.com", "password": "wrong-pass1"}, expect=401)
        self.call("post", "/auth/login", json={"email": "owner@example.com", "password": PW}, expect=429)
        self.call("post", "/auth/login", json={"email": "ghost@example.com", "password": PW}, expect=401)

    def test_unauthenticated_and_tampered_tokens(self):
        self.call("get", "/menu-items", expect=401)
        self.call("get", "/menu-items", "garbage", expect=401)
        forged = jwt.encode({"sub": "1", "rid": 1, "role": "owner", "tv": 0, "jti": "x", "exp": int(time.time()) + 999},
                            "wrong-secret-wrong-secret-wrong-secret", algorithm="HS256")
        self.call("get", "/menu-items", forged, expect=401)
        expired = jwt.encode({"sub": "1", "rid": 1, "role": "owner", "tv": 0, "jti": "y", "exp": int(time.time()) - 10},
                             "k" * 48, algorithm="HS256")
        self.call("get", "/menu-items", expired, expect=401)

    def test_change_password_invalidates_old_tokens(self):
        old = self.register()
        r = self.call("post", "/auth/change-password", old,
                      {"current_password": PW, "new_password": "NewPassw0rd"}, 200).get_json()
        self.call("get", "/auth/me", old, expect=401)
        self.call("get", "/auth/me", r["token"], expect=200)
        self.call("post", "/auth/change-password", r["token"], {"current_password": "bad", "new_password": "Another1pass"}, 401)
        self.login("owner@example.com", "NewPassw0rd")

    def test_error_format_and_bad_bodies(self):
        r = self.c.post("/api/v1/auth/login", data="not json", content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["error"]["code"], "invalid_body")
        r = self.c.get("/api/v1/nope")
        self.assertEqual(r.status_code, 404)
        self.assertIn("error", r.get_json())
        r = self.c.delete("/api/v1/auth/login")
        self.assertEqual(r.status_code, 405)
        self.assertEqual(self.c.get("/health").get_json(), {"status": "ok"})
        self.assertIn("nosniff", self.c.get("/health").headers["X-Content-Type-Options"])

    def test_secret_key_required(self):
        from app import create_app
        with self.assertRaises(RuntimeError):
            create_app({"SECRET_KEY": "short", "DATABASE_URL": self.path})

    def test_registration_can_be_disabled(self):
        from app import create_app
        app = create_app({"SECRET_KEY": "k" * 48, "DATABASE_URL": self.path, "ALLOW_REGISTRATION": False})
        r = app.test_client().post("/api/v1/auth/register", json={
            "restaurant_name": "R", "name": "N", "email": "z@z.co", "password": PW})
        self.assertEqual(r.status_code, 403)
