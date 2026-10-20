"""Independent Interest module — Taken / Given parties, segmented simple interest."""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.entities import InterestLoan, InterestParty, InterestPayment
from app.schemas.interest import (
    InterestCalcIn,
    InterestDashboardOut,
    InterestFinalizeIn,
    InterestFinalizeOut,
    InterestLoanDetailOut,
    InterestLoanIn,
    InterestLoanOut,
    InterestPartyCalcOut,
    InterestPartyDetailOut,
    InterestPartyIn,
    InterestPartyOut,
    InterestPaymentIn,
    InterestPaymentOut,
    InterestSegmentOut,
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
    """Simple interest: P × R% × (days/30) / 100."""
    if days <= 0 or rate_per_month <= 0 or principal <= 0:
        return Decimal("0")
    raw = principal * rate_per_month * Decimal(days) / (Decimal("100") * Decimal("30"))
    return _money(raw)


def _payments_for(db: Session, loan_id: UUID) -> list[InterestPayment]:
    return (
        db.query(InterestPayment)
        .filter(InterestPayment.loan_id == loan_id)
        .order_by(InterestPayment.payment_date.asc(), InterestPayment.created_at.asc())
        .all()
    )


def _segmented_calc(loan: InterestLoan, payments: list[InterestPayment], as_of: date) -> dict:
    """Interest on outstanding principal, split at each payment date."""
    if as_of < loan.start_date:
        raise HTTPException(400, "As-of date cannot be before start date")

    outstanding = _money(loan.principal)
    cursor = loan.start_date
    interest_total = Decimal("0")
    paid_total = Decimal("0")
    segments: list[InterestSegmentOut] = []
    rate = loan.rate_percent_per_month

    for pay in payments:
        if pay.payment_date > as_of:
            break
        if pay.payment_date < loan.start_date:
            continue
        days = _days_between(cursor, pay.payment_date)
        seg_i = _simple_interest(outstanding, rate, days)
        if days > 0:
            segments.append(
                InterestSegmentOut(
                    from_date=cursor,
                    to_date=pay.payment_date,
                    days=days,
                    principal=outstanding,
                    interest=seg_i,
                    note=f"Before payment {_money(pay.amount)}",
                )
            )
        interest_total += seg_i
        paid_total += _money(pay.amount)
        outstanding = _money(max(Decimal("0"), outstanding - _money(pay.amount)))
        cursor = pay.payment_date

    days = _days_between(cursor, as_of)
    seg_i = _simple_interest(outstanding, rate, days)
    if days > 0 or not segments:
        segments.append(
            InterestSegmentOut(
                from_date=cursor,
                to_date=as_of,
                days=days,
                principal=outstanding,
                interest=seg_i,
                note="Till final date",
            )
        )
    interest_total += seg_i
    interest_total = _money(interest_total)
    total_due = _money(outstanding + interest_total)
    return {
        "paid_total": _money(paid_total),
        "outstanding_principal": outstanding,
        "days": _days_between(loan.start_date, as_of),
        "interest": interest_total,
        "total_due": total_due,
        "balance": total_due,
        "segments": segments,
    }


def _direction_meaning(direction: str, balance: Decimal) -> str:
    if balance <= 0:
        return "Settled — nothing left"
    amt = f"₹{balance:,.2f}"
    if direction == "taken":
        return f"We still owe this party {amt}"
    return f"This party still owes us {amt}"


def _loan_out(db: Session, loan: InterestLoan, as_of: date | None = None) -> InterestLoanOut:
    party = db.get(InterestParty, loan.party_id)
    payments = _payments_for(db, loan.id)
    end = as_of or (loan.closed_date if loan.status == "closed" and loan.closed_date else date.today())
    fields = _segmented_calc(loan, payments, end)
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
        is_carry_forward=bool(loan.is_carry_forward),
        **fields,
    )


def _party_summary(db: Session, party: InterestParty, as_of: date | None = None) -> InterestPartyOut:
    loans = db.query(InterestLoan).filter(InterestLoan.party_id == party.id).all()
    open_loans = [l for l in loans if l.status == "open"]
    closed_loans = [l for l in loans if l.status == "closed"]
    end = as_of or date.today()
    principal_open = Decimal("0")
    balance_open = Decimal("0")
    paid_open = Decimal("0")
    for loan in open_loans:
        out = _loan_out(db, loan, end)
        principal_open += _money(out.principal)
        balance_open += _money(out.balance)
        paid_open += _money(out.paid_total)
    return InterestPartyOut(
        id=party.id,
        name=party.name,
        phone=party.phone,
        notes=party.notes,
        direction=party.direction,
        is_active=party.is_active,
        open_entries=len(open_loans),
        closed_entries=len(closed_loans),
        principal_open=_money(principal_open),
        balance_open=_money(balance_open),
        paid_open=_money(paid_open),
    )


