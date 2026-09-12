"""
Integrasi tracking pengiriman GED (jasa kirim) - KERANGKA DASAR.

STATUS: fondasi sudah siap & sudah ditest, TAPI verifikasi keamanan di sini
memakai skema PALING UMUM (API Key statis di header) karena PIC teknis GED
belum memberi dokumentasi resmi soal cara autentikasi mereka. BEGITU dapat
detail asli dari GED (mis. ternyata mereka pakai HMAC signature seperti
DOKU, atau format payload beda), sesuaikan fungsi `_verify_ged_request()`
dan skema `GedWebhookPayload` di bawah - jangan langsung dipakai produksi
sebelum disesuaikan dengan spesifikasi resmi GED.

ALUR YANG DIASUMSIKAN (konfirmasi ke GED sebelum go-live):
1. Saat tiket dikirim, kita kasih GED: Nomor Tiket kita + Serial No. alat.
2. GED simpan kedua field itu sbg referensi di sistem mereka.
3. Setiap kali status pengiriman berubah, GED POST ke endpoint ini dengan
   Nomor Tiket + Serial No. + status terbaru.
4. Kita cocokkan KEDUANYA (bukan cuma nomor tiket) sebelum update - kalau
   serial tidak cocok, ditolak (mencegah salah kirim/salah ketik dari GED
   ikut mengubah status tiket yang salah).
"""
import os
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_ged_db
from app.core.limiter import limiter
from app.models.schema import ServiceTicket, ShipmentTrackingEvent
from app.services.shipping_status import apply_ged_event

router = APIRouter(prefix="/api/v1/public", tags=["Integrasi GED"])

# Header yang dipakai utk API Key - GANTI kalau ternyata GED pakai nama
# header lain (mis. "X-API-Key" polos, atau "Authorization: Bearer ...").
GED_API_KEY_HEADER = "X-GED-API-Key"


def _verify_ged_request(request: Request):
    """
    Verifikasi PALING DASAR: cocokkan API Key statis di header dengan
    GED_WEBHOOK_SECRET yang diatur di server. SESUAIKAN fungsi ini kalau
    GED ternyata pakai skema lain (HMAC signature, mTLS, dll) - lihat
    verify_turnstile_or_raise() atau doku_payment.verify_notification_signature()
    di file lain sebagai CONTOH pola verifikasi yang lebih kuat (HMAC).
    """
    secret = os.environ.get("GED_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="Integrasi GED belum diaktifkan di server (GED_WEBHOOK_SECRET belum diisi).",
        )

    incoming_key = request.headers.get(GED_API_KEY_HEADER, "")
    if not incoming_key or incoming_key != secret:
        raise HTTPException(status_code=401, detail="API Key tidak valid.")


class GedWebhookPayload(BaseModel):
    """
    SESUAIKAN field-field ini begitu format asli dari GED diketahui - ini
    baru asumsi awal berdasarkan referensi yang disepakati (Nomor Tiket +
    Serial No.), BUKAN spesifikasi resmi dari GED.

    `event` diasumsikan salah satu dari "awb_issued" atau "delivered" -
    sistem KITA yang menentukan label Status Pengiriman yang tepat
    berdasarkan tahap tiket saat ini (lihat app/services/shipping_status.py),
    GED tidak perlu tahu soal "Stage 1"/"Stage 2".
    """
    ticket_number: str
    serial_number: str
    event: str  # "awb_issued" | "delivered" - SESUAIKAN nama field/nilai ke asli GED
    awb_number: Optional[str] = None       # wajib diisi GED saat event="awb_issued"
    received_by_name: Optional[str] = None  # wajib diisi GED saat event="delivered" (nama dari kurir, BUKAN dari data kita)
    event_timestamp: Optional[str] = None  # ISO 8601, opsional


@router.post("/ged-webhook")
@limiter.limit("30/minute")
async def ged_shipment_webhook(request: Request, db: Session = Depends(get_ged_db)):
    """
    Endpoint publik (tanpa login) yang dipanggil OTOMATIS oleh server GED
    setiap kali status pengiriman berubah. Diamankan dengan API Key statis
    (lihat _verify_ged_request) - kalau GED_WEBHOOK_SECRET belum diisi,
    endpoint ini menolak dgn jelas (503), TIDAK diam-diam menerima apa pun.
    """
    _verify_ged_request(request)

    body_raw = await request.body()
    try:
        payload_dict = json.loads(body_raw)
        payload = GedWebhookPayload(**payload_dict)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Format payload tidak sesuai: {str(e)}")

    ticket = (
        db.query(ServiceTicket)
        .filter(ServiceTicket.ticket_number == payload.ticket_number.strip())
        .first()
    )
    if not ticket:
        return JSONResponse(status_code=404, content={"ok": False, "message": "Nomor tiket tidak ditemukan."})

    ticket_serial = (ticket.serial_number or "").strip().lower()
    incoming_serial = payload.serial_number.strip().lower()
    if not ticket_serial or ticket_serial != incoming_serial:
        # SENGAJA ditolak - mencegah update "nyasar" ke tiket yang salah
        # kalau ada kesalahan input/typo di sisi GED. CATATAN: nomor AWB dan
        # nama penerima BOLEH sama antar beberapa tiket (dikirim satu paket
        # sekaligus dari lokasi yang sama) - itu wajar, bukan indikasi error.
        # Yang divalidasi ketat di sini HANYA pasangan ticket_number+serial_number.
        return JSONResponse(
            status_code=400,
            content={"ok": False, "message": "Serial number tidak cocok dengan data tiket ini."},
        )

    applied = apply_ged_event(ticket, payload.event, payload.awb_number, payload.received_by_name)
    if not applied:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "message": f"Event '{payload.event}' tidak sesuai dengan tahap tiket ini saat ini (shipping_status='{ticket.shipping_status}')."},
        )

    event_dt = None
    if payload.event_timestamp:
        try:
            event_dt = datetime.fromisoformat(payload.event_timestamp.replace("Z", "+00:00"))
        except ValueError:
            event_dt = None

    db.add(ShipmentTrackingEvent(
        ticket_id=ticket.id,
        status=ticket.shipping_status,
        raw_payload=body_raw.decode("utf-8", errors="replace"),
        event_timestamp=event_dt,
        received_at=datetime.utcnow(),
    ))
    db.commit()

    return {"ok": True, "message": "Status pengiriman berhasil diperbarui.", "new_status": ticket.shipping_status}
