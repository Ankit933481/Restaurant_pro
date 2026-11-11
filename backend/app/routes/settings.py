import re

from flask import Blueprint, jsonify

from ..db import db
from ..security import require, restaurant, rid
from ..util import body, validate

bp = Blueprint("settings", __name__)
FIELDS = ("name", "address", "phone", "currency", "currency_symbol", "currency_decimals", "tax_rate",
          "service_charge_rate", "tz_offset_minutes")


def out(r):
    return {k: r[k] for k in FIELDS}


@bp.get("/settings")
@require()
def read_settings():
    return jsonify(out(restaurant()))


@bp.put("/settings")
@require("owner")
def update_settings():
    d = validate(body(), {
        "name": {"max_len": 120}, "address": {"max_len": 250}, "phone": {"max_len": 30},
        "currency": {"pattern": re.compile(r"^[A-Za-z]{3}$")}, "currency_symbol": {"max_len": 6},
        "currency_decimals": {"type": int, "min": 0, "max": 3},
        "tax_rate": {"type": float, "min": 0, "max": 100},
        "service_charge_rate": {"type": float, "min": 0, "max": 100},
        "tz_offset_minutes": {"type": int, "min": -720, "max": 840},
    })
    if "currency" in d:
        d["currency"] = d["currency"].upper()
    if d.get("name") == "":
        d.pop("name")
    if d:
        cols = ", ".join(f"{k}=?" for k in d)
        db().execute(f"UPDATE restaurants SET {cols} WHERE id=?", (*d.values(), rid()))
    from flask import g
    g.pop("restaurant", None)
    return jsonify(out(restaurant()))