def _lock_party_direction(party: InterestParty, direction: str) -> None:
    if party.direction and party.direction != direction:
        raise HTTPException(
            400,
            f"Party '{party.name}' is only for {party.direction.upper()} — "
            f"cannot mix Taken and Given on the same party",
        )
    if not party.direction:
        party.direction = direction


# ---------- Dashboard ----------


@router.get("/dashboard", response_model=InterestDashboardOut)
def dashboard(db: Session = Depends(get_db)):
    today = date.today()
    taken = Decimal("0")
    given = Decimal("0")
    for loan in db.query(InterestLoan).filter(InterestLoan.status == "open").all():
        bal = _loan_out(db, loan, today).balance
        if loan.direction == "taken":
            taken += bal
        else:
            given += bal
    taken = _money(taken)
    given = _money(given)
    net = _money(taken - given)
    if net > 0:
        meaning = f"Net we owe parties {net}"
    elif net < 0:
        meaning = f"Net parties owe us {_money(-net)}"
    else:
        meaning = "Net settled"
    return InterestDashboardOut(
        taken_balance=taken,
        given_balance=given,
        net_balance=net,
        meaning=meaning,
    )


# ---------- Parties ----------


@router.get("/parties", response_model=list[InterestPartyOut])
def list_parties(
    db: Session = Depends(get_db),
    direction: str | None = Query(None),
):
    q = db.query(InterestParty).filter(InterestParty.is_active.is_(True))
    if direction in ("taken", "given"):
        q = q.filter(InterestParty.direction == direction)
    parties = q.order_by(InterestParty.name).all()
    return [_party_summary(db, p) for p in parties]


