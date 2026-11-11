from flask import Blueprint, current_app, g, jsonify, request

from ..db import db
from ..security import (ALL, _DUMMY_HASH, check_lockout, clear_failures, hash_password, issue_token,
                        password_policy, record_failure, require, verify_password)
from ..util import EMAIL_RE, ApiError, body, conflict, now_iso, validate

bp = Blueprint("auth", __name__)


def public_user(u):
    return {"id": u["id"], "restaurant_id": u["restaurant_id"], "name": u["name"], "email": u["email"],
            "role": u["role"], "active": bool(u["active"])}


@bp.post("/auth/register")
def register():
    if not current_app.config["ALLOW_REGISTRATION"]:
        raise ApiError(403, "registration_disabled", "Self-registration is disabled")
    d = validate(body(), {
        "restaurant_name": {"required": True, "max_len": 120},
        "name": {"required": True, "max_len": 120},
        "email": {"required": True, "max_len": 254, "pattern": EMAIL_RE},
        "password": {"required": True},
    })
    password_policy(d["password"])
    email = d["email"].lower()
    if db().one("SELECT id FROM users WHERE email=?", (email,)):
        raise conflict("An account with this email already exists")
    ts = now_iso()
    restaurant_id = db().insert("INSERT INTO restaurants(name, created_at) VALUES (?,?)",
                                (d["restaurant_name"], ts))
    uid = db().insert(
        "INSERT INTO users(restaurant_id,name,email,password_hash,role,created_at) VALUES (?,?,?,?,?,?)",
        (restaurant_id, d["name"], email, hash_password(d["password"]), "owner", ts),
        conflict="An account with this email already exists")
    if current_app.config["SEED_NEW_RESTAURANTS"]:
        from ..default_restaurant import seed_restaurant
        seed_restaurant(restaurant_id)
    user = db().one("SELECT * FROM users WHERE id=?", (uid,))
    return jsonify(token=issue_token(user), user=public_user(user)), 201


@bp.post("/auth/login")
def login():
    d = validate(body(), {"email": {"required": True, "max_len": 254}, "password": {"required": True, "max_len": 128}})
    email = d["email"].lower()
    check_lockout(email)
    user = db().one("SELECT * FROM users WHERE email=?", (email,))
    ok = verify_password(d["password"], user["password_hash"] if user else _DUMMY_HASH)
    if not user or not ok or not user["active"]:
        record_failure(email)
        raise ApiError(401, "invalid_credentials", "Incorrect email or password")
    clear_failures(email)
    return jsonify(token=issue_token(user), user=public_user(user))


@bp.post("/auth/logout")
@require()
def logout():
    db().execute("DELETE FROM revoked_tokens WHERE expires_at < ?", (int(__import__("time").time()),))
    db().execute("INSERT INTO revoked_tokens(jti, expires_at) VALUES (?,?)",
                 (g.claims["jti"], int(g.claims["exp"])))
    return jsonify(message="Logged out")


@bp.get("/auth/me")
@require()
def me():
    r = db().one("SELECT id,name,currency,currency_symbol,currency_decimals,tax_rate,service_charge_rate "
                 "FROM restaurants WHERE id=?", (g.user["restaurant_id"],))
    return jsonify(user=public_user(g.user), restaurant=r)


@bp.post("/auth/change-password")
@require(*ALL)
def change_password():
    d = validate(body(), {"current_password": {"required": True}, "new_password": {"required": True}})
    if not verify_password(d["current_password"], g.user["password_hash"]):
        raise ApiError(401, "invalid_credentials", "Current password is incorrect")
    password_policy(d["new_password"])
    db().execute("UPDATE users SET password_hash=?, token_version=token_version+1 WHERE id=?",
                 (hash_password(d["new_password"]), g.user["id"]))
    user = db().one("SELECT * FROM users WHERE id=?", (g.user["id"],))
    return jsonify(token=issue_token(user), message="Password changed; other sessions were signed out")
