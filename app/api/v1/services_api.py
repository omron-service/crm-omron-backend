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

Base.metadata.create_all(bind=engine)

router = APIRouter(prefix="/api/v1/db", tags=["Database CRUD"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class TicketCreate(BaseModel):
    service_type: str
    customer_name: str
    customer_phone: str
    branch_or_point: Optional[str] = None
    device_model: str
    serial_number: Optional[str] = None
    warranty_status: Optional[str] = "Out of Warranty"
    complaint: Optional[str] = None

class TicketPriceUpdate(BaseModel):
    ticket_number: str
    total_price: float

# --- ENDPOINTS SERVICE TICKETS ---
@router.get("/tickets/{service_type}")
def get_tickets(service_type: str, db: Session = Depends(get_db)):
    return db.query(ServiceTicket).filter(ServiceTicket.service_type == service_type).order_by(desc(ServiceTicket.id)).all()

@router.get("/all-tickets")
def get_all_tickets(db: Session = Depends(get_db)):
    return db.query(ServiceTicket).order_by(desc(ServiceTicket.id)).all()

@router.post("/tickets/")
def create_ticket(ticket: TicketCreate, db: Session = Depends(get_db)):
    prefix_code = "JKT"
    if ticket.service_type == "cabang":
        prefix_code = "CBG"
    elif ticket.service_type == "pickup":
        prefix_code = "PKP"

    year_suffix = datetime.utcnow().strftime("%y")
    prefix_full = f"{prefix_code}-{year_suffix}"

    last_ticket = db.query(ServiceTicket).filter(
        ServiceTicket.ticket_number.like(f"{prefix_full}%")
    ).order_by(desc(ServiceTicket.id)).first()

    next_sequence = 1
    if last_ticket and last_ticket.ticket_number:
        try:
            raw_seq = last_ticket.ticket_number.split("-")[-1]
            numeric_seq = int(raw_seq[2:]) if len(raw_seq) > 2 else int(raw_seq)
            next_sequence = numeric_seq + 1
        except Exception:
            next_sequence = db.query(ServiceTicket).count() + 1

    ticket_num = f"{prefix_full}{next_sequence:05d}"

    db_ticket = ServiceTicket(
        ticket_number=ticket_num,
        service_type=ticket.service_type,
        customer_name=ticket.customer_name,
        customer_phone=ticket.customer_phone,
        branch_or_point=ticket.branch_or_point,
        device_model=ticket.device_model,
        serial_number=ticket.serial_number,
        warranty_status=ticket.warranty_status or "Out of Warranty",
        complaint=ticket.complaint,
        status="Diproses"
    )
    db.add(db_ticket)
    db.commit()
    db.refresh(db_ticket)
    return db_ticket

@router.post("/tickets/update-price")
def update_ticket_price(data: TicketPriceUpdate, db: Session = Depends(get_db)):
    ticket = db.query(ServiceTicket).filter(ServiceTicket.ticket_number == data.ticket_number).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Tiket tidak ditemukan")
    ticket.total_price = data.total_price
    db.commit()
    return {"status": "success", "ticket_number": ticket.ticket_number, "total_price": ticket.total_price}
