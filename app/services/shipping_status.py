"""
Logic terpusat utk "Status Pengiriman" (shipping_status) - field TERPISAH dari
"Repair Status" (status) yang sudah ada sejak awal. Field ini jalan OTOMATIS
(tidak pernah dipilih manual oleh staff), dipicu oleh: submit form publik,
perubahan Repair Status tertentu, timer 24 jam, dan webhook GED.

Lihat PANDUAN_STATUS_PENGIRIMAN.md utk tabel logika lengkap yang sudah
disepakati bersama user.
"""
from datetime import datetime, timedelta

# ---- Nilai-nilai shipping_status yang mungkin (Stage 1 - khusus asal Pickup Center) ----
SHIP_DITERIMA_PICKUP_CENTER = "Diterima Pickup Center"
SHIP_MENUNGGU_KURIR = "Menunggu Kurir"
SHIP_DITERUSKAN_KE_OMRON = "Diteruskan ke Omron"
SHIP_DITERIMA_OMRON = "Diterima Omron"  # juga jadi TITIK MASUK Stage 2 (utk tiket langsung Pusat)

# ---- Nilai-nilai shipping_status (Stage 2 - berlaku SEMUA asal, Pusat & Pickup Center) ----
SHIP_DIPROSES = "Diproses"
SHIP_DIKIRIM_BALIK = "Dikirim Balik"  # sebelumnya "Selesai/Dikirim", diganti sesuai permintaan
SHIP_DITERIMA_FINAL = "Diterima"

# Status Repair yang jadi PEMICU pindah ke shipping_status "Diproses" (repair
# selesai, siap dikirim balik) - berlaku utk tiket Pusat MAUPUN Pickup Center,
# TIDAK berlaku utk Cabang (belum termasuk cakupan fitur ini).
REPAIR_STATUS_TRIGGERS_DIPROSES = {"Selesai/Dikirim", "Selesai Diambil"}

# Lokasi yang IKUT fitur Status Pengiriman - Cabang SENGAJA belum termasuk.
SHIPPING_ENABLED_SERVICE_TYPES = {"pusat", "pickup"}

# Batas waktu auto-transisi "Menunggu Kurir" (Stage 1) - lihat scheduler di app/services/scheduler.py
MENUNGGU_KURIR_AFTER_HOURS = 24


def initial_shipping_status_for_new_ticket(service_type: str, repair_status: str) -> str | None:
    """
    Dipanggil SAAT TIKET DIBUAT - baik dari form publik (/pickup-intake,
    /receipt) MAUPUN input manual staff. Menentukan shipping_status AWAL.
    """
    if service_type not in SHIPPING_ENABLED_SERVICE_TYPES:
        return None  # Cabang, dst - tidak ikut fitur ini sama sekali

    if service_type == "pickup" and repair_status == "Diterima":
        return SHIP_DITERIMA_PICKUP_CENTER
    if service_type == "pusat":
        return SHIP_DITERIMA_OMRON
    return None


def maybe_apply_diproses_transition(ticket) -> bool:
    """
    Dipanggil SETIAP KALI tiket diupdate (baik dari admin panel Pusat MAUPUN
    Pickup Center) - kalau Repair Status baru saja diset ke salah satu nilai
    "siap dikirim balik" DAN shipping_status tiket ini masih di titik
    "Diterima Omron" (blm pernah maju ke Diproses/lebih jauh), majukan ke
    "Diproses". TIDAK menimpa kalau shipping_status sudah lebih maju dari itu
    (mis. GED sudah keburu update duluan - jangan mundur).
    Return True kalau ada perubahan.
    """
    if ticket.service_type not in SHIPPING_ENABLED_SERVICE_TYPES:
        return False
    if ticket.status not in REPAIR_STATUS_TRIGGERS_DIPROSES:
        return False
    if ticket.shipping_status != SHIP_DITERIMA_OMRON:
        return False  # sudah maju lebih jauh, atau belum pernah sampai situ - jangan diubah paksa
    ticket.shipping_status = SHIP_DIPROSES
    ticket.shipping_updated_at = datetime.utcnow()
    return True


