from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models import ExpenseCategory, User


def ensure_admin_user(db: Session) -> None:
    settings = get_settings()
    existing = db.query(User).filter(User.username == settings.admin_username).first()
    if existing:
        return
    admin = User(
        username=settings.admin_username,
        full_name=settings.admin_full_name,
        password_hash=hash_password(settings.admin_password),
        role="admin",
        is_active=True,
    )
    db.add(admin)
    db.commit()


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
    ensure_admin_user(db)
    ensure_expense_categories(db)
