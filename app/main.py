from datetime import datetime, timedelta
from typing import Optional
import os

from fastapi import FastAPI, Request, HTTPException, Depends, Path, Query
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.api.v1 import mutations, services_api, auth as auth_api, inventory_parts, locations, ged_integration
from app.api.v1.services_api import _next_ticket_number
from app.pages import admin_dashboard, pickup_intake, track, receipt
from app.services.shipping_status import initial_shipping_status_for_new_ticket, compute_track_display
from app.db.session import get_db, init_db, get_public_db
from app.core.deps import get_current_user, require_department_access
from app.core.limiter import limiter
from app.models.schema import ServiceTicket, User
from app.services.excel_export import generate_service_report_excel, generate_payment_status_excel
from pydantic import BaseModel, Field

import logging

logger = logging.getLogger("uvicorn.error")
app = FastAPI(title="CRM Omron Healthcare API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """
    Header keamanan HTTP dasar untuk semua response:
    - X-Content-Type-Options: browser tidak menebak-nebak tipe konten (mencegah
      trik MIME-sniffing yang bisa dipakai untuk serangan XSS).
    - X-Frame-Options: halaman ini tidak bisa ditaruh di <iframe> situs lain
      (mencegah clickjacking terhadap /admin).
    - Referrer-Policy: URL lengkap (yang mungkin mengandung info sensitif di
      query string) tidak ikut terkirim ke situs lain saat user klik link keluar.
    """
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.on_event("startup")
async def _on_startup():
    # Aman dipanggil berkali-kali: hanya membuat tabel yang belum ada,
    # TIDAK PERNAH menghapus/mengubah tabel atau data yang sudah ada.
    init_db()

    # Jalankan penjadwal auto-transisi "Menunggu Kurir" di background -
    # TIDAK memblokir startup aplikasi (create_task, bukan await langsung).
    import asyncio
    from app.services.scheduler import shipping_status_scheduler_loop
    asyncio.create_task(shipping_status_scheduler_loop())


app.include_router(auth_api.router)
app.include_router(auth_api.admin_users_router)
app.include_router(mutations.router)
app.include_router(services_api.router)
app.include_router(services_api.catalog_router)
app.include_router(inventory_parts.router)
app.include_router(locations.branch_router)
app.include_router(locations.pickup_router)
app.include_router(admin_dashboard.router)
app.include_router(pickup_intake.router)
app.include_router(track.router)
app.include_router(receipt.router)
app.include_router(ged_integration.router)


@app.get("/")
def root():
    return {"status": "online", "system": "CRM Omron Healthcare API"}


def verify_turnstile_or_raise(token: Optional[str], request: Request):
    """
    Verifikasi CAPTCHA Cloudflare Turnstile (Opsi 4 pengamanan) - dipakai di
    KEDUA endpoint publik (/pickup-intake, /track).

    SENGAJA tidak wajib: kalau environment variable TURNSTILE_SECRET_KEY
    belum diisi di server, fungsi ini langsung lolos tanpa verifikasi apa pun
    (supaya tidak merusak endpoint yang sudah jalan sebelum Anda sempat
    setup akun Turnstile). Begitu TURNSTILE_SECRET_KEY diisi, verifikasi
    CAPTCHA jadi WAJIB - request tanpa token yang valid akan ditolak.
    """
    import os
    import requests as requests_lib

    secret_key = os.environ.get("TURNSTILE_SECRET_KEY", "").strip()
    if not secret_key:
        return  # Turnstile belum diaktifkan di server ini - lewati saja

    if not token:
        raise HTTPException(status_code=400, detail="Verifikasi CAPTCHA wajib diisi.")

    try:
        resp = requests_lib.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": secret_key, "response": token, "remoteip": request.client.host if request.client else ""},
            timeout=10,
        )
        result = resp.json()
    except Exception:
        raise HTTPException(status_code=503, detail="Gagal memverifikasi CAPTCHA, coba lagi.")

    if not result.get("success"):
        raise HTTPException(status_code=400, detail="Verifikasi CAPTCHA gagal, silakan coba lagi.")


class TrackQuery(BaseModel):
    query: str  # Nomor Tiket ATAU Serial Number alat
    phone: str  # utk verifikasi - dicocokkan 5 digit terakhir
    turnstileToken: Optional[str] = None  # token CAPTCHA (Opsi 4) - opsional


# Pesan error TUNGGAL dipakai utk KEDUA kasus gagal (nomor tidak ditemukan
# MAUPUN nomor ketemu tapi HP tidak cocok) - SENGAJA disamakan (Opsi 1
# pengamanan) supaya penyerang tidak bisa membedakan "nomor ini valid tapi
# HP salah" dari "nomor ini memang tidak ada". Kalau pesannya beda, itu bisa
# dipakai utk menebak-nebak nomor tiket yang valid satu per satu (enumerasi).
TRACK_GENERIC_ERROR = "Data tidak ditemukan. Pastikan Nomor Tiket/Serial Number dan Nomor HP/WhatsApp sesuai dengan yang terdaftar."


@app.post("/api/v1/public/track")
@limiter.limit("5/minute")
def track_ticket_api(request: Request, data: TrackQuery, db: Session = Depends(get_public_db)):
    """
    Lacak status servis - PUBLIK, bisa dicari pakai Nomor Tiket ATAU Serial
    Number alat, verifikasi identitas memakai 5 digit TERAKHIR dari No.
    HP/WhatsApp 1 yang terdaftar di tiket.

    Pengamanan (lihat diskusi Opsi 1-4):
    - Opsi 1: pesan error SAMA baik nomor tidak ada maupun HP tidak cocok.
    - Opsi 2: pakai koneksi database terbatas (get_public_db), bukan penuh akses.
    - Opsi 4: rate limit diperketat jadi 5x/menit + verifikasi CAPTCHA (kalau diatur).
    """
    verify_turnstile_or_raise(data.turnstileToken, request)

    query_str = (data.query or "").strip()
    phone_input = (data.phone or "").strip()
    if not query_str or not phone_input:
        return JSONResponse(status_code=400, content={"ok": False, "message": "Nomor Tiket/Serial Number dan Nomor HP/WhatsApp wajib diisi."})

    ticket = (
        db.query(ServiceTicket)
        .filter(or_(ServiceTicket.ticket_number == query_str, ServiceTicket.serial_number == query_str))
        .first()
    )

    db_phone = "".join(filter(str.isdigit, ticket.customer_phone or "" if ticket else ""))
    input_phone = "".join(filter(str.isdigit, phone_input))
    phone_matches = bool(ticket) and bool(db_phone) and len(input_phone) >= 5 and db_phone[-5:] == input_phone[-5:]

    if not ticket or not phone_matches:
        # SATU pesan generik, SATU status code (404), utk KEDUA kondisi gagal.
        return JSONResponse(status_code=404, content={"ok": False, "message": TRACK_GENERIC_ERROR})

    def _iso(d):
        return d.strftime("%Y-%m-%d") if d else None

    display = compute_track_display(ticket)

    return {
        "ok": True,
        "data": {
            "ticket": ticket.ticket_number,
            "namaCustomer": ticket.customer_name,  # SELALU nama customer asli - TIDAK PERNAH diganti nama instansi
            # displayRepairStatus/displayShippingStatus bisa None -> frontend
            # WAJIB tampilkan "-----" saat None (lihat compute_track_display).
            "repairStatus": display["displayRepairStatus"],
            "kategori": ticket.product_category,
            "model": ticket.device_model,
            "serialNo": ticket.serial_number,
            "tglTerima": _iso(ticket.received_date) or _iso(ticket.created_at),
            "tglSelesai": _iso(ticket.completed_date),
            "statusGaransi": ticket.warranty_status or "Belum ditentukan",
            "remarks": ticket.remarks,
            "keluhan": ticket.complaint,
            "shippingStatus": display["displayShippingStatus"],
            "shippingUpdatedAt": _iso(ticket.shipping_updated_at),
            "awbNumber": display["awbNumber"],
            # receiverName dari KURIR GED (bukan data kita) - hanya terisi di
            # titik akhir "Diterima", digabung dgn nama instansi kalau asal Pickup Center.
            "receiverName": display["receiverName"],
        },
    }


@app.get("/api/v1/admin/reports/excel")
def download_excel_report(
    service_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    DIPERBAIKI: sebelumnya endpoint ini SELALU mengembalikan 1 baris data mock
    yang di-hardcode, tidak peduli tombol "Download Excel" yang mana yang
    diklik. Sekarang laporan diambil dari data ASLI di database, dan wajib
    login (tidak lagi publik), serta staff hanya bisa unduh data
    departemennya sendiri.

    date_from/date_to (format "YYYY-MM-DD", opsional) - filter berdasarkan
    Tanggal Diterima (received_date); kalau kosong, pakai tanggal tiket
    dibuat (created_at) sebagai fallback. Dipanggil dari menu Laporan >
    Laporan Data Service.
    """
    query = db.query(ServiceTicket).options(
        joinedload(ServiceTicket.spareparts),
        joinedload(ServiceTicket.created_by),
    )

    if service_type:
        srv = service_type.lower().strip()
        require_department_access(current_user, srv)
        query = query.filter(func.lower(ServiceTicket.service_type) == srv)
    elif current_user.role not in ("superadmin", "admin"):
        query = query.filter(func.lower(ServiceTicket.service_type) == current_user.department)

    date_col = func.coalesce(ServiceTicket.received_date, ServiceTicket.created_at)
    if date_from:
        query = query.filter(date_col >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.filter(date_col < datetime.fromisoformat(date_to) + timedelta(days=1))

    tickets = query.order_by(ServiceTicket.id).all()

    def _fmt_date(d):
        return d.strftime("%Y-%m-%d") if d else ""

    def _sp(ticket, slot_no):
        """Ambil baris sparepart slot ke-N (1/2/3) dari sebuah tiket, kalau ada."""
        for sp in ticket.spareparts:
            if sp.slot_no == slot_no:
                return sp
        return None

    rows = []
    for t in tickets:
        sp1, sp2, sp3 = _sp(t, 1), _sp(t, 2), _sp(t, 3)
        rows.append({
            "ticket_number": t.ticket_number,
            "nama_teknisi": t.created_by.full_name if t.created_by else "",
            "received_date": _fmt_date(t.received_date),
            "completed_date": _fmt_date(t.completed_date),
            "customer_name": t.customer_name,
            "province": t.province or "",
            "city": t.city or "",
            "customer_address": t.customer_address or "",
            "instansi_name": t.instansi_name or "",
            "customer_phone": t.customer_phone or "",
            "customer_phone_2": t.customer_phone_2 or "",
            "product_category": t.product_category or "",
            "device_model": t.device_model or "",
            "serial_number": t.serial_number or "",
            "warranty_period": t.warranty_period or "",
            "warranty_status": t.warranty_status or "",
            "accessories": t.accessories or "",
            "complaint": t.complaint or "",
            "technician_analysis": t.technician_analysis or "",
            "symptom_code": t.symptom_code or "",
            "product_origin": t.product_origin or "",
            "leadtime_days": t.leadtime_days if t.leadtime_days is not None else "",
            "remarks": t.remarks or "",
            "status": t.status or "",
            "notes": t.notes or "",
            "total_price": t.total_price if t.total_price is not None else 0,
            "sp1_name": sp1.name if sp1 else "", "sp1_qty": sp1.quantity if sp1 else "",
            "sp1_code": sp1.code if sp1 else "", "sp1_price": sp1.price if sp1 else "",
            "sp2_name": sp2.name if sp2 else "", "sp2_qty": sp2.quantity if sp2 else "",
            "sp2_code": sp2.code if sp2 else "", "sp2_price": sp2.price if sp2 else "",
            "sp3_name": sp3.name if sp3 else "", "sp3_qty": sp3.quantity if sp3 else "",
            "sp3_code": sp3.code if sp3 else "", "sp3_price": sp3.price if sp3 else "",
        })

    excel_file = generate_service_report_excel(rows)
    label = service_type or (current_user.department if current_user.role not in ("superadmin", "admin") else "semua")
    filename = f"Laporan_Servis_Omron_{label}_{datetime.utcnow().strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(
        excel_file,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/api/v1/admin/reports/payment-status")
def download_payment_status_report(
    service_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Laporan Status Payment - menu Laporan > b. Laporan Status Payment.
    Format 22 kolom PERSIS sesuai template resmi yang diberikan user.
    Hanya menyertakan tiket dengan Status Garansi EKSPLISIT "Out of Warranty"
    (konsisten dengan filter yang sama dipakai di Tab Status Payment Service).
    """
    from app.services.doku_payment import PAYMENT_METHOD_LABELS

    query = db.query(ServiceTicket).options(joinedload(ServiceTicket.billing_items))

    if service_type:
        srv = service_type.lower().strip()
        require_department_access(current_user, srv)
        query = query.filter(func.lower(ServiceTicket.service_type) == srv)
    elif current_user.role not in ("superadmin", "admin"):
        query = query.filter(func.lower(ServiceTicket.service_type) == current_user.department)

    query = query.filter(ServiceTicket.warranty_status == "Out of Warranty")

    date_col = func.coalesce(ServiceTicket.received_date, ServiceTicket.created_at)
    if date_from:
        query = query.filter(date_col >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.filter(date_col < datetime.fromisoformat(date_to) + timedelta(days=1))

    tickets = query.order_by(ServiceTicket.id).all()

    DEPT_LABELS = {"pusat": "Pusat", "cabang": "Cabang", "pickup": "Pickup Center"}

    def _fmt_dt(d):
        return d.strftime("%d-%m-%Y %H:%M") if d else "-"

    rows = []
    for idx, t in enumerate(tickets, start=1):
        subtotal = sum((item.quantity or 0) * (item.price or 0) for item in t.billing_items)
        ppn = 0.0 if t.ppn_free else subtotal * 0.11
        pph23 = float(t.pph23_amount or 0) if t.use_manual_price_breakdown else 0.0
        admin_bank = float(t.admin_bank_fee or 0) if t.use_manual_price_breakdown else 0.0
        total = subtotal + ppn - pph23 + admin_bank

        rows.append({
            "no": idx,
            "ticket_number": t.ticket_number,
            "owner_name": t.invoice_owner_name or t.customer_name,
            "email": t.customer_email or "",
            "phone": t.customer_phone or "",
            "address": t.invoice_address or t.customer_address or "",
            "id_number": t.customer_id_number or "",
            "warranty_status": t.warranty_status or "",
            "harga": subtotal,
            "ppn": ppn,
            "total": total,
            "pph23": pph23,
            "admin_bank": admin_bank,
            "ppn_for_doku": "no" if t.ppn_free else "yes",
            "status_repair": t.status or "",
            "invoice_number": t.invoice_number or "",
            "invoice_date": _fmt_dt(t.invoice_created_at) if t.invoice_number else "-",
            "payment_channel": PAYMENT_METHOD_LABELS.get(t.payment_method, t.payment_method) if t.payment_method else "-",
            "payment_status": t.payment_status or "Belum Lunas",
            "created_at": _fmt_dt(t.created_at),
            "paid_at": _fmt_dt(t.paid_at) if t.paid_at else "-",
            "departement": DEPT_LABELS.get(t.service_type, t.service_type),
        })

    excel_file = generate_payment_status_excel(rows)
    label = service_type or (current_user.department if current_user.role not in ("superadmin", "admin") else "semua")
    filename = f"Laporan_Status_Payment_{label}_{datetime.utcnow().strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(
        excel_file,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ==================== PICKUP CENTER - FORM DROP-OFF PUBLIK ====================
# Pickup Center berperan sebagai drop-off point untuk tim Pusat. Form ini
# SENGAJA tidak mewajibkan login, supaya bisa dipakai tim lapangan/kurir yang
# tidak punya akun sistem. Field HANYA 11 sesuai kebutuhan drop-off (tanpa
# info garansi/analisa teknisi/sparepart - itu diisi belakangan oleh tim
# Pusat lewat panel admin biasa).

class PickupIntakeCreate(BaseModel):
    """
    Batas panjang (max_length) SENGAJA diterapkan ketat di sini karena endpoint
    ini publik/tanpa login - mencegah payload raksasa (potensi DoS ringan)
    dikirim oleh siapa saja tanpa perlu terautentikasi lebih dulu.
    """
    customer_name: str = Field(max_length=100)
    instansi_name: Optional[str] = Field(default=None, max_length=150)
    customer_phone: str = Field(max_length=30)
    customer_phone_2: Optional[str] = Field(default=None, max_length=30)
    customer_address: Optional[str] = Field(default=None, max_length=500)
    received_date: Optional[datetime] = None
    product_category: Optional[str] = Field(default=None, max_length=50)
    device_model: Optional[str] = Field(default=None, max_length=100)
    serial_number: Optional[str] = Field(default="-", max_length=50)
    accessories: Optional[str] = Field(default=None, max_length=150)
    complaint: Optional[str] = Field(default="-", max_length=1000)
    turnstileToken: Optional[str] = None  # token CAPTCHA (Opsi 4) - opsional


class ReceiptIntakeCreate(BaseModel):
    """
    Sama persis dengan PickupIntakeCreate, TAPI dipakai form /receipt yang
    membuat tiket di data PUSAT (bukan Pickup Center), dan punya 2 field
    tambahan: notes (Catatan) & notif_whatsapp (kotak centang notifikasi).
    """
    customer_name: str = Field(max_length=100)
    instansi_name: Optional[str] = Field(default=None, max_length=150)
    customer_phone: str = Field(max_length=30)
    customer_phone_2: Optional[str] = Field(default=None, max_length=30)
    customer_address: Optional[str] = Field(default=None, max_length=500)
    received_date: Optional[datetime] = None
    product_category: Optional[str] = Field(default=None, max_length=50)
    device_model: Optional[str] = Field(default=None, max_length=100)
    serial_number: Optional[str] = Field(default="-", max_length=50)
    accessories: Optional[str] = Field(default=None, max_length=150)
    complaint: Optional[str] = Field(default="-", max_length=1000)
    notes: Optional[str] = Field(default=None, max_length=1000)
    notif_whatsapp: bool = False
    turnstileToken: Optional[str] = None


@app.post("/api/v1/public/receipt")
@limiter.limit("5/minute")
def receipt_intake_create(request: Request, data: ReceiptIntakeCreate, db: Session = Depends(get_public_db)):
    """
    Endpoint form publik /receipt - PERSIS seperti /pickup-intake, BEDANYA
    tiket yang terbentuk masuk ke data PUSAT (bukan Pickup Center).
    """
    verify_turnstile_or_raise(data.turnstileToken, request)
    try:
        ticket_num = _next_ticket_number(db, "pusat")
        db_ticket = ServiceTicket(
            ticket_number=ticket_num,
            service_type="pusat",
            created_by_location="LOCATION_PUSAT",
            created_by_user_id=None,  # tidak ada login di form publik ini
            customer_name=data.customer_name,
            instansi_name=data.instansi_name,
            customer_phone=data.customer_phone,
            customer_phone_2=data.customer_phone_2,
            customer_address=data.customer_address,
            received_date=data.received_date,
            product_category=data.product_category,
            device_model=data.device_model or "-",
            serial_number=data.serial_number or "-",
            accessories=data.accessories,
            complaint=data.complaint or "-",
            notes=data.notes,
            notif_receipt_whatsapp=data.notif_whatsapp,
            # SENGAJA dikosongkan - sama seperti /pickup-intake, status garansi
            # belum diketahui saat receipt diterima, biar tim Teknisi yang isi.
            warranty_status=None,
            status="Diterima",
            shipping_status=initial_shipping_status_for_new_ticket("pusat", "Diterima"),
        )
        db.add(db_ticket)
        db.commit()
        db.refresh(db_ticket)
        return {"status": "success", "ticket_number": db_ticket.ticket_number}
    except Exception as e:
        db.rollback()
        logger.error(f"Error saving receipt intake: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Gagal menyimpan data receipt: {str(e)}")


@app.post("/api/v1/public/pickup-intake")
@limiter.limit("5/minute")
def pickup_intake_create(request: Request, data: PickupIntakeCreate, db: Session = Depends(get_public_db)):
    verify_turnstile_or_raise(data.turnstileToken, request)
    try:
        ticket_num = _next_ticket_number(db, "pickup")
        db_ticket = ServiceTicket(
            ticket_number=ticket_num,
            service_type="pickup",
            created_by_location="LOCATION_PICKUP",
            created_by_user_id=None,  # tidak ada login di form publik ini
            customer_name=data.customer_name,
            instansi_name=data.instansi_name,
            customer_phone=data.customer_phone,
            customer_phone_2=data.customer_phone_2,
            customer_address=data.customer_address,
            received_date=data.received_date,
            product_category=data.product_category,
            device_model=data.device_model or "-",
            serial_number=data.serial_number or "-",
            accessories=data.accessories,
            complaint=data.complaint or "-",
            # SENGAJA dikosongkan (bukan default kolom "Out of Warranty") - status
            # garansi belum diketahui saat drop-off, biar tim Teknisi yang
            # menentukan & mengisi sendiri saat tiket ini nanti diedit.
            warranty_status=None,
            # Status awal alur Pickup Center - Status Pengiriman (shipping_status)
            # akan otomatis berjalan dari sini via timer 24 jam & webhook GED.
            status="Diterima",
            shipping_status=initial_shipping_status_for_new_ticket("pickup", "Diterima"),
        )
        db.add(db_ticket)
        db.commit()
        db.refresh(db_ticket)
        return {"status": "success", "ticket_number": db_ticket.ticket_number}
    except Exception as e:
        db.rollback()
        logger.error(f"Error saving pickup intake: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Gagal menyimpan data drop-off: {str(e)}")


@app.post("/api/v1/public/doku-notification")
async def doku_payment_notification(request: Request, db: Session = Depends(get_db)):
    """
    Webhook/notifikasi dari DOKU - dipanggil OTOMATIS oleh server DOKU (bukan
    oleh user) setiap kali status pembayaran berubah (mis. pelanggan berhasil
    bayar VA/Alfamart/Indomaret). Dari sinilah kolom "Tanggal Bayar" terisi -
    BUKAN dari aksi staff manual, sesuai keputusan bisnis Anda.

    Endpoint ini PUBLIK (tidak pakai login) karena yang memanggil adalah
    server DOKU, bukan staff - tapi tetap AMAN karena signature-nya
    diverifikasi (lihat verify_notification_signature), jadi tidak
    sembarang pihak bisa memalsukan notifikasi "pembayaran sukses".
    """
    import os
    from app.services.doku_payment import verify_notification_signature

    body_raw = await request.body()
    client_id_header = request.headers.get("Client-Id", "")
    request_id = request.headers.get("Request-Id", "")
    timestamp = request.headers.get("Request-Timestamp", "")
    signature_header = request.headers.get("Signature", "")

    doku_client_id = os.environ.get("DOKU_CLIENT_ID")
    doku_secret_key = os.environ.get("DOKU_SECRET_KEY")
    if not doku_client_id or not doku_secret_key:
        logger.error("Notifikasi DOKU diterima tapi DOKU_CLIENT_ID/SECRET_KEY belum diatur di server.")
        raise HTTPException(status_code=503, detail="Kredensial DOKU belum diatur di server.")

    is_valid = verify_notification_signature(
        client_id=doku_client_id, secret_key=doku_secret_key, request_id=request_id,
        timestamp=timestamp, request_target="/api/v1/public/doku-notification",
        body_raw=body_raw, signature_header=signature_header,
    )
    if not is_valid:
        logger.warning("Notifikasi DOKU DITOLAK - signature tidak valid (kemungkinan bukan dari DOKU asli).")
        raise HTTPException(status_code=401, detail="Signature tidak valid.")

    import json
    try:
        payload = json.loads(body_raw)
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Body notifikasi bukan JSON valid.")

    invoice_number = (payload.get("order") or {}).get("invoice_number")
    tx_status = (payload.get("transaction") or {}).get("status", "")
    tx_date_raw = (payload.get("transaction") or {}).get("date")

    if not invoice_number:
        raise HTTPException(status_code=400, detail="Notifikasi tidak berisi order.invoice_number.")

    ticket = db.query(ServiceTicket).filter(ServiceTicket.ticket_number == invoice_number).first()
    if not ticket:
        # Tiket tidak ditemukan - tetap balas 200 (DOKU tidak perlu retry
        # notifikasi ini lagi), tapi dicatat di log utk investigasi.
        logger.warning(f"Notifikasi DOKU utk tiket yang tidak ditemukan: {invoice_number}")
        return {"status": "ignored", "reason": "ticket_not_found"}

    if tx_status.upper() == "SUCCESS":
        ticket.payment_status = "Lunas"
        try:
            ticket.paid_at = datetime.fromisoformat(tx_date_raw.replace("Z", "+00:00")) if tx_date_raw else datetime.utcnow()
        except ValueError:
            ticket.paid_at = datetime.utcnow()
        db.commit()
        logger.info(f"Pembayaran tiket {invoice_number} dikonfirmasi LUNAS via notifikasi DOKU.")

    return {"status": "success"}


