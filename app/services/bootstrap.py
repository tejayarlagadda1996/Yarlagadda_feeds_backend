from sqlalchemy.orm import Session

from app.models import ExpenseCategory


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


def bootstrap_db(db: Session) -> None:
    ensure_expense_categories(db)
