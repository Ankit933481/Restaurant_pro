import os
import sqlite3
import psycopg2
from psycopg2 import sql

SOURCE = "restaurant.db"
TARGET = os.environ.get("RENDER_DATABASE_URL")

if not TARGET:
    raise SystemExit("Set RENDER_DATABASE_URL in this terminal first.")

# Parent tables must be copied before dependent tables.
TABLES = [
    "restaurants",
    "users",
    "categories",
    "menu_items",
    "dining_tables",
    "reservations",
    "orders",
    "order_items",
    "bills",
    "revoked_tokens",
]

src = sqlite3.connect(SOURCE)
src.row_factory = sqlite3.Row
dst = psycopg2.connect(TARGET)

try:
    with dst:
        with dst.cursor() as cur:
            # Refuse to merge into a non-empty cloud database.
            for table in TABLES:
                cur.execute(
                    sql.SQL("SELECT COUNT(*) FROM {}").format(
                        sql.Identifier(table)
                    )
                )
                count = cur.fetchone()[0]
                if count:
                    raise RuntimeError(
                        f"Cloud table {table} is not empty ({count} rows). "
                        "Migration stopped without importing."
                    )

            total = 0
            for table in TABLES:
                rows = src.execute(f'SELECT * FROM "{table}"').fetchall()
                if not rows:
                    print(f"{table}: 0 rows")
                    continue

                columns = rows[0].keys()
                insert_stmt = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                    sql.Identifier(table),
                    sql.SQL(", ").join(map(sql.Identifier, columns)),
                    sql.SQL(", ").join(sql.Placeholder() for _ in columns),
                )

                for row in rows:
                    cur.execute(insert_stmt, tuple(row[column] for column in columns))

                print(f"{table}: imported {len(rows)} rows")
                total += len(rows)

            # Reset PostgreSQL generated-ID sequences to the imported IDs.
            for table in TABLES:
                if table == "revoked_tokens":
                    continue
                cur.execute(
                    """
                    SELECT pg_get_serial_sequence(%s, 'id')
                    """,
                    (f"public.{table}",),
                )
                sequence = cur.fetchone()[0]
                if sequence:
                    cur.execute(
                        sql.SQL("""
                            SELECT setval(
                                %s,
                                COALESCE((SELECT MAX(id) FROM {}), 1),
                                EXISTS (SELECT 1 FROM {})
                            )
                        """).format(
                            sql.Identifier(table),
                            sql.Identifier(table),
                        ),
                        (sequence,),
                    )

    print(f"\nMigration completed. Total rows imported: {total}")

except Exception:
    dst.rollback()
    raise
finally:
    src.close()
    dst.close()
