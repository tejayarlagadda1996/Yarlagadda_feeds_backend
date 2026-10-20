"""Independent Interest module — taken/given amounts at simple interest."""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.entities import InterestLoan, InterestParty, InterestPayment
from app.schemas.interest import (
    InterestCalcIn,
    InterestCalcOut,
    InterestCloseIn,
    InterestLoanDetailOut,
    InterestLoanIn,
    InterestLoanOut,
    InterestPartyIn,
    InterestPartyOut,
    InterestPaymentIn,
    InterestPaymentOut,
)

router = APIRouter(prefix="/interest", tags=["interest"])

_Q = Decimal("0.01")


def _money(v: Decimal) -> Decimal:
    return (v or Decimal("0")).quantize(_Q, rounding=ROUND_HALF_UP)


def _days_between(start: date, end: date) -> int:
    if end < start:
        raise HTTPException(400, "End date cannot be before start date")
    return (end - start).days


def _simple_interest(principal: Decimal, rate_per_month: Decimal, days: int) -> Decimal:
    """Simple interest with monthly rate, day count ÷ 30."""
    if days <= 0 or rate_per_month <= 0:
        return Decimal("0")
    # I = P × R% × (days/30) / 100
    raw = principal * rate_per_month * Decimal(days) / (Decimal("100") * Decimal("30"))
    return _money(raw)


def _paid_total(db: Session, loan_id: UUID) -> Decimal:
    rows = db.query(InterestPayment).filter(InterestPayment.loan_id == loan_id).all()
    return _money(sum((p.amount for p in rows), Decimal("0")))


def _calc_fields(loan: InterestLoan, paid: Decimal, as_of: date) -> dict:
    days = _days_between(loan.start_date, as_of)
    interest = _simple_interest(loan.principal, loan.rate_percent_per_month, days)
    total = _money(loan.principal + interest)
    balance = _money(total - paid)
    return {
        "days": days,
        "interest": interest,
        "total_due": total,
        "balance": balance,
        "paid_total": paid,
    }


def _direction_meaning(direction: str, balance: Decimal) -> str:
    if balance <= 0:
        return "Settled — nothing left"
    amt = f"₹{balance:,.2f}"
    if direction == "taken":
        return f"We still owe the party {amt}"
    return f"Party still owes us {amt}"


def _loan_out(db: Session, loan: InterestLoan, as_of: date | None = None) -> InterestLoanOut:
    party = db.get(InterestParty, loan.party_id)
    paid = _paid_total(db, loan.id)
    end = as_of or (loan.closed_date if loan.status == "closed" and loan.closed_date else date.today())
    fields = _calc_fields(loan, paid, end)
    return InterestLoanOut(
        id=loan.id,
        party_id=loan.party_id,
        party_name=party.name if party else None,
        direction=loan.direction,
        principal=loan.principal,
        rate_percent_per_month=loan.rate_percent_per_month,
        start_date=loan.start_date,
        notes=loan.notes,
        status=loan.status,
        closed_date=loan.closed_date,
        **fields,
    )


# ---------- Parties ----------


@router.get("/parties", response_model=list[InterestPartyOut])
def list_parties(db: Session = Depends(get_db)):
    return (
        db.query(InterestParty)
        .filter(InterestParty.is_active.is_(True))
        .order_by(InterestParty.name)
        .all()
    )


@router.post("/parties", response_model=InterestPartyOut)
def create_party(body: InterestPartyIn, db: Session = Depends(get_db)):
    row = InterestParty(name=body.name.strip(), phone=body.phone, notes=body.notes)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ---------- Loans ----------


@router.get("/loans", response_model=list[InterestLoanOut])
def list_loans(
    db: Session = Depends(get_db),
    status: str | None = Query(None),
    direction: str | None = Query(None),
):
    q = db.query(InterestLoan).order_by(InterestLoan.start_date.desc(), InterestLoan.created_at.desc())
    if status in ("open", "closed"):
        q = q.filter(InterestLoan.status == status)
    if direction in ("taken", "given"):
        q = q.filter(InterestLoan.direction == direction)
    return [_loan_out(db, r) for r in q.all()]


