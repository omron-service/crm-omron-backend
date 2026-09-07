import logging
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, func
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel

from app.db.session import get_db
from app.core.deps import get_current_user, require_department_access, require_role
from app.models.schema import ServiceTicket, LocationCounter, User, DeviceModelCatalog, TicketSparePart

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/api/v1/db", tags=["Database CRUD"])
catalog_router = APIRouter(prefix="/api/v1/device-models", tags=["Katalog Model Alat"])

VALID_LOCATIONS = ("pusat", "cabang", "pickup")
PREFIX_BY_LOCATION = {"pusat": "JKT", "cabang": "CBG", "pickup": "PKP"}

# Daftar tetap sesuai spesifikasi form (dipakai backend untuk validasi ringan;
# tampilan dropdown tetap diatur di frontend)
PRODUCT_CATEGORIES = (
    "Arm BPM", "Wrist BPM", "BGM", "BCM", "DWS", "NEB-Comp", "NEB-Mesh",
    "NEB-Ultra", "Forehead Thermo", "Ear Thermo", "Pen Thermo", "MEDICAL",
    "TENS", "Others",
)
PRODUCT_ORIGINS = ("LEU", "EU-DRC", "AMS", "IDC", "APT/TKO", "CV/PT/RS", "ALPRO")
WARRANTY_STATUS_OPTIONS = ("Under Warranty", "Out of Warranty")
WARRANTY_PERIOD_OPTIONS = ("1", "2", "3", "4", "5", "6")
REMARKS_OPTIONS = (
    "Compliance Check/Sensor Check", "Repair", "Replace Product/Claim",
    "Unrepairable/Return to Customer", "Disagree with Service Fee", "No Response",
)
REPAIR_STATUS_OPTIONS = ("Diterima", "Diproses", "Selesai/Dikirim", "Selesai Diambil", "Menunggu Sparepart")


class SparePartLine(BaseModel):
    name: Optional[str] = None
    quantity: Optional[int] = None
    code: Optional[str] = None
    price: Optional[float] = None


class TicketCreate(BaseModel):
    service_type: str  # wajib "pusat", "cabang", atau "pickup"

    # 1-9: Data pelanggan & tanggal
    customer_name: str
    instansi_name: Optional[str] = None
    customer_phone: str
    customer_phone_2: Optional[str] = None
    customer_address: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None
    received_date: Optional[datetime] = None
    completed_date: Optional[datetime] = None

    # 10-13: Produk
    product_category: Optional[str] = None
    device_model: Optional[str] = None
    serial_number: Optional[str] = "-"
    accessories: Optional[str] = None

    # 14-15: Garansi
    warranty_status: Optional[str] = "Out of Warranty"
    warranty_period: Optional[str] = None

    # 16-20: Servis
    complaint: Optional[str] = "-"
    technician_analysis: Optional[str] = None
    symptom_code: Optional[str] = None
    leadtime_days: Optional[int] = 1
    notes: Optional[str] = None

    # 21-23
    product_origin: Optional[str] = None
    remarks: Optional[str] = None
    status: Optional[str] = "Diterima"

    # 24: Sparepart (maksimal 3 slot, boleh kosong semua)
    spareparts: Optional[List[SparePartLine]] = None

    # 25: Notifikasi
    notif_receipt_whatsapp: bool = False
    notif_receipt_email: bool = False
    notif_report_whatsapp: bool = False
    notif_report_email: bool = False

    branch_or_point: Optional[str] = "-"


class TicketPriceUpdate(BaseModel):
    ticket_number: str
    total_price: float


class DeviceModelCreateIn(BaseModel):
    category: str
    model_name: str


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
        query = db.query(ServiceTicket).options(joinedload(ServiceTicket.spareparts))
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
            .options(joinedload(ServiceTicket.spareparts))
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
            instansi_name=ticket.instansi_name,
            customer_phone=ticket.customer_phone,
            customer_phone_2=ticket.customer_phone_2,
            customer_address=ticket.customer_address,
            province=ticket.province,
            city=ticket.city,
            branch_or_point=ticket.branch_or_point or "-",
            received_date=ticket.received_date,
            completed_date=ticket.completed_date,
            product_category=ticket.product_category,
            device_model=ticket.device_model or "-",
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
            status=ticket.status or "Diterima",
            notif_receipt_whatsapp=ticket.notif_receipt_whatsapp,
            notif_receipt_email=ticket.notif_receipt_email,
            notif_report_whatsapp=ticket.notif_report_whatsapp,
            notif_report_email=ticket.notif_report_email,
        )
        db.add(db_ticket)
        db.flush()  # supaya db_ticket.id tersedia untuk baris sparepart

        # Simpan maksimal 3 baris sparepart (slot 1/2/3). Baris kosong total
        # (tidak diisi apapun) dilewati saja, tidak perlu disimpan.
        if ticket.spareparts:
            for idx, sp in enumerate(ticket.spareparts[:3], start=1):
                if not any([sp.name, sp.quantity, sp.code, sp.price]):
                    continue
                db.add(TicketSparePart(
                    ticket_id=db_ticket.id,
                    slot_no=idx,
                    name=sp.name,
                    quantity=sp.quantity,
                    code=sp.code,
                    price=sp.price,
                ))

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


# ---------------- Katalog Model Alat (dropdown berjenjang Kategori -> Model) ----------------

@catalog_router.get("/")
def list_device_models(
    category: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Dipakai frontend untuk mengisi dropdown Model Alat begitu Kategori Produk dipilih."""
    query = db.query(DeviceModelCatalog).filter(DeviceModelCatalog.is_active.is_(True))
    if category:
        query = query.filter(DeviceModelCatalog.category == category)
    return query.order_by(DeviceModelCatalog.category, DeviceModelCatalog.model_name).all()


@catalog_router.post("/", status_code=201)
def create_device_model(
    data: DeviceModelCreateIn,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("superadmin")),
):
    if data.category not in PRODUCT_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"category harus salah satu dari: {', '.join(PRODUCT_CATEGORIES)}.",
        )
    exists = (
        db.query(DeviceModelCatalog)
        .filter(DeviceModelCatalog.category == data.category, DeviceModelCatalog.model_name == data.model_name)
        .first()
    )
    if exists:
        if not exists.is_active:
            exists.is_active = True
            db.commit()
            db.refresh(exists)
            return exists
        raise HTTPException(status_code=400, detail="Model ini sudah ada di kategori tersebut.")

    entry = DeviceModelCatalog(category=data.category, model_name=data.model_name)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@catalog_router.delete("/{model_id}")
def deactivate_device_model(
    model_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("superadmin")),
):
    """Nonaktifkan (soft), bukan hapus - tiket lama yang masih menyebut model ini tetap valid."""
    entry = db.query(DeviceModelCatalog).filter(DeviceModelCatalog.id == model_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Model tidak ditemukan.")
    entry.is_active = False
    db.commit()
    return {"status": "success"}
