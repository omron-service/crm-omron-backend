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

# Endpoint Halaman Web HTML Customer Tracking
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

# Endpoint Halaman Web HTML Admin & Teknisi Dashboard
@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard_page():
    return """
    <!DOCTYPE html>
    <html lang="id">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Dashboard Portal Service Center - Omron</title>
        <style>
            * { box-sizing: border-box; font-family: 'Segoe UI', Arial, sans-serif; }
            body { margin: 0; background: #f4f6f9; color: #333; }
            header { background: #0056b3; color: white; padding: 15px 30px; display: flex; justify-content: space-between; align-items: center; }
            header h1 { margin: 0; font-size: 20px; }
            .container { padding: 30px; max-width: 1000px; margin: auto; }
            .card { background: white; padding: 25px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); margin-bottom: 25px; }
            h2 { color: #0056b3; margin-top: 0; font-size: 18px; border-bottom: 2px solid #e0e0e0; padding-bottom: 10px; }
            .form-group { margin-bottom: 15px; }
            label { display: block; margin-bottom: 5px; font-weight: bold; font-size: 14px; }
            input, select, textarea { width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 5px; font-size: 14px; }
            button { background: #0056b3; color: white; border: none; padding: 12px 20px; border-radius: 5px; cursor: pointer; font-weight: bold; font-size: 14px; }
            button:hover { background: #004085; }
            .login-box { max-width: 400px; margin: 80px auto; }
            .hidden { display: none; }
            table { width: 100%; border-collapse: collapse; margin-top: 15px; }
            th, td { border: 1px solid #ddd; padding: 10px; text-align: left; font-size: 14px; }
            th { background: #f8f9fa; }
        </style>
    </head>
    <body>
        <header>
            <h1>OMRON Healthcare - Service Portal</h1>
            <span id="userStatus">Not Logged In</span>
        </header>

        <div class="container">
            <!-- Box Login -->
            <div id="loginCard" class="card login-box">
                <h2>Login Internal Admin / Teknisi</h2>
                <div class="form-group">
                    <label>Email</label>
                    <input type="email" id="emailInput" value="superadmin@omron.co.id">
                </div>
                <div class="form-group">
                    <label>Password</label>
                    <input type="password" id="passwordInput" value="AdminOmron2026!">
                </div>
                <button onclick="login()">Masuk ke Portal</button>
            </div>

            <!-- Box Dashboard Utama (Muncul setelah Login) -->
            <div id="dashboardCard" class="hidden">
                <div class="card">
                    <h2>Input Tiket Servis Baru</h2>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px;">
                        <div class="form-group">
                            <label>Nama Pelanggan</label>
                            <input type="text" id="custName" placeholder="Contoh: Budi Santoso">
                        </div>
                        <div class="form-group">
                            <label>No. HP Pelanggan</label>
                            <input type="text" id="custPhone" placeholder="081234567890">
                        </div>
                        <div class="form-group">
                            <label>Model Perangkat</label>
                            <select id="deviceModel">
                                <option value="HEM-7120">Tensimeter Digital HEM-7120</option>
                                <option value="HEM-7156">Tensimeter Digital HEM-7156</option>
                                <option value="MC-246">Thermometer Digital MC-246</option>
                                <option value="NE-C28">Nebulizer NE-C28</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Nomor Seri (Serial Number)</label>
                            <input type="text" id="serialNumber" placeholder="SN2026xxxx">
                        </div>
                    </div>
                    <div class="form-group">
                        <label>Keluhan / Kerusakan</label>
                        <textarea id="complaint" rows="3" placeholder="Hasil pengukuran tidak akurat / Mati total"></textarea>
                    </div>
                    <button onclick="createTicket()">Buat Tiket Servis</button>
                </div>

                <div class="card">
                    <h2>Daftar Tiket Servis Terbaru</h2>
                    <table>
                        <thead>
                            <tr>
                                <th>No. Tiket</th>
                                <th>Pelanggan</th>
                                <th>Model</th>
                                <th>Status</th>
                                <th>Aksi</th>
                            </tr>
                        </thead>
                        <tbody id="ticketTable">
                            <tr>
                                <td>TCK-202609-001</td>
                                <td>Budi Santoso</td>
                                <td>HEM-7120</td>
                                <td><span style="color: green; font-weight: bold;">Sedang Diperbaiki</span></td>
                                <td><button style="padding: 5px 10px; font-size: 12px;">Detail</button></td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <script>
            let authToken = '';

            function login() {
                const email = document.getElementById('emailInput').value;
                const password = document.getElementById('passwordInput').value;
                
                if(!email || !password) return alert('Lengkapi email dan password!');

                // Simulasi login sukses
                authToken = 'mock_jwt_token_2026';
                document.getElementById('userStatus').innerText = 'Super Admin (' + email + ')';
                document.getElementById('loginCard').classList.add('hidden');
                document.getElementById('dashboardCard').classList.remove('hidden');
            }

            function createTicket() {
                const name = document.getElementById('custName').value;
                const model = document.getElementById('deviceModel').value;
                if(!name) return alert('Nama pelanggan harus diisi!');

                const randomTicket = 'TCK-' + Math.floor(100000 + Math.random() * 900000);
                const table = document.getElementById('ticketTable');
                const row = `
                    <tr>
                        <td>${randomTicket}</td>
                        <td>${name}</td>
                        <td>${model}</td>
                        <td><span style="color: blue; font-weight: bold;">Baru Diterima</span></td>
                        <td><button style="padding: 5px 10px; font-size: 12px;">Detail</button></td>
                    </tr>
                `;
                table.innerHTML = row + table.innerHTML;
                alert('Tiket berhasil dibuat: ' + randomTicket);
                document.getElementById('custName').value = '';
                document.getElementById('complaint').value = '';
            }
        </script>
    </body>
    </html>
    """