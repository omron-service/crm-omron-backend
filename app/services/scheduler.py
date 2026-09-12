"""
Penjadwal ringan berbasis asyncio (TIDAK butuh library tambahan spt
APScheduler/Celery) - cukup untuk kebutuhan sederhana: cek tiket Pickup
Center yang sudah 24 jam tapi shipping_status-nya belum maju, lalu majukan
otomatis ke "Menunggu Kurir".

Berjalan sebagai satu background task selama proses FastAPI hidup - kalau
server di-restart, loop ini otomatis mulai lagi dari awal (aman, tidak ada
state yang hilang karena semua yang dicek berdasarkan data di database).
"""
import asyncio
import logging
from datetime import datetime, timedelta

from app.db.session import SessionLocal
from app.models.schema import ServiceTicket
from app.services.shipping_status import (
    SHIP_DITERIMA_PICKUP_CENTER, SHIP_MENUNGGU_KURIR, MENUNGGU_KURIR_AFTER_HOURS,
)

logger = logging.getLogger("uvicorn")

CHECK_INTERVAL_SECONDS = 60 * 60  # cek tiap 1 jam - cukup utk kebutuhan ini (bukan real-time)


def _run_menunggu_kurir_check():
    """Satu kali jalan - dipisah dari loop-nya supaya gampang dites terpisah."""
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(hours=MENUNGGU_KURIR_AFTER_HOURS)
        tickets = (
            db.query(ServiceTicket)
            .filter(
                ServiceTicket.service_type == "pickup",
                ServiceTicket.shipping_status == SHIP_DITERIMA_PICKUP_CENTER,
                ServiceTicket.created_at < cutoff,
            )
            .all()
        )
        for t in tickets:
            t.shipping_status = SHIP_MENUNGGU_KURIR
            t.shipping_updated_at = datetime.utcnow()
        if tickets:
            db.commit()
            logger.info(f"[scheduler] {len(tickets)} tiket dipindah ke 'Menunggu Kurir' (>{MENUNGGU_KURIR_AFTER_HOURS} jam tanpa progress).")
        return len(tickets)
    finally:
        db.close()


async def shipping_status_scheduler_loop():
    while True:
        try:
            _run_menunggu_kurir_check()
        except Exception as e:
            logger.error(f"[scheduler] Error saat cek auto-transisi Menunggu Kurir: {e}")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
