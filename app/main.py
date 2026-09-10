from datetime import datetime, timedelta
from typing import Optional
import os

from fastapi import FastAPI, Request, HTTPException, Depends, Path, Query
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.api.v1 import mutations, services_api, auth as auth_api, inventory_parts, locations
from app.api.v1.services_api import _next_ticket_number
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
def _on_startup():
    # Aman dipanggil berkali-kali: hanya membuat tabel yang belum ada,
    # TIDAK PERNAH menghapus/mengubah tabel atau data yang sudah ada.
    init_db()


app.include_router(auth_api.router)
app.include_router(auth_api.admin_users_router)
app.include_router(mutations.router)
app.include_router(services_api.router)
app.include_router(services_api.catalog_router)
app.include_router(inventory_parts.router)
app.include_router(locations.branch_router)
app.include_router(locations.pickup_router)


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

    return {
        "ok": True,
        "data": {
            "ticket": ticket.ticket_number,
            "namaCustomer": ticket.customer_name,
            "repairStatus": ticket.status or "Diterima",
            "kategori": ticket.product_category,
            "model": ticket.device_model,
            "serialNo": ticket.serial_number,
            "tglTerima": _iso(ticket.received_date) or _iso(ticket.created_at),
            "tglSelesai": _iso(ticket.completed_date),
            "statusGaransi": ticket.warranty_status or "Belum ditentukan",
            "remarks": ticket.remarks,
            "keluhan": ticket.complaint,
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
            # Status awal alur Pickup Center - selanjutnya diupdate manual oleh
            # tim Teknisi, atau (rencana ke depan) otomatis dari integrasi API
            # sistem tracking jasa kirim GED.
            status="Diterima di PKP",
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


@app.get("/pickup-intake", response_class=HTMLResponse)
def pickup_intake_page():
    turnstile_site_key = os.environ.get("TURNSTILE_SITE_KEY", "").strip()
    turnstile_script = (
        '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>'
        if turnstile_site_key else ""
    )
    turnstile_widget = (
        f'<div class="cf-turnstile" data-sitekey="{turnstile_site_key}"></div>' if turnstile_site_key else ""
    )
    html = """
    <!DOCTYPE html>
    <html lang="id">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Drop-Off Pickup Center - Omron Healthcare</title>
        __TURNSTILE_SCRIPT__
        <style>
            * { box-sizing: border-box; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
            body { background: #f0f2f5; margin: 0; padding: 20px; }
            .wrap { max-width: 640px; margin: 0 auto; }
            .card { background: white; padding: 25px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); margin-bottom: 20px; }
            .logo { font-size: 22px; font-weight: bold; color: #0056b3; margin-bottom: 2px; }
            .subtitle { color: #666; font-size: 13px; margin-bottom: 20px; }
            .form-group { margin-bottom: 14px; }
            label { font-size: 13px; font-weight: bold; color: #444; display: block; margin-bottom: 4px; }
            input, select { width: 100%; padding: 11px; border: 1px solid #ccc; border-radius: 6px; box-sizing: border-box; font-size: 14px; }
            .required { color: red; }
            button { width: 100%; padding: 13px; background: #0056b3; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: bold; font-size: 15px; margin-top: 8px; }
            button:hover { background: #004085; }
            .success-box { display: none; background: #d4edda; border: 1px solid #c3e6cb; color: #155724; padding: 18px; border-radius: 8px; text-align: center; }
            .success-box .ticket-no { font-size: 22px; font-weight: bold; margin: 8px 0; }
            .error-box { display: none; background: #f8d7da; border: 1px solid #f5c6cb; color: #721c24; padding: 12px; border-radius: 6px; font-size: 13px; margin-bottom: 15px; }
        </style>
    </head>
    <body>
        <div class="wrap">
            <div class="card">
                <div class="logo">OMRON</div>
                <div class="subtitle">Form Drop-Off Perangkat - Pickup Center</div>

                <div id="successBox" class="success-box">
                    ✅ Drop-off berhasil dicatat!
                    <div class="ticket-no" id="successTicketNo"></div>
                    Simpan nomor tiket ini untuk pelanggan.
                    <div style="margin-top:12px;"><button onclick="resetForm()">+ Input Drop-Off Baru</button></div>
                </div>

                <div id="errorBox" class="error-box"></div>

                <form id="intakeForm">
                    <div class="form-group"><label>Nama Customer <span class="required">*</span></label><input id="pName" required></div>
                    <div class="form-group">
                        <label>Nama Instansi</label>
                        <input id="pInstansi" list="pInstansiList" placeholder="Ketik atau pilih dari daftar Pickup Center aktif">
                        <datalist id="pInstansiList"></datalist>
                    </div>
                    <div class="form-group"><label>No. HP / WhatsApp 1 <span class="required">*</span></label><input id="pPhone1" required placeholder="081234567890"></div>
                    <div class="form-group"><label>No. HP / WhatsApp 2</label><input id="pPhone2" placeholder="(opsional)"></div>
                    <div class="form-group"><label>Alamat</label><input id="pAddress"></div>
                    <div class="form-group"><label>Tanggal Alat Diterima</label><input type="date" id="pReceivedDate"></div>
                    <div class="form-group">
                        <label>Produk Kategori</label>
                        <select id="pCategory" onchange="onCategoryChange()">
                            <option value="">-- Pilih Kategori --</option>
                            <option>Arm BPM</option><option>BCM</option><option>BGM</option><option>Comp-NEB</option>
                            <option>DWS</option><option>Ear Thermo</option><option>Forehead Thermo</option>
                            <option>MEDICAL</option><option>Mesh-NEB</option><option>Pen Thermo</option>
                            <option>TENS</option><option>Ultra-NEB</option><option>Wrist BPM</option><option>Others</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Model Alat</label>
                        <select id="pModel"><option value="">-- Pilih Kategori dulu --</option></select>
                    </div>
                    <div class="form-group"><label>Serial No. Alat</label><input id="pSerial"></div>
                    <div class="form-group"><label>Aksesoris</label><input id="pAccessories" placeholder="Contoh: Kabel, Adaptor"></div>
                    <div class="form-group"><label>Keluhan Pelanggan</label><input id="pComplaint"></div>

                    __TURNSTILE_WIDGET__

                    <button type="submit">Simpan Drop-Off</button>
                </form>
            </div>
        </div>

        <script>
            function esc(value) {
                if (value === null || value === undefined) return '';
                return String(value)
                    .replace(/&/g, '&amp;')
                    .replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;')
                    .replace(/"/g, '&quot;')
                    .replace(/'/g, '&#39;');
            }

            async function loadInstansiOptions() {
                try {
                    const res = await fetch('/api/v1/pickup-centers/public');
                    if (!res.ok) return;
                    const list = await res.json();
                    document.getElementById('pInstansiList').innerHTML =
                        list.map(p => `<option value="${esc(p.store_name)}">`).join('');
                } catch(e) { /* diamkan - form tetap bisa diisi manual kalau daftar gagal dimuat */ }
            }
            loadInstansiOptions();

            async function onCategoryChange() {
                const category = document.getElementById('pCategory').value;
                let modelEl = document.getElementById('pModel');

                if (!category) {
                    if (modelEl.tagName !== 'SELECT') {
                        modelEl.outerHTML = '<select id="pModel"><option value="">-- Pilih Kategori dulu --</option></select>';
                    } else {
                        modelEl.innerHTML = '<option value="">-- Pilih Kategori dulu --</option>';
                    }
                    return;
                }

                if (category === 'Others') {
                    modelEl.outerHTML = '<input id="pModel" placeholder="Ketik nama model alat">';
                    return;
                }

                if (modelEl.tagName !== 'SELECT') {
                    modelEl.outerHTML = '<select id="pModel"><option value="">Memuat...</option></select>';
                } else {
                    modelEl.innerHTML = '<option value="">Memuat...</option>';
                }
                modelEl = document.getElementById('pModel');

                try {
                    const res = await fetch(`/api/v1/device-models/public?category=${encodeURIComponent(category)}`);
                    const models = res.ok ? await res.json() : [];
                    modelEl.innerHTML = models.length
                        ? '<option value="">-- Pilih Model --</option>' + models.map(m => `<option value="${esc(m.model_name)}">${esc(m.model_name)}</option>`).join('')
                        : '<option value="">(Belum ada model utk kategori ini)</option>';
                } catch(e) {
                    modelEl.innerHTML = '<option value="">Gagal memuat model</option>';
                }
            }

            function resetForm() {
                document.getElementById('intakeForm').reset();
                document.getElementById('pModel').outerHTML = '<select id="pModel"><option value="">-- Pilih Kategori dulu --</option></select>';
                document.getElementById('successBox').style.display = 'none';
                document.getElementById('errorBox').style.display = 'none';
                document.getElementById('intakeForm').style.display = 'block';
            }

            document.getElementById('intakeForm').addEventListener('submit', async function(e) {
                e.preventDefault();
                const errorBox = document.getElementById('errorBox');
                errorBox.style.display = 'none';

                const name = document.getElementById('pName').value.trim();
                const phone1 = document.getElementById('pPhone1').value.trim();
                if (!name || !phone1) {
                    errorBox.textContent = 'Nama Customer dan No. HP/WhatsApp 1 wajib diisi.';
                    errorBox.style.display = 'block';
                    return;
                }

                const receivedDateVal = document.getElementById('pReceivedDate').value;
                const payload = {
                    customer_name: name,
                    instansi_name: document.getElementById('pInstansi').value.trim() || null,
                    customer_phone: phone1,
                    customer_phone_2: document.getElementById('pPhone2').value.trim() || null,
                    customer_address: document.getElementById('pAddress').value.trim() || null,
                    received_date: receivedDateVal ? new Date(receivedDateVal + 'T00:00:00').toISOString() : null,
                    product_category: document.getElementById('pCategory').value || null,
                    device_model: document.getElementById('pModel').value || null,
                    serial_number: document.getElementById('pSerial').value.trim() || '-',
                    accessories: document.getElementById('pAccessories').value.trim() || null,
                    complaint: document.getElementById('pComplaint').value.trim() || '-',
                    turnstileToken: (window.turnstile && document.querySelector('.cf-turnstile')) ? turnstile.getResponse() : null,
                };

                try {
                    const res = await fetch('/api/v1/public/pickup-intake', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Gagal menyimpan data.');

                    document.getElementById('intakeForm').style.display = 'none';
                    document.getElementById('successTicketNo').innerText = data.ticket_number;
                    document.getElementById('successBox').style.display = 'block';
                } catch(err) {
                    errorBox.textContent = err.message;
                    errorBox.style.display = 'block';
                }
            });
        </script>
    </body>
    </html>
    """
    html = html.replace("__TURNSTILE_SCRIPT__", turnstile_script).replace("__TURNSTILE_WIDGET__", turnstile_widget)
    return html


@app.get("/track", response_class=HTMLResponse)
def track_ticket_page():
    turnstile_site_key = os.environ.get("TURNSTILE_SITE_KEY", "").strip()
    turnstile_script = (
        '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>'
        if turnstile_site_key else ""
    )
    turnstile_widget = (
        f'<div class="cf-turnstile" data-sitekey="{turnstile_site_key}" style="margin:14px 0;"></div>' if turnstile_site_key else ""
    )
    html = """
<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<title>Lacak Status Service — OMRON Healthcare</title>
__TURNSTILE_SCRIPT__
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex, nofollow">
<style>
  :root{
    --navy:#0b2f6b;
    --blue:#0f4fb0;
    --blue-light:#e8f0fd;
    --orange:#f2932d;
    --bg:#f4f6fb;
    --card:#ffffff;
    --border:#e1e6ef;
    --ink:#152238;
    --ink-soft:#5c6b83;
    --ok:#1f9d55;
    --warn:#c9781f;
    --danger:#c0392b;
    --radius:12px;
  }
  *{box-sizing:border-box;}
  body{margin:0;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;background:var(--bg);color:var(--ink);}
  .wrap{min-height:100vh;display:flex;flex-direction:column;align-items:center;padding:32px 16px 60px;}
  .top{display:flex;flex-direction:column;align-items:center;margin-bottom:22px;text-align:center;}
  .logo{font-weight:800;font-size:24px;letter-spacing:.5px;color:var(--navy);}
  .logo span{color:var(--orange);}
  .top .sub{font-size:13px;color:var(--ink-soft);margin-top:4px;}

  .card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
    padding:26px 24px;width:100%;max-width:440px;box-shadow:0 10px 30px rgba(15,40,90,.06);}
  .card h1{font-size:17px;margin:0 0 4px;color:var(--navy);}
  .card .desc{font-size:12.5px;color:var(--ink-soft);margin-bottom:20px;line-height:1.5;}
  .field{margin-bottom:14px;}
  label{font-size:12.5px;font-weight:700;color:var(--ink-soft);display:block;margin-bottom:5px;}
  input[type=text],input[type=tel]{
    width:100%;padding:11px 12px;border:1px solid var(--border);border-radius:8px;font-size:14px;
    background:#fff;color:var(--ink);font-family:inherit;
  }
  input:focus{outline:none;border-color:var(--blue);box-shadow:0 0 0 3px var(--blue-light);}
  .helper{font-size:11px;color:var(--ink-soft);margin-top:5px;line-height:1.4;}
  .btn{
    border:none;border-radius:8px;padding:12px 16px;font-size:14px;font-weight:700;cursor:pointer;
    width:100%;transition:.15s;display:flex;align-items:center;justify-content:center;gap:8px;
  }
  .btn-primary{background:var(--blue);color:#fff;margin-top:6px;}
  .btn-primary:hover{background:var(--navy);}
  .btn-primary:disabled{opacity:.6;cursor:not-allowed;}
  .btn-outline{background:#fff;color:var(--blue);border:1px solid var(--blue);margin-top:10px;}
  .btn-outline:hover{background:var(--blue-light);}
  .spinner{width:15px;height:15px;border:2px solid rgba(255,255,255,.4);border-top-color:#fff;
    border-radius:50%;animation:spin .7s linear infinite;}
  @keyframes spin{to{transform:rotate(360deg);}}

  .alert{padding:11px 13px;border-radius:8px;font-size:12.5px;margin-bottom:14px;display:none;line-height:1.5;white-space:pre-wrap;}
  .alert.show{display:block;}
  .alert-error{background:#fdecea;color:var(--danger);border:1px solid #f5c6c0;}

  .result{display:none;}
  .result.show{display:block;}
  .result-head{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;margin-bottom:4px;flex-wrap:wrap;}
  .ticket-no{font-size:16px;font-weight:800;color:var(--navy);letter-spacing:.3px;}
  .cust-name{font-size:12.5px;color:var(--ink-soft);margin-bottom:14px;}
  .badge{display:inline-block;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:700;white-space:nowrap;}
  .badge-blue{background:#e5eeff;color:var(--blue);}
  .badge-green{background:#e7f8ee;color:var(--ok);}
  .badge-orange{background:#fef1e2;color:var(--warn);}
  .badge-gray{background:#eef1f6;color:var(--ink-soft);}

  .progress{display:flex;margin:20px 0 22px;}
  .step{flex:1;text-align:center;position:relative;}
  .step .dot{width:22px;height:22px;border-radius:50%;background:#e1e6ef;color:#8a97ad;font-size:11px;
    font-weight:800;display:flex;align-items:center;justify-content:center;margin:0 auto 6px;
    border:2px solid #e1e6ef;position:relative;z-index:2;}
  .step .lbl{font-size:9.5px;color:var(--ink-soft);line-height:1.25;padding:0 2px;}
  .step:before{content:'';position:absolute;top:11px;left:-50%;width:100%;height:2px;background:#e1e6ef;z-index:1;}
  .step:first-child:before{display:none;}
  .step.done .dot{background:var(--blue);border-color:var(--blue);color:#fff;}
  .step.done:before{background:var(--blue);}
  .step.current .dot{background:#fff;border-color:var(--blue);color:var(--blue);box-shadow:0 0 0 3px var(--blue-light);}
  .step.current .lbl{color:var(--navy);font-weight:700;}

  .info-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:6px;}
  .info-item{background:#f8f9fc;border:1px solid var(--border);border-radius:8px;padding:10px 12px;}
  .info-item .k{font-size:10.5px;color:var(--ink-soft);text-transform:uppercase;letter-spacing:.3px;margin-bottom:3px;}
  .info-item .v{font-size:13px;font-weight:600;color:var(--ink);word-break:break-word;}
  .info-item.full{grid-column:1/-1;}

  .foot-note{margin-top:26px;text-align:center;font-size:11.5px;color:var(--ink-soft);max-width:440px;line-height:1.6;}
  .foot-note b{color:var(--ink);}
  .privacy-note{display:flex;gap:8px;align-items:flex-start;background:var(--blue-light);border:1px solid #bcd4f7;
    border-radius:8px;padding:10px 12px;font-size:11.5px;color:var(--navy);margin-bottom:16px;line-height:1.5;}
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div class="logo">OMRON<span>&bull;</span>SERVICE</div>
    <div class="sub">Lacak Status Service Alat Anda</div>
  </div>

  <div class="card" id="formCard">
    <h1>Cek Status Service</h1>
    <div class="desc">Masukkan <b>Nomor Tiket</b> atau <b>Serial Number</b> alat, lalu konfirmasi dengan <b>5 digit terakhir</b> Nomor HP/WhatsApp 1 yang didaftarkan saat alat diserahkan.</div>

    <div class="alert alert-error" id="alertError"></div>

    <form id="trackForm" autocomplete="off">
      <div class="field">
        <label for="inpQuery">Nomor Tiket / Serial Number Alat</label>
        <input type="text" id="inpQuery" placeholder="Contoh: JKT-2600001 atau SN12345678" required>
      </div>
      <div class="field">
        <label for="inpPhone">5 Digit Terakhir No. HP/WhatsApp 1</label>
        <input type="tel" id="inpPhone" placeholder="Contoh: 45678" maxlength="5" inputmode="numeric" required>
        <div class="helper">Cukup 5 digit TERAKHIR dari nomor HP/WhatsApp yang didaftarkan saat menyerahkan alat.</div>
      </div>

      __TURNSTILE_WIDGET__

      <button type="submit" class="btn btn-primary" id="btnSubmit">Lacak Status</button>
    </form>
  </div>

  <div class="card result" id="resultCard">
    <div class="privacy-note">&#128274; Data ini hanya ditampilkan setelah Nomor Tiket/Serial dan 5 digit No. HP Anda terverifikasi cocok dengan data kami.</div>

    <div class="result-head">
      <div>
        <div class="ticket-no" id="resTicket">-</div>
        <div class="cust-name" id="resNama">-</div>
      </div>
      <span class="badge" id="resBadge">-</span>
    </div>

    <div class="progress" id="resProgress"></div>

    <div class="info-grid">
      <div class="info-item"><div class="k">Produk</div><div class="v" id="resProduk">-</div></div>
      <div class="info-item"><div class="k">Serial No.</div><div class="v" id="resSerial">-</div></div>
      <div class="info-item"><div class="k">Tgl. Diterima</div><div class="v" id="resTglTerima">-</div></div>
      <div class="info-item"><div class="k">Tgl. Selesai</div><div class="v" id="resTglSelesai">-</div></div>
      <div class="info-item"><div class="k">Status Garansi</div><div class="v" id="resGaransi">-</div></div>
      <div class="info-item"><div class="k">Rekomendasi</div><div class="v" id="resRemarks">-</div></div>
      <div class="info-item full" id="resKeluhanWrap">
        <div class="k">Keluhan yang Dilaporkan</div><div class="v" id="resKeluhan">-</div>
      </div>
    </div>

    <button type="button" class="btn btn-outline" id="btnAgain">Cek Tiket Lain</button>
  </div>

  <div class="foot-note">
    Butuh bantuan lebih lanjut? Hubungi Customer Service kami di<br>
    <b>08001401567</b> via telpon<br>
    <b>081113101567</b> via chat WhatsApp<br>
    Halaman ini hanya menampilkan data setelah verifikasi Nomor Tiket/Serial Number dan 5 digit terakhir Nomor HP/WhatsApp yang cocok.
  </div>
</div>

<script>
const STATUS_STAGES = [
  { match: ["Diterima", "Diterima di PKP"], label: "Diterima" },
  { match: ["Diproses", "Menunggu Sparepart", "Diteruskan ke Omron", "Diterima di Omron", "Diproses di Omron"], label: "Diproses" },
  { match: ["Selesai/Dikirim", "Selesai/Dikirim balik ke PKP"], label: "Selesai" },
  { match: ["Selesai Diambil", "Diterima kembali di PKP"], label: "Selesai Diambil" }
];

const BADGE_CLASS = {
  "Diterima":"badge-blue", "Diterima di PKP":"badge-blue",
  "Diproses":"badge-orange", "Menunggu Sparepart":"badge-orange",
  "Diteruskan ke Omron":"badge-orange", "Diterima di Omron":"badge-orange", "Diproses di Omron":"badge-orange",
  "Selesai/Dikirim":"badge-green", "Selesai/Dikirim balik ke PKP":"badge-green",
  "Selesai Diambil":"badge-gray", "Diterima kembali di PKP":"badge-gray"
};

const form = document.getElementById('trackForm');
const btnSubmit = document.getElementById('btnSubmit');
const alertError = document.getElementById('alertError');
const formCard = document.getElementById('formCard');
const resultCard = document.getElementById('resultCard');

function showError(msg){
  alertError.textContent = msg;
  alertError.classList.add('show');
}
function hideError(){
  alertError.classList.remove('show');
  alertError.textContent = '';
}
function esc(v){ return (v===undefined||v===null) ? '' : String(v); }
function fmtDate(d){
  if(!d) return '-';
  try{
    const dt = new Date(d);
    if(isNaN(dt.getTime())) return esc(d);
    return dt.toLocaleDateString('id-ID', { day:'2-digit', month:'long', year:'numeric' });
  }catch(e){ return esc(d); }
}

form.addEventListener('submit', async (e)=>{
  e.preventDefault();
  hideError();

  const query = document.getElementById('inpQuery').value.trim();
  const phone = document.getElementById('inpPhone').value.trim();

  if(!query || !phone){
    showError('Nomor Tiket/Serial dan 5 digit terakhir No. HP/WhatsApp wajib diisi.');
    return;
  }

  btnSubmit.disabled = true;
  btnSubmit.innerHTML = '<span class="spinner"></span> Memeriksa...';

  try{
    const res = await fetch('/api/v1/public/track', {
      method:'POST',
      headers:{ 'Content-Type':'application/json' },
      body: JSON.stringify({ query, phone, turnstileToken: (window.turnstile && document.querySelector('.cf-turnstile')) ? turnstile.getResponse() : null })
    });
    const payload = await res.json().catch(()=>({ ok:false, message:'Respons server tidak valid.' }));

    if(!res.ok || !payload.ok){
      showError(payload.message || 'Data tidak ditemukan. Pastikan Nomor Tiket/Serial dan No. HP sesuai.');
      return;
    }

    renderResult(payload.data);
    formCard.style.display = 'none';
    resultCard.classList.add('show');

  }catch(err){
    showError('Gagal menghubungi server. Periksa koneksi internet Anda dan coba lagi.');
  }finally{
    btnSubmit.disabled = false;
    btnSubmit.textContent = 'Lacak Status';
  }
});

document.getElementById('btnAgain').addEventListener('click', ()=>{
  resultCard.classList.remove('show');
  formCard.style.display = 'block';
  form.reset();
  hideError();
});

function renderResult(d){
  document.getElementById('resTicket').textContent = d.ticket || '-';
  document.getElementById('resNama').textContent = d.namaCustomer ? ('Atas nama: ' + d.namaCustomer) : '';
  const badge = document.getElementById('resBadge');
  badge.textContent = d.repairStatus || '-';
  badge.className = 'badge ' + (BADGE_CLASS[d.repairStatus] || 'badge-gray');

  document.getElementById('resProduk').textContent = [d.kategori, d.model].filter(Boolean).join(' - ') || '-';
  document.getElementById('resSerial').textContent = d.serialNo || '-';
  document.getElementById('resTglTerima').textContent = fmtDate(d.tglTerima);
  document.getElementById('resTglSelesai').textContent = d.tglSelesai ? fmtDate(d.tglSelesai) : 'Belum selesai';
  document.getElementById('resGaransi').textContent = d.statusGaransi || '-';
  document.getElementById('resRemarks').textContent = d.remarks || '-';

  const keluhanWrap = document.getElementById('resKeluhanWrap');
  if(d.keluhan){
    document.getElementById('resKeluhan').textContent = d.keluhan;
    keluhanWrap.style.display = 'block';
  } else {
    keluhanWrap.style.display = 'none';
  }

  renderProgress(d.repairStatus);
}

function renderProgress(status){
  const wrap = document.getElementById('resProgress');
  let currentIdx = STATUS_STAGES.findIndex(s => s.match.includes(status));
  if(currentIdx === -1) currentIdx = 0;
  wrap.innerHTML = STATUS_STAGES.map((s, i)=>{
    let cls = 'step';
    if(i < currentIdx) cls += ' done';
    else if(i === currentIdx) cls += ' current';
    const icon = i < currentIdx ? '&#10003;' : (i+1);
    return `<div class="${cls}"><div class="dot">${icon}</div><div class="lbl">${s.label}</div></div>`;
  }).join('');
}
</script>
</body>
</html>
"""
    html = html.replace("__TURNSTILE_SCRIPT__", turnstile_script).replace("__TURNSTILE_WIDGET__", turnstile_widget)
    return html


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard_page():
    return """
    <!DOCTYPE html>
    <html lang="id">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Portal Service Center - Omron Healthcare</title>
        <style>
            * { box-sizing: border-box; font-family: 'Segoe UI', Arial, sans-serif; }
            body { margin: 0; background: #f4f6f9; color: #333; display: flex; height: 100vh; overflow: hidden; }

            @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
            .spinner {
                display: inline-block; width: 16px; height: 16px;
                border: 3px solid rgba(255,255,255,0.4); border-top-color: #fff;
                border-radius: 50%; animation: spin 0.7s linear infinite;
                vertical-align: middle; margin-right: 6px;
            }
            .upload-preview-box {
                background: #fff; border: 1px solid #d0d7e2; border-radius: 8px;
                padding: 12px 14px; margin-bottom: 15px; display: flex;
                align-items: center; gap: 12px; flex-wrap: wrap;
            }
            .upload-preview-icon { font-size: 22px; }
            .upload-preview-info { flex: 1; min-width: 180px; }
            .upload-preview-name { font-weight: bold; color: #222; word-break: break-all; }
            .upload-preview-meta { font-size: 12px; color: #666; }
            .upload-result-box {
                border-radius: 8px; padding: 12px 14px; margin-bottom: 15px; font-size: 13px;
            }
            .upload-result-success { background: #d4edda; border: 1px solid #c3e6cb; color: #155724; }
            .upload-result-partial { background: #fff3cd; border: 1px solid #ffc107; color: #856404; }
            .upload-result-error { background: #f8d7da; border: 1px solid #f5c6cb; color: #721c24; }
            .field-note-pd { font-size: 11px; color: #888; margin-top: 3px; }

            aside { width: 260px; background: #003d80; color: white; display: flex; flex-direction: column; flex-shrink: 0; }
            aside .brand { padding: 20px; font-size: 18px; font-weight: bold; background: #002b5c; border-bottom: 1px solid rgba(255,255,255,0.1); }
            aside ul { list-style: none; padding: 0; margin: 0; overflow-y: auto; flex: 1; }
            aside li { border-bottom: 1px solid rgba(255,255,255,0.05); }
            aside .menu-title { padding: 12px 20px; font-weight: bold; font-size: 13px; color: #a2c7f5; background: rgba(0,0,0,0.1); display: flex; justify-content: space-between; align-items: center; cursor: pointer; }
            aside .submenu { list-style: none; padding: 0; background: #003366; display: none; }
            aside .submenu.open { display: block; }
            aside .submenu li a { padding: 10px 20px 10px 35px; display: block; color: #d0e1f9; text-decoration: none; font-size: 13px; }
            aside .submenu li a:hover, aside .submenu li a.active { background: #0056b3; color: white; font-weight: bold; }
            aside .single-menu { padding: 12px 20px; display: block; color: white; text-decoration: none; font-weight: bold; font-size: 14px; }
            aside .single-menu:hover { background: #0056b3; }
            aside .single-menu.hidden-menu { display: none; }

            main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
            header { background: white; padding: 15px 30px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #ddd; }
            header h1 { margin: 0; font-size: 18px; color: #0056b3; }
            .content { padding: 25px; overflow-y: auto; flex: 1; }

            .card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.06); margin-bottom: 20px; }
            h2 { color: #0056b3; margin-top: 0; font-size: 16px; border-bottom: 2px solid #e0e0e0; padding-bottom: 8px; }

            table { width: 100%; border-collapse: collapse; margin-top: 10px; }
            th, td { border: 1px solid #ddd; padding: 9px 12px; text-align: left; font-size: 13px; }
            th { background: #f8f9fa; color: #444; }
            .form-section-title { font-weight: bold; color: #0056b3; background: #e9ecef; padding: 8px 12px; border-radius: 4px; margin: 15px 0 10px 0; font-size: 14px; }
            .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-bottom: 10px; }
            .form-group { margin-bottom: 8px; }
            label { display: block; margin-bottom: 4px; font-weight: bold; font-size: 12px; color: #444; }
            input, select, textarea { width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px; font-size: 13px; }

            .action-header { display: flex; gap: 10px; align-items: center; }
            .search-input { width: 250px; padding: 8px 12px; border: 1px solid #ccc; border-radius: 4px; font-size: 13px; }

            .btn { background: #0056b3; color: white; border: none; padding: 7px 12px; border-radius: 4px; cursor: pointer; font-weight: bold; font-size: 12px; text-decoration: none; display: inline-block; }
            .btn:hover { background: #004085; }
            .btn-danger { background: #dc3545; }
            .btn-success { background: #28a745; }
            .btn-secondary { background: #6c757d; }
            .btn-warning { background: #ffc107; color: #212529; }
            .btn-info { background: #17a2b8; color: white; }
            .hidden { display: none !important; }
            .login-box { max-width: 400px; margin: 60px auto; }
            .badge { padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 11px; }
            .badge-lunas { background: #d4edda; color: #155724; }
            .badge-pending { background: #fff3cd; color: #856404; }
            .badge-active { background: #d4edda; color: #155724; }
            .badge-inactive { background: #f8d7da; color: #721c24; }
            .required { color: red; }
            .auth-tabs { display: flex; margin-bottom: 15px; border-bottom: 1px solid #ddd; }
            .auth-tabs div { flex: 1; text-align: center; padding: 10px; cursor: pointer; font-weight: bold; color: #888; font-size: 13px; }
            .auth-tabs div.active { color: #0056b3; border-bottom: 3px solid #0056b3; }
            .auth-error { color: #721c24; background: #f8d7da; border: 1px solid #f5c6cb; padding: 8px; border-radius: 5px; font-size: 12px; margin-bottom: 10px; display: none; }
        </style>
    </head>
    <body>

        <aside id="sidebar" class="hidden">
            <div class="brand">OMRON SERVICE</div>
            <ul>
                <li><a href="#" class="single-menu" onclick="showTab('dashboard')">1. Dashboard</a></li>

                <li>
                    <div class="menu-title" onclick="toggleSubmenu('sub-service')">2. Data Service <span>▼</span></div>
                    <ul id="sub-service" class="submenu open">
                        <li><a href="#" data-loc="pusat" class="active" onclick="showTab('service-pusat')">a. Data di Pusat</a></li>
                        <li><a href="#" data-loc="cabang" onclick="showTab('service-cabang')">b. Data di Cabang</a></li>
                        <li><a href="#" data-loc="pickup" onclick="showTab('service-pickup')">c. Data di Pickup Center</a></li>
                    </ul>
                </li>

                <li>
                    <div class="menu-title" onclick="toggleSubmenu('sub-payment')">3. Status Payment Service <span>▼</span></div>
                    <ul id="sub-payment" class="submenu">
                        <li><a href="#" data-loc="pusat" onclick="showTab('payment-pusat')">a. Payment di Pusat</a></li>
                        <li><a href="#" data-loc="cabang" onclick="showTab('payment-cabang')">b. Payment di Cabang</a></li>
                        <li><a href="#" data-loc="pickup" onclick="showTab('payment-pickup')">c. Payment di Pickup Center</a></li>
                    </ul>
                </li>

                <li>
                    <div class="menu-title" onclick="toggleSubmenu('sub-inventory')">4. Inventory Part <span>▼</span></div>
                    <ul id="sub-inventory" class="submenu">
                        <li><a href="#" data-loc="pusat" onclick="showTab('inventory-pusat')">a. Stok Sparepart di Pusat</a></li>
                        <li><a href="#" data-loc="cabang" onclick="showTab('inventory-cabang')">b. Stok Sparepart di Cabang</a></li>
                    </ul>
                </li>

                <li>
                    <div class="menu-title" onclick="toggleSubmenu('sub-laporan')">5. Laporan <span>▼</span></div>
                    <ul id="sub-laporan" class="submenu">
                        <li><a href="#" onclick="showTab('laporan-service')">a. Laporan Data Service</a></li>
                        <li><a href="#" onclick="showTab('laporan-payment')">b. Laporan Status Payment</a></li>
                        <li><a href="#" onclick="showTab('laporan-inventory')">c. Laporan Inventory Part</a></li>
                    </ul>
                </li>

                <li id="menu-setting">
                    <div class="menu-title" onclick="toggleSubmenu('sub-setting')">6. Setting (Super Admin) <span>▼</span></div>
                    <ul id="sub-setting" class="submenu">
                        <li><a href="#" onclick="showTab('setting-users')">a. Kelola User</a></li>
                        <li><a href="#" onclick="showTab('setting-devicemodels')">b. Kelola Model Alat</a></li>
                        <li><a href="#" onclick="showTab('setting-branches')">c. Kelola Cabang</a></li>
                        <li><a href="#" onclick="showTab('setting-pickupcenters')">d. Kelola Pickup Center</a></li>
                    </ul>
                </li>
            </ul>
        </aside>

        <main>
            <header>
                <h1 id="pageTitle">Portal Management System</h1>
                <div>
                    <span id="userStatus" style="font-weight: bold; font-size: 13px; margin-right: 15px;">Belum Login</span>
                    <button id="btnLogout" class="btn btn-danger hidden" onclick="logout()">Logout</button>
                </div>
            </header>

            <div class="content">
                <div id="authCard" class="card login-box">
                    <div class="auth-tabs">
                        <div id="tabLoginBtn" class="active" onclick="switchAuthTab('login')">Login</div>
                        <div id="tabBootstrapBtn" onclick="switchAuthTab('bootstrap')">Setup Awal</div>
                    </div>

                    <div id="authError" class="auth-error"></div>

                    <div id="loginPane">
                        <div class="form-group">
                            <label>Email</label>
                            <input type="email" id="loginEmail" placeholder="nama@omron.co.id">
                        </div>
                        <div class="form-group">
                            <label>Password</label>
                            <input type="password" id="loginPassword">
                        </div>
                        <button class="btn" style="width: 100%;" onclick="login()">Masuk ke Sistem</button>
                    </div>

                    <div id="bootstrapPane" class="hidden">
                        <p style="font-size:12px; color:#666;">Form ini hanya bisa dipakai SATU KALI, saat sistem belum punya akun sama sekali, untuk membuat akun Super Admin pertama.</p>
                        <div class="form-group">
                            <label>Nama Lengkap</label>
                            <input type="text" id="bsName">
                        </div>
                        <div class="form-group">
                            <label>Email</label>
                            <input type="email" id="bsEmail">
                        </div>
                        <div class="form-group">
                            <label>Password (min. 8 karakter)</label>
                            <input type="password" id="bsPassword">
                        </div>
                        <button class="btn btn-success" style="width: 100%;" onclick="bootstrapSuperadmin()">Buat Akun Super Admin</button>
                    </div>

                    <div id="otpPane" class="hidden">
                        <p style="font-size:12px; color:#666;">Kode OTP 6 digit sudah dikirim ke email <b id="otpEmailHint"></b>. Berlaku 5 menit.</p>
                        <div class="form-group">
                            <label>Kode OTP</label>
                            <input type="text" id="otpCode" maxlength="6" inputmode="numeric" placeholder="123456" style="letter-spacing:4px; font-size:18px; text-align:center;">
                        </div>
                        <button class="btn" style="width: 100%;" onclick="verifyOtp()">Verifikasi</button>
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-top:10px;">
                            <a href="#" onclick="cancelOtpFlow(); return false;" style="font-size:12px; color:#888;">&larr; Login ulang</a>
                            <a href="#" id="otpResendLink" onclick="resendOtp(); return false;" style="font-size:12px; color:#0056b3;">Kirim ulang kode</a>
                        </div>
                    </div>
                </div>

                <!-- 1. DASHBOARD -->
                <div id="tab-dashboard" class="tab-content hidden">
                    <div class="card">
                        <h2>Ringkasan Dashboard Utama</h2>
                        <div class="form-grid">
                            <div style="background:#e3f2fd; padding:15px; border-radius:6px; text-align:center;">
                                <h3 id="statPusat" style="margin:0; color:#0d47a1;">0</h3>
                                <small>Total Servis Pusat</small>
                            </div>
                            <div style="background:#e8f5e9; padding:15px; border-radius:6px; text-align:center;">
                                <h3 id="statCabang" style="margin:0; color:#1b5e20;">0</h3>
                                <small>Total Servis Cabang</small>
                            </div>
                            <div style="background:#fff3e0; padding:15px; border-radius:6px; text-align:center;">
                                <h3 id="statPickup" style="margin:0; color:#e65100;">0</h3>
                                <small>Servis Pickup Center</small>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- 2a/b/c DATA SERVICE (dibuat dari 1 template JS, id tetap unik per lokasi) -->
                <div id="tab-service-pusat" class="tab-content hidden"></div>
                <div id="tab-service-cabang" class="tab-content hidden"></div>
                <div id="tab-service-pickup" class="tab-content hidden"></div>

                <!-- 3. STATUS PAYMENT SERVICE (dibangun dari 1 template JS, lihat buildPaymentTabsHTML) -->
                <div id="tab-payment-pusat" class="tab-content hidden"></div>
                <div id="tab-payment-cabang" class="tab-content hidden"></div>
                <div id="tab-payment-pickup" class="tab-content hidden"></div>

                <!-- 4. INVENTORY PART (dibangun dari 1 template JS, lihat buildInventoryTabsHTML) -->
                <div id="tab-inventory-pusat" class="tab-content hidden"></div>
                <div id="tab-inventory-cabang" class="tab-content hidden"></div>

                <!-- 5. LAPORAN (dibangun dari 1 template JS, lihat buildLaporanTabsHTML) -->
                <div id="tab-laporan-service" class="tab-content hidden"></div>
                <div id="tab-laporan-payment" class="tab-content hidden"></div>
                <div id="tab-laporan-inventory" class="tab-content hidden"></div>

                <!-- 6. KELOLA USER (Super Admin) -->
                <div id="tab-setting-users" class="tab-content hidden">
                    <div class="card">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <h2 style="border:none; margin:0;">Kelola User per Departemen</h2>
                            <button class="btn btn-success" onclick="toggleUserForm()">+ Tambah User</button>
                        </div>

                        <div id="userFormBox" class="sparepart-box hidden" style="margin-top:12px; border:1px dashed #ccc; padding:10px; border-radius:6px;">
                            <div id="userFormTitle" style="font-weight:bold; color:#0056b3; margin-bottom:8px;">Tambah User Baru</div>
                            <input type="hidden" id="nuEditingId" value="">
                            <div class="form-grid">
                                <div class="form-group"><label>Nama Lengkap</label><input id="nuName"></div>
                                <div class="form-group"><label>Email</label><input id="nuEmail" type="email"></div>
                                <div class="form-group"><label id="nuPasswordLabel">Password</label><input id="nuPassword" type="password"></div>
                                <div class="form-group">
                                    <label>Role</label>
                                    <select id="nuRole" onchange="onRoleChange()">
                                        <option value="staff">Staff (dibatasi 1 departemen)</option>
                                        <option value="admin">Admin (akses semua, tanpa menu Setting)</option>
                                        <option value="superadmin">Super Admin (akses semua + Setting)</option>
                                    </select>
                                </div>
                                <div class="form-group" id="nuDeptWrap">
                                    <label>Departemen</label>
                                    <select id="nuDept">
                                        <option value="pusat">Pusat</option>
                                        <option value="cabang">Cabang</option>
                                        <option value="pickup">Pickup Center</option>
                                    </select>
                                </div>
                            </div>
                            <div style="display:flex; gap:10px;">
                                <button class="btn btn-secondary" onclick="toggleUserForm()">Batal</button>
                                <button class="btn btn-success" id="userSaveBtn" onclick="createUser()">Simpan User</button>
                            </div>
                        </div>

                        <table style="margin-top:15px;">
                            <thead><tr><th>Nama</th><th>Email</th><th>Role</th><th>Departemen</th><th>Status</th><th>Aksi</th></tr></thead>
                            <tbody id="tableUsers"></tbody>
                        </table>
                    </div>
                </div>

                <!-- 4b. KELOLA MODEL ALAT (Super Admin) -->
                <div id="tab-setting-devicemodels" class="tab-content hidden">
                    <div class="card">
                        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
                            <h2 style="border:none; margin:0;">Kelola Model Alat per Kategori</h2>
                            <div style="display:flex; gap:10px;">
                                <button class="btn btn-secondary" onclick="document.getElementById('dmExcelFileInput').click()">📤 Upload dari Excel</button>
                                <input type="file" id="dmExcelFileInput" accept=".xlsx,.xlsm" style="display:none;" onchange="uploadDeviceModelExcel(this)">
                                <button class="btn btn-success" onclick="toggleDeviceModelForm()">+ Tambah Model</button>
                            </div>
                        </div>
                        <p style="font-size:12px; color:#666;">Model yang ditambahkan di sini akan otomatis muncul di dropdown "Model Alat" pada form input tiket, sesuai Kategori Produk yang dipilih.</p>
                        <p style="font-size:12px; color:#666;">
                            <strong>Upload dari Excel:</strong> file .xlsx 2 kolom (Model Alat, Produk Kategori - urutan kolom tidak masalah, terdeteksi otomatis).
                            Data yang sudah ada TIDAK PERNAH hilang/tertimpa - hanya ditambahkan kalau belum ada, atau diaktifkan lagi kalau sebelumnya dinonaktifkan.
                        </p>

                        <div id="deviceModelFormBox" class="hidden" style="margin-top:12px; border:1px dashed #ccc; padding:10px; border-radius:6px;">
                            <div class="form-grid">
                                <div class="form-group">
                                    <label>Kategori Produk</label>
                                    <select id="dmCategory">
                                        <option value="Arm BPM">Arm BPM</option>
                                        <option value="BCM">BCM</option>
                                        <option value="BGM">BGM</option>
                                        <option value="Comp-NEB">Comp-NEB</option>
                                        <option value="DWS">DWS</option>
                                        <option value="Ear Thermo">Ear Thermo</option>
                                        <option value="Forehead Thermo">Forehead Thermo</option>
                                        <option value="MEDICAL">MEDICAL</option>
                                        <option value="Mesh-NEB">Mesh-NEB</option>
                                        <option value="Pen Thermo">Pen Thermo</option>
                                        <option value="TENS">TENS</option>
                                        <option value="Ultra-NEB">Ultra-NEB</option>
                                        <option value="Wrist BPM">Wrist BPM</option>
                                        <option value="Others">Others</option>
                                    </select>
                                </div>
                                <div class="form-group"><label>Nama Model</label><input id="dmModelName" placeholder="Contoh: HEM-7120"></div>
                            </div>
                            <button class="btn btn-success" onclick="createDeviceModel()">Simpan Model</button>
                        </div>

                        <table style="margin-top:15px;">
                            <thead><tr><th>Kategori</th><th>Nama Model</th><th>Aksi</th></tr></thead>
                            <tbody id="tableDeviceModels"></tbody>
                        </table>
                    </div>
                </div>

                <!-- 4c. KELOLA CABANG (Super Admin) -->
                <div id="tab-setting-branches" class="tab-content hidden">
                    <div class="card">
                        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
                            <h2 style="border:none; margin:0;">Kelola Cabang</h2>
                            <div style="display:flex; gap:10px;">
                                <button class="btn btn-secondary" onclick="document.getElementById('branchExcelFileInput').click()">📤 Upload dari Excel</button>
                                <input type="file" id="branchExcelFileInput" accept=".xlsx,.xlsm" style="display:none;" onchange="uploadBranchExcel(this)">
                                <button class="btn btn-success" onclick="toggleBranchForm()">+ Tambah Cabang</button>
                            </div>
                        </div>
                        <p style="font-size:12px; color:#666;">
                            <strong>Upload dari Excel:</strong> file .xlsx kolom (Nama Cabang, Kode Store, Handle by, Kota, Alamat).
                            Kode Store yang sudah ada akan diperbarui datanya; yang belum ada akan ditambahkan. Cabang lama yang tidak disebut di file tidak akan disentuh.
                        </p>

                        <div id="branchFormBox" class="hidden" style="margin-top:12px; border:1px dashed #ccc; padding:10px; border-radius:6px;">
                            <div id="branchFormTitle" style="font-weight:bold; color:#0056b3; margin-bottom:8px;">Tambah Cabang Baru</div>
                            <input type="hidden" id="branchEditingId" value="">
                            <div class="form-grid">
                                <div class="form-group"><label>Nama Cabang <span class="required">*</span></label><input id="branchName" placeholder="Contoh: OEC-Medan"></div>
                                <div class="form-group"><label>Kode Store <span class="required">*</span></label><input id="branchCode" placeholder="Contoh: MDN"></div>
                                <div class="form-group"><label>Handle by</label><input id="branchHandledBy" placeholder="Contoh: Mitracare"></div>
                                <div class="form-group"><label>Kota</label><input id="branchCity" placeholder="Contoh: Medan"></div>
                                <div class="form-group" style="grid-column:1/-1;"><label>Alamat</label><input id="branchAddress" placeholder="Alamat lengkap"></div>
                            </div>
                            <div style="display:flex; gap:10px; justify-content:flex-end;">
                                <button class="btn btn-secondary" onclick="toggleBranchForm()">Batal</button>
                                <button class="btn btn-success" id="branchSaveBtn" onclick="saveBranch()">Simpan Cabang</button>
                            </div>
                        </div>

                        <table style="margin-top:15px;">
                            <thead><tr><th>Nama Cabang</th><th>Kode</th><th>Handle by</th><th>Kota</th><th>Alamat</th><th>Status</th><th>Aksi</th></tr></thead>
                            <tbody id="tableBranches"></tbody>
                        </table>
                    </div>
                </div>

                <!-- 4d. KELOLA PICKUP CENTER (Super Admin) -->
                <div id="tab-setting-pickupcenters" class="tab-content hidden">
                    <div class="card">
                        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
                            <h2 style="border:none; margin:0;">Kelola Pickup Center</h2>
                            <div style="display:flex; gap:10px;">
                                <button class="btn btn-secondary" onclick="document.getElementById('pickupExcelFileInput').click()">📤 Upload dari Excel</button>
                                <input type="file" id="pickupExcelFileInput" accept=".xlsx,.xlsm" style="display:none;" onchange="uploadPickupExcel(this)">
                                <button class="btn btn-success" onclick="togglePickupForm()">+ Tambah Pickup Center</button>
                            </div>
                        </div>
                        <p style="font-size:12px; color:#666;">
                            <strong>Upload dari Excel:</strong> file .xlsx kolom (Store Long Code, Store Name, Store Address, City).
                            Store Long Code yang sudah ada akan diperbarui datanya; yang belum ada akan ditambahkan. Data lama yang tidak disebut di file tidak akan disentuh.
                        </p>

                        <div id="pickupFormBox" class="hidden" style="margin-top:12px; border:1px dashed #ccc; padding:10px; border-radius:6px;">
                            <div id="pickupFormTitle" style="font-weight:bold; color:#0056b3; margin-bottom:8px;">Tambah Pickup Center Baru</div>
                            <input type="hidden" id="pickupEditingId" value="">
                            <div class="form-grid">
                                <div class="form-group"><label>Store Long Code <span class="required">*</span></label><input id="pickupCode" placeholder="Contoh: 0001 - JKJSTT1"></div>
                                <div class="form-group"><label>Store Name <span class="required">*</span></label><input id="pickupName" placeholder="Contoh: APOTEK ALPRO TEBET TIMUR"></div>
                                <div class="form-group"><label>City</label><input id="pickupCity" placeholder="Contoh: JAKARTA SELATAN"></div>
                                <div class="form-group" style="grid-column:1/-1;"><label>Store Address</label><input id="pickupAddress" placeholder="Alamat lengkap"></div>
                            </div>
                            <div style="display:flex; gap:10px; justify-content:flex-end;">
                                <button class="btn btn-secondary" onclick="togglePickupForm()">Batal</button>
                                <button class="btn btn-success" id="pickupSaveBtn" onclick="savePickupCenter()">Simpan Pickup Center</button>
                            </div>
                        </div>

                        <input type="text" id="searchPickupCenters" class="search-input" placeholder="Cari nama/kode/kota..." style="margin-top:10px; width:100%;" onkeyup="filterPickupCenterTable()">
                        <table style="margin-top:15px;">
                            <thead><tr><th>Store Long Code</th><th>Store Name</th><th>City</th><th>Store Address</th><th>Status</th><th>Aksi</th></tr></thead>
                            <tbody id="tablePickupCenters"></tbody>
                        </table>
                    </div>
                </div>

            </div>
        </main>

        <script>
            let authToken = localStorage.getItem('omron_token') || '';
            let currentRole = localStorage.getItem('omron_role') || '';
            let currentDept = localStorage.getItem('omron_dept') || '';

            const LOCATIONS = [
                { key: 'pusat',  label: 'Pusat',          prefix: 'JKT' },
                { key: 'cabang', label: 'Cabang',         prefix: 'CBG' },
                { key: 'pickup', label: 'Pickup Center',  prefix: 'PKP' },
            ];

            window.onload = async function() {
                buildServiceTabsHTML();
                buildInventoryTabsHTML();
                buildPaymentTabsHTML();
                buildLaporanTabsHTML();
                if (authToken) {
                    await enterDashboard();
                } else {
                    await checkBootstrapStatus();
                }
            };

            // ---------- AUTH ----------

            async function checkBootstrapStatus() {
                try {
                    const res = await fetch('/api/v1/auth/bootstrap-status');
                    const data = await res.json();
                    if (data.needs_bootstrap) switchAuthTab('bootstrap');
                } catch(e) {}
            }

            function switchAuthTab(which) {
                document.getElementById('authError').style.display = 'none';
                document.getElementById('tabLoginBtn').classList.toggle('active', which === 'login');
                document.getElementById('tabBootstrapBtn').classList.toggle('active', which === 'bootstrap');
                document.getElementById('loginPane').classList.toggle('hidden', which !== 'login');
                document.getElementById('bootstrapPane').classList.toggle('hidden', which !== 'bootstrap');
                document.getElementById('otpPane').classList.add('hidden');
                pendingOtpToken = null;
            }

            function showAuthError(msg) {
                const box = document.getElementById('authError');
                box.textContent = msg;
                box.style.display = 'block';
            }

            async function authFetch(url, options = {}) {
                options.headers = Object.assign({}, options.headers, {
                    'Authorization': 'Bearer ' + authToken,
                });
                const res = await fetch(url, options);
                if (res.status === 401) {
                    logout();
                    throw new Error('Sesi berakhir, silakan login kembali.');
                }
                return res;
            }

            async function bootstrapSuperadmin() {
                const full_name = document.getElementById('bsName').value.trim();
                const email = document.getElementById('bsEmail').value.trim();
                const password = document.getElementById('bsPassword').value;
                if (!full_name || !email || !password) return showAuthError('Semua field wajib diisi.');

                try {
                    const res = await fetch('/api/v1/auth/bootstrap', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ full_name, email, password })
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Gagal membuat Super Admin.');
                    alert('Akun Super Admin berhasil dibuat! Silakan login.');
                    switchAuthTab('login');
                    document.getElementById('loginEmail').value = email;
                } catch(e) {
                    showAuthError(e.message);
                }
            }

            let pendingOtpToken = null; // pre_auth_token dari /login saat menunggu verifikasi OTP

            function applyLoginToken(tokenObj) {
                authToken = tokenObj.access_token;
                currentRole = tokenObj.role;
                currentDept = tokenObj.department || '';
                localStorage.setItem('omron_token', authToken);
                localStorage.setItem('omron_role', currentRole);
                localStorage.setItem('omron_dept', currentDept);
            }

            async function login() {
                const email = document.getElementById('loginEmail').value.trim();
                const password = document.getElementById('loginPassword').value;
                if (!email || !password) return showAuthError('Email dan password wajib diisi.');

                try {
                    const res = await fetch('/api/v1/auth/login', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ email, password })
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Login gagal.');

                    if (data.otp_required) {
                        // Role ini (saat ini: superadmin) wajib verifikasi kode
                        // OTP dari email dulu - token BELUM diterbitkan.
                        pendingOtpToken = data.pre_auth_token;
                        document.getElementById('otpEmailHint').innerText = data.email_hint || '';
                        document.getElementById('otpCode').value = '';
                        document.getElementById('loginPane').classList.add('hidden');
                        document.getElementById('bootstrapPane').classList.add('hidden');
                        document.getElementById('otpPane').classList.remove('hidden');
                        document.getElementById('authError').style.display = 'none';
                        return;
                    }

                    applyLoginToken(data.token);
                    await enterDashboard();
                } catch(e) {
                    showAuthError(e.message);
                }
            }

            async function verifyOtp() {
                const code = document.getElementById('otpCode').value.trim();
                if (!code || code.length !== 6) return showAuthError('Kode OTP harus 6 digit.');
                if (!pendingOtpToken) return cancelOtpFlow();

                try {
                    const res = await fetch('/api/v1/auth/verify-otp', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ pre_auth_token: pendingOtpToken, code })
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Verifikasi OTP gagal.');

                    pendingOtpToken = null;
                    applyLoginToken(data);
                    await enterDashboard();
                } catch(e) {
                    showAuthError(e.message);
                }
            }

            async function resendOtp() {
                if (!pendingOtpToken) return cancelOtpFlow();
                const link = document.getElementById('otpResendLink');
                const originalText = link.innerText;
                link.innerText = 'Mengirim...';
                try {
                    const res = await fetch('/api/v1/auth/resend-otp', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ pre_auth_token: pendingOtpToken })
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Gagal mengirim ulang kode.');
                    alert('Kode OTP baru sudah dikirim ke email Anda.');
                } catch(e) {
                    showAuthError(e.message);
                } finally {
                    link.innerText = originalText;
                }
            }

            function cancelOtpFlow() {
                pendingOtpToken = null;
                document.getElementById('otpPane').classList.add('hidden');
                document.getElementById('loginPane').classList.remove('hidden');
                document.getElementById('loginPassword').value = '';
                document.getElementById('authError').style.display = 'none';
            }

            function logout() {
                localStorage.removeItem('omron_token');
                localStorage.removeItem('omron_role');
                localStorage.removeItem('omron_dept');
                location.reload();
            }

            async function enterDashboard() {
                document.getElementById('authCard').classList.add('hidden');
                document.getElementById('sidebar').classList.remove('hidden');
                document.getElementById('btnLogout').classList.remove('hidden');

                const FULL_ACCESS_ROLES = ['superadmin', 'admin']; // akses semua departemen (beda dgn staff)
                const hasFullAccess = FULL_ACCESS_ROLES.includes(currentRole);

                document.getElementById('userStatus').innerText =
                    currentRole === 'superadmin' ? 'Super Admin'
                    : currentRole === 'admin' ? 'Admin'
                    : `Staff - ${currentDept}`;

                // Menu "Setting" SENGAJA HANYA utk 'superadmin' - role 'admin'
                // sengaja TIDAK dimasukkan di sini walau akses datanya sama
                // luasnya dgn superadmin (sesuai permintaan: admin = akses
                // penuh KECUALI menu Setting).
                document.getElementById('menu-setting').style.display = (currentRole === 'superadmin') ? '' : 'none';

                // Staff dibatasi hanya lihat departemennya sendiri. Admin (spt
                // superadmin) melihat SEMUA departemen tanpa dibatasi.
                document.querySelectorAll('[data-loc]').forEach(el => {
                    const loc = el.getAttribute('data-loc');
                    if (!hasFullAccess && loc !== currentDept) {
                        el.parentElement.style.display = 'none';
                    }
                });

                const startTab = hasFullAccess ? 'dashboard' : `service-${currentDept}`;
                showTab(startTab);
            }

            function toggleSubmenu(id) {
                const target = document.getElementById(id);
                const willOpen = !target.classList.contains('open');
                // Tutup SEMUA submenu lain dulu - hanya satu submenu yang boleh
                // terbuka di satu waktu, supaya tidak ada 2+ submenu "nyangkut"
                // terbuka bersamaan seperti yang dilaporkan.
                document.querySelectorAll('aside .submenu').forEach(el => el.classList.remove('open'));
                if (willOpen) target.classList.add('open');
            }

            // Pemetaan tabId -> id submenu induknya, dipakai supaya begitu suatu
            // halaman ditampilkan (showTab), submenu yang BENAR ikut terbuka dan
            // submenu lain otomatis tertutup - konsisten baik dibuka lewat klik
            // judul menu MAUPUN lewat klik link di dalam submenu.
            const SUBMENU_FOR_TAB_PREFIX = [
                { prefix: 'service-', submenuId: 'sub-service' },
                { prefix: 'payment-', submenuId: 'sub-payment' },
                { prefix: 'inventory-', submenuId: 'sub-inventory' },
                { prefix: 'laporan-', submenuId: 'sub-laporan' },
                { prefix: 'setting-', submenuId: 'sub-setting' },
            ];
            function openSubmenuForTab(tabId) {
                const match = SUBMENU_FOR_TAB_PREFIX.find(m => tabId.startsWith(m.prefix));
                document.querySelectorAll('aside .submenu').forEach(el => el.classList.remove('open'));
                if (match) document.getElementById(match.submenuId).classList.add('open');
            }

            // ---------- DATA REFERENSI (statis, tidak perlu API) ----------

            const PRODUCT_CATEGORIES = ["Arm BPM","BCM","BGM","Comp-NEB","DWS","Ear Thermo","Forehead Thermo","MEDICAL","Mesh-NEB","Pen Thermo","TENS","Ultra-NEB","Wrist BPM","Others"];
            const PRODUCT_ORIGINS = ["LEU","EU-DRC","AMS","IDC","APT/TKO","CV/PT/RS","ALPRO"];
            const WARRANTY_STATUS_OPTIONS = ["Under Warranty","Out of Warranty"];
            const WARRANTY_PERIOD_OPTIONS = ["1","2","3","4","5","6"];
            const REMARKS_OPTIONS = ["Compliance Check/Sensor Check","Repair","Replace Product/Claim","Unrepairable/Return to Customer","Disagree with Service Fee","No Response"];
            const REPAIR_STATUS_OPTIONS = ["Diterima","Diproses","Selesai/Dikirim","Selesai Diambil","Menunggu Sparepart"];
            const PICKUP_REPAIR_STATUS_OPTIONS = [
                "Diterima di PKP", "Diteruskan ke Omron", "Diterima di Omron", "Diproses di Omron",
                "Selesai/Dikirim balik ke PKP", "Diterima kembali di PKP", "Menunggu Sparepart",
            ];
            function repairStatusOptionsFor(locKey) {
                return locKey === 'pickup' ? PICKUP_REPAIR_STATUS_OPTIONS : REPAIR_STATUS_OPTIONS;
            }
const PROVINCE_CITY_DATA = {"Aceh": ["Banda Aceh", "Langsa", "Lhokseumawe", "Sabang", "Meulaboh", "Aceh Besar", "Aceh Utara", "Aceh Tengah"], "Sumatera Utara": ["Medan", "Binjai", "Pematangsiantar", "Tebing Tinggi", "Sibolga", "Tanjungbalai", "Padang Sidempuan", "Deli Serdang", "Karo"], "Sumatera Barat": ["Padang", "Bukittinggi", "Padang Panjang", "Payakumbuh", "Sawahlunto", "Solok", "Pariaman", "Agam"], "Riau": ["Pekanbaru", "Dumai", "Kampar", "Bengkalis", "Indragiri Hulu", "Indragiri Hilir", "Rokan Hulu", "Rokan Hilir"], "Kepulauan Riau": ["Batam", "Tanjungpinang", "Bintan", "Karimun", "Natuna", "Lingga"], "Jambi": ["Jambi", "Sungai Penuh", "Batanghari", "Bungo", "Kerinci", "Merangin", "Muaro Jambi"], "Sumatera Selatan": ["Palembang", "Lubuklinggau", "Pagar Alam", "Prabumulih", "Ogan Komering Ilir", "Ogan Komering Ulu", "Musi Banyuasin", "Musi Rawas"], "Bangka Belitung": ["Pangkal Pinang", "Bangka", "Bangka Barat", "Bangka Tengah", "Bangka Selatan", "Belitung", "Belitung Timur"], "Bengkulu": ["Bengkulu", "Rejang Lebong", "Bengkulu Utara", "Bengkulu Selatan", "Kepahiang", "Kaur"], "Lampung": ["Bandar Lampung", "Metro", "Lampung Selatan", "Lampung Tengah", "Lampung Utara", "Lampung Timur", "Tulang Bawang", "Pesawaran"], "DKI Jakarta": ["Jakarta Pusat", "Jakarta Utara", "Jakarta Barat", "Jakarta Selatan", "Jakarta Timur", "Kepulauan Seribu"], "Jawa Barat": ["Bandung", "Bekasi", "Bogor", "Depok", "Cimahi", "Sukabumi", "Tasikmalaya", "Cirebon", "Banjar", "Karawang", "Purwakarta", "Subang", "Garut", "Ciamis"], "Banten": ["Serang", "Tangerang", "Tangerang Selatan", "Cilegon", "Pandeglang", "Lebak"], "Jawa Tengah": ["Semarang", "Surakarta", "Salatiga", "Magelang", "Pekalongan", "Tegal", "Purwokerto", "Kudus", "Klaten", "Sukoharjo", "Boyolali", "Sragen", "Cilacap"], "DI Yogyakarta": ["Yogyakarta", "Sleman", "Bantul", "Kulon Progo", "Gunungkidul"], "Jawa Timur": ["Surabaya", "Malang", "Kediri", "Madiun", "Blitar", "Mojokerto", "Pasuruan", "Probolinggo", "Batu", "Sidoarjo", "Gresik", "Jember", "Banyuwangi", "Tuban"], "Bali": ["Denpasar", "Badung", "Gianyar", "Tabanan", "Buleleng", "Karangasem", "Klungkung", "Bangli", "Jembrana"], "Nusa Tenggara Barat": ["Mataram", "Bima", "Lombok Barat", "Lombok Tengah", "Lombok Timur", "Lombok Utara", "Sumbawa", "Dompu"], "Nusa Tenggara Timur": ["Kupang", "Ende", "Maumere", "Manggarai", "Manggarai Barat", "Sumba Timur", "Sumba Barat", "Timor Tengah Selatan"], "Kalimantan Barat": ["Pontianak", "Singkawang", "Sambas", "Kubu Raya", "Ketapang", "Sanggau", "Sintang"], "Kalimantan Tengah": ["Palangka Raya", "Kotawaringin Barat", "Kotawaringin Timur", "Kapuas", "Barito Utara", "Barito Selatan"], "Kalimantan Selatan": ["Banjarmasin", "Banjarbaru", "Banjar", "Barito Kuala", "Tanah Laut", "Hulu Sungai Utara", "Hulu Sungai Selatan"], "Kalimantan Timur": ["Samarinda", "Balikpapan", "Bontang", "Kutai Kartanegara", "Kutai Timur", "Kutai Barat", "Berau", "Paser"], "Kalimantan Utara": ["Tarakan", "Bulungan", "Malinau", "Nunukan", "Tana Tidung"], "Sulawesi Utara": ["Manado", "Bitung", "Tomohon", "Kotamobagu", "Minahasa", "Minahasa Utara", "Minahasa Selatan"], "Gorontalo": ["Gorontalo", "Boalemo", "Bone Bolango", "Gorontalo Utara", "Pohuwato"], "Sulawesi Tengah": ["Palu", "Poso", "Banggai", "Donggala", "Toli-Toli", "Parigi Moutong", "Morowali"], "Sulawesi Barat": ["Mamuju", "Majene", "Polewali Mandar", "Mamasa", "Pasangkayu"], "Sulawesi Selatan": ["Makassar", "Parepare", "Palopo", "Gowa", "Maros", "Bone", "Bulukumba", "Pinrang", "Wajo", "Sidenreng Rappang"], "Sulawesi Tenggara": ["Kendari", "Baubau", "Kolaka", "Konawe", "Muna", "Bombana", "Wakatobi"], "Maluku": ["Ambon", "Tual", "Maluku Tengah", "Maluku Tenggara", "Buru", "Seram Bagian Barat"], "Maluku Utara": ["Ternate", "Tidore Kepulauan", "Halmahera Barat", "Halmahera Utara", "Halmahera Tengah", "Halmahera Selatan"], "Papua": ["Jayapura", "Keerom", "Sarmi", "Biak Numfor", "Jayawijaya", "Nabire", "Mimika", "Merauke"], "Papua Barat": ["Manokwari", "Sorong", "Fakfak", "Kaimana", "Teluk Bintuni", "Teluk Wondama", "Raja Ampat"], "Papua Barat Daya": ["Sorong", "Sorong Selatan", "Tambrauw", "Maybrat", "Raja Ampat"], "Papua Tengah": ["Nabire", "Paniai", "Mimika", "Puncak", "Puncak Jaya", "Dogiyai", "Deiyai"], "Papua Pegunungan": ["Jayawijaya", "Pegunungan Bintang", "Yahukimo", "Tolikara", "Yalimo", "Lanny Jaya", "Nduga"], "Papua Selatan": ["Merauke", "Boven Digoel", "Mappi", "Asmat"]};

            function opts(list, selected) {
                return list.map(v => `<option value="${v}" ${v === selected ? 'selected' : ''}>${v}</option>`).join('\\n');
            }

            // ---------- BANGUN TAB DATA SERVICE DARI 1 TEMPLATE (fix bug duplikat id form) ----------

            function buildServiceTabsHTML() {
                LOCATIONS.forEach(loc => {
                    const k = loc.key;
                    const root = document.getElementById(`tab-service-${k}`);
                    root.innerHTML = `
                        <div id="view-table-service-${k}" class="card">
                            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
                                <h2 style="margin:0; border:none;">Data Service - ${loc.label}</h2>
                                <div class="action-header">
                                    <input type="text" id="search-service-${k}" class="search-input" placeholder="Cari tiket / nama / SN...">
                                    <button class="btn btn-success" onclick="showFormInPage('${k}')">+ Input Tiket ${loc.label.toUpperCase()}</button>
                                </div>
                            </div>
                            <table>
                                <thead>
                                    <tr><th>No. Tiket</th><th>Pemilik</th><th>Instansi</th><th>Model Alat</th><th>Serial No.</th><th>Garansi</th><th>Keluhan</th><th>Status</th><th>Tgl Diterima</th><th>Aksi</th></tr>
                                </thead>
                                <tbody id="tableService-${k}"></tbody>
                            </table>
                        </div>

                        <div id="view-form-service-${k}" class="card hidden">
                            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px; border-bottom:2px solid #0056b3; padding-bottom:10px;">
                                <h2 id="ticketFormTitle-${k}" style="margin:0; border:none;">Form Input Tiket Servis - ${loc.label} (${loc.prefix})</h2>
                                <button class="btn btn-secondary" onclick="hideFormInPage('${k}')">← Kembali ke Tabel</button>
                            </div>
                            <div style="background:#e3f2fd; padding:10px; border-radius:5px; font-size:12px; margin-bottom:15px; color:#0d47a1;">
                                ℹ️ Tiket ini akan terdaftar KHUSUS di data <strong>${loc.label}</strong> saja - tidak akan tampil atau tercatat di lokasi lain.
                            </div>

                            <div class="form-section-title">1. Data Pelanggan</div>
                            <div class="form-grid">
                                <div class="form-group"><label>Nama Customer <span class="required">*</span></label><input id="inpName-${k}" placeholder="Contoh: Budi Santoso"></div>
                                <div class="form-group">
                                    <label>Nama Instansi</label>
                                    <input id="inpInstansi-${k}" placeholder="Contoh: RS Harapan Bunda" ${k === 'pickup' ? 'list="inpInstansiList-pickup"' : ''}>
                                    ${k === 'pickup' ? '<datalist id="inpInstansiList-pickup"></datalist>' : ''}
                                </div>
                                <div class="form-group"><label>No. HP / WhatsApp 1 <span class="required">*</span></label><input id="inpPhone1-${k}" placeholder="081234567890"></div>
                                <div class="form-group"><label>No. HP / WhatsApp 2</label><input id="inpPhone2-${k}" placeholder="(opsional)"></div>
                                <div class="form-group" style="grid-column: 1 / -1;"><label>Alamat</label><input id="inpAddress-${k}" placeholder="Alamat lengkap"></div>
                                <div class="form-group">
                                    <label>Provinsi</label>
                                    <select id="inpProvince-${k}" onchange="onProvinceChange('${k}')">
                                        <option value="">-- Pilih Provinsi --</option>
                                        ${Object.keys(PROVINCE_CITY_DATA).map(p => `<option value="${p}">${p}</option>`).join('')}
                                    </select>
                                </div>
                                <div class="form-group">
                                    <label>Kota</label>
                                    <select id="inpCity-${k}"><option value="">-- Pilih Provinsi dulu --</option></select>
                                </div>
                                <div class="form-group"><label>Tanggal Alat Diterima</label><input type="date" id="inpReceivedDate-${k}"></div>
                                <div class="form-group"><label>Tanggal Alat Selesai</label><input type="date" id="inpCompletedDate-${k}"></div>
                            </div>

                            <div class="form-section-title">2. Data Produk</div>
                            <div class="form-grid">
                                <div class="form-group">
                                    <label>Produk Kategori</label>
                                    <select id="inpCategory-${k}" onchange="onCategoryChange('${k}')">
                                        <option value="">-- Pilih Kategori --</option>
                                        ${opts(PRODUCT_CATEGORIES)}
                                    </select>
                                </div>
                                <div class="form-group">
                                    <label>Model Alat</label>
                                    <select id="inpModel-${k}"><option value="">-- Pilih Kategori dulu --</option></select>
                                </div>
                                <div class="form-group"><label>Serial No. Alat</label><input id="inpSN-${k}" placeholder="SN2026xxxx"></div>
                                <div class="form-group"><label>Aksesoris</label><input id="inpAccessories-${k}" placeholder="Contoh: Kabel, Adaptor"></div>
                                <div class="form-group">
                                    <label>Status Garansi</label>
                                    <select id="inpWarrantyStatus-${k}">
                                        <option value="">-- Belum Dipilih --</option>
                                        ${opts(WARRANTY_STATUS_OPTIONS, k === 'pickup' ? '' : 'Out of Warranty')}
                                    </select>
                                </div>
                                <div class="form-group">
                                    <label>Warranty Period (tahun)</label>
                                    <select id="inpWarrantyPeriod-${k}">
                                        <option value="">-- Pilih --</option>
                                        ${opts(WARRANTY_PERIOD_OPTIONS)}
                                    </select>
                                </div>
                                <div class="form-group">
                                    <label>Asal Produk</label>
                                    <select id="inpOrigin-${k}">
                                        <option value="">-- Pilih --</option>
                                        ${opts(PRODUCT_ORIGINS)}
                                    </select>
                                </div>
                            </div>

                            <div class="form-section-title">3. Data Servis</div>
                            <div class="form-grid">
                                <div class="form-group" style="grid-column: 1 / -1;"><label>Keluhan Pelanggan</label><input id="inpKeluhan-${k}" placeholder="Keluhan perangkat"></div>
                                <div class="form-group" style="grid-column: 1 / -1;"><label>Analisa Teknisi</label><input id="inpAnalysis-${k}" placeholder="Hasil analisa teknisi"></div>
                                <div class="form-group"><label>Symptom (Kode)</label><input id="inpSymptom-${k}" placeholder="Contoh: PCB-01"></div>
                                <div class="form-group"><label>Leadtime (hari)</label><input type="number" min="0" id="inpLeadtime-${k}" value="1"></div>
                                <div class="form-group">
                                    <label>Remarks</label>
                                    <select id="inpRemarks-${k}">
                                        <option value="">-- Pilih --</option>
                                        ${opts(REMARKS_OPTIONS)}
                                    </select>
                                </div>
                                <div class="form-group">
                                    <label>Repair Status</label>
                                    <select id="inpStatus-${k}">${opts(repairStatusOptionsFor(k), k === 'pickup' ? 'Diterima di PKP' : 'Diterima')}</select>
                                </div>
                                <div class="form-group" style="grid-column: 1 / -1;"><label>Catatan</label><input id="inpNotes-${k}" placeholder="Catatan tambahan"></div>
                            </div>

                            <div class="form-section-title">4. Sparepart (opsional, maksimal 3)</div>
                            ${[1,2,3].map(n => `
                            <div class="sparepart-box" style="background:#f8f9fa; border:1px dashed #ccc; padding:10px; border-radius:6px; margin-bottom:10px;">
                                <div style="font-weight:bold; font-size:12px; color:#0056b3; margin-bottom:8px;">Sparepart ${n}</div>
                                <div class="form-grid">
                                    <div class="form-group"><label>Nama Sparepart</label><input id="inpSpName${n}-${k}" placeholder="Nama sparepart"></div>
                                    <div class="form-group"><label>Jumlah</label><input type="number" min="0" id="inpSpQty${n}-${k}"></div>
                                    <div class="form-group"><label>Kode Sparepart</label><input id="inpSpCode${n}-${k}" placeholder="Kode/part number"></div>
                                    <div class="form-group"><label>Harga (Rp)</label><input type="number" min="0" id="inpSpPrice${n}-${k}"></div>
                                </div>
                            </div>
                            `).join('')}

                            <div class="form-section-title">5. Notifikasi</div>
                            <div class="form-grid">
                                <div class="form-group">
                                    <label>Receipt Service</label>
                                    <label style="font-weight:normal; display:inline-block; margin-right:15px;"><input type="checkbox" id="inpNotifReceiptWA-${k}" style="width:auto;"> via WhatsApp</label>
                                    <label style="font-weight:normal; display:inline-block;"><input type="checkbox" id="inpNotifReceiptEmail-${k}" style="width:auto;"> via Email</label>
                                </div>
                                <div class="form-group">
                                    <label>Service Report</label>
                                    <label style="font-weight:normal; display:inline-block; margin-right:15px;"><input type="checkbox" id="inpNotifReportWA-${k}" style="width:auto;"> via WhatsApp</label>
                                    <label style="font-weight:normal; display:inline-block;"><input type="checkbox" id="inpNotifReportEmail-${k}" style="width:auto;"> via Email</label>
                                </div>
                            </div>

                            <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:20px;">
                                <button class="btn btn-secondary" onclick="hideFormInPage('${k}')">Batal</button>
                                <button class="btn btn-success" id="ticketFormSaveBtn-${k}" onclick="savePageFormData('${k}')">Simpan ke Data ${loc.label.toUpperCase()}</button>
                            </div>
                        </div>
                    `;
                    document.getElementById(`search-service-${k}`).addEventListener('keyup', () => filterTable(k));
                });
            }

            function onProvinceChange(locKey) {
                const province = document.getElementById(`inpProvince-${locKey}`).value;
                const citySelect = document.getElementById(`inpCity-${locKey}`);
                const cities = PROVINCE_CITY_DATA[province] || [];
                citySelect.innerHTML = cities.length
                    ? `<option value="">-- Pilih Kota --</option>` + opts(cities)
                    : `<option value="">-- Pilih Provinsi dulu --</option>`;
            }

            async function onCategoryChange(locKey) {
                const category = document.getElementById(`inpCategory-${locKey}`).value;
                let modelEl = document.getElementById(`inpModel-${locKey}`);

                if (!category) {
                    if (modelEl.tagName !== 'SELECT') {
                        modelEl.outerHTML = `<select id="inpModel-${locKey}"><option value="">-- Pilih Kategori dulu --</option></select>`;
                    } else {
                        modelEl.innerHTML = `<option value="">-- Pilih Kategori dulu --</option>`;
                    }
                    return;
                }

                if (category === 'Others') {
                    // Others: model alat tidak wajib ada di katalog - ganti jadi input teks bebas.
                    modelEl.outerHTML = `<input id="inpModel-${locKey}" placeholder="Ketik nama model alat">`;
                    return;
                }

                // Kategori selain Others: pastikan elemennya <select>, lalu isi dari katalog.
                if (modelEl.tagName !== 'SELECT') {
                    modelEl.outerHTML = `<select id="inpModel-${locKey}"><option value="">Memuat...</option></select>`;
                } else {
                    modelEl.innerHTML = `<option value="">Memuat...</option>`;
                }
                modelEl = document.getElementById(`inpModel-${locKey}`); // ambil ulang referensi kalau tadi baru diganti tag-nya

                try {
                    const res = await authFetch(`/api/v1/device-models/?category=${encodeURIComponent(category)}`);
                    const models = res.ok ? await res.json() : [];
                    modelEl.innerHTML = models.length
                        ? `<option value="">-- Pilih Model --</option>` + models.map(m => `<option value="${esc(m.model_name)}">${esc(m.model_name)}</option>`).join('')
                        : `<option value="">(Belum ada model utk kategori ini - tambah di Kelola Model Alat)</option>`;
                } catch(e) {
                    modelEl.innerHTML = `<option value="">Gagal memuat model</option>`;
                }
            }

            function showTab(tabId) {
                document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
                const target = document.getElementById('tab-' + tabId);
                if (target) target.classList.remove('hidden');
                document.getElementById('pageTitle').innerText = 'Menu: ' + tabId.toUpperCase().replace(/-/g, ' ');
                openSubmenuForTab(tabId);

                if (tabId.startsWith('service-')) hideFormInPage(tabId.replace('service-', ''));
                if (tabId === 'setting-users') { renderUsers(); return; }
                if (tabId === 'setting-devicemodels') { renderDeviceModels(); return; }
                if (tabId === 'setting-branches') { renderBranches(); return; }
                if (tabId === 'setting-pickupcenters') { renderPickupCenters(); return; }
                if (tabId.startsWith('inventory-')) { renderInventoryStock(tabId.replace('inventory-', '')); return; }
                if (tabId.startsWith('laporan-')) { return; }  // halaman statis (form filter), tidak perlu fetch data tabel

                renderTableData(tabId);
                updateDashboardStats();
            }

            async function updateDashboardStats() {
                try {
                    const res = await authFetch('/api/v1/db/all-tickets');
                    if (res.ok) {
                        const data = await res.json();
                        document.getElementById('statPusat').innerText = data.filter(d => (d.service_type || '').toLowerCase() === 'pusat').length;
                        document.getElementById('statCabang').innerText = data.filter(d => (d.service_type || '').toLowerCase() === 'cabang').length;
                        document.getElementById('statPickup').innerText = data.filter(d => (d.service_type || '').toLowerCase() === 'pickup').length;
                    }
                } catch(e) {}
            }

            async function renderTableData(menu) {
                let endpoint = '/api/v1/db/all-tickets';
                if (menu.startsWith('service-') || menu.startsWith('payment-')) {
                    const srvType = menu.replace('service-', '').replace('payment-', '');
                    endpoint = '/api/v1/db/tickets/' + srvType;
                }
                try {
                    const res = await authFetch(endpoint);
                    if (res.ok) {
                        const data = await res.json();
                        if (menu.startsWith('payment-')) populatePaymentRows(menu, data);
                        else if (menu.startsWith('service-')) populateTableRows(menu.replace('service-', ''), data);
                    }
                } catch(e) { console.error('Error fetching database:', e); }
            }

            function populateTableRows(locKey, data) {
                const el = document.getElementById(`tableService-${locKey}`);
                if (!el) return;
                el.innerHTML = data.length ? data.map(d => `
                    <tr>
                        <td><a href="#" onclick="openEditTicket('${esc(d.ticket_number)}', '${locKey}'); return false;" style="font-weight:bold; text-decoration:underline; color:#0056b3; cursor:pointer;" title="Klik untuk buka/edit tiket">${esc(d.ticket_number)}</a></td>
                        <td>${esc(d.customer_name)}</td>
                        <td>${esc(d.instansi_name) || '-'}</td>
                        <td>${esc(d.device_model)}</td>
                        <td>${esc(d.serial_number) || '-'}</td>
                        <td>${esc(d.warranty_status) || '-'}</td>
                        <td>${esc(d.complaint) || '-'}</td>
                        <td><span class="badge badge-lunas">${esc(d.status) || 'Diterima'}</span></td>
                        <td>${d.received_date ? d.received_date.split('T')[0] : (d.created_at ? d.created_at.split('T')[0] : '-')}</td>
                        <td style="text-align:center;">
                            <a href="#" onclick="downloadTicketReport('${esc(d.ticket_number)}'); return false;" title="Download Service Report" style="font-weight:bold; text-decoration:underline; color:#0056b3; cursor:pointer;">D</a>
                        </td>
                    </tr>
                `).join('') : `<tr><td colspan="11" style="text-align:center;">Belum ada data di lokasi ini</td></tr>`;
            }

            function populatePaymentRows(menu, data) {
                const loc = menu.replace('payment-', '');
                // HANYA tiket dgn status garansi eksplisit "Out of Warranty" yang masuk
                // Tab Payment - tiket yang status garansinya masih kosong (belum
                // ditentukan tim Teknisi) TIDAK ditampilkan di sini.
                const filtered = data.filter(d => d.warranty_status === 'Out of Warranty');
                paymentRowsCache[loc] = filtered;
                const el = document.getElementById(`tablePayment-${loc}`);
                if (!el) return;
                el.innerHTML = filtered.length ? filtered.map(d => `
                    <tr>
                        <td><a href="#" onclick="openPaymentDetail('${esc(d.ticket_number)}', '${loc}'); return false;" style="font-weight:bold; text-decoration:underline; color:#0056b3; cursor:pointer;" title="Klik untuk kelola pembayaran">${esc(d.ticket_number)}</a></td>
                        <td>${esc(d.customer_name)}</td>
                        <td>${esc(d.device_model)}</td>
                        <td>Rp ${(d.total_price || 0).toLocaleString('id-ID')}</td>
                        <td><code>${esc(d.payment_code) || '-'}</code></td>
                        <td><span class="badge ${d.payment_status === 'Lunas' ? 'badge-lunas' : 'badge-pending'}">${esc(d.payment_status) || 'Belum Lunas'}</span></td>
                    </tr>
                `).join('') : `<tr><td colspan="6" style="text-align:center;">Tidak ada tiket Out of Warranty untuk pembayaran di lokasi ini.</td></tr>`;
            }

            function filterTable(locKey) {
                const q = document.getElementById(`search-service-${locKey}`).value.toLowerCase();
                document.querySelectorAll(`#tableService-${locKey} tr`).forEach(row => {
                    row.style.display = row.innerText.toLowerCase().includes(q) ? '' : 'none';
                });
            }

            let currentEditingTicket = {}; // { [locKey]: null | "JKT-2600001" }

            let pickupInstansiOptionsLoaded = false;
            async function loadPickupInstansiOptions() {
                if (pickupInstansiOptionsLoaded) return;
                try {
                    const res = await authFetch('/api/v1/pickup-centers/');
                    if (!res.ok) return;
                    const list = await res.json();
                    document.getElementById('inpInstansiList-pickup').innerHTML =
                        list.map(p => `<option value="${esc(p.store_name)}">`).join('');
                    pickupInstansiOptionsLoaded = true;
                } catch(e) { /* diamkan - field tetap bisa diisi manual */ }
            }

            function showFormInPage(locKey) {
                currentEditingTicket[locKey] = null; // mode CREATE (bukan edit)
                resetTicketForm(locKey);

                const loc = LOCATIONS.find(l => l.key === locKey);
                document.getElementById(`ticketFormTitle-${locKey}`).innerText =
                    `Form Input Tiket Servis - ${loc.label} (${loc.prefix})`;
                document.getElementById(`ticketFormSaveBtn-${locKey}`).innerText =
                    `Simpan ke Data ${loc.label.toUpperCase()}`;

                if (locKey === 'pickup') loadPickupInstansiOptions();

                document.getElementById('view-table-service-' + locKey).classList.add('hidden');
                document.getElementById('view-form-service-' + locKey).classList.remove('hidden');
            }

            async function openEditTicket(ticketNumber, locKey) {
                // Dipanggil saat NOMOR TIKET diklik di tabel - memuat data tiket yang
                // sudah ada ke form yang sama, lalu form disimpan lewat PUT (update),
                // bukan POST (create baru).
                try {
                    if (locKey === 'pickup') loadPickupInstansiOptions();
                    const res = await authFetch(`/api/v1/db/tickets/detail/${encodeURIComponent(ticketNumber)}`);
                    if (!res.ok) {
                        const err = await res.json().catch(() => ({}));
                        throw new Error(err.detail || 'Gagal memuat data tiket.');
                    }
                    const t = await res.json();

                    currentEditingTicket[locKey] = ticketNumber;
                    await fillTicketForm(locKey, t);

                    document.getElementById(`ticketFormTitle-${locKey}`).innerText = `Edit Tiket ${ticketNumber}`;
                    document.getElementById(`ticketFormSaveBtn-${locKey}`).innerText = 'Update Tiket';

                    document.getElementById('view-table-service-' + locKey).classList.add('hidden');
                    document.getElementById('view-form-service-' + locKey).classList.remove('hidden');
                } catch(e) {
                    alert(e.message);
                }
            }

            async function fillTicketForm(locKey, t) {
                const k = locKey;
                setVal(`inpName-${k}`, t.customer_name || '');
                setVal(`inpInstansi-${k}`, t.instansi_name || '');
                setVal(`inpPhone1-${k}`, t.customer_phone || '');
                setVal(`inpPhone2-${k}`, t.customer_phone_2 || '');
                setVal(`inpAddress-${k}`, t.customer_address || '');
                setVal(`inpReceivedDate-${k}`, t.received_date ? t.received_date.split('T')[0] : '');
                setVal(`inpCompletedDate-${k}`, t.completed_date ? t.completed_date.split('T')[0] : '');

                setVal(`inpProvince-${k}`, t.province || '');
                onProvinceChange(k); // isi ulang dropdown Kota sesuai Provinsi
                setVal(`inpCity-${k}`, t.city || '');

                setVal(`inpCategory-${k}`, t.product_category || '');
                if (t.product_category) {
                    await onCategoryChange(k); // isi ulang dropdown Model sesuai Kategori (async, tunggu selesai)
                }
                setVal(`inpModel-${k}`, t.device_model || '');

                setVal(`inpSN-${k}`, t.serial_number || '');
                setVal(`inpAccessories-${k}`, t.accessories || '');
                setVal(`inpWarrantyStatus-${k}`, t.warranty_status || '');
                setVal(`inpWarrantyPeriod-${k}`, t.warranty_period || '');
                setVal(`inpOrigin-${k}`, t.product_origin || '');

                setVal(`inpKeluhan-${k}`, t.complaint || '');
                setVal(`inpAnalysis-${k}`, t.technician_analysis || '');
                setVal(`inpSymptom-${k}`, t.symptom_code || '');
                setVal(`inpLeadtime-${k}`, t.leadtime_days != null ? t.leadtime_days : 1);
                setVal(`inpRemarks-${k}`, t.remarks || '');
                setVal(`inpStatus-${k}`, t.status || (k === 'pickup' ? 'Diterima di PKP' : 'Diterima'));
                setVal(`inpNotes-${k}`, t.notes || '');

                const spareparts = t.spareparts || [];
                [1, 2, 3].forEach(n => {
                    const sp = spareparts.find(s => s.slot_no === n);
                    setVal(`inpSpName${n}-${k}`, sp && sp.name ? sp.name : '');
                    setVal(`inpSpQty${n}-${k}`, sp && sp.quantity != null ? sp.quantity : '');
                    setVal(`inpSpCode${n}-${k}`, sp && sp.code ? sp.code : '');
                    setVal(`inpSpPrice${n}-${k}`, sp && sp.price != null ? sp.price : '');
                });

                document.getElementById(`inpNotifReceiptWA-${k}`).checked = !!t.notif_receipt_whatsapp;
                document.getElementById(`inpNotifReceiptEmail-${k}`).checked = !!t.notif_receipt_email;
                document.getElementById(`inpNotifReportWA-${k}`).checked = !!t.notif_report_whatsapp;
                document.getElementById(`inpNotifReportEmail-${k}`).checked = !!t.notif_report_email;
            }

            async function downloadTicketReport(ticketNumber) {
                try {
                    const res = await authFetch(`/api/v1/db/tickets/${encodeURIComponent(ticketNumber)}/service-report`);
                    if (!res.ok) {
                        const err = await res.json().catch(() => ({}));
                        throw new Error(err.detail || 'Gagal mengunduh Service Report.');
                    }
                    const blob = await res.blob();
                    const dlUrl = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = dlUrl;
                    a.download = `ServiceReport-OEC-${ticketNumber}.xlsx`;
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    window.URL.revokeObjectURL(dlUrl);
                } catch(e) {
                    alert(e.message);
                }
            }

            function hideFormInPage(locKey) {
                const formView = document.getElementById('view-form-service-' + locKey);
                if (formView) formView.classList.add('hidden');
                const tableView = document.getElementById('view-table-service-' + locKey);
                if (tableView) tableView.classList.remove('hidden');
            }

            function setVal(id, value) {
                const el = document.getElementById(id);
                if (el) el.value = value;
            }

            function resetTicketForm(locKey) {
                // Dipanggil setiap kali form "+ Input Tiket" dibuka, supaya data dari
                // pengisian sebelumnya tidak ikut terbawa (form selalu mulai kosong).
                const k = locKey;

                setVal(`inpName-${k}`, '');
                setVal(`inpInstansi-${k}`, '');
                setVal(`inpPhone1-${k}`, '');
                setVal(`inpPhone2-${k}`, '');
                setVal(`inpAddress-${k}`, '');
                setVal(`inpReceivedDate-${k}`, '');
                setVal(`inpCompletedDate-${k}`, '');

                setVal(`inpProvince-${k}`, '');
                onProvinceChange(k);  // ikut kosongkan & reset dropdown Kota

                setVal(`inpCategory-${k}`, '');
                document.getElementById(`inpModel-${k}`).outerHTML =
                    `<select id="inpModel-${k}"><option value="">-- Pilih Kategori dulu --</option></select>`;

                setVal(`inpSN-${k}`, '');
                setVal(`inpAccessories-${k}`, '');
                setVal(`inpWarrantyStatus-${k}`, k === 'pickup' ? '' : 'Out of Warranty');
                setVal(`inpWarrantyPeriod-${k}`, '');
                setVal(`inpOrigin-${k}`, '');

                setVal(`inpKeluhan-${k}`, '');
                setVal(`inpAnalysis-${k}`, '');
                setVal(`inpSymptom-${k}`, '');
                setVal(`inpLeadtime-${k}`, '1');
                setVal(`inpRemarks-${k}`, '');
                setVal(`inpStatus-${k}`, k === 'pickup' ? 'Diterima di PKP' : 'Diterima');
                setVal(`inpNotes-${k}`, '');

                [1, 2, 3].forEach(n => {
                    setVal(`inpSpName${n}-${k}`, '');
                    setVal(`inpSpQty${n}-${k}`, '');
                    setVal(`inpSpCode${n}-${k}`, '');
                    setVal(`inpSpPrice${n}-${k}`, '');
                });

                ['inpNotifReceiptWA', 'inpNotifReceiptEmail', 'inpNotifReportWA', 'inpNotifReportEmail'].forEach(prefix => {
                    const el = document.getElementById(`${prefix}-${k}`);
                    if (el) el.checked = false;
                });
            }

            // Escape HTML untuk SEMUA data yang berasal dari database sebelum dimasukkan
            // ke innerHTML - mencegah stored XSS (mis. dari form publik /pickup-intake
            // yang tidak butuh login, atau input customer_name/complaint di form tiket).
            function esc(value) {
                if (value === null || value === undefined) return '';
                return String(value)
                    .replace(/&/g, '&amp;')
                    .replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;')
                    .replace(/"/g, '&quot;')
                    .replace(/'/g, '&#39;');
            }

            function valOf(id) {
                const el = document.getElementById(id);
                return el ? el.value.trim() : '';
            }

            function toIsoOrNull(dateStr) {
                return dateStr ? new Date(dateStr + 'T00:00:00').toISOString() : null;
            }

            async function savePageFormData(locKey) {
                // Setiap input punya id unik per-lokasi (mis. inpName-pusat, inpName-cabang),
                // jadi TIDAK ADA LAGI risiko membaca data sisa dari form lokasi lain
                // yang sebelumnya pernah dibuka (bug id duplikat pada versi lama).
                const k = locKey;
                const name = valOf(`inpName-${k}`);
                const phone1 = valOf(`inpPhone1-${k}`);

                if (!name || !phone1) return alert('Nama Customer dan No. HP/WhatsApp 1 Wajib Diisi!');

                const spareparts = [1, 2, 3].map(n => ({
                    name: valOf(`inpSpName${n}-${k}`) || null,
                    quantity: valOf(`inpSpQty${n}-${k}`) ? parseInt(valOf(`inpSpQty${n}-${k}`)) : null,
                    code: valOf(`inpSpCode${n}-${k}`) || null,
                    price: valOf(`inpSpPrice${n}-${k}`) ? parseFloat(valOf(`inpSpPrice${n}-${k}`)) : null,
                }));

                const payload = {
                    service_type: k,
                    customer_name: name,
                    instansi_name: valOf(`inpInstansi-${k}`) || null,
                    customer_phone: phone1,
                    customer_phone_2: valOf(`inpPhone2-${k}`) || null,
                    customer_address: valOf(`inpAddress-${k}`) || null,
                    province: valOf(`inpProvince-${k}`) || null,
                    city: valOf(`inpCity-${k}`) || null,
                    received_date: toIsoOrNull(valOf(`inpReceivedDate-${k}`)),
                    completed_date: toIsoOrNull(valOf(`inpCompletedDate-${k}`)),
                    product_category: valOf(`inpCategory-${k}`) || null,
                    device_model: valOf(`inpModel-${k}`) || '-',
                    serial_number: valOf(`inpSN-${k}`) || '-',
                    accessories: valOf(`inpAccessories-${k}`) || null,
                    warranty_status: valOf(`inpWarrantyStatus-${k}`) || null,
                    warranty_period: valOf(`inpWarrantyPeriod-${k}`) || null,
                    product_origin: valOf(`inpOrigin-${k}`) || null,
                    complaint: valOf(`inpKeluhan-${k}`) || '-',
                    technician_analysis: valOf(`inpAnalysis-${k}`) || null,
                    symptom_code: valOf(`inpSymptom-${k}`) || null,
                    leadtime_days: valOf(`inpLeadtime-${k}`) ? parseInt(valOf(`inpLeadtime-${k}`)) : 1,
                    notes: valOf(`inpNotes-${k}`) || null,
                    remarks: valOf(`inpRemarks-${k}`) || null,
                    status: valOf(`inpStatus-${k}`) || 'Diterima',
                    spareparts: spareparts,
                    notif_receipt_whatsapp: document.getElementById(`inpNotifReceiptWA-${k}`).checked,
                    notif_receipt_email: document.getElementById(`inpNotifReceiptEmail-${k}`).checked,
                    notif_report_whatsapp: document.getElementById(`inpNotifReportWA-${k}`).checked,
                    notif_report_email: document.getElementById(`inpNotifReportEmail-${k}`).checked,
                };

                // Mode EDIT: PUT ke tiket yang sudah ada, tanpa mengirim service_type
                // (lokasi tiket permanen sejak dibuat, tidak bisa diubah lewat edit).
                const editingTicketNumber = currentEditingTicket[k];
                const isEditing = !!editingTicketNumber;
                if (isEditing) delete payload.service_type;

                const url = isEditing
                    ? `/api/v1/db/tickets/${encodeURIComponent(editingTicketNumber)}`
                    : '/api/v1/db/tickets/';
                const method = isEditing ? 'PUT' : 'POST';

                try {
                    const res = await authFetch(url, {
                        method: method,
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                    const resData = await res.json();

                    if (res.ok) {
                        alert(isEditing
                            ? `BERHASIL! Tiket ${resData.ticket_number} berhasil diupdate.`
                            : `BERHASIL! Tiket ${resData.ticket_number} berhasil masuk khusus ke Data ${k.toUpperCase()}!`);
                        currentEditingTicket[k] = null;
                        hideFormInPage(k);
                        renderTableData('service-' + k);
                        updateDashboardStats();
                    } else {
                        alert(resData.detail || 'Gagal menyimpan tiket.');
                    }
                } catch(e) {
                    alert('Error koneksi: ' + e.message);
                }
            }

            // ---------- KELOLA USER (Super Admin) ----------

            function onRoleChange() {
                const isStaff = document.getElementById('nuRole').value === 'staff';
                document.getElementById('nuDeptWrap').style.display = isStaff ? '' : 'none';
            }

            let usersCache = [];

            function toggleUserForm() {
                const box = document.getElementById('userFormBox');
                const willShow = box.classList.contains('hidden');
                box.classList.toggle('hidden');
                if (willShow) {
                    // Selalu mulai dalam mode TAMBAH (bukan edit) kalau dibuka
                    // lewat tombol "+ Tambah User" - editUser() akan mengisi
                    // ulang field-field ini kalau dibuka lewat tombol Edit.
                    document.getElementById('nuEditingId').value = '';
                    document.getElementById('userFormTitle').innerText = 'Tambah User Baru';
                    document.getElementById('userSaveBtn').innerText = 'Simpan User';
                    document.getElementById('nuPasswordLabel').innerText = 'Password';
                    setVal('nuName', ''); setVal('nuEmail', ''); setVal('nuPassword', '');
                    setVal('nuRole', 'staff'); setVal('nuDept', 'pusat');
                    onRoleChange();
                }
            }

            function editUser(id) {
                const u = usersCache.find(x => x.id === id);
                if (!u) return;
                document.getElementById('nuEditingId').value = id;
                document.getElementById('userFormTitle').innerText = `Edit User: ${u.full_name}`;
                document.getElementById('userSaveBtn').innerText = 'Update User';
                document.getElementById('nuPasswordLabel').innerText = 'Password (kosongkan jika tidak diubah)';
                setVal('nuName', u.full_name || '');
                setVal('nuEmail', u.email || '');
                setVal('nuPassword', '');
                setVal('nuRole', u.role || 'staff');
                setVal('nuDept', u.department || 'pusat');
                onRoleChange();
                document.getElementById('userFormBox').classList.remove('hidden');
            }

            async function renderUsers() {
                try {
                    const res = await authFetch('/api/v1/admin/users/');
                    if (!res.ok) return;
                    usersCache = await res.json();
                    const ROLE_LABELS = { staff: 'Staff', admin: 'Admin', superadmin: 'Super Admin' };
                    const el = document.getElementById('tableUsers');
                    el.innerHTML = usersCache.map(u => `
                        <tr>
                            <td>${esc(u.full_name)}</td>
                            <td>${esc(u.email)}</td>
                            <td>${esc(ROLE_LABELS[u.role] || u.role)}</td>
                            <td>${esc(u.department) || '-'}</td>
                            <td><span class="badge ${u.is_active ? 'badge-active' : 'badge-inactive'}">${u.is_active ? 'Aktif' : 'Nonaktif'}</span></td>
                            <td style="white-space:nowrap;">
                                <button class="btn btn-secondary" onclick="editUser(${u.id})">Edit</button>
                                ${u.is_active
                                    ? `<button class="btn btn-danger" onclick="setUserActive(${u.id}, false)">Nonaktifkan</button>`
                                    : `<button class="btn btn-success" onclick="setUserActive(${u.id}, true)">Aktifkan</button>`}
                            </td>
                        </tr>
                    `).join('\\n');
                } catch(e) { console.error(e); }
            }

            async function createUser() {
                const editingId = valOf('nuEditingId');
                const isEditing = !!editingId;
                const role = document.getElementById('nuRole').value;
                const password = document.getElementById('nuPassword').value;

                const payload = {
                    full_name: document.getElementById('nuName').value.trim(),
                    email: document.getElementById('nuEmail').value.trim(),
                    role: role,
                    department: role === 'staff' ? document.getElementById('nuDept').value : null,
                };
                if (!isEditing || password) payload.password = password;

                if (!payload.full_name || !payload.email) return alert('Nama dan Email wajib diisi.');
                if (!isEditing && !password) return alert('Password wajib diisi utk user baru.');

                const url = isEditing ? `/api/v1/admin/users/${editingId}` : '/api/v1/admin/users/';
                const method = isEditing ? 'PUT' : 'POST';

                try {
                    const res = await authFetch(url, {
                        method: method,
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Gagal menyimpan user.');
                    alert(isEditing ? 'User berhasil diupdate!' : 'User berhasil dibuat!');
                    document.getElementById('userFormBox').classList.add('hidden');
                    renderUsers();
                } catch(e) {
                    alert(e.message);
                }
            }

            async function setUserActive(userId, active) {
                const endpoint = `/api/v1/admin/users/${userId}/${active ? 'reactivate' : 'deactivate'}`;
                try {
                    const res = await authFetch(endpoint, { method: 'PATCH' });
                    if (!res.ok) {
                        const data = await res.json();
                        throw new Error(data.detail || 'Gagal mengubah status user.');
                    }
                    renderUsers();
                } catch(e) {
                    alert(e.message);
                }
            }

            // ---------- KELOLA MODEL ALAT (Super Admin) ----------

            function toggleDeviceModelForm() {
                document.getElementById('deviceModelFormBox').classList.toggle('hidden');
            }

            async function renderDeviceModels() {
                try {
                    const res = await authFetch('/api/v1/device-models/');
                    if (!res.ok) return;
                    const models = await res.json();
                    const el = document.getElementById('tableDeviceModels');
                    el.innerHTML = models.length ? models.map(m => `
                        <tr>
                            <td>${esc(m.category)}</td>
                            <td>${esc(m.model_name)}</td>
                            <td><button class="btn btn-danger" onclick="deactivateDeviceModel(${m.id})">Nonaktifkan</button></td>
                        </tr>
                    `).join('') : `<tr><td colspan="3" style="text-align:center;">Belum ada model alat ditambahkan.</td></tr>`;
                } catch(e) { console.error(e); }
            }

            async function createDeviceModel() {
                const category = document.getElementById('dmCategory').value;
                const model_name = document.getElementById('dmModelName').value.trim();
                if (!model_name) return alert('Nama Model wajib diisi.');

                try {
                    const res = await authFetch('/api/v1/device-models/', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ category, model_name })
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Gagal menambah model.');
                    document.getElementById('dmModelName').value = '';
                    renderDeviceModels();
                } catch(e) {
                    alert(e.message);
                }
            }

            async function uploadDeviceModelExcel(inputEl) {
                const file = inputEl.files[0];
                if (!file) return;

                const formData = new FormData();
                formData.append('file', file);

                try {
                    // Catatan: JANGAN set header 'Content-Type' manual di sini - browser
                    // yang mengisi otomatis (termasuk boundary multipart-nya), kalau
                    // dipaksa manual malah rusak.
                    const res = await authFetch('/api/v1/device-models/bulk-upload', {
                        method: 'POST',
                        body: formData
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Gagal upload file.');

                    let msg = `Upload selesai!\n\n`
                        + `Total baris diproses: ${data.total_baris_diproses}\n`
                        + `Ditambahkan baru: ${data.ditambahkan_baru}\n`
                        + `Diaktifkan kembali: ${data.diaktifkan_kembali}\n`
                        + `Sudah ada (dilewati): ${data.sudah_ada_dilewati}\n`
                        + `Gagal: ${data.gagal}`;
                    if (data.gagal > 0) {
                        msg += `\n\nContoh baris gagal:\n` + data.detail_gagal.slice(0, 5)
                            .map(e => `- Baris ${e.row}: ${e.reason} (${e.data})`).join('\\n');
                    }
                    alert(msg);
                    renderDeviceModels();
                } catch(e) {
                    alert(e.message);
                } finally {
                    inputEl.value = ''; // reset supaya bisa upload file yang sama lagi kalau perlu
                }
            }

            async function deactivateDeviceModel(modelId) {
                if (!confirm('Nonaktifkan model ini? Model tidak akan muncul lagi di dropdown, tapi tiket lama yang sudah pakai model ini tetap aman.')) return;
                try {
                    const res = await authFetch(`/api/v1/device-models/${modelId}`, { method: 'DELETE' });
                    if (!res.ok) {
                        const data = await res.json();
                        throw new Error(data.detail || 'Gagal menonaktifkan model.');
                    }
                    renderDeviceModels();
                } catch(e) {
                    alert(e.message);
                }
            }

            // ---------- KELOLA CABANG (Super Admin) ----------

            let branchesCache = [];

            function toggleBranchForm() {
                const box = document.getElementById('branchFormBox');
                const willShow = box.classList.contains('hidden');
                box.classList.toggle('hidden');
                if (willShow) {
                    document.getElementById('branchEditingId').value = '';
                    document.getElementById('branchFormTitle').innerText = 'Tambah Cabang Baru';
                    document.getElementById('branchSaveBtn').innerText = 'Simpan Cabang';
                    ['branchName','branchCode','branchHandledBy','branchCity','branchAddress'].forEach(id => setVal(id, ''));
                }
            }

            function editBranch(id) {
                const b = branchesCache.find(x => x.id === id);
                if (!b) return;
                document.getElementById('branchEditingId').value = id;
                document.getElementById('branchFormTitle').innerText = `Edit Cabang: ${b.name}`;
                document.getElementById('branchSaveBtn').innerText = 'Update Cabang';
                setVal('branchName', b.name || '');
                setVal('branchCode', b.code || '');
                setVal('branchHandledBy', b.handled_by || '');
                setVal('branchCity', b.city || '');
                setVal('branchAddress', b.address || '');
                document.getElementById('branchFormBox').classList.remove('hidden');
            }

            async function saveBranch() {
                const name = valOf('branchName');
                const code = valOf('branchCode');
                if (!name || !code) return alert('Nama Cabang dan Kode Store wajib diisi.');

                const payload = {
                    name, code,
                    handled_by: valOf('branchHandledBy') || null,
                    city: valOf('branchCity') || null,
                    address: valOf('branchAddress') || null,
                };
                const editingId = valOf('branchEditingId');
                const url = editingId ? `/api/v1/branches/${editingId}` : '/api/v1/branches/';
                const method = editingId ? 'PUT' : 'POST';

                try {
                    const res = await authFetch(url, {
                        method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Gagal menyimpan cabang.');
                    toggleBranchForm();
                    renderBranches();
                } catch(e) {
                    alert(e.message);
                }
            }

            async function renderBranches() {
                try {
                    const res = await authFetch('/api/v1/branches/?include_inactive=true');
                    if (!res.ok) return;
                    branchesCache = await res.json();
                    const el = document.getElementById('tableBranches');
                    el.innerHTML = branchesCache.length ? branchesCache.map(b => `
                        <tr>
                            <td>${esc(b.name)}</td>
                            <td><strong>${esc(b.code)}</strong></td>
                            <td>${esc(b.handled_by) || '-'}</td>
                            <td>${esc(b.city) || '-'}</td>
                            <td style="max-width:280px;">${esc(b.address) || '-'}</td>
                            <td><span class="badge ${b.is_active ? 'badge-active' : 'badge-inactive'}">${b.is_active ? 'Aktif' : 'Nonaktif'}</span></td>
                            <td style="white-space:nowrap;">
                                <button class="btn btn-secondary" onclick="editBranch(${b.id})">Edit</button>
                                ${b.is_active
                                    ? `<button class="btn btn-danger" onclick="setBranchActive(${b.id}, false)">Nonaktifkan</button>`
                                    : `<button class="btn btn-success" onclick="setBranchActive(${b.id}, true)">Aktifkan</button>`}
                            </td>
                        </tr>
                    `).join('') : `<tr><td colspan="7" style="text-align:center;">Belum ada data cabang.</td></tr>`;
                } catch(e) { console.error(e); }
            }

            async function setBranchActive(id, active) {
                const endpoint = `/api/v1/branches/${id}/${active ? 'reactivate' : 'deactivate'}`;
                try {
                    const res = await authFetch(endpoint, { method: 'PATCH' });
                    if (!res.ok) { const d = await res.json(); throw new Error(d.detail || 'Gagal mengubah status.'); }
                    renderBranches();
                } catch(e) { alert(e.message); }
            }

            async function uploadBranchExcel(inputEl) {
                const file = inputEl.files[0];
                if (!file) return;
                const formData = new FormData();
                formData.append('file', file);
                try {
                    const res = await authFetch('/api/v1/branches/bulk-upload', { method: 'POST', body: formData });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Gagal upload file.');
                    let msg = `Upload selesai!\\n\\nTotal baris diproses: ${data.total_baris_diproses}\\n`
                        + `Ditambahkan baru: ${data.ditambahkan_baru}\\nDiperbarui: ${data.diperbarui}\\nGagal: ${data.gagal}`;
                    if (data.gagal > 0) {
                        msg += `\\n\\nContoh baris gagal:\\n` + data.detail_gagal.slice(0, 5)
                            .map(e => `- Baris ${e.row}: ${e.reason}`).join('\\n');
                    }
                    alert(msg);
                    renderBranches();
                } catch(e) {
                    alert(e.message);
                } finally {
                    inputEl.value = '';
                }
            }

            // ---------- KELOLA PICKUP CENTER (Super Admin) ----------

            let pickupCentersCache = [];

            function togglePickupForm() {
                const box = document.getElementById('pickupFormBox');
                const willShow = box.classList.contains('hidden');
                box.classList.toggle('hidden');
                if (willShow) {
                    document.getElementById('pickupEditingId').value = '';
                    document.getElementById('pickupFormTitle').innerText = 'Tambah Pickup Center Baru';
                    document.getElementById('pickupSaveBtn').innerText = 'Simpan Pickup Center';
                    ['pickupCode','pickupName','pickupCity','pickupAddress'].forEach(id => setVal(id, ''));
                }
            }

            function editPickupCenter(id) {
                const p = pickupCentersCache.find(x => x.id === id);
                if (!p) return;
                document.getElementById('pickupEditingId').value = id;
                document.getElementById('pickupFormTitle').innerText = `Edit Pickup Center: ${p.store_name}`;
                document.getElementById('pickupSaveBtn').innerText = 'Update Pickup Center';
                setVal('pickupCode', p.store_long_code || '');
                setVal('pickupName', p.store_name || '');
                setVal('pickupCity', p.city || '');
                setVal('pickupAddress', p.store_address || '');
                document.getElementById('pickupFormBox').classList.remove('hidden');
            }

            async function savePickupCenter() {
                const code = valOf('pickupCode');
                const name = valOf('pickupName');
                if (!code || !name) return alert('Store Long Code dan Store Name wajib diisi.');

                const payload = {
                    store_long_code: code, store_name: name,
                    city: valOf('pickupCity') || null,
                    store_address: valOf('pickupAddress') || null,
                };
                const editingId = valOf('pickupEditingId');
                const url = editingId ? `/api/v1/pickup-centers/${editingId}` : '/api/v1/pickup-centers/';
                const method = editingId ? 'PUT' : 'POST';

                try {
                    const res = await authFetch(url, {
                        method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Gagal menyimpan pickup center.');
                    togglePickupForm();
                    renderPickupCenters();
                } catch(e) {
                    alert(e.message);
                }
            }

            async function renderPickupCenters() {
                try {
                    const res = await authFetch('/api/v1/pickup-centers/?include_inactive=true');
                    if (!res.ok) return;
                    pickupCentersCache = await res.json();
                    renderPickupCenterRows(pickupCentersCache);
                } catch(e) { console.error(e); }
            }

            function renderPickupCenterRows(list) {
                const el = document.getElementById('tablePickupCenters');
                el.innerHTML = list.length ? list.map(p => `
                    <tr>
                        <td><strong>${esc(p.store_long_code)}</strong></td>
                        <td>${esc(p.store_name)}</td>
                        <td>${esc(p.city) || '-'}</td>
                        <td style="max-width:280px;">${esc(p.store_address) || '-'}</td>
                        <td><span class="badge ${p.is_active ? 'badge-active' : 'badge-inactive'}">${p.is_active ? 'Aktif' : 'Nonaktif'}</span></td>
                        <td style="white-space:nowrap;">
                            <button class="btn btn-secondary" onclick="editPickupCenter(${p.id})">Edit</button>
                            ${p.is_active
                                ? `<button class="btn btn-danger" onclick="setPickupCenterActive(${p.id}, false)">Nonaktifkan</button>`
                                : `<button class="btn btn-success" onclick="setPickupCenterActive(${p.id}, true)">Aktifkan</button>`}
                        </td>
                    </tr>
                `).join('') : `<tr><td colspan="6" style="text-align:center;">Belum ada data pickup center.</td></tr>`;
            }

            function filterPickupCenterTable() {
                const q = valOf('searchPickupCenters').toLowerCase();
                const filtered = pickupCentersCache.filter(p =>
                    (p.store_name || '').toLowerCase().includes(q) ||
                    (p.store_long_code || '').toLowerCase().includes(q) ||
                    (p.city || '').toLowerCase().includes(q)
                );
                renderPickupCenterRows(filtered);
            }

            async function setPickupCenterActive(id, active) {
                const endpoint = `/api/v1/pickup-centers/${id}/${active ? 'reactivate' : 'deactivate'}`;
                try {
                    const res = await authFetch(endpoint, { method: 'PATCH' });
                    if (!res.ok) { const d = await res.json(); throw new Error(d.detail || 'Gagal mengubah status.'); }
                    renderPickupCenters();
                } catch(e) { alert(e.message); }
            }

            async function uploadPickupExcel(inputEl) {
                const file = inputEl.files[0];
                if (!file) return;
                const formData = new FormData();
                formData.append('file', file);
                try {
                    const res = await authFetch('/api/v1/pickup-centers/bulk-upload', { method: 'POST', body: formData });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Gagal upload file.');
                    let msg = `Upload selesai!\\n\\nTotal baris diproses: ${data.total_baris_diproses}\\n`
                        + `Ditambahkan baru: ${data.ditambahkan_baru}\\nDiperbarui: ${data.diperbarui}\\nGagal: ${data.gagal}`;
                    if (data.gagal > 0) {
                        msg += `\\n\\nContoh baris gagal:\\n` + data.detail_gagal.slice(0, 5)
                            .map(e => `- Baris ${e.row}: ${e.reason}`).join('\\n');
                    }
                    alert(msg);
                    renderPickupCenters();
                } catch(e) {
                    alert(e.message);
                } finally {
                    inputEl.value = '';
                }
            }

            // ---------- INVENTORY PART (Stok Sparepart Pusat & Cabang) ----------

            const INVENTORY_LOCATION_LABELS = { pusat: 'Pusat', cabang: 'Cabang' };

            const INVENTORY_ACTIONS = {
                pusat: [
                    { type: 'terima_gudang', label: 'Terima dari Gudang' },
                    { type: 'kirim_ke_cabang', label: 'Kirim ke Cabang' },
                    { type: 'terima_dari_cabang', label: 'Terima dari Cabang' },
                ],
                cabang: [
                    { type: 'terima_dari_pusat', label: 'Terima dari Pusat' },
                    { type: 'kirim_balik_ke_pusat', label: 'Kirim Balik ke Pusat' },
                ],
            };

            const INVENTORY_REPORTS = {
                pusat: [
                    { kind: 'stock-list', label: 'Total List Sparepart Pusat' },
                    { kind: 'movement', movement_type: 'kirim_ke_cabang', label: 'Total Kirim ke Cabang' },
                    { kind: 'movement', movement_type: 'terpakai_pusat', label: 'Total Terpakai di Pusat' },
                    { kind: 'opname', label: 'Hasil Stok Opname Pusat' },
                ],
                cabang: [
                    { kind: 'stock-list', label: 'Total List Sparepart Cabang' },
                    { kind: 'movement', movement_type: 'terpakai_cabang', label: 'Total Terpakai di Cabang' },
                    { kind: 'opname', label: 'Hasil Stok Opname Cabang' },
                ],
            };

            let currentMovementType = {};

            function buildInventoryTabsHTML() {
                Object.keys(INVENTORY_ACTIONS).forEach(loc => {
                    const label = INVENTORY_LOCATION_LABELS[loc];
                    const root = document.getElementById(`tab-inventory-${loc}`);
                    const actionButtons = INVENTORY_ACTIONS[loc]
                        .map(a => `<button class="btn btn-success" onclick="openMovementForm('${loc}','${a.type}','${a.label}')">+ ${a.label}</button>`)
                        .join('\\n');
                    const reportOptions = INVENTORY_REPORTS[loc]
                        .map((r, idx) => `<option value="${idx}">${r.label}</option>`)
                        .join('\\n');
                    const bulkUploadOptions = INVENTORY_ACTIONS[loc]
                        .map(a => `<option value="${a.type}">${a.label} (Excel)</option>`)
                        .join('\\n');

                    root.innerHTML = `
                        <div class="card">
                            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px; flex-wrap:wrap; gap:10px;">
                                <h2 style="margin:0; border:none;">Inventory Part - Stok Sparepart ${label}</h2>
                                <div class="action-header" style="flex-wrap:wrap;">
                                    ${actionButtons}
                                    <button class="btn btn-warning" onclick="toggleOpnameForm('${loc}')">+ Stok Opname</button>
                                </div>
                            </div>

                            <div style="display:flex; justify-content:flex-end; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:15px; background:#f8f9fa; padding:10px; border-radius:6px;">
                                <span style="font-size:12px; color:#666; margin-right:auto;">Update banyak sparepart sekaligus lewat Excel:</span>
                                <button class="btn btn-secondary" onclick="downloadMovementTemplate('terima')">📄 Contoh Format Terima</button>
                                <button class="btn btn-secondary" onclick="downloadMovementTemplate('kirim')">📄 Contoh Format Kirim</button>
                                <select onchange="if(this.value !== ''){ prepareMovementBulkUpload('${loc}', this.value); this.selectedIndex = 0; }">
                                    <option value="">📤 Upload Massal Excel ▾</option>
                                    ${bulkUploadOptions}
                                </select>
                                <input type="file" id="invBulkFileInput-${loc}" accept=".xlsx,.xlsm" style="display:none;" onchange="handleMovementBulkFile('${loc}', this)">
                            </div>

                            <!-- Preview file yang dipilih, sebelum benar-benar diupload -->
                            <div id="invUploadPreview-${loc}" class="hidden upload-preview-box">
                                <div class="upload-preview-icon">📄</div>
                                <div class="upload-preview-info">
                                    <div class="upload-preview-name" id="invUploadFileName-${loc}"></div>
                                    <div class="upload-preview-meta" id="invUploadFileMeta-${loc}"></div>
                                </div>
                                <button class="btn btn-secondary" id="invUploadCancelBtn-${loc}" onclick="cancelMovementBulkUpload('${loc}')">Batal</button>
                                <button class="btn btn-success" id="invUploadConfirmBtn-${loc}" onclick="confirmMovementBulkUpload('${loc}')">⬆ Upload</button>
                            </div>

                            <!-- Hasil upload (muncul setelah proses selesai) -->
                            <div id="invUploadResult-${loc}" class="hidden upload-result-box"></div>

                            <div id="invMovementFormBox-${loc}" class="hidden" style="background:#f8f9fa; border:1px dashed #ccc; padding:10px; border-radius:6px; margin-bottom:15px;">
                                <div style="font-weight:bold; color:#0056b3; margin-bottom:8px;" id="invMovementTitle-${loc}"></div>
                                <div class="form-grid">
                                    <div class="form-group"><label>Nama Sparepart</label><input id="invName-${loc}" placeholder="Nama sparepart"></div>
                                    <div class="form-group"><label>Kode Sparepart <span class="required">*</span></label><input id="invCode-${loc}" placeholder="Kode/part number"></div>
                                    <div class="form-group"><label>Status</label>
                                        <select id="invStatus-${loc}">
                                            <option value="">-- Opsional --</option>
                                            <option value="Active">Active</option>
                                            <option value="Discontinue">Discontinue</option>
                                        </select>
                                    </div>
                                    <div class="form-group"><label>Model Alat</label><input id="invDeviceModel-${loc}" placeholder="Opsional, mis. HEM-7120"></div>
                                    <div class="form-group"><label>Jumlah <span class="required">*</span></label><input type="number" min="1" id="invQty-${loc}"></div>
                                    <div class="form-group hidden" id="invBranchWrap-${loc}">
                                        <label id="invBranchLabel-${loc}">Cabang</label>
                                        <select id="invBranch-${loc}"><option value="">-- Pilih Cabang --</option></select>
                                    </div>
                                    <div class="form-group" style="grid-column:1/-1;"><label>Catatan</label><input id="invNote-${loc}" placeholder="Opsional"></div>
                                </div>
                                <div style="display:flex; gap:10px; justify-content:flex-end;">
                                    <button class="btn btn-secondary" onclick="closeMovementForm('${loc}')">Batal</button>
                                    <button class="btn btn-success" onclick="submitMovement('${loc}')">Simpan</button>
                                </div>
                            </div>

                            <div id="invOpnameFormBox-${loc}" class="hidden" style="background:#fff3cd; border:1px dashed #ffc107; padding:10px; border-radius:6px; margin-bottom:15px;">
                                <div style="font-weight:bold; color:#856404; margin-bottom:8px;">Stok Opname (Hitung Fisik) - ${label}</div>
                                <div class="form-grid">
                                    <div class="form-group"><label>Kode Sparepart <span class="required">*</span></label><input id="invOpCode-${loc}" placeholder="Kode/part number"></div>
                                    <div class="form-group"><label>Nama Sparepart</label><input id="invOpName-${loc}" placeholder="Nama sparepart"></div>
                                    <div class="form-group"><label>Jumlah Hasil Hitung Fisik <span class="required">*</span></label><input type="number" min="0" id="invOpQty-${loc}"></div>
                                    <div class="form-group" style="grid-column:1/-1;"><label>Catatan</label><input id="invOpNote-${loc}" placeholder="Opsional"></div>
                                </div>
                                <div style="display:flex; gap:10px; justify-content:flex-end;">
                                    <button class="btn btn-secondary" onclick="toggleOpnameForm('${loc}')">Batal</button>
                                    <button class="btn btn-warning" onclick="submitOpname('${loc}')">Simpan Stok Opname</button>
                                </div>
                            </div>

                            <table>
                                <thead><tr><th>Kode</th><th>Nama Sparepart</th><th>Model Alat</th><th>Status</th><th>Jumlah Stok</th><th>Harga Satuan</th><th>Update Terakhir</th></tr></thead>
                                <tbody id="tableInventory-${loc}"></tbody>
                            </table>
                        </div>
                    `;
                });
            }

            // ---------- TAB 3: STATUS PAYMENT SERVICE ----------

            const PAYMENT_METHOD_OPTIONS = [
                { value: 'ONLINE_TO_OFFLINE_ALFA', label: 'Alfamart' },
                { value: 'ONLINE_TO_OFFLINE_INDOMARET', label: 'Indomaret' },
                { value: 'VIRTUAL_ACCOUNT_BRI', label: 'VA BRI' },
                { value: 'VIRTUAL_ACCOUNT_BCA', label: 'VA BCA' },
                { value: 'VIRTUAL_ACCOUNT_BNI', label: 'VA BNI' },
                { value: 'VIRTUAL_ACCOUNT_PERMATA', label: 'VA Permata' },
                { value: 'VIRTUAL_ACCOUNT_BANK_MANDIRI', label: 'VA Mandiri' },
            ];

            let paymentRowsCache = {};   // { [loc]: [...tiket Out of Warranty di lokasi ini] }
            let currentPaymentTicket = {}; // { [loc]: "JKT-2600001" | null }

            function buildPaymentTabsHTML() {
                const PAYMENT_LOCATION_LABELS = { pusat: 'Pusat', cabang: 'Cabang', pickup: 'Pickup Center' };
                Object.keys(PAYMENT_LOCATION_LABELS).forEach(loc => {
                    const label = PAYMENT_LOCATION_LABELS[loc];
                    const root = document.getElementById(`tab-payment-${loc}`);
                    const methodOptions = PAYMENT_METHOD_OPTIONS
                        .map(m => `<option value="${m.value}">${m.label}</option>`).join('');

                    root.innerHTML = `
                        <div id="view-table-payment-${loc}">
                            <div class="card">
                                <h2>Status Payment Service - ${label} (Out of Warranty)</h2>
                                <table>
                                    <thead><tr><th>No. Tiket</th><th>Pemilik</th><th>Model Alat</th><th>Total Biaya</th><th>Kode Payment</th><th>Status Bayar</th></tr></thead>
                                    <tbody id="tablePayment-${loc}"></tbody>
                                </table>
                            </div>
                        </div>

                        <div id="view-detail-payment-${loc}" class="hidden">
                            <div class="card">
                                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
                                    <h2 id="pdTitle-${loc}" style="margin:0; border:none;">Kelola Pembayaran</h2>
                                    <button class="btn btn-secondary" onclick="closePaymentDetail('${loc}')">&larr; Kembali ke Daftar</button>
                                </div>

                                <div class="form-grid" style="margin-top:10px;">
                                    <div><label style="font-weight:bold; color:#666; font-size:12px;">Nama Pemilik</label><div id="pdCustomerName-${loc}" style="padding:8px 0; font-size:13px;"></div></div>
                                    <div><label style="font-weight:bold; color:#666; font-size:12px;">No. HP/WA</label><div id="pdPhone-${loc}" style="padding:8px 0; font-size:13px;"></div></div>
                                    <div><label style="font-weight:bold; color:#666; font-size:12px;">Status Garansi</label><div id="pdWarranty-${loc}" style="padding:8px 0; font-size:13px;"></div></div>
                                </div>

                                <hr style="margin:15px 0; border:none; border-top:1px solid #eee;">

                                <div class="form-group">
                                    <label>Nama Pemilik untuk Invoice</label>
                                    <input id="pdOwnerName-${loc}">
                                    <div class="field-note-pd">Otomatis tersalin dari "Nama Pemilik" tiket. Kalau nama di NIK/NPWP beda (mis. invoice atas nama instansi/orang lain), hapus dan ketik langsung di sini - TIDAK mengubah Nama Pemilik di tiket/Data Service, hanya dipakai di dokumen Penawaran/Invoice ini saja.</div>
                                </div>

                                <div class="form-grid">
                                    <div class="form-group"><label>NIK / NPWP</label><input id="pdIdNumber-${loc}" placeholder="Opsional"></div>
                                    <div class="form-group"><label>Email</label><input type="email" id="pdEmail-${loc}" placeholder="nama@email.com (opsional)"></div>
                                </div>
                                <div class="form-group">
                                    <label>Alamat</label>
                                    <input id="pdAddress-${loc}">
                                    <div class="field-note-pd">Otomatis terisi dari data tiket, bisa diedit khusus untuk keperluan Penawaran/Invoice ini.</div>
                                </div>

                                <hr style="margin:15px 0; border-top:2px dashed #0056b3;">
                                <div style="font-weight:bold; color:#0056b3; font-size:13px; margin-bottom:10px;">Item Layanan (bisa lebih dari satu alat)</div>

                                <div id="pdItemsContainer-${loc}"></div>
                                <button class="btn btn-secondary" style="font-size:11px; padding:5px 9px;" onclick="addBillingItemRow('${loc}')">+ Tambah Item</button>
                                <div style="text-align:right; font-size:13px; font-weight:bold; color:#0056b3; margin-top:8px; padding-top:10px; border-top:1px solid #ddd;">
                                    Total Harga Service: Rp <span id="pdTotalDisplay-${loc}">0</span>
                                </div>

                                <hr style="margin:15px 0; border:none; border-top:1px solid #eee;">

                                <div style="display:flex; align-items:center; gap:8px; margin-bottom:8px;">
                                    <input type="checkbox" id="pdManualPrice-${loc}" style="width:auto;" onchange="document.getElementById('pdManualWrap-${loc}').classList.toggle('hidden', !this.checked)">
                                    <label for="pdManualPrice-${loc}" style="margin-bottom:0; font-weight:normal; font-size:13px;">Input Harga Manual (PPH 23 &amp; Biaya Admin Bank)</label>
                                </div>
                                <div id="pdManualWrap-${loc}" class="hidden form-grid">
                                    <div class="form-group"><label>PPH 23 (Rp)</label><input type="number" min="0" id="pdPph23-${loc}" placeholder="0"></div>
                                    <div class="form-group"><label>Biaya Admin Bank (Rp)</label><input type="number" min="0" id="pdAdminBank-${loc}" placeholder="0"></div>
                                </div>

                                <div style="display:flex; align-items:center; gap:8px; margin:8px 0 15px;">
                                    <input type="checkbox" id="pdPpnFree-${loc}" style="width:auto;">
                                    <label for="pdPpnFree-${loc}" style="margin-bottom:0; font-weight:normal; font-size:13px;">Bebas PPN (0%) untuk transaksi ini</label>
                                </div>

                                <button class="btn btn-success" onclick="savePaymentInfo('${loc}')">💾 Simpan Info Pembayaran</button>

                                <hr style="margin:15px 0; border:none; border-top:1px solid #eee;">

                                <div style="display:flex; gap:10px; flex-wrap:wrap;">
                                    <button class="btn btn-secondary" onclick="downloadQuotationPdf('${loc}')">📄 Download Penawaran Harga (PDF)</button>
                                    <button class="btn btn-secondary" onclick="downloadInvoicePdf('${loc}')">🧾 Download Invoice Service (PDF)</button>
                                </div>

                                <hr style="margin:15px 0; border:none; border-top:1px solid #eee;">

                                <h3 style="margin-bottom:8px;">Generate Kode Bayar (Virtual Account)</h3>
                                <div class="form-grid">
                                    <div class="form-group">
                                        <label>Pilih Metode Pembayaran</label>
                                        <select id="pdPaymentMethod-${loc}">
                                            <option value="">-- Pilih Metode --</option>
                                            ${methodOptions}
                                        </select>
                                    </div>
                                </div>
                                <button class="btn btn-warning" onclick="generatePaymentCode('${loc}')" id="pdGenerateBtn-${loc}">💳 Generate Kode Bayar</button>

                                <div id="pdPaymentResult-${loc}" class="hidden upload-result-box" style="margin-top:12px;"></div>
                            </div>
                        </div>
                    `;
                });
            }

            // ---------- ITEM LAYANAN (bisa lebih dari 1 alat per dokumen) ----------

            let billingItemCounters = {}; // { [loc]: jumlah item yang sudah dibuat, utk penomoran Item # }

            function billingCategoryOptions(selected) {
                return PRODUCT_CATEGORIES.map(c => `<option value="${c}" ${c === selected ? 'selected' : ''}>${c}</option>`).join('');
            }

            async function onBillingItemCategoryChange(selectEl) {
                const row = selectEl.closest('.item-row');
                const category = selectEl.value;
                let modelEl = row.querySelector('.item-model');

                if (!category) {
                    modelEl.innerHTML = '<option value="">-- Pilih Kategori dulu --</option>';
                    return;
                }
                if (category === 'Others') {
                    modelEl.outerHTML = `<input class="item-model" placeholder="Ketik nama model alat">`;
                    return;
                }
                if (modelEl.tagName !== 'SELECT') {
                    modelEl.outerHTML = `<select class="item-model"><option value="">Memuat...</option></select>`;
                    modelEl = row.querySelector('.item-model');
                } else {
                    modelEl.innerHTML = '<option value="">Memuat...</option>';
                }
                try {
                    const res = await authFetch(`/api/v1/device-models/?category=${encodeURIComponent(category)}`);
                    const models = res.ok ? await res.json() : [];
                    modelEl.innerHTML = models.length
                        ? '<option value="">-- Pilih Model --</option>' + models.map(m => `<option value="${esc(m.model_name)}">${esc(m.model_name)}</option>`).join('')
                        : '<option value="">(Belum ada model utk kategori ini)</option>';
                } catch(e) {
                    modelEl.innerHTML = '<option value="">Gagal memuat model</option>';
                }
            }

            function addBillingItemRow(loc, prefill) {
                prefill = prefill || {};
                billingItemCounters[loc] = (billingItemCounters[loc] || 0) + 1;
                const num = billingItemCounters[loc];
                const isFirst = num === 1;
                const container = document.getElementById(`pdItemsContainer-${loc}`);
                const div = document.createElement('div');
                div.className = 'item-row';
                div.style.cssText = 'background:#f8f9fa; border:1px dashed #ccc; padding:10px; border-radius:6px; margin-bottom:10px;';
                div.innerHTML = `
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                        <span style="font-weight:bold; font-size:12px; color:#0056b3;">Item #${num}${isFirst ? ' (alat pada tiket ini)' : ''}</span>
                        <button class="btn btn-danger" style="font-size:11px; padding:4px 8px;" onclick="this.closest('.item-row').remove(); recalcBillingTotal('${loc}');">Hapus</button>
                    </div>
                    <div class="form-grid">
                        <div class="form-group">
                            <label>Jenis Layanan</label>
                            <select class="item-service-type">
                                <option value="Perbaikan" ${prefill.service_type !== 'Kalibrasi' ? 'selected' : ''}>Perbaikan</option>
                                <option value="Kalibrasi" ${prefill.service_type === 'Kalibrasi' ? 'selected' : ''}>Kalibrasi</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Kategori Produk</label>
                            <select class="item-category" onchange="onBillingItemCategoryChange(this)">
                                <option value="">-- Pilih Kategori --</option>
                                ${billingCategoryOptions(prefill.product_category)}
                            </select>
                            ${isFirst ? '<div class="field-note-pd">Otomatis terisi dari data tiket, bisa diedit khusus untuk keperluan Penawaran/Invoice ini.</div>' : ''}
                        </div>
                        <div class="form-group">
                            <label>Model Alat</label>
                            <select class="item-model"><option value="">-- Pilih Kategori dulu --</option></select>
                            ${isFirst ? '<div class="field-note-pd">Otomatis terisi dari data tiket, bisa diedit khusus untuk keperluan Penawaran/Invoice ini.</div>' : ''}
                        </div>
                        <div class="form-group"><label>Jumlah</label><input type="number" class="item-qty" value="${prefill.quantity || 1}" min="1" oninput="recalcBillingTotal('${loc}')"></div>
                        <div class="form-group"><label>Harga (Rp)</label><input type="number" class="item-price" value="${prefill.price || 0}" min="0" oninput="recalcBillingTotal('${loc}')"></div>
                        ${!isFirst ? `
                        <div class="form-group">
                            <label>No. Tiket Referensi</label>
                            <input class="item-ref-ticket" placeholder="Contoh: JKT-2600002" onblur="lookupRefTicket(this, '${loc}')">
                            <div class="field-note-pd item-ref-status">Ketik nomor tiket alat lain, Kategori &amp; Model diambil otomatis.</div>
                        </div>` : ''}
                    </div>
                    <input type="hidden" class="item-serial" value="${esc(prefill.serial_number || '')}">
                    <input type="hidden" class="item-description" value="${esc(prefill.description || '')}">
                `;
                container.appendChild(div);
                if (prefill.product_category) {
                    onBillingItemCategoryChange(div.querySelector('.item-category')).then(() => {
                        div.querySelector('.item-model').value = prefill.device_model || '';
                    });
                }
                recalcBillingTotal(loc);
            }

            function recalcBillingTotal(loc) {
                let total = 0;
                document.querySelectorAll(`#pdItemsContainer-${loc} .item-row`).forEach(row => {
                    const qty = parseFloat(row.querySelector('.item-qty')?.value || 0);
                    const price = parseFloat(row.querySelector('.item-price')?.value || 0);
                    total += qty * price;
                });
                document.getElementById(`pdTotalDisplay-${loc}`).innerText = total.toLocaleString('id-ID');
            }

            async function lookupRefTicket(inputEl, loc) {
                const row = inputEl.closest('.item-row');
                const statusEl = row.querySelector('.item-ref-status');
                const ticketNo = inputEl.value.trim().toUpperCase();
                inputEl.value = ticketNo;
                if (!ticketNo) {
                    statusEl.textContent = 'Ketik nomor tiket alat lain, Kategori & Model diambil otomatis.';
                    statusEl.style.color = '#888';
                    return;
                }
                try {
                    const res = await authFetch(`/api/v1/db/tickets/detail/${encodeURIComponent(ticketNo)}`);
                    if (!res.ok) {
                        statusEl.textContent = `✗ Tiket "${ticketNo}" tidak ditemukan.`;
                        statusEl.style.color = '#dc3545';
                        return;
                    }
                    const t = await res.json();
                    const categorySelect = row.querySelector('.item-category');
                    categorySelect.value = t.product_category || '';
                    await onBillingItemCategoryChange(categorySelect);
                    row.querySelector('.item-model').value = t.device_model || '';
                    row.querySelector('.item-serial').value = t.serial_number || '';
                    row.querySelector('.item-description').value = t.complaint || '';
                    statusEl.textContent = `✓ Ditemukan - pemilik: ${t.customer_name}. Kategori & Model otomatis terisi.`;
                    statusEl.style.color = '#28a745';
                } catch(e) {
                    statusEl.textContent = 'Gagal memeriksa nomor tiket.';
                    statusEl.style.color = '#dc3545';
                }
            }

            async function openPaymentDetail(ticketNumber, loc) {
                try {
                    const res = await authFetch(`/api/v1/db/tickets/detail/${encodeURIComponent(ticketNumber)}`);
                    if (!res.ok) { const e = await res.json().catch(()=>({})); throw new Error(e.detail || 'Gagal memuat data tiket.'); }
                    const t = await res.json();

                    currentPaymentTicket[loc] = ticketNumber;
                    document.getElementById(`pdTitle-${loc}`).innerText = `Kelola Pembayaran - ${ticketNumber}`;
                    document.getElementById(`pdCustomerName-${loc}`).innerText = t.customer_name || '-';
                    document.getElementById(`pdPhone-${loc}`).innerText = t.customer_phone || '-';
                    document.getElementById(`pdWarranty-${loc}`).innerText = t.warranty_status || '-';

                    setVal(`pdOwnerName-${loc}`, t.invoice_owner_name || t.customer_name || '');
                    setVal(`pdIdNumber-${loc}`, t.customer_id_number || '');
                    setVal(`pdEmail-${loc}`, t.customer_email || '');
                    setVal(`pdAddress-${loc}`, t.invoice_address || t.customer_address || '');
                    document.getElementById(`pdPpnFree-${loc}`).checked = !!t.ppn_free;
                    document.getElementById(`pdManualPrice-${loc}`).checked = !!t.use_manual_price_breakdown;
                    document.getElementById(`pdManualWrap-${loc}`).classList.toggle('hidden', !t.use_manual_price_breakdown);
                    setVal(`pdPph23-${loc}`, t.pph23_amount || '');
                    setVal(`pdAdminBank-${loc}`, t.admin_bank_fee || '');
                    setVal(`pdPaymentMethod-${loc}`, t.payment_method || '');

                    // Muat ulang Item Layanan: kalau tiket sudah pernah simpan item, pakai
                    // itu; kalau belum pernah sama sekali, Item #1 dibuat otomatis dari
                    // data tiket ini sendiri (kategori/model/serial/keluhan).
                    document.getElementById(`pdItemsContainer-${loc}`).innerHTML = '';
                    billingItemCounters[loc] = 0;
                    const items = t.billing_items || [];
                    if (items.length) {
                        items.sort((a, b) => (a.sequence || 0) - (b.sequence || 0)).forEach(item => {
                            addBillingItemRow(loc, {
                                service_type: item.service_type, product_category: item.product_category,
                                device_model: item.device_model, quantity: item.quantity, price: item.price,
                                serial_number: item.serial_number, description: item.description,
                            });
                            if (item.ref_ticket_number) {
                                const rows = document.querySelectorAll(`#pdItemsContainer-${loc} .item-row`);
                                const lastRow = rows[rows.length - 1];
                                const refInput = lastRow.querySelector('.item-ref-ticket');
                                if (refInput) refInput.value = item.ref_ticket_number;
                            }
                        });
                    } else {
                        addBillingItemRow(loc, {
                            service_type: 'Perbaikan', product_category: t.product_category,
                            device_model: t.device_model, quantity: 1, price: t.total_price || 0,
                            serial_number: t.serial_number, description: t.complaint,
                        });
                    }

                    const resultBox = document.getElementById(`pdPaymentResult-${loc}`);
                    if (t.payment_url) {
                        resultBox.className = 'upload-result-box upload-result-success';
                        resultBox.innerHTML = `<strong>Kode bayar sudah pernah dibuat.</strong><br>`
                            + `Metode: ${esc(getMethodLabel(t.payment_method))}<br>`
                            + `Link: <a href="${esc(t.payment_url)}" target="_blank" rel="noopener">${esc(t.payment_url)}</a>`
                            + (t.payment_expired_at ? `<br>Berlaku sampai: ${new Date(t.payment_expired_at).toLocaleString('id-ID')}` : '');
                        resultBox.classList.remove('hidden');
                    } else {
                        resultBox.classList.add('hidden');
                    }

                    document.getElementById(`view-table-payment-${loc}`).classList.add('hidden');
                    document.getElementById(`view-detail-payment-${loc}`).classList.remove('hidden');
                } catch(e) {
                    alert(e.message);
                }
            }

            function getMethodLabel(value) {
                const found = PAYMENT_METHOD_OPTIONS.find(m => m.value === value);
                return found ? found.label : (value || '-');
            }

            function closePaymentDetail(loc) {
                currentPaymentTicket[loc] = null;
                document.getElementById(`view-detail-payment-${loc}`).classList.add('hidden');
                document.getElementById(`view-table-payment-${loc}`).classList.remove('hidden');
                renderTableData('payment-' + loc);
            }

            async function savePaymentInfo(loc) {
                const ticketNumber = currentPaymentTicket[loc];
                if (!ticketNumber) return;

                const items = [];
                document.querySelectorAll(`#pdItemsContainer-${loc} .item-row`).forEach(row => {
                    const category = row.querySelector('.item-category')?.value || null;
                    const modelEl = row.querySelector('.item-model');
                    const model = modelEl ? modelEl.value : null;
                    const qty = parseInt(row.querySelector('.item-qty')?.value || '1');
                    const price = parseFloat(row.querySelector('.item-price')?.value || '0');
                    const refTicket = row.querySelector('.item-ref-ticket')?.value.trim() || null;
                    items.push({
                        service_type: row.querySelector('.item-service-type')?.value || 'Perbaikan',
                        product_category: category,
                        device_model: model,
                        serial_number: row.querySelector('.item-serial')?.value || null,
                        description: row.querySelector('.item-description')?.value || null,
                        quantity: qty > 0 ? qty : 1,
                        price: price >= 0 ? price : 0,
                        ref_ticket_number: refTicket,
                    });
                });

                const useManual = document.getElementById(`pdManualPrice-${loc}`).checked;
                const payload = {
                    invoice_owner_name: valOf(`pdOwnerName-${loc}`) || null,
                    customer_id_number: valOf(`pdIdNumber-${loc}`) || null,
                    customer_email: valOf(`pdEmail-${loc}`) || null,
                    invoice_address: valOf(`pdAddress-${loc}`) || null,
                    ppn_free: document.getElementById(`pdPpnFree-${loc}`).checked,
                    use_manual_price_breakdown: useManual,
                    pph23_amount: useManual && valOf(`pdPph23-${loc}`) ? parseFloat(valOf(`pdPph23-${loc}`)) : null,
                    admin_bank_fee: useManual && valOf(`pdAdminBank-${loc}`) ? parseFloat(valOf(`pdAdminBank-${loc}`)) : null,
                    items: items,
                };

                try {
                    const res = await authFetch(`/api/v1/db/tickets/${encodeURIComponent(ticketNumber)}/billing-info`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload),
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Gagal menyimpan info pembayaran.');
                    alert('Info pembayaran berhasil disimpan.');
                    renderTableData('payment-' + loc);
                } catch(e) {
                    alert(e.message);
                }
            }

            async function _downloadPdf(url, filename) {
                try {
                    const res = await authFetch(url);
                    if (!res.ok) { const e = await res.json().catch(()=>({})); throw new Error(e.detail || 'Gagal mengunduh PDF.'); }
                    const blob = await res.blob();
                    const dlUrl = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = dlUrl; a.download = filename;
                    document.body.appendChild(a); a.click(); a.remove();
                    window.URL.revokeObjectURL(dlUrl);
                } catch(e) {
                    alert(e.message);
                }
            }

            function downloadQuotationPdf(loc) {
                const ticketNumber = currentPaymentTicket[loc];
                if (!ticketNumber) return;
                _downloadPdf(`/api/v1/db/tickets/${encodeURIComponent(ticketNumber)}/quotation-pdf`, `Penawaran-${ticketNumber}.pdf`);
            }

            function downloadInvoicePdf(loc) {
                const ticketNumber = currentPaymentTicket[loc];
                if (!ticketNumber) return;
                _downloadPdf(`/api/v1/db/tickets/${encodeURIComponent(ticketNumber)}/invoice-pdf`, `Invoice-${ticketNumber}.pdf`);
            }

            async function generatePaymentCode(loc) {
                const ticketNumber = currentPaymentTicket[loc];
                if (!ticketNumber) return;
                const method = valOf(`pdPaymentMethod-${loc}`);
                if (!method) return alert('Pilih metode pembayaran dulu.');

                const btn = document.getElementById(`pdGenerateBtn-${loc}`);
                const resultBox = document.getElementById(`pdPaymentResult-${loc}`);
                btn.disabled = true;
                btn.innerHTML = `<span class="spinner"></span> Memproses...`;

                try {
                    const res = await authFetch(`/api/v1/db/tickets/${encodeURIComponent(ticketNumber)}/generate-payment`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ payment_method: method }),
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Gagal generate kode bayar.');

                    resultBox.className = 'upload-result-box upload-result-success';
                    resultBox.innerHTML = `<strong>✅ Kode bayar berhasil dibuat!</strong> (mode: ${esc(data.environment)})<br>`
                        + `Metode: ${esc(getMethodLabel(data.payment_method))}<br>`
                        + `Link pembayaran: <a href="${esc(data.payment_url)}" target="_blank" rel="noopener">${esc(data.payment_url)}</a>`
                        + (data.expired_at ? `<br>Berlaku sampai: ${new Date(data.expired_at).toLocaleString('id-ID')}` : '');
                    resultBox.classList.remove('hidden');
                    renderTableData('payment-' + loc);
                } catch(e) {
                    resultBox.className = 'upload-result-box upload-result-error';
                    resultBox.innerHTML = `<strong>❌ Gagal generate kode bayar.</strong><br>${esc(e.message)}`;
                    resultBox.classList.remove('hidden');
                } finally {
                    btn.disabled = false;
                    btn.innerHTML = '💳 Generate Kode Bayar';
                }
            }

            // Jenis pergerakan yang butuh dropdown Cabang, dan label yang sesuai
            // ("Cabang Tujuan" untuk kirim, "Cabang Asal" untuk terima).
            const BRANCH_FIELD_CONFIG = {
                kirim_ke_cabang: 'Cabang Tujuan',
                terima_dari_cabang: 'Cabang Asal',
            };
            let branchListCache = null;

            async function openMovementForm(loc, type, label) {
                document.getElementById(`invOpnameFormBox-${loc}`).classList.add('hidden');
                currentMovementType[loc] = type;
                document.getElementById(`invMovementTitle-${loc}`).innerText = label;
                setVal(`invCode-${loc}`, '');
                setVal(`invName-${loc}`, '');
                setVal(`invStatus-${loc}`, '');
                setVal(`invDeviceModel-${loc}`, '');
                setVal(`invQty-${loc}`, '');
                setVal(`invNote-${loc}`, '');

                const branchWrap = document.getElementById(`invBranchWrap-${loc}`);
                const branchFieldLabel = BRANCH_FIELD_CONFIG[type];
                if (branchFieldLabel) {
                    document.getElementById(`invBranchLabel-${loc}`).innerHTML =
                        `${branchFieldLabel} <span class="required">*</span>`;
                    branchWrap.classList.remove('hidden');
                    await populateBranchSelect(loc);
                } else {
                    branchWrap.classList.add('hidden');
                    setVal(`invBranch-${loc}`, '');
                }

                document.getElementById(`invMovementFormBox-${loc}`).classList.remove('hidden');
            }

            async function populateBranchSelect(loc) {
                const select = document.getElementById(`invBranch-${loc}`);
                select.innerHTML = '<option value="">Memuat...</option>';
                try {
                    if (!branchListCache) {
                        const res = await authFetch('/api/v1/branches/');
                        branchListCache = res.ok ? await res.json() : [];
                    }
                    select.innerHTML = branchListCache.length
                        ? '<option value="">-- Pilih Cabang --</option>' + branchListCache.map(b => `<option value="${esc(b.name)}">${esc(b.name)} (${esc(b.code)})</option>`).join('')
                        : '<option value="">(Belum ada data cabang - tambah di Kelola Cabang)</option>';
                } catch(e) {
                    select.innerHTML = '<option value="">Gagal memuat daftar cabang</option>';
                }
            }

            function closeMovementForm(loc) {
                document.getElementById(`invMovementFormBox-${loc}`).classList.add('hidden');
            }

            function toggleOpnameForm(loc) {
                document.getElementById(`invMovementFormBox-${loc}`).classList.add('hidden');
                const box = document.getElementById(`invOpnameFormBox-${loc}`);
                box.classList.toggle('hidden');
                if (!box.classList.contains('hidden')) {
                    setVal(`invOpCode-${loc}`, '');
                    setVal(`invOpName-${loc}`, '');
                    setVal(`invOpQty-${loc}`, '');
                    setVal(`invOpNote-${loc}`, '');
                }
            }

            async function submitMovement(loc) {
                const code = valOf(`invCode-${loc}`);
                const qty = valOf(`invQty-${loc}`);
                if (!code || !qty) return alert('Kode Sparepart dan Jumlah wajib diisi.');

                const movementType = currentMovementType[loc];
                const branchFieldLabel = BRANCH_FIELD_CONFIG[movementType];
                const relatedBranch = valOf(`invBranch-${loc}`);
                if (branchFieldLabel && !relatedBranch) {
                    return alert(`${branchFieldLabel} wajib dipilih untuk pergerakan ini.`);
                }

                const payload = {
                    location: loc,
                    movement_type: movementType,
                    code: code,
                    name: valOf(`invName-${loc}`) || null,
                    quantity: parseInt(qty),
                    note: valOf(`invNote-${loc}`) || null,
                    device_model: valOf(`invDeviceModel-${loc}`) || null,
                    part_status: valOf(`invStatus-${loc}`) || null,
                    related_branch: relatedBranch || null,
                };

                try {
                    const res = await authFetch('/api/v1/inventory-parts/movement', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Gagal menyimpan pergerakan stok.');
                    alert(`Berhasil! Stok ${data.code} di ${loc.toUpperCase()} sekarang: ${data.new_quantity}`);
                    closeMovementForm(loc);
                    renderInventoryStock(loc);
                } catch(e) {
                    alert(e.message);
                }
            }

            async function submitOpname(loc) {
                const code = valOf(`invOpCode-${loc}`);
                const qty = valOf(`invOpQty-${loc}`);
                if (!code || qty === '') return alert('Kode Sparepart dan Jumlah Hasil Hitung Fisik wajib diisi.');

                const payload = {
                    location: loc,
                    code: code,
                    name: valOf(`invOpName-${loc}`) || null,
                    counted_quantity: parseInt(qty),
                    note: valOf(`invOpNote-${loc}`) || null,
                };

                try {
                    const res = await authFetch('/api/v1/inventory-parts/opname', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Gagal menyimpan stok opname.');
                    alert(`Stok Opname tersimpan.\\nStok sistem sebelumnya: ${data.system_quantity}\\nHasil hitung fisik: ${data.counted_quantity}\\nSelisih: ${data.difference}`);
                    toggleOpnameForm(loc);
                    renderInventoryStock(loc);
                } catch(e) {
                    alert(e.message);
                }
            }

            async function renderInventoryStock(loc) {
                try {
                    const res = await authFetch(`/api/v1/inventory-parts/stock/${loc}`);
                    const el = document.getElementById(`tableInventory-${loc}`);
                    if (!res.ok || !el) return;
                    const data = await res.json();
                    el.innerHTML = data.length ? data.map(d => `
                        <tr>
                            <td><strong>${esc(d.code)}</strong></td>
                            <td>${esc(d.name) || '-'}</td>
                            <td>${esc(d.model_alat) || '-'}</td>
                            <td>${d.status ? `<span class="badge ${d.status === 'Active' ? 'badge-active' : 'badge-inactive'}">${esc(d.status)}</span>` : '-'}</td>
                            <td>${d.quantity}</td>
                            <td>Rp ${(d.unit_price || 0).toLocaleString('id-ID')}</td>
                            <td>${d.updated_at ? d.updated_at.split('T')[0] : '-'}</td>
                        </tr>
                    `).join('') : `<tr><td colspan="7" style="text-align:center;">Belum ada sparepart di lokasi ini</td></tr>`;
                } catch(e) { console.error(e); }
            }

            async function downloadInventoryReport(loc, idx) {
                const report = INVENTORY_REPORTS[loc][idx];
                let url = '';
                if (report.kind === 'stock-list') url = `/api/v1/inventory-parts/report/stock-list?location=${loc}`;
                else if (report.kind === 'movement') url = `/api/v1/inventory-parts/report/movements?location=${loc}&movement_type=${report.movement_type}`;
                else if (report.kind === 'opname') url = `/api/v1/inventory-parts/report/opname?location=${loc}`;

                try {
                    const res = await authFetch(url);
                    if (!res.ok) {
                        const err = await res.json().catch(() => ({}));
                        throw new Error(err.detail || 'Gagal mengunduh laporan.');
                    }
                    const blob = await res.blob();
                    const dlUrl = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = dlUrl;
                    a.download = `${report.label.replace(/ /g, '_')}_${loc}.xlsx`;
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    window.URL.revokeObjectURL(dlUrl);
                } catch(e) {
                    alert(e.message);
                }
            }

            let pendingBulkFile = {}; // { [loc]: File yang dipilih, menunggu konfirmasi }

            function getMovementLabel(loc, type) {
                const found = INVENTORY_ACTIONS[loc].find(a => a.type === type);
                return found ? found.label : type;
            }

            function prepareMovementBulkUpload(loc, movementType) {
                currentMovementType[loc] = movementType;
                document.getElementById(`invBulkFileInput-${loc}`).click();
            }

            function handleMovementBulkFile(loc, inputEl) {
                const file = inputEl.files[0];
                if (!file) return;
                pendingBulkFile[loc] = file;

                // File baru dipilih - sembunyikan hasil upload sebelumnya, tampilkan preview.
                document.getElementById(`invUploadResult-${loc}`).classList.add('hidden');

                const sizeKb = (file.size / 1024).toFixed(1);
                const ext = (file.name.split('.').pop() || '').toUpperCase();
                const typeLabel = getMovementLabel(loc, currentMovementType[loc]);

                document.getElementById(`invUploadFileName-${loc}`).innerText = file.name;
                document.getElementById(`invUploadFileMeta-${loc}`).innerText =
                    `Tipe file: ${ext} · Ukuran: ${sizeKb} KB · Untuk: ${typeLabel}`;
                document.getElementById(`invUploadPreview-${loc}`).classList.remove('hidden');
            }

            function cancelMovementBulkUpload(loc) {
                pendingBulkFile[loc] = null;
                document.getElementById(`invBulkFileInput-${loc}`).value = '';
                document.getElementById(`invUploadPreview-${loc}`).classList.add('hidden');
            }

            async function confirmMovementBulkUpload(loc) {
                const file = pendingBulkFile[loc];
                if (!file) return;
                const movementType = currentMovementType[loc];

                const confirmBtn = document.getElementById(`invUploadConfirmBtn-${loc}`);
                const cancelBtn = document.getElementById(`invUploadCancelBtn-${loc}`);
                confirmBtn.disabled = true;
                cancelBtn.disabled = true;
                confirmBtn.innerHTML = `<span class="spinner"></span> Mengupload...`;

                const formData = new FormData();
                formData.append('file', file);
                formData.append('location', loc);
                formData.append('movement_type', movementType);

                const resultBox = document.getElementById(`invUploadResult-${loc}`);

                try {
                    const res = await authFetch('/api/v1/inventory-parts/movement/bulk-upload', {
                        method: 'POST', body: formData
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Gagal upload file.');

                    const allSuccess = data.gagal === 0;
                    resultBox.className = 'upload-result-box ' + (allSuccess ? 'upload-result-success' : 'upload-result-partial');
                    let html = `<strong>${allSuccess ? '✅ Upload berhasil!' : '⚠️ Upload selesai, sebagian baris gagal'}</strong><br>`
                        + `Total baris diproses: ${data.total_baris_diproses} · Berhasil: ${data.berhasil} · Gagal: ${data.gagal}`;
                    if (data.gagal > 0) {
                        html += '<ul style="margin:8px 0 0 18px; padding:0;">' +
                            data.detail_gagal.slice(0, 5).map(e => `<li>Baris ${e.row}: ${esc(e.reason)}</li>`).join('') +
                            '</ul>';
                    }
                    resultBox.innerHTML = html;
                    resultBox.classList.remove('hidden');

                    cancelMovementBulkUpload(loc); // sembunyikan panel preview, reset input file
                    renderInventoryStock(loc);
                } catch(e) {
                    resultBox.className = 'upload-result-box upload-result-error';
                    resultBox.innerHTML = `<strong>❌ Upload gagal.</strong><br>${esc(e.message)}`;
                    resultBox.classList.remove('hidden');
                } finally {
                    confirmBtn.disabled = false;
                    cancelBtn.disabled = false;
                    confirmBtn.innerHTML = '⬆ Upload';
                }
            }

            async function downloadMovementTemplate(kind) {
                try {
                    const res = await authFetch(`/api/v1/inventory-parts/movement/template?kind=${kind}`);
                    if (!res.ok) throw new Error('Gagal mengunduh contoh format.');
                    const blob = await res.blob();
                    const dlUrl = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = dlUrl;
                    a.download = kind === 'kirim' ? 'Contoh_Format_Upload_Kirim_Stok.xlsx' : 'Contoh_Format_Upload_Terima_Stok.xlsx';
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    window.URL.revokeObjectURL(dlUrl);
                } catch(e) {
                    alert(e.message);
                }
            }

            // ---------- MENU 5: LAPORAN ----------

            const INV_LAPORAN_JENIS = {
                pusat: [
                    { kind: 'stock-list', label: 'Total stok part di pusat' },
                    { kind: 'movement', movement_type: 'terpakai_pusat', label: 'Total terpakai di pusat' },
                    { kind: 'movement', movement_type: 'kirim_ke_cabang', label: 'Total kirim ke cabang' },
                    { kind: 'opname', label: 'Hasil stok opname di pusat' },
                ],
                cabang: [
                    { kind: 'stock-list', label: 'Total stok part di cabang' },
                    { kind: 'movement', movement_type: 'terpakai_cabang', label: 'Total terpakai di cabang' },
                    { kind: 'movement', movement_type: 'kirim_balik_ke_pusat', label: 'Total kirim ke pusat (retur)' },
                    { kind: 'opname', label: 'Hasil stok opname di cabang' },
                ],
            };

            function buildLaporanTabsHTML() {
                // a. Laporan Data Service
                document.getElementById('tab-laporan-service').innerHTML = `
                    <div class="card" style="max-width:650px;">
                        <h2>Laporan Data Service</h2>
                        <div class="form-section-title">Tentukan Filter Laporan</div>
                        <div class="form-grid">
                            <div class="form-group"><label>Tanggal Dari</label><input type="date" id="lapServiceDateFrom"></div>
                            <div class="form-group"><label>Tanggal Sampai</label><input type="date" id="lapServiceDateTo"></div>
                        </div>
                        <div class="form-group">
                            <label>Departemen</label>
                            <select id="lapServiceDept">
                                <option value="" selected>-- Pilih Departemen --</option>
                                <option value="pusat">Data Service di Pusat</option>
                                <option value="cabang">Data Service di Cabang</option>
                                <option value="pickup">Data Service di Pickup Center</option>
                            </select>
                        </div>
                        <button class="btn" onclick="downloadLaporanService()">📊 Download Laporan</button>
                    </div>
                `;

                // b. Laporan Status Payment
                document.getElementById('tab-laporan-payment').innerHTML = `
                    <div class="card" style="max-width:650px;">
                        <h2>Laporan Status Payment</h2>
                        <div class="form-section-title">Tentukan Filter Laporan</div>
                        <div class="form-grid">
                            <div class="form-group"><label>Tanggal Dari</label><input type="date" id="lapPaymentDateFrom"></div>
                            <div class="form-group"><label>Tanggal Sampai</label><input type="date" id="lapPaymentDateTo"></div>
                        </div>
                        <div class="form-group">
                            <label>Departemen</label>
                            <select id="lapPaymentDept">
                                <option value="" selected>-- Pilih Departemen --</option>
                                <option value="pusat">Data Payment di Pusat</option>
                                <option value="cabang">Data Payment di Cabang</option>
                                <option value="pickup">Data Payment di Pickup Center</option>
                            </select>
                        </div>
                        <button class="btn" onclick="downloadLaporanPayment()">📊 Download Laporan</button>
                    </div>
                `;

                // c. Laporan Inventory Part
                document.getElementById('tab-laporan-inventory').innerHTML = `
                    <div class="card" style="max-width:650px;">
                        <h2>Laporan Inventory Part</h2>
                        <div class="form-section-title">Tentukan Filter Laporan</div>
                        <div class="form-grid">
                            <div class="form-group"><label>Tanggal Dari</label><input type="date" id="lapInvDateFrom"></div>
                            <div class="form-group"><label>Tanggal Sampai</label><input type="date" id="lapInvDateTo"></div>
                        </div>
                        <div class="form-group">
                            <label>Departemen</label>
                            <select id="lapInvDept" onchange="onLapInvDeptChange()">
                                <option value="" selected>-- Pilih Departemen --</option>
                                <option value="pusat">Stok di Pusat</option>
                                <option value="cabang">Stok di Cabang</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Jenis Laporan</label>
                            <select id="lapInvJenis" class="hidden"></select>
                            <div class="field-note" id="lapInvJenisPlaceholder">Pilih Departemen dulu untuk melihat pilihan Jenis Laporan.</div>
                        </div>
                        <button class="btn" onclick="downloadLaporanInventory()">📊 Download Laporan</button>
                    </div>
                `;
            }

            function onLapInvDeptChange() {
                const dept = document.getElementById('lapInvDept').value;
                const select = document.getElementById('lapInvJenis');
                const placeholder = document.getElementById('lapInvJenisPlaceholder');
                if (!dept) {
                    select.classList.add('hidden');
                    placeholder.classList.remove('hidden');
                    return;
                }
                const options = INV_LAPORAN_JENIS[dept];
                select.innerHTML = '<option value="" selected>-- Pilih Jenis Laporan --</option>'
                    + options.map((o, idx) => `<option value="${idx}">${o.label}</option>`).join('');
                select.classList.remove('hidden');
                placeholder.classList.add('hidden');
            }

            async function _downloadReportFile(url, filename) {
                try {
                    const res = await authFetch(url);
                    if (!res.ok) {
                        const err = await res.json().catch(() => ({}));
                        throw new Error(err.detail || 'Gagal mengunduh laporan.');
                    }
                    const blob = await res.blob();
                    const dlUrl = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = dlUrl;
                    a.download = filename;
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    window.URL.revokeObjectURL(dlUrl);
                } catch(e) {
                    alert(e.message);
                }
            }

            function downloadLaporanService() {
                const dept = valOf('lapServiceDept');
                if (!dept) return alert('Pilih Departemen dulu.');
                const dateFrom = valOf('lapServiceDateFrom');
                const dateTo = valOf('lapServiceDateTo');
                const params = new URLSearchParams({ service_type: dept });
                if (dateFrom) params.set('date_from', dateFrom);
                if (dateTo) params.set('date_to', dateTo);
                _downloadReportFile(`/api/v1/admin/reports/excel?${params}`, `Laporan_Data_Service_${dept}.xlsx`);
            }

            function downloadLaporanPayment() {
                const dept = valOf('lapPaymentDept');
                if (!dept) return alert('Pilih Departemen dulu.');
                const dateFrom = valOf('lapPaymentDateFrom');
                const dateTo = valOf('lapPaymentDateTo');
                const params = new URLSearchParams({ service_type: dept });
                if (dateFrom) params.set('date_from', dateFrom);
                if (dateTo) params.set('date_to', dateTo);
                _downloadReportFile(`/api/v1/admin/reports/payment-status?${params}`, `Laporan_Status_Payment_${dept}.xlsx`);
            }

            function downloadLaporanInventory() {
                const dept = valOf('lapInvDept');
                if (!dept) return alert('Pilih Departemen dulu.');
                const jenisIdx = valOf('lapInvJenis');
                if (jenisIdx === '') return alert('Pilih Jenis Laporan dulu.');
                const jenis = INV_LAPORAN_JENIS[dept][parseInt(jenisIdx)];
                const dateFrom = valOf('lapInvDateFrom');
                const dateTo = valOf('lapInvDateTo');

                let url = '';
                if (jenis.kind === 'stock-list') {
                    url = `/api/v1/inventory-parts/report/stock-list?location=${dept}`;
                } else if (jenis.kind === 'movement') {
                    const params = new URLSearchParams({ location: dept, movement_type: jenis.movement_type });
                    if (dateFrom) params.set('date_from', dateFrom);
                    if (dateTo) params.set('date_to', dateTo);
                    url = `/api/v1/inventory-parts/report/movements?${params}`;
                } else if (jenis.kind === 'opname') {
                    const params = new URLSearchParams({ location: dept });
                    if (dateFrom) params.set('date_from', dateFrom);
                    if (dateTo) params.set('date_to', dateTo);
                    url = `/api/v1/inventory-parts/report/opname?${params}`;
                }
                _downloadReportFile(url, `${jenis.label.replace(/ /g, '_')}_${dept}.xlsx`);
            }
        </script>
    </body>
    </html>
    """
