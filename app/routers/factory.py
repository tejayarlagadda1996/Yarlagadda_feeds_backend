from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Buyer,
    CatchEvent,
    CatchSaleLineItem,
    CatchVehicleSale,
    Expense,
    FishTank,
    FishType,
    Income,
    InventoryTransaction,
    LabourAdvance,
    Labourer,
    LabourSalaryPayment,
    MaterialInventory,
    MaterialPayment,
    MaterialPurchase,
    MaterialType,
    Supplier,
)
from app.schemas.factory import (
    AdvanceIn,
    AdvanceOut,
    BuyerIn,
    BuyerOut,
    CatchEventIn,
    CatchEventOut,
    FishTankIn,
    FishTankOut,
    FishTypeIn,
    FishTypeOut,
    LabourerIn,
    LabourerOut,
    MaterialTypeIn,
    MaterialTypeOut,
    OpeningBalanceIn,
    PaymentIn,
    PaymentOut,
    PurchaseIn,
    PurchaseOut,
    SalaryIn,
    SalaryOut,
    SupplierIn,
    SupplierOut,
    VehicleSaleIn,
    VehicleSaleOut,
)
from app.services.bootstrap import OPENING_BALANCE_MATERIAL, OPENING_BALANCE_REF, ensure_opening_balance_material

router = APIRouter(tags=["factory"])


def _payment_status(total: Decimal, paid: Decimal) -> str:
    if paid <= 0:
        return "unpaid"
    if paid >= total:
        return "paid"
    return "partial"


def _bump_inventory(db: Session, material_type_id: UUID, qty: Decimal, txn_type: str, ref_type: str, ref_id: UUID) -> None:
    inv = db.query(MaterialInventory).filter(MaterialInventory.material_type_id == material_type_id).first()
    if inv is None:
        inv = MaterialInventory(material_type_id=material_type_id, quantity_on_hand=Decimal("0"))
        db.add(inv)
        db.flush()
    new_qty = inv.quantity_on_hand + qty
    if new_qty < 0:
        raise HTTPException(400, "Not enough stock")
    inv.quantity_on_hand = new_qty
    db.add(
        InventoryTransaction(
            material_type_id=material_type_id,
            txn_type=txn_type,
            quantity=qty,
            reference_type=ref_type,
            reference_id=ref_id,
            txn_date=date.today(),
        )
    )


# ---------- Materials ----------
@router.get("/material-types", response_model=list[MaterialTypeOut])
def list_material_types(db: Session = Depends(get_db)):
    return (
        db.query(MaterialType)
        .filter(
            MaterialType.is_active.is_(True),
            MaterialType.name != OPENING_BALANCE_MATERIAL,
        )
        .order_by(MaterialType.name)
        .all()
    )


