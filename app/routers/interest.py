"""Interest module — Taken/Given parties; each entry & return accrues interest; A+B−C calc + print."""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.entities import InterestLoan, InterestParty, InterestPartyReturn
from app.schemas.interest import (
    InterestCalcIn,
    InterestCalcLineOut,
    InterestDashboardOut,
    InterestFinalizeIn,
    InterestFinalizeOut,
    InterestLoanIn,
    InterestLoanOut,
    InterestPartyCalcOut,
    InterestPartyDetailOut,
    InterestPartyIn,
    InterestPartyOut,
    InterestPartyReturnIn,
    InterestPartyReturnOut,
)

router = APIRouter(prefix="/interest", tags=["interest"])

_Q = Decimal("0.01")
_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _money(v: Decimal) -> Decimal:
    return (v or Decimal("0")).quantize(_Q, rounding=ROUND_HALF_UP)


def _days_between(start: date, end: date) -> int:
    if end < start:
        raise HTTPException(400, "End date cannot be before start date")
    return (end - start).days


def _simple_interest(principal: Decimal, rate_per_month: Decimal, days: int) -> Decimal:
    if days <= 0 or rate_per_month <= 0 or principal <= 0:
        return Decimal("0")
    raw = principal * rate_per_month * Decimal(days) / (Decimal("100") * Decimal("30"))
    return _money(raw)


def _line_interest(amount: Decimal, rate: Decimal, start: date, as_of: date) -> tuple[int, Decimal, Decimal]:
    days = _days_between(start, as_of)
    interest = _simple_interest(amount, rate, days)
    return days, interest, _money(amount + interest)


def _loan_out(db: Session, loan: InterestLoan, as_of: date | None = None) -> InterestLoanOut:
    party = db.get(InterestParty, loan.party_id)
    end = as_of or (loan.closed_date if loan.status == "closed" and loan.closed_date else date.today())
    days, interest, total = _line_interest(loan.principal, loan.rate_percent_per_month, loan.start_date, end)
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
        days=days,
        interest=interest,
        total_with_interest=total,
    )


def _return_out(row: InterestPartyReturn, as_of: date | None = None) -> InterestPartyReturnOut:
    end = as_of or (row.closed_date if row.status == "closed" and row.closed_date else date.today())
    days, interest, total = _line_interest(row.amount, row.rate_percent_per_month, row.return_date, end)
    return InterestPartyReturnOut(
        id=row.id,
        party_id=row.party_id,
        amount=row.amount,
        rate_percent_per_month=row.rate_percent_per_month,
        return_date=row.return_date,
        notes=row.notes,
        status=row.status,
        closed_date=row.closed_date,
        days=days,
        interest=interest,
        total_with_interest=total,
    )


def _party_balance(db: Session, party: InterestParty, as_of: date | None = None) -> Decimal:
    end = as_of or date.today()
    loans = (
        db.query(InterestLoan)
        .filter(InterestLoan.party_id == party.id, InterestLoan.status == "open")
        .all()
    )
    returns = (
        db.query(InterestPartyReturn)
        .filter(InterestPartyReturn.party_id == party.id, InterestPartyReturn.status == "open")
        .all()
    )
    debit = sum((_loan_out(db, l, end).total_with_interest for l in loans), Decimal("0"))
    credit = sum((_return_out(r, end).total_with_interest for r in returns), Decimal("0"))
    return _money(debit - credit)