def apply_ged_event(ticket, event: str, awb_number: str | None, received_by_name: str | None) -> bool:
    """
    Dipanggil dari webhook GED. `event` diasumsikan salah satu dari:
    "awb_issued" atau "delivered" (SESUAIKAN kalau format asli GED beda).

    Sistem KITA yang menentukan label mana yang tepat, berdasarkan
    shipping_status TERAKHIR tiket saat ini - GED tidak perlu tahu soal
    "Stage 1"/"Stage 2", cukup kasih tahu 2 jenis kejadian dasar ini.
    Return True kalau ada perubahan status (event dikenali & diterapkan).
    """
    current = ticket.shipping_status

    if event == "awb_issued":
        ticket.awb_number = awb_number
        if current in (SHIP_DITERIMA_PICKUP_CENTER, SHIP_MENUNGGU_KURIR):
            ticket.shipping_status = SHIP_DITERUSKAN_KE_OMRON
        elif current == SHIP_DIPROSES:
            ticket.shipping_status = SHIP_DIKIRIM_BALIK
        else:
            return False  # event tidak sesuai konteks tiket saat ini - abaikan, jangan paksa ubah
        ticket.shipping_updated_at = datetime.utcnow()
        return True

    if event == "delivered":
        if current == SHIP_DITERUSKAN_KE_OMRON:
            ticket.shipping_status = SHIP_DITERIMA_OMRON
        elif current == SHIP_DIKIRIM_BALIK:
            ticket.shipping_status = SHIP_DITERIMA_FINAL
            ticket.received_by_name = received_by_name  # nama penerima HANYA relevan di titik akhir ini
        else:
            return False
        ticket.shipping_updated_at = datetime.utcnow()
        return True

    return False  # event tidak dikenali sama sekali


def compute_track_display(ticket) -> dict:
    """
    Menentukan APA YANG TAMPIL ke pelanggan di /track - termasuk logic
    "-----" (dash) supaya hanya SATU status yang "aktif" ditampilkan tiap
    saat, sesuai kondisi fisik alatnya. Lihat tabel kesepakatan lengkap.
    """
    shipping_status = ticket.shipping_status
    repair_status = ticket.status or "Diterima"

    SHIPPING_ACTIVE_STAGE1 = {SHIP_DITERIMA_PICKUP_CENTER, SHIP_MENUNGGU_KURIR, SHIP_DITERUSKAN_KE_OMRON}

    if shipping_status in SHIPPING_ACTIVE_STAGE1:
        display_repair = None       # "-----" - teknisi belum pegang alatnya sama sekali
        display_shipping = shipping_status
    elif shipping_status == SHIP_DITERIMA_OMRON:
        display_repair = repair_status
        display_shipping = None     # "-----" - sedang dikerjakan, belum ada aktivitas kirim
    elif shipping_status in (SHIP_DIPROSES, SHIP_DIKIRIM_BALIK, SHIP_DITERIMA_FINAL):
        display_repair = repair_status
        display_shipping = shipping_status
    else:
        # shipping_status belum diisi sama sekali (tiket lama sblm fitur ini
        # ada, atau Cabang yg memang tidak ikut fitur ini) - tampilkan Repair
        # Status seperti biasa, kosongkan Status Pengiriman.
        display_repair = repair_status
        display_shipping = None

    # Nama Penerima - HANYA muncul di titik akhir "Diterima", datanya dari
    # kurir GED (received_by_name), BUKAN dari customer_name/instansi_name kita.
    receiver_name = None
    if shipping_status == SHIP_DITERIMA_FINAL and ticket.received_by_name:
        if ticket.service_type == "pickup" and ticket.instansi_name:
            receiver_name = f"{ticket.instansi_name} - {ticket.received_by_name}"
        else:
            receiver_name = ticket.received_by_name

    return {
        "displayRepairStatus": display_repair,   # None -> frontend tampilkan "-----"
        "displayShippingStatus": display_shipping,
        "awbNumber": ticket.awb_number,
        "receiverName": receiver_name,
    }
