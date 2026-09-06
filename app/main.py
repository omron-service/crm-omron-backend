from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, StreamingResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlalchemy.orm import Session

from app.api.v1 import mutations, services_api
from app.api.v1.services_api import get_db
from app.models.schema import ServiceTicket
from app.services.excel_export import generate_service_report_excel

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="CRM Omron Healthcare API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(mutations.router)
app.include_router(services_api.router)


@app.get("/")
def root():
    return {"status": "online", "system": "CRM Omron Healthcare API"}


@app.get("/api/v1/public/track/{ticket_number}")
@limiter.limit("10/minute")
def track_ticket_api(request: Request, ticket_number: str, phone: str = "", db: Session = Depends(get_db)):
    """
    Mengecek status tiket berdasarkan Nomor Tiket dan Verifikasi Nomor HP/WhatsApp.
    """
    if not phone:
        raise HTTPException(status_code=400, detail="Nomor HP/WhatsApp wajib diisi untuk verifikasi.")

    # Cari tiket di Database berdasarkan Nomor Tiket
    ticket = db.query(ServiceTicket).filter(ServiceTicket.ticket_number == ticket_number.strip()).first()
    
    if not ticket:
        raise HTTPException(status_code=404, detail="Nomor tiket tidak ditemukan.")

    # Normalisasi nomor HP untuk pencocokan (menghilangkan karakter non-digit)
    db_phone = "".join(filter(str.isdigit, ticket.customer_phone or ""))
    input_phone = "".join(filter(str.isdigit, phone or ""))

    # Cek pencocokan nomor HP (support format 08xx maupun 628xx)
    if not (db_phone in input_phone or input_phone in db_phone or db_phone[-8:] == input_phone[-8:]):
        raise HTTPException(status_code=403, detail="Nomor HP/WhatsApp tidak cocok dengan nomor yang terdaftar pada tiket ini.")

    return {
        "ticket_number": ticket.ticket_number,
        "customer_name": ticket.customer_name,
        "device_model": ticket.device_model,
        "status": ticket.status or "Diproses",
        "current_location": ticket.branch_or_point or "Service Center Pusat (Jakarta)",
        "created_at": ticket.created_at.strftime("%Y-%m-%d") if ticket.created_at else "-"
    }


@app.get("/api/v1/admin/reports/excel")
def download_excel_report():
    mock_tickets = [
        {
            "ticket_number": "JKT-2600001",
            "created_at": "2026-09-01",
            "customer_name": "Budi Santoso",
            "customer_phone": "081234567890",
            "device_model": "HEM-7120",
            "serial_number": "SN7120-9921",
            "status": "Diproses",
            "technician": "Ahmad Teknisi",
        }
    ]
    excel_file = generate_service_report_excel(mock_tickets)
    filename = "Laporan_Servis_Omron_2026.xlsx"
    return StreamingResponse(
        excel_file,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/track", response_class=HTMLResponse)
def track_ticket_page():
    return """
    <!DOCTYPE html>
    <html lang="id">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Pelacakan Servis - Omron Healthcare</title>
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f0f2f5; margin: 0; padding: 20px; display: flex; justify-content: center; align-items: center; min-height: 80vh; }
            .card { background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); max-width: 420px; width: 100%; text-align: center; }
            .logo { font-size: 24px; font-weight: bold; color: #0056b3; margin-bottom: 5px; }
            .subtitle { color: #666; font-size: 14px; margin-bottom: 20px; }
            .form-group { text-align: left; margin-bottom: 12px; }
            label { font-size: 12px; font-weight: bold; color: #444; display: block; margin-bottom: 4px; }
            input { width: 100%; padding: 12px; border: 1px solid #ccc; border-radius: 6px; box-sizing: border-box; font-size: 14px; }
            button { width: 100%; padding: 12px; background: #0056b3; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: bold; font-size: 14px; margin-top: 10px; }
            button:hover { background: #004085; }
            .result { margin-top: 20px; padding: 15px; background: #e9ecef; border-radius: 8px; text-align: left; font-size: 14px; display: none; line-height: 1.6; }
            .status-badge { color: #155724; background-color: #d4edda; border: 1px solid #c3e6cb; padding: 2px 8px; border-radius: 4px; font-weight: bold; }
            .error-box { color: #721c24; background-color: #f8d7da; border: 1px solid #f5c6cb; padding: 10px; border-radius: 6px; margin-top: 15px; display: none; font-size: 13px; text-align: left; }
        </style>
    </head>
    <body>
        <div class="card">
            <div class="logo">OMRON</div>
            <div class="subtitle">Layanan Pelacakan Servis Perangkat</div>
            
            <div class="form-group">
                <label>Nomor Tiket Servis</label>
                <input type="text" id="ticketInput" placeholder="Contoh: JKT-2600001">
            </div>

            <div class="form-group">
                <label>Nomor HP / WhatsApp (Verifikasi Pemilik)</label>
                <input type="tel" id="phoneInput" placeholder="Contoh: 081234567890">
            </div>

            <button onclick="trackTicket()">Lacak Status Perangkat</button>
            
            <div id="errorBox" class="error-box"></div>
            <div id="resultBox" class="result"></div>
        </div>

        <script>
            async function trackTicket() {
                const ticket = document.getElementById('ticketInput').value.trim();
                const phone = document.getElementById('phoneInput').value.trim();
                const resultBox = document.getElementById('resultBox');
                const errorBox = document.getElementById('errorBox');

                errorBox.style.display = 'none';
                resultBox.style.display = 'none';

                if(!ticket) return alert('Silakan masukkan nomor tiket Anda!');
                if(!phone) return alert('Silakan masukkan nomor HP/WhatsApp terdaftar untuk verifikasi!');

                resultBox.style.display = 'block';
                resultBox.innerHTML = 'Memuat data pelacakan...';

                try {
                    const res = await fetch(`/api/v1/public/track/${encodeURIComponent(ticket)}?phone=${encodeURIComponent(phone)}`);
                    const data = await res.json();

                    if(!res.ok) {
                        throw new Error(data.detail || 'Gagal memuat status tiket.');
                    }

                    resultBox.innerHTML = `
                        <strong>No. Tiket:</strong> ${data.ticket_number}<br>
                        <strong>Nama Pemilik:</strong> ${data.customer_name}<br>
                        <strong>Model Perangkat:</strong> ${data.device_model}<br>
                        <strong>Status Servis:</strong> <span class="status-badge">${data.status}</span><br>
                        <strong>Lokasi Perangkat:</strong> ${data.current_location}<br>
                        <strong>Tanggal Diterima:</strong> ${data.created_at}
                    `;
                } catch(err) {
                    resultBox.style.display = 'none';
                    errorBox.style.display = 'block';
                    errorBox.innerHTML = `⚠️ <strong>Gagal Verifikasi:</strong> ${err.message}`;
                }
            }
        </script>
    </body>
    </html>
    """


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard_page():
    return """...""" # Tetap menyatu dengan UI Admin Dashboard
