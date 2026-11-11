from flask import Blueprint, g, jsonify

from ..db import db
from ..security import (ALL, BILLING, FLOOR, KITCHEN, MGMT, ROLES, hash_password, password_policy, require, rid)
from ..util import EMAIL_RE, body, conflict, forbidden, invalid, not_found, now_iso, validate
from .auth import public_user

bp = Blueprint("staff", __name__)
PRIVILEGED = ("owner", "manager")

PERMISSIONS = {
    "menu": {"read": ALL, "write": MGMT},
    "tables": {"read": ALL, "write": MGMT, "set_status": FLOOR},
    "reservations": {"read": FLOOR, "write": FLOOR},
    "orders": {"read": ALL, "write": FLOOR, "cancel_after_kitchen_start": MGMT},
    "kitchen": {"read": KITCHEN, "write": KITCHEN},
    "billing": {"read": BILLING, "write": BILLING, "discount_over_20_percent": MGMT},
    "staff": {"read": MGMT, "write": MGMT, "manage_owner_or_manager": ("owner",)},
    "reports": {"read": MGMT},
    "settings": {"read": ALL, "write": ("owner",)},
}


def staff_out(u):
    return {**public_user(u), "created_at": u["created_at"]}


def target(uid):
    u = db().one("SELECT * FROM users WHERE id=? AND restaurant_id=?", (uid, rid()))
    if not u:
        raise not_found("Staff member")
    return u


def check_hierarchy(actor, target_role, new_role=None):
    if actor["role"] != "owner" and (target_role in PRIVILEGED or new_role in PRIVILEGED):
        raise forbidden("Only the owner can manage owners and managers")


@bp.get("/staff/permissions")
@require()
def permissions():
    return jsonify(roles=list(ROLES), permissions={k: {a: list(r) for a, r in v.items()} for k, v in PERMISSIONS.items()})


@bp.get("/staff")
@require(*MGMT)
def list_staff():
    rows = db().query("SELECT * FROM users WHERE restaurant_id=? ORDER BY active DESC, name", (rid(),))
    return jsonify(items=[staff_out(r) for r in rows])


@bp.post("/staff")
@require(*MGMT)
def create_staff():
    d = validate(body(), {"name": {"required": True, "max_len": 120},
                          "email": {"required": True, "max_len": 254, "pattern": EMAIL_RE},
                          "password": {"required": True}, "role": {"required": True, "choices": ROLES}})
    check_hierarchy(g.user, d["role"])
    password_policy(d["password"])
    uid = db().insert(
        "INSERT INTO users(restaurant_id,name,email,password_hash,role,created_at) VALUES (?,?,?,?,?,?)",
        (rid(), d["name"], d["email"].lower(), hash_password(d["password"]), d["role"], now_iso()),
        conflict="An account with this email already exists")
    return jsonify(staff_out(target(uid))), 201


@bp.put("/staff/<int:uid>")
@require(*MGMT)
def update_staff(uid):
    u = target(uid)
    d = validate(body(), {"name": {"max_len": 120}, "role": {"choices": ROLES}, "active": {"type": bool}})
    check_hierarchy(g.user, u["role"], d.get("role"))
    if "name" in d and not d["name"]:
        raise invalid("Invalid input", {"name": "must not be empty"})
    demoting = ("role" in d and d["role"] != u["role"]) or d.get("active") is False
    if u["id"] == g.user["id"] and demoting:
        raise conflict("You cannot change your own role or deactivate your own account")
    if u["role"] == "owner" and demoting:
        others = db().one("SELECT COUNT(*) AS n FROM users WHERE restaurant_id=? AND role='owner' AND active=1 AND id<>?",
                          (rid(), uid))["n"]
        if not others:
            raise conflict("The restaurant must keep at least one active owner")
    if "active" in d:
        d["active"] = int(d["active"])
    if d:
        cols = ", ".join(f"{k}=?" for k in d)
        extra = ", token_version=token_version+1" if demoting else ""
        db().execute(f"UPDATE users SET {cols}{extra} WHERE id=? AND restaurant_id=?", (*d.values(), uid, rid()))
    return jsonify(staff_out(target(uid)))


@bp.post("/staff/<int:uid>/reset-password")
@require(*MGMT)
def reset_password(uid):
    u = target(uid)
    check_hierarchy(g.user, u["role"])
    d = validate(body(), {"new_password": {"required": True}})
    password_policy(d["new_password"])
    db().execute("UPDATE users SET password_hash=?, token_version=token_version+1 WHERE id=? AND restaurant_id=?",
                 (hash_password(d["new_password"]), uid, rid()))
    return jsonify(message="Password reset; the user was signed out everywhere")
