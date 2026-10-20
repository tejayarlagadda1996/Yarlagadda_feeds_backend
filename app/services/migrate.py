"""Lightweight SQLite column adds for existing DBs."""

from sqlalchemy import text
from sqlalchemy.engine import Engine


def _sqlite_columns(engine: Engine, table: str) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {r[1] for r in rows}


def _sqlite_tables(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    return {r[0] for r in rows}


def ensure_schema(engine: Engine) -> None:
    url = str(engine.url)
    if not url.startswith("sqlite"):
        return

    tables = _sqlite_tables(engine)
    alters: list[str] = []

    if "material_purchases" in tables:
        cols = _sqlite_columns(engine, "material_purchases")
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

    if "interest_parties" in tables:
        ip_cols = _sqlite_columns(engine, "interest_parties")
        if "direction" not in ip_cols:
            alters.append("ALTER TABLE interest_parties ADD COLUMN direction VARCHAR(16)")

    if "interest_loans" in tables:
        il_cols = _sqlite_columns(engine, "interest_loans")
        if "is_carry_forward" not in il_cols:
            alters.append(
                "ALTER TABLE interest_loans ADD COLUMN is_carry_forward BOOLEAN NOT NULL DEFAULT 0"
            )

    if not alters and "interest_parties" not in tables:
        return

    with engine.begin() as conn:
        for sql in alters:
            conn.execute(text(sql))
        if "material_purchases" in tables:
            conn.execute(
                text(
                    "UPDATE material_purchases SET material_amount = total_amount "
                    "WHERE material_amount = 0 AND total_amount > 0"
                )
            )
        if "interest_parties" in tables and "interest_loans" in tables:
            conn.execute(
                text(
                    """
                    UPDATE interest_parties
                    SET direction = (
                        SELECT direction FROM interest_loans
                        WHERE interest_loans.party_id = interest_parties.id
                        ORDER BY created_at ASC LIMIT 1
                    )
                    WHERE direction IS NULL
                      AND EXISTS (
                        SELECT 1 FROM interest_loans
                        WHERE interest_loans.party_id = interest_parties.id
                      )
                    """
                )
            )
