"""
Pengiriman email OTP lewat Gmail SMTP - dipakai khusus 2FA login Super Admin.

KREDENSIAL YANG DIBUTUHKAN (environment variables di Railway):
- GMAIL_ADDRESS       : alamat Gmail pengirim, mis. cs.omronservice@gmail.com
- GMAIL_APP_PASSWORD  : App Password 16 digit dari Google (BUKAN password
                         login Gmail biasa) - lihat panduan pembuatan di
                         PANDUAN_OTP_EMAIL.md.

Kalau kedua variable ini belum diisi, fungsi ini akan melempar DokuConfigError
-gaya (OtpEmailConfigError) dengan pesan jelas - endpoint login akan menolak
proses OTP dengan pesan yang bisa dipahami admin, BUKAN error mentah/500.
"""
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


class OtpEmailConfigError(Exception):
    """Kredensial Gmail belum diisi di server."""
    pass


class OtpEmailSendError(Exception):
    """Kredensial ada, tapi pengiriman ke Gmail gagal (mis. App Password salah)."""
    pass


def send_otp_email(to_email: str, otp_code: str, full_name: str):
    gmail_address = os.environ.get("GMAIL_ADDRESS", "").strip()
    gmail_app_password = os.environ.get("GMAIL_APP_PASSWORD", "").strip()

    if not gmail_address or not gmail_app_password:
        raise OtpEmailConfigError(
            "Kredensial pengirim email belum diatur di server (GMAIL_ADDRESS / "
            "GMAIL_APP_PASSWORD belum diisi di Environment Variables Railway). "
            "Hubungi admin sistem."
        )

    subject = "Kode OTP Login - CRM Omron Service"
    body_text = (
        f"Halo {full_name},\n\n"
        f"Kode OTP login Anda: {otp_code}\n\n"
        f"Kode ini berlaku selama 5 menit dan hanya bisa dipakai SATU KALI.\n"
        f"JANGAN bagikan kode ini kepada siapa pun, termasuk pihak yang mengaku dari tim IT/Omron.\n\n"
        f"Kalau Anda tidak merasa sedang login, abaikan email ini dan segera "
        f"hubungi admin sistem - ada kemungkinan seseorang mencoba masuk ke akun Anda."
    )

    msg = MIMEMultipart()
    msg["From"] = gmail_address
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body_text, "plain"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as server:
            server.starttls()
            server.login(gmail_address, gmail_app_password)
            server.sendmail(gmail_address, [to_email], msg.as_string())
    except smtplib.SMTPAuthenticationError:
        raise OtpEmailSendError(
            "Gagal login ke Gmail - App Password kemungkinan salah atau sudah dicabut. "
            "Buat App Password baru dan update GMAIL_APP_PASSWORD di Railway."
        )
    except Exception as e:
        raise OtpEmailSendError(f"Gagal mengirim email OTP: {str(e)}")
