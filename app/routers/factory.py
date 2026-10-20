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
    CloseBalanceIn,
    OpeningBalanceIn,
    PartyPayIn,
    PaymentIn,
    PaymentOut,
    PaymentUpdate,
    PurchaseIn,
    PurchaseOut,
    PurchaseUpdate,
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
    """Most recently used parties first (handy when adding a buying)."""
    suppliers = db.query(Supplier).filter(Supplier.is_active.is_(True)).all()
    last_map: dict = {}
    for sid, last_at in (
        db.query(MaterialPurchase.supplier_id, func.max(MaterialPurchase.created_at))
        .group_by(MaterialPurchase.supplier_id)
        .all()
    ):
        last_map[sid] = last_at
    suppliers.sort(
        key=lambda s: (0 if s.id in last_map else 1, -(last_map[s.id].timestamp() if s.id in last_map else 0), s.name)
    )
    return suppliers


@router.post("/suppliers", response_model=SupplierOut)
def create_supplier(body: SupplierIn, db: Session = Depends(get_db)):
    row = Supplier(**body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _party_total(material_amount: Decimal, transport: Decimal, mode: str) -> Decimal:
    """Amount owed to the party for this buying."""
    if mode == "deducted":
        return max(Decimal("0"), material_amount - transport)
    if mode == "included" or mode == "add_to_party":
        # included: rate already has transport; party gets material_amount as-is
        # add_to_party kept for alias — treat same as separate paid to party = material + transport
        if mode == "add_to_party":
            return material_amount + transport
        return material_amount
    # none | separate — party only for material
    return material_amount


def _purchase_out(db: Session, row: MaterialPurchase) -> PurchaseOut:
    out = PurchaseOut.model_validate(row)
    s = db.get(Supplier, row.supplier_id)
    m = db.get(MaterialType, row.material_type_id)
    out.supplier_name = s.name if s else None
    out.material_name = m.name if m else None
    out.vehicle_number = row.invoice_ref
    mat = row.material_amount or row.total_amount
    transport = row.transport_amount or Decimal("0")
    mode = row.transport_mode or "none"
    if mode == "included":
        out.landed_cost = mat
    elif transport > 0:
        out.landed_cost = mat + transport if mode != "included" else mat
    else:
        out.landed_cost = mat
    return out


def _is_opening_purchase(p: MaterialPurchase) -> bool:
    return (p.invoice_ref or "") == OPENING_BALANCE_REF


@router.get("/vendors")
def list_vendor_balances(db: Session = Depends(get_db)):
    """All parties with purchase/payment totals and balance due (0 if none)."""
    suppliers = db.query(Supplier).filter(Supplier.is_active.is_(True)).order_by(Supplier.name).all()
    out = []
    for s in suppliers:
        purchases = db.query(MaterialPurchase).filter(MaterialPurchase.supplier_id == s.id).all()
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
        material_amount=amount,
        transport_amount=Decimal("0"),
        transport_mode="none",
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
            vehicle = p.invoice_ref or "-"
            transport = float(p.transport_amount or 0)
            tmode = p.transport_mode or "none"
            sub = f"{float(p.quantity)} t · Vehicle {vehicle}"
            if transport > 0:
                sub += f" · Transport ₹{transport:.0f} ({tmode})"
            events.append(
                {
                    "id": str(p.id),
                    "type": "buy",
                    "date": p.purchase_date.isoformat(),
                    "sort_at": buy_at,
                    "amount": float(p.total_amount),
                    "title": material.name if material else "Material",
                    "subtitle": sub,
                    "status": p.payment_status,
                    "balance_amount": float(p.balance_amount),
                    "paid_amount": float(p.paid_amount),
                    "unit_price": float(p.unit_price),
                    "quantity": float(p.quantity),
                    "lorry": p.invoice_ref,
                    "vehicle_number": p.invoice_ref,
                    "transport_amount": transport,
                    "transport_mode": tmode,
                    "material_amount": float(p.material_amount or p.total_amount),
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
            notes_l = (pay.notes or "").lower()
            is_write_off = "write off" in notes_l or "written off" in notes_l or (
                pay.payment_mode == "other" and "settled" in notes_l
            )
            events.append(
                {
                    "id": str(pay.id),
                    "type": "write_off" if is_write_off else "pay",
                    "date": pay.payment_date.isoformat(),
                    "sort_at": pay_at,
                    "amount": float(pay.amount),
                    "title": "Write off" if is_write_off else "Payment",
                    "subtitle": (
                        f"Cleared due · {label}"
                        if is_write_off
                        else f"For {label} · {pay.payment_mode}"
                    ),
                    "status": "written_off" if is_write_off else "paid",
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
    rows = (
        db.query(MaterialPurchase)
        .order_by(MaterialPurchase.purchase_date.desc(), MaterialPurchase.created_at.desc())
        .limit(200)
        .all()
    )
    return [_purchase_out(db, r) for r in rows if (r.invoice_ref or "") != OPENING_BALANCE_REF]


@router.get("/purchases/{purchase_id}", response_model=PurchaseOut)
def get_purchase(purchase_id: UUID, db: Session = Depends(get_db)):
    row = db.get(MaterialPurchase, purchase_id)
    if not row:
        raise HTTPException(404, "Buying not found")
    return _purchase_out(db, row)


def _normalize_transport(mode: str, transport: Decimal) -> tuple[str, Decimal]:
    mode = (mode or "none").strip().lower()
    if mode not in ("none", "included", "deducted", "separate", "add_to_party"):
        raise HTTPException(400, "Invalid transport mode")
    transport = (transport or Decimal("0")).quantize(Decimal("0.01"))
    if transport > 0 and mode == "none":
        mode = "separate"
    return mode, transport


def _sync_transport_expense(db: Session, row: MaterialPurchase) -> None:
    db.query(Expense).filter(
        Expense.source_id == row.id,
        Expense.source_module.in_(("transport", "transport_in_rate")),
    ).delete(synchronize_session=False)
    transport = row.transport_amount or Decimal("0")
    mode = row.transport_mode or "none"
    if transport <= 0:
        return
    if mode == "included":
        db.add(
            Expense(
                expense_date=row.purchase_date,
                amount=transport,
                description=f"Transport (in rate) · vehicle {row.invoice_ref or '-'}",
                source_module="transport_in_rate",
                source_id=row.id,
            )
        )
    else:
        db.add(
            Expense(
                expense_date=row.purchase_date,
                amount=transport,
                description=f"Transport · vehicle {row.invoice_ref or '-'} · material cost",
                source_module="transport",
                source_id=row.id,
            )
        )


@router.post("/purchases", response_model=PurchaseOut)
def create_purchase(body: PurchaseIn, db: Session = Depends(get_db)):
    mode, transport = _normalize_transport(body.transport_mode, body.transport_amount or Decimal("0"))

    material_amount = (body.quantity * body.unit_price).quantize(Decimal("0.01"))
    total = _party_total(material_amount, transport, mode).quantize(Decimal("0.01"))
    paid = min(body.paid_now, total)

    row = MaterialPurchase(
        supplier_id=body.supplier_id,
        material_type_id=body.material_type_id,
        purchase_date=body.purchase_date,
        quantity=body.quantity,
        unit_price=body.unit_price,
        material_amount=material_amount,
        transport_amount=transport,
        transport_mode=mode,
        total_amount=total,
        paid_amount=paid,
        balance_amount=total - paid,
        payment_status=_payment_status(total, paid),
        invoice_ref=body.invoice_ref,
        notes=body.notes,
    )
    db.add(row)
    db.flush()
    if (row.invoice_ref or "") != OPENING_BALANCE_REF:
        _bump_inventory(db, body.material_type_id, body.quantity, "purchase_in", "purchase", row.id)
        _sync_transport_expense(db, row)

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
                description="Party payment on buying",
                source_module="material_payment",
                source_id=row.id,
            )
        )
    db.commit()
    db.refresh(row)
    return _purchase_out(db, row)


@router.put("/purchases/{purchase_id}", response_model=PurchaseOut)
def update_purchase(purchase_id: UUID, body: PurchaseUpdate, db: Session = Depends(get_db)):
    row = db.get(MaterialPurchase, purchase_id)
    if not row:
        raise HTTPException(404, "Buying not found")

    opening = _is_opening_purchase(row)
    old_qty = row.quantity
    old_material_id = row.material_type_id

    if body.supplier_id is not None:
        row.supplier_id = body.supplier_id
    if body.material_type_id is not None and not opening:
        row.material_type_id = body.material_type_id
    if body.purchase_date is not None:
        row.purchase_date = body.purchase_date
    if body.notes is not None:
        row.notes = body.notes
    if body.invoice_ref is not None and not opening:
        row.invoice_ref = body.invoice_ref

    if opening:
        # Opening / other due — amount via unit_price (qty stays 1)
        if body.unit_price is not None:
            amount = body.unit_price.quantize(Decimal("0.01"))
            row.unit_price = amount
            row.material_amount = amount
            row.total_amount = amount
            if row.paid_amount > amount:
                raise HTTPException(400, "Paid already more than new due amount")
            row.balance_amount = amount - row.paid_amount
            row.payment_status = _payment_status(amount, row.paid_amount)
    else:
        qty = body.quantity if body.quantity is not None else row.quantity
        rate = body.unit_price if body.unit_price is not None else row.unit_price
        mode = body.transport_mode if body.transport_mode is not None else (row.transport_mode or "none")
        transport = (
            body.transport_amount
            if body.transport_amount is not None
            else (row.transport_amount or Decimal("0"))
        )
        mode, transport = _normalize_transport(mode, transport)
        material_amount = (qty * rate).quantize(Decimal("0.01"))
        total = _party_total(material_amount, transport, mode).quantize(Decimal("0.01"))
        if row.paid_amount > total:
            raise HTTPException(400, "Paid already more than new bill total")
        row.quantity = qty
        row.unit_price = rate
        row.material_amount = material_amount
        row.transport_amount = transport
        row.transport_mode = mode
        row.total_amount = total
        row.balance_amount = total - row.paid_amount
        row.payment_status = _payment_status(total, row.paid_amount)

        # Inventory adjust for qty / material change
        if old_material_id != row.material_type_id:
            _bump_inventory(db, old_material_id, -old_qty, "adjustment", "purchase_edit", row.id)
            _bump_inventory(db, row.material_type_id, qty, "purchase_in", "purchase_edit", row.id)
        elif qty != old_qty:
            _bump_inventory(db, row.material_type_id, qty - old_qty, "adjustment", "purchase_edit", row.id)
        _sync_transport_expense(db, row)

    db.commit()
    db.refresh(row)
    return _purchase_out(db, row)


def _apply_party_payment(
    db: Session,
    *,
    supplier: Supplier,
    amount: Decimal,
    pay_date: date,
    payment_mode: str,
    notes: str | None,
    write_off: bool = False,
) -> dict:
    """Allocate payment oldest-open-bill first; update each bill balance."""
    open_rows = (
        db.query(MaterialPurchase)
        .filter(MaterialPurchase.supplier_id == supplier.id, MaterialPurchase.balance_amount > 0)
        .order_by(MaterialPurchase.purchase_date.asc(), MaterialPurchase.created_at.asc())
        .all()
    )
    if not open_rows:
        return {"applied": 0, "amount": 0.0, "bills": 0, "message": "Nothing due"}

    total_due = sum((p.balance_amount for p in open_rows), Decimal("0"))
    if amount > total_due + Decimal("0.01"):
        raise HTTPException(400, f"Amount bigger than due ({float(total_due):.0f})")

    remaining = amount.quantize(Decimal("0.01"))
    applied = Decimal("0")
    bills = 0
    allocations: list[dict] = []
    for p in open_rows:
        if remaining <= 0:
            break
        take = min(remaining, p.balance_amount).quantize(Decimal("0.01"))
        if take <= 0:
            continue
        note = notes or ("Balance closed / settled" if write_off else "Party payment")
        pay = MaterialPayment(
            purchase_id=p.id,
            payment_date=pay_date,
            amount=take,
            payment_mode="other" if write_off else payment_mode,
            notes=note,
        )
        db.add(pay)
        db.flush()
        if not write_off:
            db.add(
                Expense(
                    expense_date=pay_date,
                    amount=take,
                    description=f"Party payment · {supplier.name}",
                    source_module="material_payment",
                    source_id=pay.id,
                )
            )
        p.paid_amount += take
        p.balance_amount = (p.total_amount - p.paid_amount).quantize(Decimal("0.01"))
        p.payment_status = _payment_status(p.total_amount, p.paid_amount)
        remaining -= take
        applied += take
        bills += 1
        allocations.append(
            {
                "purchase_id": str(p.id),
                "amount": float(take),
                "bill_balance_after": float(p.balance_amount),
            }
        )

    db.commit()
    return {
        "applied": float(applied),
        "amount": float(applied),
        "bills": bills,
        "party": supplier.name,
        "balance_due_after": float(total_due - applied),
        "allocations": allocations,
        "write_off": write_off,
    }


@router.post("/vendors/{supplier_id}/pay")
def pay_vendor(supplier_id: UUID, body: PartyPayIn, db: Session = Depends(get_db)):
    """Pay a party any amount — auto-applied to oldest open bills first."""
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(404, "Party not found")
    return _apply_party_payment(
        db,
        supplier=supplier,
        amount=body.amount,
        pay_date=body.payment_date or date.today(),
        payment_mode=body.payment_mode,
        notes=body.notes,
        write_off=False,
    )


@router.post("/vendors/{supplier_id}/close-balance")
def close_vendor_balance(
    supplier_id: UUID,
    body: CloseBalanceIn,
    db: Session = Depends(get_db),
):
    """Pay off or write-off all open dues for a party."""
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(404, "Party not found")
    open_rows = (
        db.query(MaterialPurchase)
        .filter(MaterialPurchase.supplier_id == supplier_id, MaterialPurchase.balance_amount > 0)
        .all()
    )
    total_due = sum((p.balance_amount for p in open_rows), Decimal("0"))
    if total_due <= 0:
        return {"closed": 0, "amount": 0, "message": "Nothing due"}
    result = _apply_party_payment(
        db,
        supplier=supplier,
        amount=total_due,
        pay_date=body.payment_date or date.today(),
        payment_mode=body.payment_mode,
        notes=body.notes or ("Balance closed / settled" if body.write_off else "Balance closed"),
        write_off=body.write_off,
    )
    return {
        "closed": result["bills"],
        "amount": result["amount"],
        "write_off": body.write_off,
        "party": supplier.name,
    }


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


def _payment_out(db: Session, pay: MaterialPayment) -> PaymentOut:
    out = PaymentOut.model_validate(pay)
    purchase = db.get(MaterialPurchase, pay.purchase_id)
    if purchase:
        s = db.get(Supplier, purchase.supplier_id)
        m = db.get(MaterialType, purchase.material_type_id)
        out.supplier_name = s.name if s else None
        out.material_name = (
            "Old balance"
            if _is_opening_purchase(purchase)
            else (m.name if m else None)
        )
    return out


@router.get("/payments", response_model=list[PaymentOut])
def list_payments(db: Session = Depends(get_db)):
    rows = db.query(MaterialPayment).order_by(MaterialPayment.payment_date.desc()).limit(200).all()
    return [_payment_out(db, r) for r in rows]


@router.get("/payments/{payment_id}", response_model=PaymentOut)
def get_payment(payment_id: UUID, db: Session = Depends(get_db)):
    pay = db.get(MaterialPayment, payment_id)
    if not pay:
        raise HTTPException(404, "Payment not found")
    return _payment_out(db, pay)


@router.post("/payments", response_model=PaymentOut)
def create_payment(body: PaymentIn, db: Session = Depends(get_db)):
    purchase = db.get(MaterialPurchase, body.purchase_id)
    if not purchase:
        raise HTTPException(404, "Purchase not found")
    if body.amount > purchase.balance_amount:
        raise HTTPException(400, "Amount bigger than balance")
    pay = MaterialPayment(**body.model_dump())
    db.add(pay)
    db.flush()
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
    return _payment_out(db, pay)


@router.put("/payments/{payment_id}", response_model=PaymentOut)
def update_payment(payment_id: UUID, body: PaymentUpdate, db: Session = Depends(get_db)):
    pay = db.get(MaterialPayment, payment_id)
    if not pay:
        raise HTTPException(404, "Payment not found")
    purchase = db.get(MaterialPurchase, pay.purchase_id)
    if not purchase:
        raise HTTPException(404, "Purchase not found")

    old_amount = pay.amount
    new_amount = body.amount if body.amount is not None else old_amount
    max_allowed = purchase.balance_amount + old_amount
    if new_amount > max_allowed:
        raise HTTPException(400, "Amount bigger than remaining due on this bill")

    if body.payment_date is not None:
        pay.payment_date = body.payment_date
    if body.payment_mode is not None:
        pay.payment_mode = body.payment_mode
    if body.reference_no is not None:
        pay.reference_no = body.reference_no
    if body.notes is not None:
        pay.notes = body.notes
    pay.amount = new_amount

    purchase.paid_amount = purchase.paid_amount - old_amount + new_amount
    purchase.balance_amount = purchase.total_amount - purchase.paid_amount
    purchase.payment_status = _payment_status(purchase.total_amount, purchase.paid_amount)

    # Keep linked expense in sync when it was a real payment (not write-off)
    notes_l = (pay.notes or "").lower()
    is_write_off = "write off" in notes_l or (
        pay.payment_mode == "other" and "settled" in notes_l
    )
    exp = (
        db.query(Expense)
        .filter(Expense.source_module == "material_payment", Expense.source_id == pay.id)
        .first()
    )
    if is_write_off:
        if exp:
            db.delete(exp)
    elif exp:
        exp.amount = new_amount
        exp.expense_date = pay.payment_date
    else:
        db.add(
            Expense(
                expense_date=pay.payment_date,
                amount=new_amount,
                description="Supplier payment",
                source_module="material_payment",
                source_id=pay.id,
            )
        )

    db.commit()
    db.refresh(pay)
    return _payment_out(db, pay)


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
