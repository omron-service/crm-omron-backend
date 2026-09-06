import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import create_engine, desc
from sqlalchemy.orm import sessionmaker, Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from app.models.schema import Base, ServiceTicket

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local_test.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
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
    service_type: Optional[str] = "pusat"
    customer_name: str
    customer_phone: str
    branch_or_point: Optional[str] = "-"
    device_model: Optional[str] = "HEM-7120"
    serial_number: Optional[str] = "-"
    warranty_status: Optional[str] = "Out of Warranty"
    complaint: Optional[str] = "-"

class TicketPriceUpdate(BaseModel):
    ticket_number: str
    total_price: float

@router.get("/all-tickets")
def get_all_tickets(db: Session = Depends(get_db)):
    try:
        return db.query(ServiceTicket).order_by(desc(ServiceTicket.id)).all()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database Query Error: {str(e)}")

@router.get("/tickets/{service_type}")
def get_tickets(service_type: str, db: Session = Depends(get_db)):
    try:
        tickets = db.query(ServiceTicket).filter(ServiceTicket.service_type == service_type).order_by(desc(ServiceTicket.id)).all()
        if not tickets:
            return db.query(ServiceTicket).order_by(desc(ServiceTicket.id)).all()
        return tickets
    except Exception as e:
        return db.query(ServiceTicket).order_by(desc(ServiceTicket.id)).all()

@router.post("/tickets/")
def create_ticket(ticket: TicketCreate, db: Session = Depends(get_db)):
    try:
        srv_type = ticket.service_type or "pusat"
        prefix_code = "JKT"
        if srv_type == "cabang":
            prefix_code = "CBG"
        elif srv_type == "pickup":
            prefix_code = "PKP"

        year_suffix = datetime.utcnow().strftime("%y")
        prefix_full = f"{prefix_code}-{year_suffix}"

        last_ticket = db.query(ServiceTicket).order_by(desc(ServiceTicket.id)).first()

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
            service_type=srv_type,
            customer_name=ticket.customer_name,
            customer_phone=ticket.customer_phone,
            branch_or_point=ticket.branch_or_point or "-",
            device_model=ticket.device_model or "HEM-7120",
            serial_number=ticket.serial_number or "-",
            warranty_status=ticket.warranty_status or "Out of Warranty",
            complaint=ticket.complaint or "-",
            status="Diproses"
        )
        db.add(db_ticket)
        db.commit()
        db.refresh(db_ticket)
        return db_ticket
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Gagal Simpan Tiket ke DB: {str(e)}")

@router.post("/tickets/update-price")
def update_ticket_price(data: TicketPriceUpdate, db: Session = Depends(get_db)):
    ticket = db.query(ServiceTicket).filter(ServiceTicket.ticket_number == data.ticket_number).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Tiket tidak ditemukan")
    ticket.total_price = data.total_price
    db.commit()
    return {"status": "success", "ticket_number": ticket.ticket_number, "total_price": ticket.total_price}
