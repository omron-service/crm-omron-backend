import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, func
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.db.session import get_db
from app.core.deps import get_current_user, require_department_access
from app.models.schema import ServiceTicket, LocationCounter, User

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/api/v1/db", tags=["Database CRUD"])

VALID_LOCATIONS = ("pusat", "cabang", "pickup")
PREFIX_BY_LOCATION = {"pusat": "JKT", "cabang": "CBG", "pickup": "PKP"}


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


def _next_ticket_number(db: Session, srv_type: str) -> str:
    """
    Nomor urut per-lokasi diambil dari tabel counter khusus dengan row lock
    (SELECT ... FOR UPDATE), bukan dari COUNT(*) tabel tiket. Ini mencegah dua
    request yang masuk bersamaan di lokasi yang sama mendapat nomor yang sama.
    """
    counter = (
        db.query(LocationCounter)
        .filter(LocationCounter.service_type == srv_type)
        .with_for_update()
        .first()
    )
    if counter is None:
        counter = LocationCounter(service_type=srv_type, last_number=0)
        db.add(counter)
        db.flush()

    counter.last_number += 1
    year_suffix = datetime.utcnow().strftime("%y")
    prefix_full = f"{PREFIX_BY_LOCATION[srv_type]}-{year_suffix}"
    return f"{prefix_full}{counter.last_number:05d}"


@router.get("/all-tickets")
def get_all_tickets(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        query = db.query(ServiceTicket)
        # Staff hanya melihat data departemennya sendiri. Superadmin melihat semua.
        if current_user.role != "superadmin":
            query = query.filter(func.lower(ServiceTicket.service_type) == current_user.department)
        return query.order_by(desc(ServiceTicket.id)).all()
    except Exception as e:
        logger.error(f"Error fetching all tickets: {str(e)}")
        return []


@router.get("/tickets/{service_type}")
def get_tickets_by_location(
    service_type: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    srv = service_type.lower().strip()
    require_department_access(current_user, srv)
    try:
        # Isolasi Murni: hanya mengambil data yang match persis dengan lokasi tersebut.
        tickets = (
            db.query(ServiceTicket)
            .filter(func.lower(ServiceTicket.service_type) == srv)
            .order_by(desc(ServiceTicket.id))
            .all()
        )
        return tickets
    except Exception as e:
        logger.error(f"Error fetching tickets for {service_type}: {str(e)}")
        return []


@router.post("/tickets/")
def create_ticket(
    ticket: TicketCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    srv_type = ticket.service_type.lower().strip()
    if srv_type not in VALID_LOCATIONS:
        raise HTTPException(
            status_code=400,
            detail=f"service_type harus salah satu dari: {', '.join(VALID_LOCATIONS)}.",
        )

    # PENTING: cek izin lokasi SEBELUM menyimpan apapun. Ini mencegah staff
    # cabang membuat tiket di data pusat (atau sebaliknya) walau mereka
    # memanggil API ini langsung (mis. lewat Postman), bukan lewat UI.
    require_department_access(current_user, srv_type)

    try:
        ticket_num = _next_ticket_number(db, srv_type)

        # SATU request = SATU baris tiket, dengan SATU service_type yang tetap.
        # Tidak ada logika di endpoint ini yang menulis ke lokasi lain.
        db_ticket = ServiceTicket(
            ticket_number=ticket_num,
            service_type=srv_type,
            created_by_location=f"LOCATION_{srv_type.upper()}",
            created_by_user_id=current_user.id,
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
            status=ticket.status or "Diproses",
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
def update_ticket_price(
    data: TicketPriceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ticket = db.query(ServiceTicket).filter(ServiceTicket.ticket_number == data.ticket_number).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Tiket tidak ditemukan")

    require_department_access(current_user, ticket.service_type)

    ticket.total_price = data.total_price
    db.commit()
    return {"status": "success", "ticket_number": ticket.ticket_number, "total_price": ticket.total_price}


# CATATAN: sengaja TIDAK ADA endpoint DELETE untuk ServiceTicket di file ini.
# Kalau ke depan butuh "membatalkan" tiket, gunakan field `status`
# (mis. status="Dibatalkan"), JANGAN hapus baris datanya.
