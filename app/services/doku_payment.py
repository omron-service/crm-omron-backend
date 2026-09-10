"""
Integrasi DOKU Checkout API untuk generate kode bayar (Virtual Account bank
dan pembayaran ritel Alfamart/Indomaret).

Referensi resmi: https://developers.doku.com/accept-payments/doku-checkout
Endpoint yang dipakai: POST /checkout/v1/payment ("Obtain payment.url")

CARA KERJA SINGKAT:
1. Kita kirim: jumlah tagihan, nomor invoice (nomor tiket), dan jenis kanal
   pembayaran yang dipilih staff (mis. VIRTUAL_ACCOUNT_BCA).
2. DOKU membalas dengan `payment.url` - halaman pembayaran ter-hosting DOKU
   yang MENAMPILKAN nomor VA / kode bayar ke pelanggan. Kita simpan link ini
   dan tampilkan/bagikan ke pelanggan (tidak perlu kita yang menampilkan
   nomor VA-nya sendiri - DOKU yang menampilkannya di halaman itu).

KREDENSIAL YANG DIBUTUHKAN (environment variables di Railway):
- DOKU_CLIENT_ID   : Client ID dari DOKU Back Office
- DOKU_SECRET_KEY  : Secret Key dari DOKU Back Office
- DOKU_ENV         : "sandbox" (uji coba) atau "production" (transaksi asli)
                      Default "sandbox" kalau tidak diisi - SENGAJA aman by
                      default, supaya tidak tidak sengaja kena transaksi asli
                      sebelum kredensial production benar-benar dipasang.
"""
import base64
import hashlib
import hmac
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import requests

# Kanal pembayaran yang didukung, sesuai daftar resmi DOKU Checkout -
# key di sini PERSIS yang dikirim ke API DOKU, value adalah label utk ditampilkan.
PAYMENT_METHOD_LABELS = {
    "ONLINE_TO_OFFLINE_ALFA": "Alfamart",
    "ONLINE_TO_OFFLINE_INDOMARET": "Indomaret",
    "VIRTUAL_ACCOUNT_BRI": "VA BRI",
    "VIRTUAL_ACCOUNT_BCA": "VA BCA",
    "VIRTUAL_ACCOUNT_BNI": "VA BNI",
    "VIRTUAL_ACCOUNT_PERMATA": "VA Permata",
    "VIRTUAL_ACCOUNT_BANK_MANDIRI": "VA Mandiri",
}

SANDBOX_BASE_URL = "https://api-sandbox.doku.com"
PRODUCTION_BASE_URL = "https://api.doku.com"
CHECKOUT_PATH = "/checkout/v1/payment"


class DokuConfigError(Exception):
    """Kredensial DOKU belum diisi/salah - beda dari error respons API DOKU."""
    pass


class DokuApiError(Exception):
    """DOKU membalas dengan error (mis. saldo channel belum aktif, kredensial salah, dll)."""
    pass


def _get_config():
    client_id = os.environ.get("DOKU_CLIENT_ID")
    secret_key = os.environ.get("DOKU_SECRET_KEY")
    env = os.environ.get("DOKU_ENV", "sandbox").strip().lower()

    if not client_id or not secret_key:
        raise DokuConfigError(
            "Kredensial DOKU belum diatur di server (DOKU_CLIENT_ID / DOKU_SECRET_KEY "
            "belum diisi di Environment Variables Railway). Hubungi admin sistem."
        )
    base_url = PRODUCTION_BASE_URL if env == "production" else SANDBOX_BASE_URL
    return client_id, secret_key, base_url, env


def _generate_signature(client_id: str, secret_key: str, request_id: str, timestamp: str, body_json: str) -> str:
    """
    Mengikuti spesifikasi resmi DOKU (Signature Component from Request Header):
    1. Digest = base64(SHA256(request_body))
    2. Susun komponen jadi teks (satu baris per komponen, dipisah newline, TANPA newline di akhir):
       Client-Id:{client_id}
       Request-Id:{request_id}
       Request-Timestamp:{timestamp}
       Request-Target:{path}
       Digest:{digest}
    3. Signature = "HMACSHA256=" + base64(HMAC-SHA256(teks_di_atas, secret_key))
    """
    digest = base64.b64encode(hashlib.sha256(body_json.encode("utf-8")).digest()).decode()

    raw = (
        f"Client-Id:{client_id}\n"
        f"Request-Id:{request_id}\n"
        f"Request-Timestamp:{timestamp}\n"
        f"Request-Target:{CHECKOUT_PATH}\n"
        f"Digest:{digest}"
    )
    signature = base64.b64encode(
        hmac.new(secret_key.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).digest()
    ).decode()
    return f"HMACSHA256={signature}"


