from sqlalchemy.orm import Session

from app.models import ExpenseCategory, MaterialType

OPENING_BALANCE_MATERIAL = "Previous balance"
OPENING_BALANCE_REF = "OPENING"


def ensure_expense_categories(db: Session) -> None:
    defaults = [
        ("Raw Material", True),
        ("Labour Salary", True),
        ("Labour Advance", True),
        ("Utilities", False),
        ("Transport", False),
        ("Maintenance", False),
        ("Other", False),
    ]
    for name, is_system in defaults:
        exists = db.query(ExpenseCategory).filter(ExpenseCategory.name == name).first()
        if not exists:
            db.add(ExpenseCategory(name=name, is_system=is_system))
    db.commit()


def ensure_opening_balance_material(db: Session) -> MaterialType:
    row = db.query(MaterialType).filter(MaterialType.name == OPENING_BALANCE_MATERIAL).first()
    if row is None:
        row = MaterialType(
            name=OPENING_BALANCE_MATERIAL,
            unit="opening",
            description="System: old vendor dues carried into the app",
            is_active=True,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def bootstrap_db(db: Session) -> None:
    ensure_expense_categories(db)
    ensure_opening_balance_material(db)
