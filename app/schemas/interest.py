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
    # Optional lock when creating from Taken/Given tab
    direction: str | None = None


class InterestPartyOut(BaseModel):
    id: UUID
    name: str
    phone: str | None = None
    notes: str | None = None
    direction: str | None = None
    is_active: bool
    open_entries: int = 0
    closed_entries: int = 0
    principal_open: Money = Decimal("0")
    balance_open: Money = Decimal("0")
    paid_open: Money = Decimal("0")

    model_config = {"from_attributes": True}


class InterestLoanIn(BaseModel):
    party_id: UUID | None = None
    party_name: str | None = None  # create party if party_id missing
    direction: str  # taken | given
    principal: Decimal = Field(gt=0)
    rate_percent_per_month: Decimal = Field(ge=0)
    start_date: date
    notes: str | None = None


class InterestPaymentIn(BaseModel):
    payment_date: date
    amount: Decimal = Field(gt=0)
    notes: str | None = None


class InterestPaymentOut(BaseModel):
    id: UUID
    loan_id: UUID
    payment_date: date
    amount: Money
    notes: str | None = None

    model_config = {"from_attributes": True}


class InterestSegmentOut(BaseModel):
    from_date: date
    to_date: date
    days: int
    principal: Money
    interest: Money
    note: str | None = None


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
    paid_total: Money = Decimal("0")
    outstanding_principal: Money = Decimal("0")
    days: int = 0
    interest: Money = Decimal("0")
    total_due: Money = Decimal("0")
    balance: Money = Decimal("0")
    segments: list[InterestSegmentOut] = []

    model_config = {"from_attributes": True}


class InterestLoanDetailOut(InterestLoanOut):
    payments: list[InterestPaymentOut] = []


class InterestCalcIn(BaseModel):
    as_of_date: date


class InterestPartyCalcOut(BaseModel):
    party_id: UUID
    party_name: str | None = None
    direction: str
    as_of_date: date
    entries: list[InterestLoanOut]
    principal_open: Money
    outstanding_principal: Money
    interest: Money
    paid_total: Money
    balance: Money
    meaning: str


class InterestFinalizeIn(BaseModel):
    as_of_date: date
    rate_percent_per_month: Decimal | None = None
    notes: str | None = None


class InterestFinalizeOut(BaseModel):
    party_id: UUID
    closed_count: int
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
    history: list[InterestLoanDetailOut]
