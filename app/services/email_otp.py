"""
Pengiriman email OTP lewat Resend API - dipakai khusus 2FA login Super Admin.

KENAPA BUKAN GMAIL SMTP LAGI: Railway (hosting server ini) memblokir SEMUA
koneksi SMTP keluar (port 25/465/587) di level platform, sebagai kebijakan
anti-spam mereka - ini dikonfirmasi resmi oleh tim Railway sendiri, BUKAN
bug di kode ini. Gmail SMTP TIDAK AKAN PERNAH bisa jalan dari Railway, apa
pun yang diperbaiki di kode. Solusinya: pakai layanan email yang punya
HTTPS API (bukan SMTP) - Railway sendiri merekomendasikan Resend.

KREDENSIAL YANG DIBUTUHKAN (environment variables di Railway):
- RESEND_API_KEY   : API key dari resend.com (gratis, tanpa kartu kredit)
- RESEND_FROM_EMAIL: opsional - default "onboarding@resend.dev" (alamat
                      pengirim bawaan Resend, bisa dipakai tanpa verifikasi
                      domain).

CATATAN PENTING soal batasan tier gratis Resend TANPA verifikasi domain:
email HANYA bisa dikirim ke alamat yang SAMA dengan email pendaftaran akun
Resend Anda. Jadi daftar Resend pakai email Super Admin yang login di
sistem ini, supaya OTP-nya benar-benar sampai. Kalau nanti ada Super Admin
lain dengan email berbeda, perlu verifikasi domain di Resend dulu (butuh
domain sendiri - sama seperti prasyarat Opsi 3 Cloudflare sebelumnya).
"""
import os
import requests


class OtpEmailConfigError(Exception):
    """Kredensial Resend belum diisi di server."""
    pass


class OtpEmailSendError(Exception):
    """Kredensial ada, tapi pengiriman ke Resend gagal (mis. API key salah,
    atau email tujuan bukan email pendaftaran akun Resend - lihat catatan
    di atas soal batasan tier gratis tanpa verifikasi domain)."""
    pass


def send_otp_email(to_email: str, otp_code: str, full_name: str):
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    from_email = os.environ.get("RESEND_FROM_EMAIL", "onboarding@resend.dev").strip()

    if not api_key:
        raise OtpEmailConfigError(
            "Kredensial pengirim email belum diatur di server (RESEND_API_KEY "
            "belum diisi di Environment Variables Railway). Hubungi admin sistem."
        )

    body_text = (
        f"Halo {full_name},\n\n"
        f"Kode OTP login Anda: {otp_code}\n\n"
        f"Kode ini berlaku selama 5 menit dan hanya bisa dipakai SATU KALI.\n"
        f"JANGAN bagikan kode ini kepada siapa pun, termasuk pihak yang mengaku dari tim IT/Omron.\n\n"
        f"Kalau Anda tidak merasa sedang login, abaikan email ini dan segera "
        f"hubungi admin sistem - ada kemungkinan seseorang mencoba masuk ke akun Anda."
    )

    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "from": f"CRM Omron Service <{from_email}>",
                "to": [to_email],
                "subject": "Kode OTP Login - CRM Omron Service",
                "text": body_text,
            },
            timeout=15,
        )
    except requests.RequestException as e:
        raise OtpEmailSendError(f"Gagal menghubungi server Resend: {str(e)}")

    if resp.status_code not in (200, 201):
        detail = resp.text[:300]
        raise OtpEmailSendError(
            f"Resend menolak pengiriman (HTTP {resp.status_code}): {detail}. "
            f"Kalau pesannya soal 'domain not verified' atau penerima ditolak, "
            f"ingat: tanpa verifikasi domain, Resend HANYA bisa kirim ke email "
            f"yang sama dengan email pendaftaran akun Resend Anda."
        )

