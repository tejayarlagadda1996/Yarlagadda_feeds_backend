"""Lightweight SQLite column adds for existing DBs."""

from sqlalchemy import text
from sqlalchemy.engine import Engine


def _sqlite_columns(engine: Engine, table: str) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {r[1] for r in rows}


def ensure_schema(engine: Engine) -> None:
    url = str(engine.url)
    if not url.startswith("sqlite"):
        return
    cols = _sqlite_columns(engine, "material_purchases")
    alters: list[str] = []
    if "material_amount" not in cols:
        alters.append(
            "ALTER TABLE material_purchases ADD COLUMN material_amount NUMERIC(14,2) NOT NULL DEFAULT 0"
        )
    if "transport_amount" not in cols:
        alters.append(
            "ALTER TABLE material_purchases ADD COLUMN transport_amount NUMERIC(14,2) NOT NULL DEFAULT 0"
        )
    if "transport_mode" not in cols:
        alters.append(
            "ALTER TABLE material_purchases ADD COLUMN transport_mode VARCHAR(32) NOT NULL DEFAULT 'none'"
        )
    if not alters:
        return
    with engine.begin() as conn:
        for sql in alters:
            conn.execute(text(sql))
        # Backfill material_amount from total when missing
        conn.execute(
            text(
                "UPDATE material_purchases SET material_amount = total_amount "
                "WHERE material_amount = 0 AND total_amount > 0"
            )
        )