def _party_summary(db: Session, party: InterestParty) -> InterestPartyOut:
    loans = db.query(InterestLoan).filter(InterestLoan.party_id == party.id).all()
    returns = db.query(InterestPartyReturn).filter(InterestPartyReturn.party_id == party.id).all()
    open_loans = [l for l in loans if l.status == "open"]
    open_returns = [r for r in returns if r.status == "open"]
    closed_loans = [l for l in loans if l.status == "closed"]
    today = date.today()
    principal_open = _money(sum((l.principal for l in open_loans), Decimal("0")))
    returns_open = _money(sum((r.amount for r in open_returns), Decimal("0")))
    return InterestPartyOut(
        id=party.id,
        name=party.name,
        phone=party.phone,
        notes=party.notes,
        direction=party.direction,
        is_active=party.is_active,
        open_entries=len(open_loans),
        open_returns=len(open_returns),
        closed_entries=len(closed_loans),
        principal_open=principal_open,
        returns_open=returns_open,
        balance_open=_party_balance(db, party, today),
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


def _default_rate(db: Session, party_id: UUID) -> Decimal:
    loan = (
        db.query(InterestLoan)
        .filter(InterestLoan.party_id == party_id, InterestLoan.status == "open")
        .order_by(InterestLoan.start_date.desc())
        .first()
    )
    if loan:
        return loan.rate_percent_per_month
    return Decimal("2")


# ---------- Dashboard ----------


@router.get("/dashboard", response_model=InterestDashboardOut)
def dashboard(db: Session = Depends(get_db)):
    taken = Decimal("0")
    given = Decimal("0")
    for party in db.query(InterestParty).filter(InterestParty.is_active.is_(True)).all():
        if not party.direction:
            continue
        bal = _party_balance(db, party)
        if party.direction == "taken":
            taken += bal
        else:
            given += bal
    taken, given = _money(taken), _money(given)
    net = _money(taken - given)
    if net > 0:
        meaning = f"Net we owe parties ₹{net:,.2f}  (Taken − Given)"
    elif net < 0:
        meaning = f"Net parties owe us ₹{_money(-net):,.2f}  (Given − Taken)"
    else:
        meaning = "Net settled (Taken − Given = 0)"
    return InterestDashboardOut(
        taken_balance=taken,
        given_balance=given,
        net_balance=net,
        meaning=meaning,
    )


# ---------- Parties ----------


@router.get("/parties", response_model=list[InterestPartyOut])
def list_parties(db: Session = Depends(get_db), direction: str | None = Query(None)):
    q = db.query(InterestParty).filter(InterestParty.is_active.is_(True))
    if direction in ("taken", "given"):
        q = q.filter(InterestParty.direction == direction)
    return [_party_summary(db, p) for p in q.order_by(InterestParty.name).all()]


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
        .order_by(InterestLoan.start_date.asc())
        .all()
    )
    open_returns = (
        db.query(InterestPartyReturn)
        .filter(InterestPartyReturn.party_id == party_id, InterestPartyReturn.status == "open")
        .order_by(InterestPartyReturn.return_date.asc())
        .all()
    )
    hist_loans = (
        db.query(InterestLoan)
        .filter(InterestLoan.party_id == party_id, InterestLoan.status == "closed")
        .order_by(InterestLoan.closed_date.desc())
        .all()
    )
    hist_returns = (
        db.query(InterestPartyReturn)
        .filter(InterestPartyReturn.party_id == party_id, InterestPartyReturn.status == "closed")
        .order_by(InterestPartyReturn.closed_date.desc())
        .all()
    )
    return InterestPartyDetailOut(
        party=_party_summary(db, party),
        open_loans=[_loan_out(db, l) for l in open_loans],
        open_returns=[_return_out(r) for r in open_returns],
        history_loans=[_loan_out(db, l) for l in hist_loans],
        history_returns=[_return_out(r) for r in hist_returns],
    )