@router.post("/material-types", response_model=MaterialTypeOut)
def create_material_type(body: MaterialTypeIn, db: Session = Depends(get_db)):
    row = MaterialType(**body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/suppliers", response_model=list[SupplierOut])
def list_suppliers(db: Session = Depends(get_db)):
    return db.query(Supplier).filter(Supplier.is_active.is_(True)).order_by(Supplier.name).all()


@router.post("/suppliers", response_model=SupplierOut)
def create_supplier(body: SupplierIn, db: Session = Depends(get_db)):
    row = Supplier(**body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _is_opening_purchase(p: MaterialPurchase) -> bool:
    return (p.invoice_ref or "") == OPENING_BALANCE_REF


@router.get("/vendors")
def list_vendor_balances(db: Session = Depends(get_db)):
    """Vendors with purchase/payment totals and balance due."""
    suppliers = db.query(Supplier).filter(Supplier.is_active.is_(True)).order_by(Supplier.name).all()
    out = []
    for s in suppliers:
        purchases = db.query(MaterialPurchase).filter(MaterialPurchase.supplier_id == s.id).all()
        if not purchases:
            continue
        total_buy = sum((p.total_amount for p in purchases), Decimal("0"))
        total_paid = sum((p.paid_amount for p in purchases), Decimal("0"))
        balance = sum((p.balance_amount for p in purchases), Decimal("0"))
        out.append(
            {
                "id": str(s.id),
                "name": s.name,
                "phone": s.phone,
                "total_buy": float(total_buy),
                "total_paid": float(total_paid),
                "balance_due": float(balance),
                "open_bills": sum(1 for p in purchases if p.balance_amount > 0),
            }
        )
    out.sort(key=lambda x: (-x["balance_due"], x["name"]))
    return out


@router.post("/vendors/{supplier_id}/opening-balance")
def add_vendor_opening_balance(
    supplier_id: UUID,
    body: OpeningBalanceIn,
    db: Session = Depends(get_db),
):
    """Record old money still owed to this vendor (does not change stock)."""
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(404, "Vendor not found")

    amount = body.amount.quantize(Decimal("0.01"))
    bal_date = body.balance_date or date.today()
    material = ensure_opening_balance_material(db)

    row = MaterialPurchase(
        supplier_id=supplier.id,
        material_type_id=material.id,
        purchase_date=bal_date,
        quantity=Decimal("1"),
        unit_price=amount,
        total_amount=amount,
        paid_amount=Decimal("0"),
        balance_amount=amount,
        payment_status="unpaid",
        invoice_ref=OPENING_BALANCE_REF,
        notes=body.notes or "Old balance brought into app",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": str(row.id),
        "supplier_id": str(supplier.id),
        "supplier_name": supplier.name,
        "amount": float(amount),
        "balance_date": bal_date.isoformat(),
        "notes": row.notes,
        "balance_due": float(row.balance_amount),
    }


@router.get("/vendors/{supplier_id}/ledger")
def vendor_ledger(supplier_id: UUID, db: Session = Depends(get_db)):
    """Chronological buy + pay history for one vendor."""
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(404, "Vendor not found")

    purchases = (
        db.query(MaterialPurchase)
        .filter(MaterialPurchase.supplier_id == supplier_id)
        .order_by(MaterialPurchase.purchase_date.desc(), MaterialPurchase.created_at.desc())
        .all()
    )
    events: list[dict] = []
    for p in purchases:
        material = db.get(MaterialType, p.material_type_id)
        buy_at = p.created_at.isoformat() if p.created_at else f"{p.purchase_date.isoformat()}T00:00:00"
        opening = _is_opening_purchase(p)
        if opening:
            events.append(
                {
                    "id": str(p.id),
                    "type": "opening",
                    "date": p.purchase_date.isoformat(),
                    "sort_at": buy_at,
                    "amount": float(p.total_amount),
                    "title": "Old balance",
                    "subtitle": p.notes or "Brought forward",
                    "status": p.payment_status,
                    "balance_amount": float(p.balance_amount),
                    "paid_amount": float(p.paid_amount),
                    "unit_price": float(p.unit_price),
                    "quantity": float(p.quantity),
                    "lorry": None,
                    "notes": p.notes,
                    "purchase_id": str(p.id),
                    "material_name": "Old balance",
                }
            )
        else:
            events.append(
                {
                    "id": str(p.id),
                    "type": "buy",
                    "date": p.purchase_date.isoformat(),
                    "sort_at": buy_at,
                    "amount": float(p.total_amount),
                    "title": material.name if material else "Material",
                    "subtitle": f"{float(p.quantity)} tonne · Lorry {p.invoice_ref or '-'}",
                    "status": p.payment_status,
                    "balance_amount": float(p.balance_amount),
                    "paid_amount": float(p.paid_amount),
                    "unit_price": float(p.unit_price),
                    "quantity": float(p.quantity),
                    "lorry": p.invoice_ref,
                    "notes": p.notes,
                    "purchase_id": str(p.id),
                    "material_name": material.name if material else None,
                }
            )
        payments = (
            db.query(MaterialPayment)
            .filter(MaterialPayment.purchase_id == p.id)
            .order_by(MaterialPayment.payment_date.desc(), MaterialPayment.created_at.desc())
            .all()
        )
        for pay in payments:
            pay_at = (
                pay.created_at.isoformat()
                if pay.created_at
                else f"{pay.payment_date.isoformat()}T00:00:00"
            )
            label = "old balance" if opening else (material.name if material else "material")
            events.append(
                {
                    "id": str(pay.id),
                    "type": "pay",
                    "date": pay.payment_date.isoformat(),
                    "sort_at": pay_at,
                    "amount": float(pay.amount),
                    "title": "Payment",
                    "subtitle": f"For {label} · {pay.payment_mode}",
                    "status": "paid",
                    "payment_mode": pay.payment_mode,
                    "reference_no": pay.reference_no,
                    "notes": pay.notes,
                    "purchase_id": str(p.id),
                    "material_name": "Old balance" if opening else (material.name if material else None),
                    "lorry": None if opening else p.invoice_ref,
                    "purchase_total": float(p.total_amount),
                    "purchase_balance": float(p.balance_amount),
                }
            )

    # Newest first — buy and pay mixed by date/time
    events.sort(key=lambda e: (e["date"], e.get("sort_at") or e["date"]), reverse=True)
    total_buy = sum((p.total_amount for p in purchases), Decimal("0"))
    total_paid = sum((p.paid_amount for p in purchases), Decimal("0"))
    balance = sum((p.balance_amount for p in purchases), Decimal("0"))
    return {
        "vendor": {"id": str(supplier.id), "name": supplier.name, "phone": supplier.phone},
        "total_buy": float(total_buy),
        "total_paid": float(total_paid),
        "balance_due": float(balance),
        "transactions": events,
        "open_purchases": [
            {
                "id": str(p.id),
                "material_name": (
                    "Old balance"
                    if _is_opening_purchase(p)
                    else (
                        db.get(MaterialType, p.material_type_id).name
                        if db.get(MaterialType, p.material_type_id)
                        else "Material"
                    )
                ),
                "lorry": None if _is_opening_purchase(p) else p.invoice_ref,
                "date": p.purchase_date.isoformat(),
                "total_amount": float(p.total_amount),
                "balance_amount": float(p.balance_amount),
            }
            for p in purchases
            if p.balance_amount > 0
        ],
    }


@router.get("/purchases", response_model=list[PurchaseOut])
def list_purchases(db: Session = Depends(get_db)):
    rows = db.query(MaterialPurchase).order_by(MaterialPurchase.purchase_date.desc()).limit(200).all()
    out: list[PurchaseOut] = []
    for r in rows:
        p = PurchaseOut.model_validate(r)
        s = db.get(Supplier, r.supplier_id)
        m = db.get(MaterialType, r.material_type_id)
        p.supplier_name = s.name if s else None
        p.material_name = m.name if m else None
        out.append(p)
    return out


@router.post("/purchases", response_model=PurchaseOut)
def create_purchase(body: PurchaseIn, db: Session = Depends(get_db)):
    total = (body.quantity * body.unit_price).quantize(Decimal("0.01"))
    paid = min(body.paid_now, total)
    row = MaterialPurchase(
        supplier_id=body.supplier_id,
        material_type_id=body.material_type_id,
        purchase_date=body.purchase_date,
        quantity=body.quantity,
        unit_price=body.unit_price,
        total_amount=total,
        paid_amount=paid,
        balance_amount=total - paid,
        payment_status=_payment_status(total, paid),
        invoice_ref=body.invoice_ref,
        notes=body.notes,
    )
    db.add(row)
    db.flush()
    _bump_inventory(db, body.material_type_id, body.quantity, "purchase_in", "purchase", row.id)
    if paid > 0:
        db.add(
            MaterialPayment(
                purchase_id=row.id,
                payment_date=body.purchase_date,
                amount=paid,
                payment_mode="cash",
            )
        )
        db.add(
            Expense(
                expense_date=body.purchase_date,
                amount=paid,
                description=f"Material payment",
                source_module="material_payment",
                source_id=row.id,
            )
        )
    db.commit()
    db.refresh(row)
    out = PurchaseOut.model_validate(row)
    s = db.get(Supplier, row.supplier_id)
    m = db.get(MaterialType, row.material_type_id)
    out.supplier_name = s.name if s else None
    out.material_name = m.name if m else None
    return out


@router.get("/inventory")
def list_inventory(db: Session = Depends(get_db)):
    rows = db.query(MaterialInventory, MaterialType).join(
        MaterialType, MaterialInventory.material_type_id == MaterialType.id
    ).all()
    return [
        {
            "material_type_id": str(inv.material_type_id),
            "name": mt.name,
            "unit": mt.unit,
            "quantity_on_hand": float(inv.quantity_on_hand),
        }
        for inv, mt in rows
    ]


@router.get("/payments", response_model=list[PaymentOut])
def list_payments(db: Session = Depends(get_db)):
    return db.query(MaterialPayment).order_by(MaterialPayment.payment_date.desc()).limit(200).all()


@router.post("/payments", response_model=PaymentOut)
def create_payment(body: PaymentIn, db: Session = Depends(get_db)):
    purchase = db.get(MaterialPurchase, body.purchase_id)
    if not purchase:
        raise HTTPException(404, "Purchase not found")
    if body.amount > purchase.balance_amount:
        raise HTTPException(400, "Amount bigger than balance")
    pay = MaterialPayment(**body.model_dump())
    db.add(pay)
    purchase.paid_amount += body.amount
    purchase.balance_amount = purchase.total_amount - purchase.paid_amount
    purchase.payment_status = _payment_status(purchase.total_amount, purchase.paid_amount)
    db.add(
        Expense(
            expense_date=body.payment_date,
            amount=body.amount,
            description="Supplier payment",
            source_module="material_payment",
            source_id=pay.id,
        )
    )
    db.commit()
    db.refresh(pay)
    return pay


# ---------- Labour ----------
@router.get("/labourers", response_model=list[LabourerOut])
def list_labourers(db: Session = Depends(get_db)):
    return db.query(Labourer).filter(Labourer.is_active.is_(True)).order_by(Labourer.name).all()


@router.post("/labourers", response_model=LabourerOut)
def create_labourer(body: LabourerIn, db: Session = Depends(get_db)):
    row = Labourer(**body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/advances", response_model=list[AdvanceOut])
def list_advances(db: Session = Depends(get_db)):
    rows = db.query(LabourAdvance).order_by(LabourAdvance.advance_date.desc()).limit(200).all()
    out = []
    for r in rows:
        a = AdvanceOut.model_validate(r)
        lab = db.get(Labourer, r.labourer_id)
        a.labourer_name = lab.name if lab else None
        out.append(a)
    return out


@router.post("/advances", response_model=AdvanceOut)
def create_advance(body: AdvanceIn, db: Session = Depends(get_db)):
    row = LabourAdvance(**body.model_dump())
    db.add(row)
    db.add(
        Expense(
            expense_date=body.advance_date,
            amount=body.amount,
            description="Worker advance",
            source_module="labour_advance",
        )
    )
    db.commit()
    db.refresh(row)
    out = AdvanceOut.model_validate(row)
    lab = db.get(Labourer, row.labourer_id)
    out.labourer_name = lab.name if lab else None
    return out


@router.get("/salaries", response_model=list[SalaryOut])
def list_salaries(db: Session = Depends(get_db)):
    rows = db.query(LabourSalaryPayment).order_by(LabourSalaryPayment.salary_month.desc()).limit(200).all()
    out = []
    for r in rows:
        s = SalaryOut.model_validate(r)
        lab = db.get(Labourer, r.labourer_id)
        s.labourer_name = lab.name if lab else None
        out.append(s)
    return out


@router.post("/salaries", response_model=SalaryOut)
def create_salary(body: SalaryIn, db: Session = Depends(get_db)):
    lab = db.get(Labourer, body.labourer_id)
    if not lab:
        raise HTTPException(404, "Worker not found")
    month = body.salary_month.replace(day=1)
    advances = (
        db.query(func.coalesce(func.sum(LabourAdvance.amount), 0))
        .filter(LabourAdvance.labourer_id == body.labourer_id, LabourAdvance.salary_month == month)
        .scalar()
    )
    advances = Decimal(str(advances))
    gross = lab.monthly_wage
    net = gross - advances
    if net < 0:
        net = Decimal("0")
    row = LabourSalaryPayment(
        labourer_id=body.labourer_id,
        salary_month=month,
        gross_wage=gross,
        advances_deducted=advances,
        net_paid=net,
        payment_date=body.payment_date,
        payment_mode=body.payment_mode,
        notes=body.notes,
    )
    db.add(row)
    if net > 0:
        db.add(
            Expense(
                expense_date=body.payment_date,
                amount=net,
                description=f"Salary {lab.name}",
                source_module="labour_salary",
            )
        )
    db.commit()
    db.refresh(row)
    out = SalaryOut.model_validate(row)
    out.labourer_name = lab.name
    return out


# ---------- Fish ----------
@router.get("/tanks", response_model=list[FishTankOut])
def list_tanks(db: Session = Depends(get_db)):
    return db.query(FishTank).filter(FishTank.is_active.is_(True)).all()


@router.post("/tanks", response_model=FishTankOut)
def create_tank(body: FishTankIn, db: Session = Depends(get_db)):
    row = FishTank(**body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/fish-types", response_model=list[FishTypeOut])
def list_fish_types(db: Session = Depends(get_db)):
    return db.query(FishType).filter(FishType.is_active.is_(True)).all()


@router.post("/fish-types", response_model=FishTypeOut)
def create_fish_type(body: FishTypeIn, db: Session = Depends(get_db)):
    row = FishType(**body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/buyers", response_model=list[BuyerOut])
def list_buyers(db: Session = Depends(get_db)):
    return db.query(Buyer).filter(Buyer.is_active.is_(True)).all()


@router.post("/buyers", response_model=BuyerOut)
def create_buyer(body: BuyerIn, db: Session = Depends(get_db)):
    row = Buyer(**body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/catch-events", response_model=list[CatchEventOut])
def list_catch_events(db: Session = Depends(get_db)):
    rows = db.query(CatchEvent).order_by(CatchEvent.catch_start_date.desc()).all()
    out = []
    for r in rows:
        e = CatchEventOut.model_validate(r)
        tank = db.get(FishTank, r.tank_id)
        e.tank_name = tank.name if tank else None
        total = (
            db.query(func.coalesce(func.sum(CatchSaleLineItem.line_amount), 0))
            .join(CatchVehicleSale)
            .filter(CatchVehicleSale.catch_event_id == r.id)
            .scalar()
        )
        e.total_amount = Decimal(str(total))
        out.append(e)
    return out


@router.post("/catch-events", response_model=CatchEventOut)
def create_catch_event(body: CatchEventIn, db: Session = Depends(get_db)):
    row = CatchEvent(**body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    out = CatchEventOut.model_validate(row)
    tank = db.get(FishTank, row.tank_id)
    out.tank_name = tank.name if tank else None
    return out


@router.get("/vehicle-sales", response_model=list[VehicleSaleOut])
def list_vehicle_sales(db: Session = Depends(get_db)):
    rows = db.query(CatchVehicleSale).order_by(CatchVehicleSale.sale_date.desc()).limit(200).all()
    out = []
    for r in rows:
        v = VehicleSaleOut.model_validate(r)
        buyer = db.get(Buyer, r.buyer_id) if r.buyer_id else None
        v.buyer_name = buyer.name if buyer else None
        total = (
            db.query(func.coalesce(func.sum(CatchSaleLineItem.line_amount), 0))
            .filter(CatchSaleLineItem.vehicle_sale_id == r.id)
            .scalar()
        )
        v.total_amount = Decimal(str(total))
        out.append(v)
    return out


@router.post("/vehicle-sales", response_model=VehicleSaleOut)
def create_vehicle_sale(body: VehicleSaleIn, db: Session = Depends(get_db)):
    if not body.lines:
        raise HTTPException(400, "Add at least one fish line")
    sale = CatchVehicleSale(
        catch_event_id=body.catch_event_id,
        buyer_id=body.buyer_id,
        vehicle_number=body.vehicle_number,
        sale_date=body.sale_date,
        driver_name=body.driver_name,
        notes=body.notes,
    )
    db.add(sale)
    db.flush()
    total = Decimal("0")
    for line in body.lines:
        amount = (line.weight_kg * line.rate_per_kg).quantize(Decimal("0.01"))
        total += amount
        db.add(
            CatchSaleLineItem(
                vehicle_sale_id=sale.id,
                fish_type_id=line.fish_type_id,
                weight_kg=line.weight_kg,
                fish_count=line.fish_count,
                rate_per_kg=line.rate_per_kg,
                line_amount=amount,
            )
        )
    db.add(
        Income(
            income_date=body.sale_date,
            amount=total,
            description=f"Fish sale vehicle {body.vehicle_number}",
            source_module="catch_sale",
            source_id=sale.id,
        )
    )
    db.commit()
    db.refresh(sale)
    out = VehicleSaleOut.model_validate(sale)
    out.total_amount = total
    buyer = db.get(Buyer, sale.buyer_id) if sale.buyer_id else None
    out.buyer_name = buyer.name if buyer else None
    return out
