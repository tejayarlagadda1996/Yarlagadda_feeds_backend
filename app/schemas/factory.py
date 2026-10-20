from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, PlainSerializer

# JSON numbers (not strings) for Flutter
Money = Annotated[Decimal, PlainSerializer(lambda v: float(v), return_type=float, when_used='json')]



# ---- Materials / suppliers / purchases / payments ----
class MaterialTypeIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    unit: str = "tonne"
    description: str | None = None


class MaterialTypeOut(MaterialTypeIn):
    id: UUID
    is_active: bool

    model_config = {"from_attributes": True}


class SupplierIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    phone: str | None = None
    address: str | None = None
    notes: str | None = None


class SupplierOut(SupplierIn):
    id: UUID
    is_active: bool

    model_config = {"from_attributes": True}


class PurchaseIn(BaseModel):
    supplier_id: UUID
    material_type_id: UUID
    purchase_date: date
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    invoice_ref: str | None = None
    notes: str | None = None
    paid_now: Decimal = Field(default=Decimal("0"), ge=0)


class PurchaseOut(BaseModel):
    id: UUID
    supplier_id: UUID
    material_type_id: UUID
    purchase_date: date
    quantity: Money
    unit_price: Money
    total_amount: Money
    paid_amount: Money
    balance_amount: Money
    payment_status: str
    invoice_ref: str | None
    notes: str | None
    supplier_name: str | None = None
    material_name: str | None = None

    model_config = {"from_attributes": True}


class PaymentIn(BaseModel):
    purchase_id: UUID
    payment_date: date
    amount: Decimal = Field(gt=0)
    payment_mode: str = "cash"
    reference_no: str | None = None
    notes: str | None = None


class OpeningBalanceIn(BaseModel):
    """Old money still owed to a vendor before app tracking started."""

    amount: Decimal = Field(gt=0)
    balance_date: date | None = None
    notes: str | None = None


class PaymentOut(BaseModel):
    id: UUID
    purchase_id: UUID
    payment_date: date
    amount: Money
    payment_mode: str
    reference_no: str | None
    notes: str | None

    model_config = {"from_attributes": True}


# ---- Labour ----
class LabourerIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    phone: str | None = None
    role_title: str | None = None
    monthly_wage: Decimal = Field(default=Decimal("0"), ge=0)
    join_date: date | None = None
    notes: str | None = None


class LabourerOut(LabourerIn):
    id: UUID
    is_active: bool

    model_config = {"from_attributes": True}


class AdvanceIn(BaseModel):
    labourer_id: UUID
    advance_date: date
    amount: Decimal = Field(gt=0)
    advance_type: str = "weekly"
    salary_month: date
    notes: str | None = None


class AdvanceOut(BaseModel):
    id: UUID
    labourer_id: UUID
    advance_date: date
    amount: Money
    advance_type: str
    salary_month: date
    notes: str | None
    labourer_name: str | None = None

    model_config = {"from_attributes": True}


class SalaryIn(BaseModel):
    labourer_id: UUID
    salary_month: date
    payment_date: date
    payment_mode: str = "cash"
    notes: str | None = None


class SalaryOut(BaseModel):
    id: UUID
    labourer_id: UUID
    salary_month: date
    gross_wage: Money
    advances_deducted: Money
    net_paid: Money
    payment_date: date
    payment_mode: str
    notes: str | None
    labourer_name: str | None = None

    model_config = {"from_attributes": True}


# ---- Fish catch ----
class FishTankIn(BaseModel):
    name: str
    location: str | None = None
    capacity_notes: str | None = None


class FishTankOut(FishTankIn):
    id: UUID
    is_active: bool

    model_config = {"from_attributes": True}


class FishTypeIn(BaseModel):
    name: str


class FishTypeOut(FishTypeIn):
    id: UUID
    is_active: bool

    model_config = {"from_attributes": True}


class BuyerIn(BaseModel):
    name: str
    phone: str | None = None
    address: str | None = None


class BuyerOut(BuyerIn):
    id: UUID
    is_active: bool

    model_config = {"from_attributes": True}


class CatchEventIn(BaseModel):
    tank_id: UUID
    catch_start_date: date
    catch_end_date: date | None = None
    cycle_months: int | None = None
    notes: str | None = None


class CatchEventOut(BaseModel):
    id: UUID
    tank_id: UUID
    catch_start_date: date
    catch_end_date: date | None
    cycle_months: int | None
    notes: str | None
    tank_name: str | None = None
    total_amount: Money = Decimal("0")

    model_config = {"from_attributes": True}


class SaleLineIn(BaseModel):
    fish_type_id: UUID
    weight_kg: Decimal = Field(ge=0)
    fish_count: int = Field(default=0, ge=0)
    rate_per_kg: Decimal = Field(ge=0)


class VehicleSaleIn(BaseModel):
    catch_event_id: UUID
    buyer_id: UUID | None = None
    vehicle_number: str
    sale_date: date
    driver_name: str | None = None
    notes: str | None = None
    lines: list[SaleLineIn]


class VehicleSaleOut(BaseModel):
    id: UUID
    catch_event_id: UUID
    buyer_id: UUID | None
    vehicle_number: str
    sale_date: date
    driver_name: str | None
    notes: str | None
    buyer_name: str | None = None
    total_amount: Money = Decimal("0")

    model_config = {"from_attributes": True}


# ---- Feed ----
class FeedBatchIn(BaseModel):
    batch_date: date
    notes: str | None = None
    materials: list[dict]  # {material_type_id, quantity_used}
    deliveries: list[dict]  # {tank_id, quantity_kg, delivery_date}


class FeedBatchOut(BaseModel):
    id: UUID
    batch_date: date
    total_qty_kg: Money
    notes: str | None

    model_config = {"from_attributes": True}


# ---- Money ----
class ExpenseIn(BaseModel):
    expense_date: date
    amount: Decimal = Field(gt=0)
    description: str | None = None
    category_id: UUID | None = None


class ExpenseOut(BaseModel):
    id: UUID
    expense_date: date
    amount: Money
    description: str | None
    category_id: UUID | None
    category_name: str | None = None

    model_config = {"from_attributes": True}


class IncomeIn(BaseModel):
    income_date: date
    amount: Decimal = Field(gt=0)
    description: str | None = None


class IncomeOut(BaseModel):
    id: UUID
    income_date: date
    amount: Money
    description: str | None

    model_config = {"from_attributes": True}


class InvestmentIn(BaseModel):
    investment_date: date
    amount: Decimal = Field(gt=0)
    investor_name: str | None = None
    description: str | None = None


class InvestmentOut(BaseModel):
    id: UUID
    investment_date: date
    amount: Money
    investor_name: str | None
    description: str | None

    model_config = {"from_attributes": True}


class CategoryOut(BaseModel):
    id: UUID
    name: str

    model_config = {"from_attributes": True}


class MonthReportOut(BaseModel):
    year: int
    month: int
    total_expenses: Money
    total_income: Money
    total_investments: Money
    material_payments: Money
    labour_paid: Money
    catch_sales: Money
    net: Money
