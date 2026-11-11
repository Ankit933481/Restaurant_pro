"""Password hashing, JWT issue/verify, role-based access control."""
import hashlib
import hmac
import os
import re
import time
import uuid
from functools import wraps

import jwt
from flask import current_app, g, request

from .db import db
from .util import ApiError, forbidden, invalid

ROLES = ("owner", "manager", "cashier", "waiter", "kitchen")
ALL = ROLES
MGMT = ("owner", "manager")
FLOOR = ("owner", "manager", "cashier", "waiter")
BILLING = ("owner", "manager", "cashier")
KITCHEN = ("owner", "manager", "kitchen")

_SCRYPT = dict(n=2**14, r=8, p=1, dklen=32)


def hash_password(password):
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    try:
        _, salt, digest = stored.split("$")
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), **_SCRYPT)
        return hmac.compare_digest(actual.hex(), digest)
    except (ValueError, TypeError):
        return False


_DUMMY_HASH = hash_password("dummy-password-for-timing")


def password_policy(password):
    problems = []
    if len(password) < 8:
        problems.append("at least 8 characters")
    if not re.search(r"[A-Za-z]", password):
        problems.append("a letter")
    if not re.search(r"\d", password):
        problems.append("a digit")
    if len(password) > 128:
        problems.append("at most 128 characters")
    if problems:
        raise invalid("Password does not meet requirements", {"password": "must contain " + ", ".join(problems)})


def issue_token(user):
    ttl = current_app.config["TOKEN_TTL_HOURS"] * 3600
    now = int(time.time())
    return jwt.encode(
        {"sub": str(user["id"]), "rid": user["restaurant_id"], "role": user["role"],
         "tv": user["token_version"], "jti": uuid.uuid4().hex, "iat": now, "exp": now + ttl},
        current_app.config["SECRET_KEY"], algorithm="HS256",
    )


def authenticate():
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise ApiError(401, "unauthorized", "Authentication required")
    try:
        claims = jwt.decode(header[7:], current_app.config["SECRET_KEY"], algorithms=["HS256"],
                            options={"require": ["exp", "sub", "jti"]})
    except jwt.PyJWTError:
        raise ApiError(401, "unauthorized", "Invalid or expired token")
    if db().one("SELECT jti FROM revoked_tokens WHERE jti=?", (claims["jti"],)):
        raise ApiError(401, "unauthorized", "Token has been revoked")
    user = db().one("SELECT * FROM users WHERE id=?", (int(claims["sub"]),))
    if (not user or not user["active"] or user["token_version"] != claims.get("tv")
            or user["restaurant_id"] != claims.get("rid")):
        raise ApiError(401, "unauthorized", "Account is inactive or credentials changed")
    g.user, g.claims = user, claims
    return user


def require(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = authenticate()
            if roles and user["role"] not in roles:
                raise forbidden()
            return fn(*args, **kwargs)
        return wrapper
    return deco


def rid():
    return g.user["restaurant_id"]


def restaurant():
    if "restaurant" not in g:
        g.restaurant = db().one("SELECT * FROM restaurants WHERE id=?", (rid(),))
    return g.restaurant


# Simple per-process login throttle (use a shared store such as Redis if you scale horizontally).
_FAILS = {}
MAX_FAILS, WINDOW = 5, 900


def check_lockout(key):
    recent = [t for t in _FAILS.get(key, []) if time.time() - t < WINDOW]
    _FAILS[key] = recent
    if len(recent) >= MAX_FAILS:
        raise ApiError(429, "too_many_attempts", "Too many failed logins. Try again in 15 minutes.")


def record_failure(key):
    _FAILS.setdefault(key, []).append(time.time())


def clear_failures(key):
    _FAILS.pop(key, None)


def reset_throttle():
    _FAILS.clear()
