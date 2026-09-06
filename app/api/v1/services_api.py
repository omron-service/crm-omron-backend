import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import create_engine, desc
from sqlalchemy.orm import sessionmaker, Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from app.models.schema import Base, ServiceTicket, PaymentRecord, InventoryPart

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local_test.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Inisialisasi tabel (Aman: create_all tidak akan menghapus data yang sudah ada)
Base.metadata.create_all(bind=engine)

router = APIRouter(prefix="/api/v1/db", tags=["Database CRUD"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Pydantic Schemas
class TicketCreate(BaseModel):
    service_type: str
    customer_name: str
    customer_phone: str
    branch_or_point: Optional[str] = None
    device_model: str
    serial_number: Optional[str] = None
    complaint: Optional[str] = None

class PaymentCreate(BaseModel):
    ticket_number: str
    service_type: str
    amount: float
    payment_method: Optional[str] = None
    branch_or_point: Optional[str] = None

class InventoryCreate(BaseModel):
    part_code: str
    part_name: str
    inventory_type: str
    category: Optional[str] = None
    branch: Optional[str] = None
    qty: int

# --- ENDPOINTS SERVICE TICKETS ---
@router.get("/tickets/{service_type}")
def get_tickets(service_type: str, db: Session = Depends(get_db)):
    return db.query(ServiceTicket).filter(ServiceTicket.service_type == service_type).order_by(desc(ServiceTicket.id)).all()

@router.post("/tickets/")
def create_ticket(ticket: TicketCreate, db: Session = Depends(get_db)):
    # 1. Tentukan Kode Service Center (JKT untuk pusat, CBG untuk cabang, PKP untuk pickup)
    prefix_code = "JKT"
    if ticket.service_type == "cabang":
        prefix_code = "CBG"
    elif ticket.service_type == "pickup":
        prefix_code = "PKP"

    year_suffix = datetime.utcnow().strftime("%y") # Contoh: '26' untuk tahun 2026
    prefix_full = f"{prefix_code}-{year_suffix}"

    # 2. Cari tiket terakhir di DB yang berawalan prefix tersebut untuk penomoran kontinu
    last_ticket = db.query(ServiceTicket).filter(
        ServiceTicket.ticket_number.like(f"{prefix_full}%")
    ).order_by(desc(ServiceTicket.id)).first()

    next_sequence = 1
    if last_ticket and last_ticket.ticket_number:
        try:
            # Mengambil 5 digit angka terakhir dari nomor tiket (contoh: JKT-2600001 -> 00001)
            raw_seq = last_ticket.ticket_number.split("-")[-1]
            numeric_seq = int(raw_seq[2:]) if len(raw_seq) > 2 else int(raw_seq)
            next_sequence = numeric_seq + 1
        except Exception:
            next_sequence = db.query(ServiceTicket).count() + 1

    # Format 5 digit nomor tiket (contoh: JKT-2600001)
    ticket_num = f"{prefix_full}{next_sequence:05d}"

    db_ticket = ServiceTicket(
        ticket_number=ticket_num,
        service_type=ticket.service_type,
        customer_name=ticket.customer_name,
        customer_phone=ticket.customer_phone,
        branch_or_point=ticket.branch_or_point,
        device_model=ticket.device_model,
        serial_number=ticket.serial_number,
        complaint=ticket.complaint,
        status="Diproses"
    )
    db.add(db_ticket)
    db.commit()
    db.refresh(db_ticket)
    return db_ticket

# --- ENDPOINTS PAYMENTS ---
@router.get("/payments/{service_type}")
def get_payments(service_type: str, db: Session = Depends(get_db)):
    return db.query(PaymentRecord).filter(PaymentRecord.service_type == service_type).order_by(desc(PaymentRecord.id)).all()

@router.post("/payments/")
def create_payment(payment: PaymentCreate, db: Session = Depends(get_db)):
    import random
    pay_code = f"PAY-{random.randint(100000, 999999)}"
    db_payment = PaymentRecord(
        ticket_number=payment.ticket_number,
        service_type=payment.service_type,
        amount=payment.amount,
        payment_method=payment.payment_method,
        payment_code=pay_code,
        branch_or_point=payment.branch_or_point,
        status="Lunas"
    )
    db.add(db_payment)
    db.commit()
    db.refresh(db_payment)
    return db_payment

# --- ENDPOINTS INVENTORY ---
@router.get("/inventory/{inventory_type}")
def get_inventory(inventory_type: str, db: Session = Depends(get_db)):
    return db.query(InventoryPart).filter(InventoryPart.inventory_type == inventory_type).order_by(desc(InventoryPart.id)).all()

@router.post("/inventory/")
def create_inventory(item: InventoryCreate, db: Session = Depends(get_db)):
    db_item = InventoryPart(
        part_code=item.part_code,
        part_name=item.part_name,
        inventory_type=item.inventory_type,
        category=item.category,
        branch=item.branch,
        qty=item.qty
    )
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item
