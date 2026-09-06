import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.schema import Base, InventoryPart, PaymentRecord, ServiceTicket

# Database URL dari Environment Variable Railway / Neon.tech
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local_test.db")

# Fix prefix postgres:// jika ada dari Heroku/Neon
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Inisialisasi Tabel di DB Neon.tech
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
    branch_or_point: str | None = None
    device_model: str
    serial_number: str | None = None
    complaint: str | None = None


class PaymentCreate(BaseModel):
    ticket_number: str
    service_type: str
    amount: float
    payment_method: str | None = None
    branch_or_point: str | None = None


class InventoryCreate(BaseModel):
    part_code: str
    part_name: str
    inventory_type: str
    category: str | None = None
    branch: str | None = None
    qty: int


# --- ENDPOINTS SERVICE TICKETS ---
@router.get("/tickets/{service_type}")
def get_tickets(service_type: str, db: Session = Depends(get_db)):
    return (
        db.query(ServiceTicket)
        .filter(ServiceTicket.service_type == service_type)
        .all()
    )


@router.post("/tickets/")
def create_ticket(ticket: TicketCreate, db: Session = Depends(get_db)):
    import random

    ticket_num = f"TCK-{random.randint(100000, 999999)}"
    db_ticket = ServiceTicket(
        ticket_number=ticket_num,
        service_type=ticket.service_type,
        customer_name=ticket.customer_name,
        customer_phone=ticket.customer_phone,
        branch_or_point=ticket.branch_or_point,
        device_model=ticket.device_model,
        serial_number=ticket.serial_number,
        complaint=ticket.complaint,
        status="Diterima",
    )
    db.add(db_ticket)
    db.commit()
    db.refresh(db_ticket)
    return db_ticket


# --- ENDPOINTS PAYMENTS ---
@router.get("/payments/{service_type}")
def get_payments(service_type: str, db: Session = Depends(get_db)):
    return (
        db.query(PaymentRecord)
        .filter(PaymentRecord.service_type == service_type)
        .all()
    )


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
        status="Lunas",
    )
    db.add(db_payment)
    db.commit()
    db.refresh(db_payment)
    return db_payment


# --- ENDPOINTS INVENTORY ---
@router.get("/inventory/{inventory_type}")
def get_inventory(inventory_type: str, db: Session = Depends(get_db)):
    return (
        db.query(InventoryPart)
        .filter(InventoryPart.inventory_type == inventory_type)
        .all()
    )


@router.post("/inventory/")
def create_inventory(item: InventoryCreate, db: Session = Depends(get_db)):
    db_item = InventoryPart(
        part_code=item.part_code,
        part_name=item.part_name,
        inventory_type=item.inventory_type,
        category=item.category,
        branch=item.branch,
        qty=item.qty,
    )
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item
