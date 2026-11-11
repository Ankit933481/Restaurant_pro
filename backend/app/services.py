"""Business rules shared by several route modules."""
from .db import db
from .util import now_iso

ACTIVE = ("new", "preparing", "ready", "served")


def release_table_if_idle(table_id, restaurant_id):
    """Mark an occupied table available when it has no active orders left."""
    if table_id is None:
        return
    n = db().one(
        "SELECT COUNT(*) AS n FROM orders WHERE table_id=? AND restaurant_id=? "
        "AND status IN ('new','preparing','ready','served')", (table_id, restaurant_id))["n"]
    if n == 0:
        db().execute("UPDATE dining_tables SET status='available' WHERE id=? AND restaurant_id=? "
                     "AND status='occupied'", (table_id, restaurant_id))


def set_order_status(order_id, restaurant_id, status):
    db().execute("UPDATE orders SET status=?, updated_at=? WHERE id=? AND restaurant_id=?",
                 (status, now_iso(), order_id, restaurant_id))
