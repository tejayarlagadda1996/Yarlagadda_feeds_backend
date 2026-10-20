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


class InterestPartyOut(InterestPartyIn):
    id: UUID
    is_active: bool

    model_config = {"from_attributes": True}


class InterestLoanIn(BaseModel):
    party_id: UUID
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
    paid_total: Money = Decimal("0")
    # Snapshot calc as of today (or closed_date)
    days: int = 0
    interest: Money = Decimal("0")
    total_due: Money = Decimal("0")
    balance: Money = Decimal("0")

    model_config = {"from_attributes": True}


class InterestLoanDetailOut(InterestLoanOut):
    payments: list[InterestPaymentOut] = []


class InterestCalcIn(BaseModel):
    as_of_date: date


class InterestCalcOut(BaseModel):
    loan_id: UUID
    party_name: str | None = None
    direction: str
    principal: Money
    rate_percent_per_month: Money
    start_date: date
    as_of_date: date
    days: int
    interest: Money
    total_due: Money
    paid_total: Money
    balance: Money
    meaning: str


class InterestCloseIn(BaseModel):
    closed_date: date
    notes: str | None = None