@router.post("/parties", response_model=InterestPartyOut)
def create_party(body: InterestPartyIn, db: Session = Depends(get_db)):
    direction = None
    if body.direction:
        direction = body.direction.strip().lower()
        if direction not in ("taken", "given"):
            raise HTTPException(400, "Direction must be taken or given")
    row = InterestParty(
        name=body.name.strip(),
        phone=body.phone,
        notes=body.notes,
        direction=direction,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _party_summary(db, row)


@router.get("/parties/{party_id}", response_model=InterestPartyDetailOut)
def get_party(party_id: UUID, db: Session = Depends(get_db)):
    party = db.get(InterestParty, party_id)
    if not party:
        raise HTTPException(404, "Party not found")
    open_loans = (
        db.query(InterestLoan)
        .filter(InterestLoan.party_id == party_id, InterestLoan.status == "open")
        .order_by(InterestLoan.start_date.desc())
        .all()
    )
    closed = (
        db.query(InterestLoan)
        .filter(InterestLoan.party_id == party_id, InterestLoan.status == "closed")
        .order_by(InterestLoan.closed_date.desc(), InterestLoan.start_date.desc())
        .all()
    )
    history: list[InterestLoanDetailOut] = []
    for loan in closed:
        base = _loan_out(db, loan)
        pays = _payments_for(db, loan.id)
        history.append(
            InterestLoanDetailOut(
                **base.model_dump(),
                payments=[InterestPaymentOut.model_validate(p) for p in reversed(pays)],
            )
        )
    return InterestPartyDetailOut(
        party=_party_summary(db, party),
        open_loans=[_loan_out(db, l) for l in open_loans],
        history=history,
    )


@router.post("/parties/{party_id}/calculate", response_model=InterestPartyCalcOut)
def calculate_party(party_id: UUID, body: InterestCalcIn, db: Session = Depends(get_db)):
    party = db.get(InterestParty, party_id)
    if not party:
        raise HTTPException(404, "Party not found")
    if not party.direction:
        raise HTTPException(400, "Party has no Taken/Given entries yet")
    open_loans = (
        db.query(InterestLoan)
        .filter(InterestLoan.party_id == party_id, InterestLoan.status == "open")
        .order_by(InterestLoan.start_date.asc())
        .all()
    )
    if not open_loans:
        raise HTTPException(400, "No open entries to calculate")
    entries = [_loan_out(db, l, body.as_of_date) for l in open_loans]
    principal = _money(sum((e.principal for e in entries), Decimal("0")))
    outstanding = _money(sum((e.outstanding_principal for e in entries), Decimal("0")))
    interest = _money(sum((e.interest for e in entries), Decimal("0")))
    paid = _money(sum((e.paid_total for e in entries), Decimal("0")))
    balance = _money(sum((e.balance for e in entries), Decimal("0")))
    return InterestPartyCalcOut(
        party_id=party.id,
        party_name=party.name,
        direction=party.direction,
        as_of_date=body.as_of_date,
        entries=entries,
        principal_open=principal,
        outstanding_principal=outstanding,
        interest=interest,
        paid_total=paid,
        balance=balance,
        meaning=_direction_meaning(party.direction, balance),
    )


@router.post("/parties/{party_id}/finalize", response_model=InterestFinalizeOut)
def finalize_party(party_id: UUID, body: InterestFinalizeIn, db: Session = Depends(get_db)):
    """Close open entries into history and start one new carry-forward entry for remaining balance."""
    party = db.get(InterestParty, party_id)
    if not party or not party.direction:
        raise HTTPException(404, "Party not found")
    open_loans = (
        db.query(InterestLoan)
        .filter(InterestLoan.party_id == party_id, InterestLoan.status == "open")
        .order_by(InterestLoan.start_date.asc())
        .all()
    )
    if not open_loans:
        raise HTTPException(400, "Nothing open to finalize")

    calc_entries = [_loan_out(db, l, body.as_of_date) for l in open_loans]
    balance = _money(sum((e.balance for e in calc_entries), Decimal("0")))
    # Prefer rate from latest open entry unless overridden
    rate = body.rate_percent_per_month
    if rate is None:
        rate = open_loans[-1].rate_percent_per_month

    closed_count = 0
    for loan in open_loans:
        loan.status = "closed"
        loan.closed_date = body.as_of_date
        note = f"Finalized on {body.as_of_date.isoformat()}"
        if body.notes:
            note = f"{note} · {body.notes}"
        loan.notes = ((loan.notes or "") + "\n" + note).strip()
        closed_count += 1

    new_loan = None
    if balance > 0:
        new_loan_row = InterestLoan(
            party_id=party.id,
            direction=party.direction,
            principal=balance,
            rate_percent_per_month=rate.quantize(Decimal("0.0001")),
            start_date=body.as_of_date,
            notes=f"Carry forward after finalize on {body.as_of_date.isoformat()}",
            status="open",
            is_carry_forward=True,
        )
        db.add(new_loan_row)
        db.flush()
        new_loan = _loan_out(db, new_loan_row, body.as_of_date)

    db.commit()
    if new_loan is None:
        msg = f"Closed {closed_count} entr(y/ies). Fully settled — nothing carried forward."
    else:
        msg = f"Closed {closed_count} entr(y/ies). New open balance {balance}."
    return InterestFinalizeOut(
        party_id=party.id,
        closed_count=closed_count,
        new_loan=new_loan,
        message=msg,
    )


# ---------- Loans ----------


@router.get("/loans", response_model=list[InterestLoanOut])
def list_loans(
    db: Session = Depends(get_db),
    status: str | None = Query(None),
    direction: str | None = Query(None),
    party_id: UUID | None = Query(None),
):
    q = db.query(InterestLoan).order_by(InterestLoan.start_date.desc(), InterestLoan.created_at.desc())
    if status in ("open", "closed"):
        q = q.filter(InterestLoan.status == status)
    if direction in ("taken", "given"):
        q = q.filter(InterestLoan.direction == direction)
    if party_id:
        q = q.filter(InterestLoan.party_id == party_id)
    return [_loan_out(db, r) for r in q.all()]


@router.post("/loans", response_model=InterestLoanOut)
def create_loan(body: InterestLoanIn, db: Session = Depends(get_db)):
    direction = (body.direction or "").strip().lower()
    if direction not in ("taken", "given"):
        raise HTTPException(400, "Direction must be taken or given")

    party: InterestParty | None = None
    if body.party_id:
        party = db.get(InterestParty, body.party_id)
        if not party or not party.is_active:
            raise HTTPException(404, "Interest party not found")
    elif body.party_name and body.party_name.strip():
        party = InterestParty(name=body.party_name.strip(), direction=direction)
        db.add(party)
        db.flush()
    else:
        raise HTTPException(400, "Select or create a party")

    _lock_party_direction(party, direction)

    row = InterestLoan(
        party_id=party.id,
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
    payments = list(reversed(_payments_for(db, loan_id)))
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
        raise HTTPException(400, "Entry is in history — cannot add payment")
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


@router.post("/loans/{loan_id}/calculate", response_model=InterestLoanOut)
def calculate_loan(loan_id: UUID, body: InterestCalcIn, db: Session = Depends(get_db)):
    loan = db.get(InterestLoan, loan_id)
    if not loan:
        raise HTTPException(404, "Loan not found")
    return _loan_out(db, loan, body.as_of_date)
