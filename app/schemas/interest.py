from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, PlainSerializer

Money = Annotated[Decimal, PlainSerializer(lambda v: float(v), return_type=float, when_used="json")]


class InterestPartyIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    phone: str | None = None
    notes: str | None = None
    direction: str | None = None


class InterestPartyOut(BaseModel):
    id: UUID
    name: str
    phone: str | None = None
    notes: str | None = None
    direction: str | None = None
    is_active: bool
    open_entries: int = 0
    open_returns: int = 0
    closed_entries: int = 0
    principal_open: Money = Decimal("0")
    returns_open: Money = Decimal("0")
    balance_open: Money = Decimal("0")

    model_config = {"from_attributes": True}


class InterestLoanIn(BaseModel):
    party_id: UUID | None = None
    party_name: str | None = None
    direction: str
    principal: Decimal = Field(gt=0)
    rate_percent_per_month: Decimal = Field(ge=0)
    start_date: date
    notes: str | None = None


class InterestPartyReturnIn(BaseModel):
    amount: Decimal = Field(gt=0)
    rate_percent_per_month: Decimal = Field(ge=0)
    return_date: date
    notes: str | None = None


class InterestPartyReturnOut(BaseModel):
    id: UUID
    party_id: UUID
    amount: Money
    rate_percent_per_month: Money
    return_date: date
    notes: str | None = None
    status: str
    closed_date: date | None = None
    days: int = 0
    interest: Money = Decimal("0")
    total_with_interest: Money = Decimal("0")

    model_config = {"from_attributes": True}


class InterestLoanOut(BaseModel):
    id: UUID
    party_id: UUID
    party_name: str | None = None
    direction: str
    principal: Money
    rate_percent_per_month: Money
    start_date: date
    notes: str | None = None
    status: str
    closed_date: date | None = None
    is_carry_forward: bool = False
    days: int = 0
    interest: Money = Decimal("0")
    total_with_interest: Money = Decimal("0")

    model_config = {"from_attributes": True}


class InterestLoanDetailOut(InterestLoanOut):
    pass


class InterestCalcIn(BaseModel):
    as_of_date: date


class InterestCalcLineOut(BaseModel):
    """One clearly labeled line in the printable calculation."""

    letter: str  # A, B, C...
    kind: str  # entry | return
    sign: str  # plus | minus
    title: str
    explanation: str
    amount: Money
    rate_percent_per_month: Money
    from_date: date
    to_date: date
    days: int
    interest: Money
    line_total: Money


class InterestPartyCalcOut(BaseModel):
    party_id: UUID
    party_name: str | None = None
    direction: str
    as_of_date: date
    lines: list[InterestCalcLineOut]
    entries_total: Money
    returns_total: Money
    balance: Money
    formula: str
    meaning: str
    print_title: str
    print_subtitle: str


class InterestFinalizeIn(BaseModel):
    as_of_date: date
    rate_percent_per_month: Decimal | None = None
    notes: str | None = None


class InterestFinalizeOut(BaseModel):
    party_id: UUID
    closed_entries: int
    closed_returns: int
    new_loan: InterestLoanOut | None = None
    message: str


class InterestDashboardOut(BaseModel):
    taken_balance: Money
    given_balance: Money
    net_balance: Money
    meaning: str


class InterestPartyDetailOut(BaseModel):
    party: InterestPartyOut
    open_loans: list[InterestLoanOut]
    open_returns: list[InterestPartyReturnOut]
    history_loans: list[InterestLoanOut]
    history_returns: list[InterestPartyReturnOut]
