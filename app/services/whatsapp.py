import os
import requests

FONNTE_TOKEN = os.getenv("FONNTE_TOKEN", "DUMMY_TOKEN_WA")

def send_whatsapp_notification(target_phone: str, message: str) -> bool:
    """
    Mengirim notifikasi WhatsApp via Fonnte Gateway
    """
    url = "https://api.fonnte.com/send"
    headers = {
        "Authorization": FONNTE_TOKEN
    }
    payload = {
        "target": target_phone,
        "message": message,
        "countryCode": "62"
    }
    
    try:
        # Jika masih dummy token, cetak di log konsol saja
        if FONNTE_TOKEN == "DUMMY_TOKEN_WA":
            print(f"[SIMULASI WA SENT] Ke: {target_phone} | Pesan: {message}")
            return True
            
        response = requests.post(url, headers=headers, data=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Gagal mengirim WhatsApp: {e}")
        return False