@router.post("/parties/{party_id}/returns", response_model=InterestPartyReturnOut)
def add_party_return(party_id: UUID, body: InterestPartyReturnIn, db: Session = Depends(get_db)):
    party = db.get(InterestParty, party_id)
    if not party:
        raise HTTPException(404, "Party not found")
    if not party.direction:
        raise HTTPException(400, "Add a Taken/Given entry before recording a return payment")
    row = InterestPartyReturn(
        party_id=party_id,
        amount=_money(body.amount),
        rate_percent_per_month=body.rate_percent_per_month.quantize(Decimal("0.0001")),
        return_date=body.return_date,
        notes=body.notes,
        status="open",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _return_out(row)


@router.post("/parties/{party_id}/calculate", response_model=InterestPartyCalcOut)
def calculate_party(party_id: UUID, body: InterestCalcIn, db: Session = Depends(get_db)):
    party = db.get(InterestParty, party_id)
    if not party or not party.direction:
        raise HTTPException(404, "Party not found")
    as_of = body.as_of_date
    open_loans = (
        db.query(InterestLoan)
        .filter(InterestLoan.party_id == party_id, InterestLoan.status == "open")
        .order_by(InterestLoan.start_date.asc(), InterestLoan.created_at.asc())
        .all()
    )
    open_returns = (
        db.query(InterestPartyReturn)
        .filter(InterestPartyReturn.party_id == party_id, InterestPartyReturn.status == "open")
        .order_by(InterestPartyReturn.return_date.asc(), InterestPartyReturn.created_at.asc())
        .all()
    )
    if not open_loans and not open_returns:
        raise HTTPException(400, "Nothing open to calculate")

    lines: list[InterestCalcLineOut] = []
    letter_i = 0
    debit_letters: list[str] = []
    credit_letters: list[str] = []
    entries_total = Decimal("0")
    returns_total = Decimal("0")

    taken = party.direction == "taken"
    entry_word = "Taken" if taken else "Given"
    return_word = "Return payment" if taken else "Received back"

    for loan in open_loans:
        letter = _LETTERS[letter_i] if letter_i < len(_LETTERS) else f"L{letter_i}"
        letter_i += 1
        days, interest, total = _line_interest(
            loan.principal, loan.rate_percent_per_month, loan.start_date, as_of
        )
        entries_total += total
        debit_letters.append(letter)
        lines.append(
            InterestCalcLineOut(
                letter=letter,
                kind="entry",
                sign="plus",
                title=f"{letter}) {entry_word} {loan.principal} on {loan.start_date.isoformat()}",
                explanation=(
                    f"{entry_word} amount ₹{_money(loan.principal):,.2f} from {loan.start_date.isoformat()} "
                    f"to {as_of.isoformat()} ({days} days) at {loan.rate_percent_per_month}% per month. "
                    f"Interest = principal × rate × (days÷30) ÷ 100 = ₹{interest:,.2f}. "
                    f"Line total = amount + interest = ₹{total:,.2f}."
                ),
                amount=loan.principal,
                rate_percent_per_month=loan.rate_percent_per_month,
                from_date=loan.start_date,
                to_date=as_of,
                days=days,
                interest=interest,
                line_total=total,
            )
        )

    for row in open_returns:
        letter = _LETTERS[letter_i] if letter_i < len(_LETTERS) else f"R{letter_i}"
        letter_i += 1
        days, interest, total = _line_interest(
            row.amount, row.rate_percent_per_month, row.return_date, as_of
        )
        returns_total += total
        credit_letters.append(letter)
        lines.append(
            InterestCalcLineOut(
                letter=letter,
                kind="return",
                sign="minus",
                title=f"{letter}) {return_word} {row.amount} on {row.return_date.isoformat()}",
                explanation=(
                    f"{return_word} ₹{_money(row.amount):,.2f} on {row.return_date.isoformat()} "
                    f"is credited with interest till {as_of.isoformat()} ({days} days) at "
                    f"{row.rate_percent_per_month}% per month = ₹{interest:,.2f}. "
                    f"Credit line = amount + interest = ₹{total:,.2f} (subtracted from Taken/Given total)."
                ),
                amount=row.amount,
                rate_percent_per_month=row.rate_percent_per_month,
                from_date=row.return_date,
                to_date=as_of,
                days=days,
                interest=interest,
                line_total=total,
            )
        )

    entries_total = _money(entries_total)
    returns_total = _money(returns_total)
    balance = _money(entries_total - returns_total)

    plus_part = " + ".join(debit_letters) if debit_letters else "0"
    if credit_letters:
        formula = f"{plus_part} − {' − '.join(credit_letters)} = ₹{balance:,.2f}"
    else:
        formula = f"{plus_part} = ₹{balance:,.2f}"

    if taken:
        meaning = (
            f"We still owe {party.name} ₹{balance:,.2f}"
            if balance > 0
            else ("Settled" if balance == 0 else f"Overpaid / credit ₹{_money(-balance):,.2f}")
        )
        print_title = f"Interest statement — Taken from {party.name}"
        print_subtitle = "Each Taken amount grows with interest. Return payments also grow with interest and are subtracted."
    else:
        meaning = (
            f"{party.name} still owes us ₹{balance:,.2f}"
            if balance > 0
            else ("Settled" if balance == 0 else f"Over-received ₹{_money(-balance):,.2f}")
        )
        print_title = f"Interest statement — Given to {party.name}"
        print_subtitle = "Each Given amount grows with interest. Amounts received back grow with interest and are subtracted."

    return InterestPartyCalcOut(
        party_id=party.id,
        party_name=party.name,
        direction=party.direction,
        as_of_date=as_of,
        lines=lines,
        entries_total=entries_total,
        returns_total=returns_total,
        balance=balance,
        formula=formula,
        meaning=meaning,
        print_title=print_title,
        print_subtitle=print_subtitle,
    )


@router.post("/parties/{party_id}/finalize", response_model=InterestFinalizeOut)
def finalize_party(party_id: UUID, body: InterestFinalizeIn, db: Session = Depends(get_db)):
    party = db.get(InterestParty, party_id)
    if not party or not party.direction:
        raise HTTPException(404, "Party not found")

    calc = calculate_party(party_id, InterestCalcIn(as_of_date=body.as_of_date), db)
    balance = calc.balance

    open_loans = (
        db.query(InterestLoan)
        .filter(InterestLoan.party_id == party_id, InterestLoan.status == "open")
        .all()
    )
    open_returns = (
        db.query(InterestPartyReturn)
        .filter(InterestPartyReturn.party_id == party_id, InterestPartyReturn.status == "open")
        .all()
    )
    if not open_loans and not open_returns:
        raise HTTPException(400, "Nothing open to finalize")

    rate = body.rate_percent_per_month
    if rate is None:
        rate = _default_rate(db, party_id)

    for loan in open_loans:
        loan.status = "closed"
        loan.closed_date = body.as_of_date
        note = f"Finalized on {body.as_of_date.isoformat()}"
        if body.notes:
            note = f"{note} · {body.notes}"
        loan.notes = ((loan.notes or "") + "\n" + note).strip()

    for row in open_returns:
        row.status = "closed"
        row.closed_date = body.as_of_date

    new_loan_out = None
    if balance > 0:
        new_row = InterestLoan(
            party_id=party.id,
            direction=party.direction,
            principal=balance,
            rate_percent_per_month=rate.quantize(Decimal("0.0001")),
            start_date=body.as_of_date,
            notes=f"Carry forward after finalize on {body.as_of_date.isoformat()}",
            status="open",
            is_carry_forward=True,
        )
        db.add(new_row)
        db.flush()
        new_loan_out = _loan_out(db, new_row, body.as_of_date)

    db.commit()
    msg = (
        f"Closed {len(open_loans)} entr(y/ies) and {len(open_returns)} return(s). "
        + (f"New open balance ₹{balance:,.2f}." if new_loan_out else "Fully settled.")
    )
    return InterestFinalizeOut(
        party_id=party.id,
        closed_entries=len(open_loans),
        closed_returns=len(open_returns),
        new_loan=new_loan_out,
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
    q = db.query(InterestLoan).order_by(InterestLoan.start_date.desc())
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


@router.get("/loans/{loan_id}", response_model=InterestLoanOut)
def get_loan(loan_id: UUID, db: Session = Depends(get_db)):
    loan = db.get(InterestLoan, loan_id)
    if not loan:
        raise HTTPException(404, "Loan not found")
    return _loan_out(db, loan)
