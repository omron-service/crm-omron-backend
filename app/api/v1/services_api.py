import logging
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, func
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel, Field

from app.db.session import get_db
from app.core.deps import get_current_user, require_department_access, require_role
from app.models.schema import (
    ServiceTicket, LocationCounter, User, DeviceModelCatalog, TicketSparePart,
    PartCatalog, PartStock, PartStockMovement,
)
from app.services.service_report_template import generate_ticket_service_report

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/api/v1/db", tags=["Database CRUD"])
catalog_router = APIRouter(prefix="/api/v1/device-models", tags=["Katalog Model Alat"])

VALID_LOCATIONS = ("pusat", "cabang", "pickup")
PREFIX_BY_LOCATION = {"pusat": "JKT", "cabang": "CBG", "pickup": "PKP"}

# Daftar tetap sesuai spesifikasi form (dipakai backend untuk validasi ringan;
# tampilan dropdown tetap diatur di frontend). Diurutkan A-Z, KECUALI "Others"
# sengaja selalu diletakkan di paling akhir.
PRODUCT_CATEGORIES = (
    "Arm BPM", "BCM", "BGM", "Comp-NEB", "DWS", "Ear Thermo", "Forehead Thermo",
    "MEDICAL", "Mesh-NEB", "Pen Thermo", "TENS", "Ultra-NEB", "Wrist BPM",
    "Others",
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
    # gt=0: sengaja tidak boleh nol/negatif - kalau boleh negatif, nilai ini
    # bisa dipakai memanipulasi stok Pusat supaya BERTAMBAH (lihat
    # _apply_pusat_stock_change: stock.quantity -= signed_quantity).
    quantity: Optional[int] = Field(default=None, gt=0)
    code: Optional[str] = None
    price: Optional[float] = Field(default=None, ge=0)


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


class TicketUpdate(BaseModel):
    """
    Sama seperti TicketCreate, TAPI tanpa `service_type` - lokasi tiket (Pusat/
    Cabang/Pickup Center) permanen sejak dibuat dan tidak bisa diubah lewat edit.
    """
    customer_name: str
    instansi_name: Optional[str] = None
    customer_phone: str
    customer_phone_2: Optional[str] = None
    customer_address: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None
    received_date: Optional[datetime] = None
    completed_date: Optional[datetime] = None

    product_category: Optional[str] = None
    device_model: Optional[str] = None
    serial_number: Optional[str] = "-"
    accessories: Optional[str] = None

    warranty_status: Optional[str] = "Out of Warranty"
    warranty_period: Optional[str] = None

    complaint: Optional[str] = "-"
    technician_analysis: Optional[str] = None
    symptom_code: Optional[str] = None
    leadtime_days: Optional[int] = 1
    notes: Optional[str] = None

    product_origin: Optional[str] = None
    remarks: Optional[str] = None
    status: Optional[str] = "Diterima"

    spareparts: Optional[List[SparePartLine]] = None

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


def _apply_pusat_stock_change(
    db: Session, code: str, name: Optional[str], signed_quantity: int,
    ticket_number: str, user_id: Optional[int],
):
    """
    ATURAN BISNIS: Pickup Center adalah drop-off point untuk tim Pusat (bukan
    lokasi inventory tersendiri). Jadi setiap sparepart yang dipakai untuk
    tiket service_type='pickup' memotong stok PUSAT.

    signed_quantity POSITIF = dipakai (stok Pusat berkurang), dicatat sebagai
    movement_type='terpakai_pusat' - ikut terhitung di laporan "Total Terpakai
    di Pusat".
    signed_quantity NEGATIF = dikembalikan (stok Pusat bertambah lagi) - dipakai
    saat tiket pickup DIEDIT dan jumlah/kode sparepart-nya dikurangi/dihapus.
    Dicatat sebagai movement_type='koreksi_edit_tiket_pickup' (jenis terpisah,
    supaya TIDAK ikut menggelembungkan laporan "Total Terpakai").

    Sengaja TIDAK memblokir kalau stok Pusat tidak mencukupi - servis ke
    pelanggan tetap harus tercatat; kalau stok jadi minus, itu jadi sinyal
    untuk restock, dicatat jelas di kolom catatan movement-nya.
    """
    if not code:
        return
    code = code.strip()
    if not code or signed_quantity == 0:
        return

    part = db.query(PartCatalog).filter(PartCatalog.code == code).first()
    if part is None:
        part = PartCatalog(code=code, name=name)
        db.add(part)
        db.flush()
    elif name and part.name != name:
        part.name = name

    stock = (
        db.query(PartStock)
        .filter(PartStock.part_id == part.id, PartStock.location == "pusat")
        .with_for_update()
        .first()
    )
    if stock is None:
        stock = PartStock(part_id=part.id, location="pusat", quantity=0)
        db.add(stock)
        db.flush()

    stock.quantity -= signed_quantity

    if signed_quantity > 0:
        movement_type = "terpakai_pusat"
        note = f"Otomatis: dipakai untuk tiket Pickup Center {ticket_number}"
        if stock.quantity < 0:
            note += f" (PERINGATAN: stok Pusat kurang {-stock.quantity})"
    else:
        movement_type = "koreksi_edit_tiket_pickup"
        note = f"Otomatis: dikembalikan krn edit tiket Pickup Center {ticket_number}"

    db.add(PartStockMovement(
        part_id=part.id,
        location="pusat",
        movement_type=movement_type,
        quantity=abs(signed_quantity),
        note=note,
        performed_by_user_id=user_id,
    ))


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

                # Pickup Center = drop-off point utk tim Pusat, jadi sparepart yang
                # dipakai di tiket pickup memotong stok PUSAT (bukan stok tersendiri).
                if srv_type == "pickup" and sp.code and sp.quantity:
                    _apply_pusat_stock_change(
                        db, sp.code, sp.name, sp.quantity, ticket_num, current_user.id
                    )

        db.commit()
        db.refresh(db_ticket)
        return db_ticket
    except Exception as e:
        db.rollback()
        logger.error(f"Error saving ticket: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Gagal simpan ke DB: {str(e)}")


@router.get("/tickets/detail/{ticket_number}")
def get_ticket_detail(
    ticket_number: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Dipakai frontend untuk mengisi form Edit Tiket begitu nomor tiket diklik."""
    ticket = (
        db.query(ServiceTicket)
        .options(joinedload(ServiceTicket.spareparts))
        .filter(ServiceTicket.ticket_number == ticket_number.strip())
        .first()
    )
    if not ticket:
        raise HTTPException(status_code=404, detail="Tiket tidak ditemukan.")
    require_department_access(current_user, ticket.service_type)
    return ticket


@router.put("/tickets/{ticket_number}")
def update_ticket(
    ticket_number: str,
    data: TicketUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update tiket yang SUDAH ADA. `service_type` (lokasi) TIDAK bisa diubah -
    permanen sejak tiket dibuat. Staff hanya bisa edit tiket di departemennya
    sendiri (superadmin bebas semua lokasi), sama seperti aturan create/lihat.
    """
    ticket = (
        db.query(ServiceTicket)
        .options(joinedload(ServiceTicket.spareparts))
        .filter(ServiceTicket.ticket_number == ticket_number.strip())
        .first()
    )
    if not ticket:
        raise HTTPException(status_code=404, detail="Tiket tidak ditemukan.")

    require_department_access(current_user, ticket.service_type)

    try:
        ticket.customer_name = data.customer_name
        ticket.instansi_name = data.instansi_name
        ticket.customer_phone = data.customer_phone
        ticket.customer_phone_2 = data.customer_phone_2
        ticket.customer_address = data.customer_address
        ticket.province = data.province
        ticket.city = data.city
        ticket.branch_or_point = data.branch_or_point or "-"
        ticket.received_date = data.received_date
        ticket.completed_date = data.completed_date
        ticket.product_category = data.product_category
        ticket.device_model = data.device_model or "-"
        ticket.serial_number = data.serial_number or "-"
        ticket.accessories = data.accessories
        ticket.warranty_status = data.warranty_status or "Out of Warranty"
        ticket.warranty_period = data.warranty_period
        ticket.product_origin = data.product_origin
        ticket.complaint = data.complaint or "-"
        ticket.technician_analysis = data.technician_analysis
        ticket.symptom_code = data.symptom_code
        ticket.leadtime_days = data.leadtime_days or 1
        ticket.notes = data.notes
        ticket.remarks = data.remarks
        ticket.status = data.status or "Diterima"
        ticket.notif_receipt_whatsapp = data.notif_receipt_whatsapp
        ticket.notif_receipt_email = data.notif_receipt_email
        ticket.notif_report_whatsapp = data.notif_report_whatsapp
        ticket.notif_report_email = data.notif_report_email

        # ---- Sparepart: upsert per slot (1-3). Baris TIDAK PERNAH dihapus dari
        # tabel - kalau slot dikosongkan, field-nya di-null-kan saja, row-nya tetap
        # ada. Kalau tiket ini Pickup Center, stok Pusat disesuaikan: jumlah lama
        # dikembalikan dulu, baru jumlah baru dipotong - supaya stok selalu akurat
        # walau kode/jumlah sparepart-nya diganti-ganti lewat edit berkali-kali. ----
        existing_by_slot = {sp.slot_no: sp for sp in ticket.spareparts}
        incoming = list(data.spareparts or [])[:3]
        while len(incoming) < 3:
            incoming.append(SparePartLine())

        for idx, new_line in enumerate(incoming, start=1):
            old = existing_by_slot.get(idx)
            old_code = old.code if old else None
            old_qty = (old.quantity or 0) if old else 0
            has_new_data = any([new_line.name, new_line.quantity, new_line.code, new_line.price])

            if ticket.service_type == "pickup":
                if old_code and old_qty:
                    _apply_pusat_stock_change(
                        db, old_code, None, -old_qty, ticket.ticket_number, current_user.id
                    )
                if has_new_data and new_line.code and new_line.quantity:
                    _apply_pusat_stock_change(
                        db, new_line.code, new_line.name, new_line.quantity,
                        ticket.ticket_number, current_user.id,
                    )

            if has_new_data:
                if old:
                    old.name = new_line.name
                    old.quantity = new_line.quantity
                    old.code = new_line.code
                    old.price = new_line.price
                else:
                    db.add(TicketSparePart(
                        ticket_id=ticket.id, slot_no=idx,
                        name=new_line.name, quantity=new_line.quantity,
                        code=new_line.code, price=new_line.price,
                    ))
            elif old:
                old.name = None
                old.quantity = None
                old.code = None
                old.price = None

        db.commit()
        db.refresh(ticket)
        return ticket
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating ticket: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Gagal update tiket: {str(e)}")


@router.get("/tickets/{ticket_number}/service-report")
def download_ticket_service_report(
    ticket_number: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Download 'FORMULIR PERBAIKAN' (Service Report) untuk satu tiket, format
    meniru template resmi Omron."""
    ticket = (
        db.query(ServiceTicket)
        .options(joinedload(ServiceTicket.spareparts))
        .filter(ServiceTicket.ticket_number == ticket_number.strip())
        .first()
    )
    if not ticket:
        raise HTTPException(status_code=404, detail="Tiket tidak ditemukan.")
    require_department_access(current_user, ticket.service_type)

    excel_file = generate_ticket_service_report(ticket, ticket.spareparts)
    filename = f"ServiceReport-OEC-{ticket.ticket_number}.xlsx"
    return StreamingResponse(
        excel_file,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


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
    """Dipakai frontend /admin untuk mengisi dropdown Model Alat begitu Kategori Produk dipilih."""
    query = db.query(DeviceModelCatalog).filter(DeviceModelCatalog.is_active.is_(True))
    if category:
        query = query.filter(DeviceModelCatalog.category == category)
    return query.order_by(DeviceModelCatalog.category, DeviceModelCatalog.model_name).all()


@catalog_router.get("/public")
def list_device_models_public(category: Optional[str] = None, db: Session = Depends(get_db)):
    """
    Versi PUBLIK (tanpa login) dari endpoint di atas - dipakai khusus oleh form
    drop-off Pickup Center di /pickup-intake, karena form itu memang tidak
    mewajibkan login (diisi tim lapangan/kurir tanpa akun sistem).
    """
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


@catalog_router.post("/bulk-upload")
def bulk_upload_device_models(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("superadmin")),
):
    """
    Upload katalog Model Alat dari file Excel (.xlsx), format 2 kolom: Model Alat
    dan Produk Kategori (urutan kolom terdeteksi otomatis dari isi datanya, bukan
    dari teks header - supaya tetap benar walau header di file kebalik-balik).

    ATURAN PENTING (sesuai permintaan): data yang SUDAH ADA sebelumnya TIDAK PERNAH
    dihapus/ditimpa isinya. Kombinasi (kategori, model) yang:
    - BELUM ADA di database -> ditambahkan sebagai entri baru.
    - SUDAH ADA dan aktif    -> dilewati saja (tidak ada yang perlu diubah).
    - SUDAH ADA tapi nonaktif -> diaktifkan kembali (satu-satunya bentuk "update").
    Kombinasi (kategori, model) lain yang SUDAH ADA di database tapi TIDAK
    disebutkan di file yang diupload TIDAK IKUT DINONAKTIFKAN/DIHAPUS - upload ini
    murni menambah, tidak pernah mengurangi.
    """
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="File harus berformat .xlsx (Excel).")

    try:
        import openpyxl
        from io import BytesIO

        content = file.file.read()
        wb = openpyxl.load_workbook(BytesIO(content), data_only=True)
        ws = wb.active
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Gagal membaca file Excel: {str(e)}")

    valid_categories_lower = {c.lower(): c for c in PRODUCT_CATEGORIES}

    created, reactivated, skipped_existing = 0, 0, 0
    errors = []

    rows = list(ws.iter_rows(min_row=1, values_only=True))
    if not rows:
        raise HTTPException(status_code=400, detail="File Excel kosong.")

    # Deteksi baris pertama sebagai header (dilewati) kalau salah satu selnya
    # cocok dengan kata "kategori" atau "model" (tidak peduli urutan/besar-kecil huruf).
    start_row = 0
    header_probe = " ".join(str(v).lower() for v in rows[0] if v)
    if "kategori" in header_probe or "model" in header_probe:
        start_row = 1

    for idx, row in enumerate(rows[start_row:], start=start_row + 1):
        if not row or len(row) < 2:
            continue
        col_a = str(row[0]).strip() if row[0] is not None else ""
        col_b = str(row[1]).strip() if row[1] is not None else ""
        if not col_a and not col_b:
            continue  # baris kosong, lewati

        # Deteksi otomatis mana kolom Model dan mana kolom Kategori: kolom yang
        # isinya cocok (case-insensitive) dengan salah satu PRODUCT_CATEGORIES
        # dianggap sebagai kolom Kategori, sisanya jadi kolom Model.
        if col_b.lower() in valid_categories_lower:
            model_name, category = col_a, valid_categories_lower[col_b.lower()]
        elif col_a.lower() in valid_categories_lower:
            model_name, category = col_b, valid_categories_lower[col_a.lower()]
        else:
            errors.append({
                "row": idx,
                "reason": f"Kategori tidak dikenali (harus salah satu dari: {', '.join(PRODUCT_CATEGORIES)})",
                "data": f"{col_a} | {col_b}",
            })
            continue

        if not model_name:
            errors.append({"row": idx, "reason": "Nama model kosong", "data": f"{col_a} | {col_b}"})
            continue

        existing = (
            db.query(DeviceModelCatalog)
            .filter(DeviceModelCatalog.category == category, DeviceModelCatalog.model_name == model_name)
            .first()
        )
        if existing:
            if not existing.is_active:
                existing.is_active = True
                reactivated += 1
            else:
                skipped_existing += 1
        else:
            db.add(DeviceModelCatalog(category=category, model_name=model_name))
            created += 1

    db.commit()

    return {
        "status": "success",
        "total_baris_diproses": len(rows) - start_row,
        "ditambahkan_baru": created,
        "diaktifkan_kembali": reactivated,
        "sudah_ada_dilewati": skipped_existing,
        "gagal": len(errors),
        "detail_gagal": errors[:50],  # batasi supaya respons tidak raksasa
    }
