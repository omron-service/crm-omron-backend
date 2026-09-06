import os
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import create_engine, desc, func
from sqlalchemy.orm import sessionmaker, Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from app.models.schema import Base, ServiceTicket

logger = logging.getLogger("uvicorn.error")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local_crm.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if "sqlite" in DATABASE_URL:
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=10,
        max_overflow=20
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

try:
    Base.metadata.create_all(bind=engine)
except Exception as e:
    logger.error(f"Error saat inisialisasi skema tabel: {str(e)}")

router = APIRouter(prefix="/api/v1/db", tags=["Database CRUD"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class TicketCreate(BaseModel):
    service_type: str  # wajib "pusat", "cabang", atau "pickup"
    customer_name: str
    customer_phone: str
    customer_phone_2: Optional[str] = None
    customer_address: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None
    branch_or_point: Optional[str] = "-"
    
    product_category: Optional[str] = None
    device_model: Optional[str] = "HEM-7120"
    serial_number: Optional[str] = "-"
    accessories: Optional[str] = None
    warranty_status: Optional[str] = "Out of Warranty"
    warranty_period: Optional[str] = None
    product_origin: Optional[str] = None

    complaint: Optional[str] = "-"
    technician_analysis: Optional[str] = None
    symptom_code: Optional[str] = None
    leadtime_days: Optional[int] = 1
    notes: Optional[str] = None
    remarks: Optional[str] = None
    status: Optional[str] = "Diproses"

class TicketPriceUpdate(BaseModel):
    ticket_number: str
    total_price: float

@router.get("/all-tickets")
def get_all_tickets(db: Session = Depends(get_db)):
    try:
        return db.query(ServiceTicket).order_by(desc(ServiceTicket.id)).all()
    except Exception as e:
        logger.error(f"Error fetching all tickets: {str(e)}")
        return []

@router.get("/tickets/{service_type}")
def get_tickets_by_location(service_type: str, db: Session = Depends(get_db)):
    srv = service_type.lower().strip()
    try:
        # Isolasi Murni: Hanya mengambil data yang match persis dengan lokasi tersebut
        tickets = db.query(ServiceTicket).filter(func.lower(ServiceTicket.service_type) == srv).order_by(desc(ServiceTicket.id)).all()
        return tickets
    except Exception as e:
        logger.error(f"Error fetching tickets for {service_type}: {str(e)}")
        return []

@router.post("/tickets/")
def create_ticket(ticket: TicketCreate, db: Session = Depends(get_db)):
    try:
        srv_type = ticket.service_type.lower().strip()
        if srv_type not in ["pusat", "cabang", "pickup"]:
            srv_type = "pusat"

        # Prefix otomatis sesuai jenis lokasi input
        prefix_code = "JKT"
        if srv_type == "cabang":
            prefix_code = "CBG"
        elif srv_type == "pickup":
            prefix_code = "PKP"

        year_suffix = datetime.utcnow().strftime("%y")
        prefix_full = f"{prefix_code}-{year_suffix}"

        # Hitung urutan khusus di lokasi yang sama
        count_specific = db.query(ServiceTicket).filter(func.lower(ServiceTicket.service_type) == srv_type).count() + 1
        ticket_num = f"{prefix_full}{count_specific:05d}"

        db_ticket = ServiceTicket(
            ticket_number=ticket_num,
            service_type=srv_type,
            created_by_location=f"LOCATION_{srv_type.upper()}",
            customer_name=ticket.customer_name,
            customer_phone=ticket.customer_phone,
            customer_phone_2=ticket.customer_phone_2,
            customer_address=ticket.customer_address,
            province=ticket.province,
            city=ticket.city,
            branch_or_point=ticket.branch_or_point or "-",
            product_category=ticket.product_category,
            device_model=ticket.device_model or "HEM-7120",
            serial_number=ticket.serial_number or "-",
            accessories=ticket.accessories,
            warranty_status=ticket.warranty_status or "Out of Warranty",
            warranty_period=ticket.warranty_period,
            product_origin=ticket.product_origin,
            complaint=ticket.complaint or "-",
            technician_analysis=ticket.technician_analysis,
            symptom_code=ticket.symptom_code,
            leadtime_days=ticket.leadtime_days or 1,
            notes=ticket.notes,
            remarks=ticket.remarks,
            status=ticket.status or "Diproses"
        )
        db.add(db_ticket)
        db.commit()
        db.refresh(db_ticket)
        return db_ticket
    except Exception as e:
        db.rollback()
        logger.error(f"Error saving ticket: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Gagal simpan ke DB: {str(e)}")

@router.post("/tickets/update-price")
def update_ticket_price(data: TicketPriceUpdate, db: Session = Depends(get_db)):
    ticket = db.query(ServiceTicket).filter(ServiceTicket.ticket_number == data.ticket_number).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Tiket tidak ditemukan")
    ticket.total_price = data.total_price
    db.commit()
    return {"status": "success", "ticket_number": ticket.ticket_number, "total_price": ticket.total_price}
