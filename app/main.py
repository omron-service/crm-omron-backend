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
    if not phone:
        raise HTTPException(status_code=400, detail="Nomor HP/WhatsApp wajib diisi untuk verifikasi.")

    ticket = db.query(ServiceTicket).filter(ServiceTicket.ticket_number == ticket_number.strip()).first()
    
    if not ticket:
        raise HTTPException(status_code=404, detail="Nomor tiket tidak ditemukan.")

    db_phone = "".join(filter(str.isdigit, ticket.customer_phone or ""))
    input_phone = "".join(filter(str.isdigit, phone or ""))

    if not db_phone or not input_phone or not (db_phone in input_phone or input_phone in db_phone or db_phone[-8:] == input_phone[-8:]):
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
    return """
    <!DOCTYPE html>
    <html lang="id">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Portal Service Center - Omron Healthcare</title>
        <style>
            * { box-sizing: border-box; font-family: 'Segoe UI', Arial, sans-serif; }
            body { margin: 0; background: #f4f6f9; color: #333; display: flex; height: 100vh; overflow: hidden; }
            
            aside { width: 260px; background: #003d80; color: white; display: flex; flex-direction: column; flex-shrink: 0; }
            aside .brand { padding: 20px; font-size: 18px; font-weight: bold; background: #002b5c; border-bottom: 1px solid rgba(255,255,255,0.1); }
            aside ul { list-style: none; padding: 0; margin: 0; overflow-y: auto; flex: 1; }
            aside li { border-bottom: 1px solid rgba(255,255,255,0.05); }
            aside .menu-title { padding: 12px 20px; font-weight: bold; font-size: 13px; color: #a2c7f5; background: rgba(0,0,0,0.1); display: flex; justify-content: space-between; align-items: center; cursor: pointer; }
            aside .submenu { list-style: none; padding: 0; background: #003366; display: none; }
            aside .submenu.open { display: block; }
            aside .submenu li a { padding: 10px 20px 10px 35px; display: block; color: #d0e1f9; text-decoration: none; font-size: 13px; }
            aside .submenu li a:hover, aside .submenu li a.active { background: #0056b3; color: white; font-weight: bold; }
            aside .single-menu { padding: 12px 20px; display: block; color: white; text-decoration: none; font-weight: bold; font-size: 14px; }
            aside .single-menu:hover { background: #0056b3; }

            main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
            header { background: white; padding: 15px 30px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #ddd; }
            header h1 { margin: 0; font-size: 18px; color: #0056b3; }
            .content { padding: 25px; overflow-y: auto; flex: 1; }

            .card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.06); margin-bottom: 20px; }
            h2 { color: #0056b3; margin-top: 0; font-size: 16px; border-bottom: 2px solid #e0e0e0; padding-bottom: 8px; }
            
            table { width: 100%; border-collapse: collapse; margin-top: 10px; }
            th, td { border: 1px solid #ddd; padding: 9px 12px; text-align: left; font-size: 13px; }
            th { background: #f8f9fa; color: #444; }
            .form-section-title { font-weight: bold; color: #0056b3; background: #e9ecef; padding: 8px 12px; border-radius: 4px; margin: 15px 0 10px 0; font-size: 14px; }
            .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-bottom: 10px; }
            .form-group { margin-bottom: 8px; }
            label { display: block; margin-bottom: 4px; font-weight: bold; font-size: 12px; color: #444; }
            input, select, textarea { width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px; font-size: 13px; }
            
            .action-header { display: flex; gap: 10px; align-items: center; }
            .search-input { width: 250px; padding: 8px 12px; border: 1px solid #ccc; border-radius: 4px; font-size: 13px; }

            .btn { background: #0056b3; color: white; border: none; padding: 7px 12px; border-radius: 4px; cursor: pointer; font-weight: bold; font-size: 12px; text-decoration: none; display: inline-block; }
            .btn:hover { background: #004085; }
            .btn-danger { background: #dc3545; }
            .btn-success { background: #28a745; }
            .btn-secondary { background: #6c757d; }
            .btn-warning { background: #ffc107; color: #212529; }
            .btn-info { background: #17a2b8; color: white; }
            .hidden { display: none !important; }
            .login-box { max-width: 400px; margin: 80px auto; }
            .badge { padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 11px; }
            .badge-lunas { background: #d4edda; color: #155724; }
            .badge-pending { background: #fff3cd; color: #856404; }
            .required { color: red; }
            .sparepart-box { background: #f8f9fa; border: 1px dashed #ccc; padding: 10px; border-radius: 6px; margin-bottom: 10px; }

            .modal-overlay { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); display: flex; justify-content: center; align-items: center; z-index: 999; }
            .modal-content { background: white; width: 90%; max-width: 500px; border-radius: 8px; padding: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.2); }
            .modal-header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #eee; padding-bottom: 10px; margin-bottom: 15px; }
            .modal-header h3 { margin: 0; color: #0056b3; font-size: 16px; }
            .close-btn { font-size: 20px; cursor: pointer; border: none; background: none; font-weight: bold; color: #888; }
        </style>
    </head>
    <body>

        <aside id="sidebar" class="hidden">
            <div class="brand">OMRON SERVICE</div>
            <ul>
                <li><a href="#" class="single-menu" onclick="showTab('dashboard')">1. Dashboard</a></li>

                <li>
                    <div class="menu-title" onclick="toggleSubmenu('sub-service')">2. Data Service <span>▼</span></div>
                    <ul id="sub-service" class="submenu open">
                        <li><a href="#" class="active" onclick="showTab('service-pusat')">a. Data di Pusat</a></li>
                        <li><a href="#" onclick="showTab('service-cabang')">b. Data di Cabang</a></li>
                        <li><a href="#" onclick="showTab('service-pickup')">c. Data di Pickup Center</a></li>
                    </ul>
                </li>

                <li>
                    <div class="menu-title" onclick="toggleSubmenu('sub-payment')">3. Status Payment Service <span>▼</span></div>
                    <ul id="sub-payment" class="submenu">
                        <li><a href="#" onclick="showTab('payment-pusat')">a. Payment di Pusat</a></li>
                        <li><a href="#" onclick="showTab('payment-cabang')">b. Payment di Cabang</a></li>
                        <li><a href="#" onclick="showTab('payment-pickup')">c. Payment di Pickup Center</a></li>
                    </ul>
                </li>

                <li>
                    <div class="menu-title" onclick="toggleSubmenu('sub-inventory')">4. Inventory Part <span>▼</span></div>
                    <ul id="sub-inventory" class="submenu">
                        <li><a href="#" onclick="showTab('inv-pusat-list')">a.1. List Stok Pusat</a></li>
                        <li><a href="#" onclick="showTab('inv-pusat-pakai')">a.2. Pemakaian Stok Pusat</a></li>
                        <li><a href="#" onclick="showTab('inv-pusat-terima')">a.3. Penerimaan dr Gudang Utama</a></li>
                        <li><a href="#" onclick="showTab('inv-pusat-kirim')">a.4. Pengiriman ke Cabang</a></li>
                        <li><a href="#" onclick="showTab('inv-cabang-list')">b.1. List Stok Cabang</a></li>
                        <li><a href="#" onclick="showTab('inv-cabang-pakai')">b.2. Pemakaian Stok Cabang</a></li>
                        <li><a href="#" onclick="showTab('inv-cabang-terima')">b.3. Penerimaan dr Pusat</a></li>
                        <li><a href="#" onclick="showTab('inv-cabang-minta')">b.4. Permintaan Stok ke Pusat</a></li>
                    </ul>
                </li>

                <li>
                    <div class="menu-title" onclick="toggleSubmenu('sub-setting')">5. Setting (Super Admin) <span>▼</span></div>
                    <ul id="sub-setting" class="submenu">
                        <li><a href="#" onclick="showTab('setting-fields')">a. Field Data Service</a></li>
                        <li><a href="#" onclick="showTab('setting-payment')">b. Field Payment & Reset Kode</a></li>
                    </ul>
                </li>
            </ul>
        </aside>

        <main>
            <header>
                <h1 id="pageTitle">Portal Management System</h1>
                <div>
                    <button id="btnSyncDb" class="btn btn-warning hidden" style="margin-right: 10px;" onclick="syncDatabase()">🔄 Sync DB</button>
                    <span id="userStatus" style="font-weight: bold; font-size: 13px; margin-right: 15px;">Belum Login</span>
                    <button id="btnLogout" class="btn btn-danger hidden" onclick="logout()">Logout</button>
                </div>
            </header>

            <div class="content">
                <div id="loginCard" class="card login-box">
                    <h2>Login Super Admin / Internal</h2>
                    <div class="form-group">
                        <label>Email / Username</label>
                        <input type="email" id="emailInput" value="superadmin@omron.co.id">
                    </div>
                    <div class="form-group">
                        <label>Password</label>
                        <input type="password" id="passwordInput" value="AdminOmron2026!">
                    </div>
                    <button class="btn" style="width: 100%;" onclick="login()">Masuk ke Sistem</button>
                </div>

                <!-- 1. DASHBOARD -->
                <div id="tab-dashboard" class="tab-content hidden">
                    <div class="card">
                        <h2>Ringkasan Dashboard Utama</h2>
                        <div class="form-grid">
                            <div style="background:#e3f2fd; padding:15px; border-radius:6px; text-align:center;">
                                <h3 id="statPusat" style="margin:0; color:#0d47a1;">0</h3>
                                <small>Total Servis Pusat</small>
                            </div>
                            <div style="background:#e8f5e9; padding:15px; border-radius:6px; text-align:center;">
                                <h3 id="statCabang" style="margin:0; color:#1b5e20;">0</h3>
                                <small>Total Servis Cabang</small>
                            </div>
                            <div style="background:#fff3e0; padding:15px; border-radius:6px; text-align:center;">
                                <h3 id="statPickup" style="margin:0; color:#e65100;">0</h3>
                                <small>Servis Pickup Center</small>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- 2a. DATA SERVICE - PUSAT -->
                <div id="tab-service-pusat" class="tab-content hidden">
                    <div id="view-table-service-pusat" class="card">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                            <h2 style="margin: 0; border: none;">2a. Data Service - Pusat</h2>
                            <div class="action-header">
                                <input type="text" id="search-service-pusat" class="search-input" placeholder="Cari tiket / nama / SN..." onkeyup="filterTable('service-pusat')">
                                <a href="/api/v1/admin/reports/excel" class="btn btn-secondary">📊 Download Excel</a>
                                <button class="btn btn-success" onclick="showFormInPage('service-pusat')">+ Input Tiket PUSAT</button>
                            </div>
                        </div>
                        <table>
                            <thead>
                                <tr>
                                    <th>No. Tiket</th>
                                    <th>Pemilik</th>
                                    <th>No. HP/WA</th>
                                    <th>Model Alat</th>
                                    <th>Serial No.</th>
                                    <th>Garansi</th>
                                    <th>Keluhan</th>
                                    <th>Status</th>
                                    <th>Tgl Diterima</th>
                                </tr>
                            </thead>
                            <tbody id="tableServicePusat"></tbody>
                        </table>
                    </div>

                    <div id="view-form-service-pusat" class="card hidden">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; border-bottom: 2px solid #0056b3; padding-bottom: 10px;">
                            <h2 style="margin: 0; border: none;">Form Input Tiket Servis - PUSAT (JKT)</h2>
                            <button class="btn btn-secondary" onclick="hideFormInPage('service-pusat')">← Kembali ke Tabel</button>
                        </div>
                        <div id="formContainer-service-pusat"></div>
                        <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px;">
                            <button class="btn btn-secondary" onclick="hideFormInPage('service-pusat')">Batal</button>
                            <button class="btn btn-success" onclick="savePageFormData('service-pusat')">Simpan ke Data PUSAT</button>
                        </div>
                    </div>
                </div>

                <!-- 2b. DATA SERVICE - CABANG -->
                <div id="tab-service-cabang" class="tab-content hidden">
                    <div id="view-table-service-cabang" class="card">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                            <h2 style="margin: 0; border: none;">2b. Data Service - Cabang</h2>
                            <div class="action-header">
                                <input type="text" id="search-service-cabang" class="search-input" placeholder="Cari tiket / nama / SN..." onkeyup="filterTable('service-cabang')">
                                <a href="/api/v1/admin/reports/excel" class="btn btn-secondary">📊 Download Excel</a>
                                <button class="btn btn-success" onclick="showFormInPage('service-cabang')">+ Input Tiket CABANG</button>
                            </div>
                        </div>
                        <table>
                            <thead>
                                <tr>
                                    <th>No. Tiket</th>
                                    <th>Cabang</th>
                                    <th>Pemilik</th>
                                    <th>Model Alat</th>
                                    <th>Serial No.</th>
                                    <th>Garansi</th>
                                    <th>Status</th>
                                    <th>Tgl Diterima</th>
                                </tr>
                            </thead>
                            <tbody id="tableServiceCabang"></tbody>
                        </table>
                    </div>

                    <div id="view-form-service-cabang" class="card hidden">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; border-bottom: 2px solid #0056b3; padding-bottom: 10px;">
                            <h2 style="margin: 0; border: none;">Form Input Tiket Servis - CABANG (CBG)</h2>
                            <button class="btn btn-secondary" onclick="hideFormInPage('service-cabang')">← Kembali ke Tabel</button>
                        </div>
                        <div id="formContainer-service-cabang"></div>
                        <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px;">
                            <button class="btn btn-secondary" onclick="hideFormInPage('service-cabang')">Batal</button>
                            <button class="btn btn-success" onclick="savePageFormData('service-cabang')">Simpan ke Data CABANG</button>
                        </div>
                    </div>
                </div>

                <!-- 2c. DATA SERVICE - PICKUP CENTER -->
                <div id="tab-service-pickup" class="tab-content hidden">
                    <div id="view-table-service-pickup" class="card">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                            <h2 style="margin: 0; border: none;">2c. Data Service - Pickup Center</h2>
                            <div class="action-header">
                                <input type="text" id="search-service-pickup" class="search-input" placeholder="Cari tiket / nama / SN..." onkeyup="filterTable('service-pickup')">
                                <a href="/api/v1/admin/reports/excel" class="btn btn-secondary">📊 Download Excel</a>
                                <button class="btn btn-success" onclick="showFormInPage('service-pickup')">+ Input Tiket PICKUP</button>
                            </div>
                        </div>
                        <table>
                            <thead>
                                <tr>
                                    <th>No. Tiket</th>
                                    <th>Pickup Point</th>
                                    <th>Pemilik</th>
                                    <th>Model Alat</th>
                                    <th>Serial No.</th>
                                    <th>Garansi</th>
                                    <th>Status Kurir</th>
                                    <th>Tgl Diterima</th>
                                </tr>
                            </thead>
                            <tbody id="tableServicePickup"></tbody>
                        </table>
                    </div>

                    <div id="view-form-service-pickup" class="card hidden">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; border-bottom: 2px solid #0056b3; padding-bottom: 10px;">
                            <h2 style="margin: 0; border: none;">Form Input Tiket Servis - PICKUP CENTER (PKP)</h2>
                            <button class="btn btn-secondary" onclick="hideFormInPage('service-pickup')">← Kembali ke Tabel</button>
                        </div>
                        <div id="formContainer-service-pickup"></div>
                        <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px;">
                            <button class="btn btn-secondary" onclick="hideFormInPage('service-pickup')">Batal</button>
                            <button class="btn btn-success" onclick="savePageFormData('service-pickup')">Simpan ke Data PICKUP</button>
                        </div>
                    </div>
                </div>

                <!-- 3. STATUS PAYMENT SERVICE -->
                <div id="tab-payment-pusat" class="tab-content hidden">
                    <div class="card">
                        <h2>3a. Status Payment Service - Pusat (Out of Warranty)</h2>
                        <table>
                            <thead>
                                <tr>
                                    <th>No. Tiket</th>
                                    <th>Pemilik</th>
                                    <th>Model Alat</th>
                                    <th>Total Biaya</th>
                                    <th>Kode Payment</th>
                                    <th>Status Bayar</th>
                                    <th>Aksi Pembayaran</th>
                                </tr>
                            </thead>
                            <tbody id="tablePaymentPusat"></tbody>
                        </table>
                    </div>
                </div>

                <div id="tab-payment-cabang" class="tab-content hidden">
                    <div class="card">
                        <h2>3b. Status Payment Service - Cabang (Out of Warranty)</h2>
                        <table>
                            <thead>
                                <tr>
                                    <th>No. Tiket</th>
                                    <th>Cabang</th>
                                    <th>Pemilik</th>
                                    <th>Total Biaya</th>
                                    <th>Kode Payment</th>
                                    <th>Status Bayar</th>
                                    <th>Aksi Pembayaran</th>
                                </tr>
                            </thead>
                            <tbody id="tablePaymentCabang"></tbody>
                        </table>
                    </div>
                </div>

                <div id="tab-payment-pickup" class="tab-content hidden">
                    <div class="card">
                        <h2>3c. Status Payment Service - Pickup Center (Out of Warranty)</h2>
                        <table>
                            <thead>
                                <tr>
                                    <th>No. Tiket</th>
                                    <th>Pickup Location</th>
                                    <th>Pemilik</th>
                                    <th>Total Biaya</th>
                                    <th>Status Bayar</th>
                                    <th>Aksi Pembayaran</th>
                                </tr>
                            </thead>
                            <tbody id="tablePaymentPickup"></tbody>
                        </table>
                    </div>
                </div>

                <!-- 4. INVENTORY PART -->
                <div id="tab-inv-pusat-list" class="tab-content hidden">
                    <div class="card">
                        <h2>4a.1. List Stok Spare Part di Pusat</h2>
                        <table>
                            <thead><tr><th>Kode Part</th><th>Nama Spare Part</th><th>Kategori</th><th>Stok Pusat</th></tr></thead>
                            <tbody id="tableInvPusatList"></tbody>
                        </table>
                    </div>
                </div>

                <div id="tab-inv-pusat-pakai" class="tab-content hidden"><div class="card"><h2>4a.2. Pemakaian Stok di Pusat</h2></div></div>
                <div id="tab-inv-pusat-terima" class="tab-content hidden"><div class="card"><h2>4a.3. Penerimaan Stok dari Gudang Utama</h2></div></div>
                <div id="tab-inv-pusat-kirim" class="tab-content hidden"><div class="card"><h2>4a.4. Pengiriman Stok ke Cabang</h2></div></div>
                <div id="tab-inv-cabang-list" class="tab-content hidden"><div class="card"><h2>4b.1. List Stok di Cabang</h2></div></div>
                <div id="tab-inv-cabang-pakai" class="tab-content hidden"><div class="card"><h2>4b.2. Pemakaian Stok di Cabang</h2></div></div>
                <div id="tab-inv-cabang-terima" class="tab-content hidden"><div class="card"><h2>4b.3. Penerimaan Stok dari Pusat</h2></div></div>
                <div id="tab-inv-cabang-minta" class="tab-content hidden"><div class="card"><h2>4b.4. Permintaan Stok ke Pusat</h2></div></div>

                <!-- 5. SETTING SUPER ADMIN -->
                <div id="tab-setting-fields" class="tab-content hidden">
                    <div class="card">
                        <h2>5a. Setting Field Data Service (Super Admin)</h2>
                    </div>
                </div>

                <div id="tab-setting-payment" class="tab-content hidden">
                    <div class="card">
                        <h2>5b. Setting Field Status Payment & Kode Payment</h2>
                    </div>
                </div>

            </div>
        </main>

        <script>
            let authToken = localStorage.getItem('omron_token') || '';
            let rawServiceData = {};

            window.onload = function() {
                if (authToken) {
                    showDashboardUI();
                }
            };

            function toggleSubmenu(id) {
                document.getElementById(id).classList.toggle('open');
            }

            function showDashboardUI() {
                document.getElementById('loginCard').classList.add('hidden');
                document.getElementById('sidebar').classList.remove('hidden');
                document.getElementById('btnLogout').classList.remove('hidden');
                document.getElementById('btnSyncDb').classList.remove('hidden');
                document.getElementById('userStatus').innerText = 'Super Admin Active';
                showTab('dashboard');
            }

            function showTab(tabId) {
                document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
                
                const target = document.getElementById('tab-' + tabId);
                if(target) target.classList.remove('hidden');

                document.getElementById('pageTitle').innerText = 'Menu: ' + tabId.toUpperCase().replace(/-/g, ' ');

                if (tabId.startsWith('service-')) {
                    hideFormInPage(tabId);
                }

                renderTableData(tabId);
                updateDashboardStats();
            }

            async function updateDashboardStats() {
                try {
                    const res = await fetch('/api/v1/db/all-tickets');
                    if(res.ok) {
                        const data = await res.json();
                        document.getElementById('statPusat').innerText = data.filter(d => (d.service_type || 'pusat').toLowerCase() === 'pusat').length;
                        document.getElementById('statCabang').innerText = data.filter(d => (d.service_type || '').toLowerCase() === 'cabang').length;
                        document.getElementById('statPickup').innerText = data.filter(d => (d.service_type || '').toLowerCase() === 'pickup').length;
                    }
                } catch(e) {}
            }

            async function renderTableData(menu) {
                // Bersihkan tampilan tabel terlebih dahulu
                populateTableRows(menu, []);

                let endpoint = '/api/v1/db/all-tickets';
                if (menu.startsWith('service-') || menu.startsWith('payment-')) {
                    const srvType = menu.replace('service-', '').replace('payment-', '');
                    endpoint = '/api/v1/db/tickets/' + srvType;
                }

                try {
                    const res = await fetch(endpoint);
                    if (res.ok) {
                        let data = await res.json();
                        rawServiceData[menu] = data;

                        if(menu.startsWith('payment-')) {
                            populatePaymentRows(menu, data);
                        } else {
                            populateTableRows(menu, data);
                        }
                    }
                } catch(e) {
                    console.error('Error fetching database:', e);
                }
            }

            function populateTableRows(menu, data) {
                if(menu === 'service-pusat' || menu === 'service-cabang' || menu === 'service-pickup') {
                    const targetEl = menu === 'service-pusat' ? 'tableServicePusat' : (menu === 'service-cabang' ? 'tableServiceCabang' : 'tableServicePickup');
                    const el = document.getElementById(targetEl);
                    if(!el) return;

                    el.innerHTML = data.length ? data.map(d => `
                        <tr>
                            <td><strong>${d.ticket_number}</strong></td>
                            <td>${d.customer_name}</td>
                            <td>${d.customer_phone || '-'}</td>
                            <td>${d.device_model}</td>
                            <td>${d.serial_number||'-'}</td>
                            <td>${d.warranty_status||'Out of Warranty'}</td>
                            <td>${d.complaint||'-'}</td>
                            <td><span class="badge badge-lunas">${d.status||'Diproses'}</span></td>
                            <td>${d.created_at ? d.created_at.split('T')[0] : '-'}</td>
                        </tr>
                    `).join('') : `<tr><td colspan="9" style="text-align:center;">Belum ada data di lokasi ini</td></tr>`;
                }
            }

            function populatePaymentRows(menu, data) {
                const filtered = data.filter(d => !d.warranty_status || d.warranty_status === 'Out of Warranty');
                const targetEl = menu === 'payment-pusat' ? 'tablePaymentPusat' : (menu === 'payment-cabang' ? 'tablePaymentCabang' : 'tablePaymentPickup');
                const el = document.getElementById(targetEl);
                if(!el) return;

                el.innerHTML = filtered.length ? filtered.map(d => `
                    <tr>
                        <td><strong>${d.ticket_number}</strong></td>
                        <td>${d.customer_name}</td>
                        <td>${d.device_model}</td>
                        <td>Rp ${(d.total_price || 150000).toLocaleString('id-ID')}</td>
                        <td><code>${d.payment_code || 'PAY-882019'}</code></td>
                        <td><span class="badge ${d.payment_status === 'Lunas' ? 'badge-lunas' : 'badge-pending'}">${d.payment_status || 'Belum Lunas'}</span></td>
                        <td>
                            <button class="btn btn-info">Input Price</button>
                            <a href="/api/v1/admin/reports/excel" class="btn btn-secondary">Invoice</a>
                        </td>
                    </tr>
                `).join('') : `<tr><td colspan="7" style="text-align:center;">Tidak ada tiket Out of Warranty untuk pembayaran di lokasi ini.</td></tr>`;
            }

            function showFormInPage(menuKey) {
                document.getElementById('view-table-' + menuKey).classList.add('hidden');
                const formView = document.getElementById('view-form-' + menuKey);
                formView.classList.remove('hidden');

                const container = document.getElementById('formContainer-' + menuKey);
                container.innerHTML = getTicketFormHTML(menuKey);
            }

            function hideFormInPage(menuKey) {
                const formView = document.getElementById('view-form-' + menuKey);
                if(formView) formView.classList.add('hidden');
                const tableView = document.getElementById('view-table-' + menuKey);
                if(tableView) tableView.classList.remove('hidden');
            }

            function getTicketFormHTML(menuKey) {
                const prefixMap = { 'service-pusat': 'JKT', 'service-cabang': 'CBG', 'service-pickup': 'PKP' };
                const locPrefix = prefixMap[menuKey] || 'JKT';

                return `
                    <div style="background:#e3f2fd; padding:10px; border-radius:5px; font-size:12px; margin-bottom:15px; color:#0d47a1;">
                        ℹ️ Tiket ini akan terdaftar khusus di data <strong>${locPrefix}</strong>.
                    </div>

                    <div class="form-section-title">1. Data Pelanggan</div>
                    <div class="form-grid">
                        <div class="form-group"><label>Nama Pemilik <span class="required">*</span></label><input id="inpName" placeholder="Contoh: Budi Santoso"></div>
                        <div class="form-group"><label>No. HP / WhatsApp <span class="required">*</span></label><input id="inpPhone1" placeholder="081234567890"></div>
                    </div>

                    <div class="form-section-title">2. Data Produk</div>
                    <div class="form-grid">
                        <div class="form-group"><label>Model Alat</label><input id="inpModel" value="HEM-7120"></div>
                        <div class="form-group"><label>Serial No. Alat</label><input id="inpSN" placeholder="SN2026xxxx"></div>
                        <div class="form-group"><label>Keluhan</label><input id="inpKeluhan" placeholder="Keluhan perangkat"></div>
                    </div>
                `;
            }

            async function savePageFormData(menuKey) {
                const name = document.getElementById('inpName').value.trim();
                const phone = document.getElementById('inpPhone1').value.trim();

                if(!name || !phone) {
                    return alert('Nama Pemilik dan No. HP/WhatsApp Wajib Diisi!');
                }

                // Ambil service_type yang presisi: pusat / cabang / pickup
                const srvType = menuKey.replace('service-', '');

                const payload = {
                    service_type: srvType,
                    customer_name: name,
                    customer_phone: phone,
                    device_model: document.getElementById('inpModel').value.trim() || 'HEM-7120',
                    serial_number: document.getElementById('inpSN').value.trim() || '-',
                    complaint: document.getElementById('inpKeluhan').value.trim() || '-'
                };

                try {
                    const res = await fetch('/api/v1/db/tickets/', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });

                    const resData = await res.json();

                    if (res.ok) {
                        alert(`BERHASIL! Tiket ${resData.ticket_number} berhasil masuk khusus ke Data ${srvType.toUpperCase()}!`);
                        hideFormInPage(menuKey);
                        renderTableData(menuKey);
                        updateDashboardStats();
                    } else {
                        alert('Gagal menyimpan tiket.');
                    }
                } catch(e) {
                    alert('Error koneksi database: ' + e.message);
                }
            }

            async function login() {
                authToken = 'jwt_superadmin_omron_2026';
                localStorage.setItem('omron_token', authToken);
                showDashboardUI();
            }

            function logout() {
                localStorage.removeItem('omron_token');
                location.reload();
            }
        </script>
    </body>
    </html>
    """