def verify_notification_signature(
    client_id: str, secret_key: str, request_id: str, timestamp: str,
    request_target: str, body_raw: bytes, signature_header: str,
) -> bool:
    """
    Verifikasi signature notifikasi/webhook yang DATANG DARI DOKU (arah
    kebalikan dari _generate_signature - di sini DOKU adalah pengirim, kita
    yang memverifikasi). Dipakai oleh endpoint publik /doku-notification agar
    tidak ada pihak lain yang bisa memalsukan notifikasi "pembayaran sukses".
    """
    digest = base64.b64encode(hashlib.sha256(body_raw).digest()).decode()
    raw = (
        f"Client-Id:{client_id}\n"
        f"Request-Id:{request_id}\n"
        f"Request-Timestamp:{timestamp}\n"
        f"Request-Target:{request_target}\n"
        f"Digest:{digest}"
    )
    expected = base64.b64encode(
        hmac.new(secret_key.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).digest()
    ).decode()
    expected_header = f"HMACSHA256={expected}"
    return hmac.compare_digest(expected_header, signature_header or "")


def create_payment_code(
    invoice_number: str,
    amount: float,
    payment_method: str,
    customer_name: Optional[str] = None,
    customer_phone: Optional[str] = None,
    callback_url: Optional[str] = None,
    payment_due_minutes: int = 1440,  # default 24 jam
) -> dict:
    """
    Membuat kode bayar/VA lewat DOKU Checkout. Mengembalikan dict:
    {payment_url, token_id, expired_date_utc}

    Melempar DokuConfigError kalau kredensial belum diatur, atau DokuApiError
    kalau DOKU menolak request (kredensial salah, channel belum aktif, dst).
    """
    if payment_method not in PAYMENT_METHOD_LABELS:
        raise ValueError(
            f"Metode pembayaran '{payment_method}' tidak dikenali. "
            f"Pilihan yang valid: {', '.join(PAYMENT_METHOD_LABELS.keys())}."
        )
    if not amount or amount <= 0:
        raise ValueError("Jumlah tagihan (Harga Service) harus lebih dari 0 sebelum generate kode bayar.")

    client_id, secret_key, base_url, env = _get_config()

    import json
    body = {
        "order": {
            "amount": int(round(amount)),  # DOKU: IDR tanpa desimal
            "invoice_number": invoice_number,
        },
        "payment": {
            "payment_method_types": [payment_method],
            "payment_due_date": payment_due_minutes,
        },
    }
    if callback_url:
        body["order"]["callback_url"] = callback_url
    if customer_name or customer_phone:
        body["customer"] = {}
        if customer_name:
            body["customer"]["name"] = customer_name
        if customer_phone:
            body["customer"]["phone"] = customer_phone

    body_json = json.dumps(body, separators=(",", ":"))

    request_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    signature = _generate_signature(client_id, secret_key, request_id, timestamp, body_json)

    headers = {
        "Client-Id": client_id,
        "Request-Id": request_id,
        "Request-Timestamp": timestamp,
        "Signature": signature,
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(base_url + CHECKOUT_PATH, headers=headers, data=body_json, timeout=20)
    except requests.RequestException as e:
        raise DokuApiError(f"Gagal menghubungi server DOKU ({env}): {str(e)}")

    if resp.status_code != 200:
        detail = resp.text[:300]
        raise DokuApiError(f"DOKU menolak permintaan (HTTP {resp.status_code}, mode {env}): {detail}")

    data = resp.json()
    payment_info = data.get("response", {}).get("payment", {})
    if not payment_info.get("url"):
        raise DokuApiError(f"Respons DOKU tidak berisi link pembayaran: {data}")

    return {
        "payment_url": payment_info.get("url"),
        "token_id": payment_info.get("token_id"),
        "expired_date_raw": payment_info.get("expired_date"),  # format yyyyMMddHHmmss (UTC+7)
        "environment": env,
    }