@router.post("/loans", response_model=InterestLoanOut)
def create_loan(body: InterestLoanIn, db: Session = Depends(get_db)):
    direction = (body.direction or "").strip().lower()
    if direction not in ("taken", "given"):
        raise HTTPException(400, "Direction must be taken or given")
    party = db.get(InterestParty, body.party_id)
    if not party or not party.is_active:
        raise HTTPException(404, "Interest party not found")
    row = InterestLoan(
        party_id=body.party_id,
        direction=direction,
        principal=_money(body.principal),
        rate_percent_per_month=body.rate_percent_per_month.quantize(Decimal("0.0001")),
        start_date=body.start_date,
        notes=body.notes,
        status="open",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _loan_out(db, row)


@router.get("/loans/{loan_id}", response_model=InterestLoanDetailOut)
def get_loan(loan_id: UUID, db: Session = Depends(get_db)):
    loan = db.get(InterestLoan, loan_id)
    if not loan:
        raise HTTPException(404, "Loan not found")
    base = _loan_out(db, loan)
    payments = (
        db.query(InterestPayment)
        .filter(InterestPayment.loan_id == loan_id)
        .order_by(InterestPayment.payment_date.desc(), InterestPayment.created_at.desc())
        .all()
    )
    return InterestLoanDetailOut(
        **base.model_dump(),
        payments=[InterestPaymentOut.model_validate(p) for p in payments],
    )


@router.post("/loans/{loan_id}/payments", response_model=InterestPaymentOut)
def add_payment(loan_id: UUID, body: InterestPaymentIn, db: Session = Depends(get_db)):
    loan = db.get(InterestLoan, loan_id)
    if not loan:
        raise HTTPException(404, "Loan not found")
    if loan.status == "closed":
        raise HTTPException(400, "Loan is already closed")
    if body.payment_date < loan.start_date:
        raise HTTPException(400, "Payment date cannot be before start date")
    row = InterestPayment(
        loan_id=loan_id,
        payment_date=body.payment_date,
        amount=_money(body.amount),
        notes=body.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/loans/{loan_id}/calculate", response_model=InterestCalcOut)
def calculate_loan(loan_id: UUID, body: InterestCalcIn, db: Session = Depends(get_db)):
    loan = db.get(InterestLoan, loan_id)
    if not loan:
        raise HTTPException(404, "Loan not found")
    party = db.get(InterestParty, loan.party_id)
    paid = _paid_total(db, loan.id)
    fields = _calc_fields(loan, paid, body.as_of_date)
    return InterestCalcOut(
        loan_id=loan.id,
        party_name=party.name if party else None,
        direction=loan.direction,
        principal=loan.principal,
        rate_percent_per_month=loan.rate_percent_per_month,
        start_date=loan.start_date,
        as_of_date=body.as_of_date,
        days=fields["days"],
        interest=fields["interest"],
        total_due=fields["total_due"],
        paid_total=fields["paid_total"],
        balance=fields["balance"],
        meaning=_direction_meaning(loan.direction, fields["balance"]),
    )


@router.post("/loans/{loan_id}/close", response_model=InterestLoanOut)
def close_loan(loan_id: UUID, body: InterestCloseIn, db: Session = Depends(get_db)):
    loan = db.get(InterestLoan, loan_id)
    if not loan:
        raise HTTPException(404, "Loan not found")
    if loan.status == "closed":
        raise HTTPException(400, "Already closed")
    if body.closed_date < loan.start_date:
        raise HTTPException(400, "Close date cannot be before start date")
    loan.status = "closed"
    loan.closed_date = body.closed_date
    if body.notes:
        loan.notes = ((loan.notes or "") + "\n" + body.notes).strip()
    db.commit()
    db.refresh(loan)
    return _loan_out(db, loan)
