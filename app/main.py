from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.api.v1 import mutations

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="CRM Omron Healthcare API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Register Router
app.include_router(mutations.router)

@app.get("/")
def root():
    return {"status": "online", "system": "CRM Omron Healthcare API"}

# Endpoint API JSON Tracking
@app.get("/api/v1/public/track/{ticket_number}")
@limiter.limit("10/minute")
def track_ticket_api(request: Request, ticket_number: str):
    return {
        "ticket_number": ticket_number,
        "device_model": "Omron HEM-7120",
        "status": "Sedang Diperbaiki Teknisi",
        "current_location": "Service Center Pusat (Jakarta)"
    }

# Endpoint Halaman Web HTML Tracking
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
            input { width: 100%; padding: 12px; margin-bottom: 12px; border: 1px solid #ccc; border-radius: 6px; box-sizing: border-box; font-size: 14px; }
            button { width: 100%; padding: 12px; background: #0056b3; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: bold; font-size: 14px; }
            button:hover { background: #004085; }
            .result { margin-top: 20px; padding: 15px; background: #e9ecef; border-radius: 8px; text-align: left; font-size: 14px; display: none; line-height: 1.6; }
            .status-badge { color: #155724; background-color: #d4edda; border: 1px solid #c3e6cb; padding: 2px 8px; border-radius: 4px; font-weight: bold; }
        </style>
    </head>
    <body>
        <div class="card">
            <div class="logo">OMRON</div>
            <div class="subtitle">Layanan Pelacakan Servis Perangkat</div>
            <input type="text" id="ticketInput" placeholder="Masukkan Nomor Tiket (cth: TCK-202609-001)">
            <button onclick="trackTicket()">Lacak Status Perangkat</button>
            <div id="resultBox" class="result"></div>
        </div>

        <script>
            async function trackTicket() {
                const ticket = document.getElementById('ticketInput').value.trim();
                const resultBox = document.getElementById('resultBox');
                if(!ticket) return alert('Silakan masukkan nomor tiket Anda!');
                
                resultBox.style.display = 'block';
                resultBox.innerHTML = 'Memuat data...';

                try {
                    const res = await fetch(`/api/v1/public/track/${ticket}`);
                    if(!res.ok) throw new Error('Nomor tiket tidak ditemukan.');
                    const data = await res.json();
                    
                    resultBox.innerHTML = `
                        <strong>No. Tiket:</strong> ${data.ticket_number}<br>
                        <strong>Model Alat:</strong> ${data.device_model}<br>
                        <strong>Status:</strong> <span class="status-badge">${data.status}</span><br>
                        <strong>Lokasi:</strong> ${data.current_location}
                    `;
                } catch(err) {
                    resultBox.innerHTML = `<span style="color:red;">${err.message}</span>`;
                }
            }
        </script>
    </body>
    </html>
    """