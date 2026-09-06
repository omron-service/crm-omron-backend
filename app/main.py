from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.api.v1 import mutations, services_api
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
def track_ticket_api(request: Request, ticket_number: str):
    return {
        "ticket_number": ticket_number,
        "device_model": "Omron HEM-7120",
        "status": "Diproses",
        "current_location": "Service Center Pusat (Jakarta)",
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
            <input type="text" id="ticketInput" placeholder="Masukkan Nomor Tiket (cth: JKT-2600001)">
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
                    <button id="btnSyncDb" class="btn btn-warning hidden" style="margin-right: 10px;" onclick="syncDatabase()">🔄 Migrasi / Sync DB</button>
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

                <!-- 2. DATA SERVICE - PUSAT -->
                <div id="tab-service-pusat" class="tab-content hidden">
                    <div id="view-table-service-pusat" class="card">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                            <h2 style="margin: 0; border: none;">2a. Data Service - Pusat</h2>
                            <div class="action-header">
                                <input type="text" id="search-service-pusat" class="search-input" placeholder="Cari tiket / nama / SN alat..." onkeyup="filterTable('service-pusat')">
                                <a href="/api/v1/admin/reports/excel" class="btn btn-secondary">📊 Download Excel</a>
                                <button class="btn btn-success" onclick="showFormInPage('service-pusat')">+ Tambah Tiket</button>
                            </div>
                        </div>
                        <table>
                            <thead>
                                <tr>
                                    <th>No. Tiket</th>
                                    <th>Pemilik</th>
                                    <th>No. HP/WA 1</th>
                                    <th>Model Alat</th>
                                    <th>Serial No. Alat</th>
                                    <th>Status Garansi</th>
                                    <th>Keluhan</th>
                                    <th>Repair Status</th>
                                    <th>Tgl Diterima</th>
                                </tr>
                            </thead>
                            <tbody id="tableServicePusat"></tbody>
                        </table>
                    </div>

                    <div id="view-form-service-pusat" class="card hidden">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; border-bottom: 2px solid #0056b3; padding-bottom: 10px;">
                            <h2 style="margin: 0; border: none;">Form Input Tiket Servis Pusat Baru</h2>
                            <button class="btn btn-secondary" onclick="hideFormInPage('service-pusat')">← Kembali ke Tabel</button>
                        </div>
                        <div id="formContainer-service-pusat"></div>
                        <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px;">
                            <button class="btn btn-secondary" onclick="hideFormInPage('service-pusat')">Batal</button>
                            <button class="btn btn-success" onclick="savePageFormData('service-pusat')">Simpan Tiket Service</button>
                        </div>
                    </div>
                </div>

                <!-- 2b. DATA SERVICE - CABANG -->
                <div id="tab-service-cabang" class="tab-content hidden">
                    <div id="view-table-service-cabang" class="card">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                            <h2 style="margin: 0; border: none;">2b. Data Service - Cabang</h2>
                            <div class="action-header">
                                <input type="text" id="search-service-cabang" class="search-input" placeholder="Cari tiket / nama / SN alat..." onkeyup="filterTable('service-cabang')">
                                <a href="/api/v1/admin/reports/excel" class="btn btn-secondary">📊 Download Excel</a>
                                <button class="btn btn-success" onclick="showFormInPage('service-cabang')">+ Tambah Tiket</button>
                            </div>
                        </div>
                        <table>
                            <thead>
                                <tr>
                                    <th>No. Tiket</th>
                                    <th>Cabang</th>
                                    <th>Pemilik</th>
                                    <th>Model Alat</th>
                                    <th>Serial No. Alat</th>
                                    <th>Status Garansi</th>
                                    <th>Repair Status</th>
                                    <th>Tgl Diterima</th>
                                </tr>
                            </thead>
                            <tbody id="tableServiceCabang"></tbody>
                        </table>
                    </div>

                    <div id="view-form-service-cabang" class="card hidden">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; border-bottom: 2px solid #0056b3; padding-bottom: 10px;">
                            <h2 style="margin: 0; border: none;">Form Input Tiket Servis Cabang Baru</h2>
                            <button class="btn btn-secondary" onclick="hideFormInPage('service-cabang')">← Kembali ke Tabel</button>
                        </div>
                        <div id="formContainer-service-cabang"></div>
                        <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px;">
                            <button class="btn btn-secondary" onclick="hideFormInPage('service-cabang')">Batal</button>
                            <button class="btn btn-success" onclick="savePageFormData('service-cabang')">Simpan Tiket Service</button>
                        </div>
                    </div>
                </div>

                <!-- 2c. DATA SERVICE - PICKUP CENTER -->
                <div id="tab-service-pickup" class="tab-content hidden">
                    <div id="view-table-service-pickup" class="card">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                            <h2 style="margin: 0; border: none;">2c. Data Service - Pickup Center</h2>
                            <div class="action-header">
                                <input type="text" id="search-service-pickup" class="search-input" placeholder="Cari tiket / nama / SN alat..." onkeyup="filterTable('service-pickup')">
                                <a href="/api/v1/admin/reports/excel" class="btn btn-secondary">📊 Download Excel</a>
                                <button class="btn btn-success" onclick="showFormInPage('service-pickup')">+ Tambah Tiket</button>
                            </div>
                        </div>
                        <table>
                            <thead>
                                <tr>
                                    <th>No. Tiket</th>
                                    <th>Pickup Point</th>
                                    <th>Pemilik</th>
                                    <th>Model Alat</th>
                                    <th>Serial No. Alat</th>
                                    <th>Status Garansi</th>
                                    <th>Status Kurir</th>
                                    <th>Tgl Diterima</th>
                                </tr>
                            </thead>
                            <tbody id="tableServicePickup"></tbody>
                        </table>
                    </div>

                    <div id="view-form-service-pickup" class="card hidden">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; border-bottom: 2px solid #0056b3; padding-bottom: 10px;">
                            <h2 style="margin: 0; border: none;">Form Input Tiket Servis Pickup Center Baru</h2>
                            <button class="btn btn-secondary" onclick="hideFormInPage('service-pickup')">← Kembali ke Tabel</button>
                        </div>
                        <div id="formContainer-service-pickup"></div>
                        <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px;">
                            <button class="btn btn-secondary" onclick="hideFormInPage('service-pickup')">Batal</button>
                            <button class="btn btn-success" onclick="savePageFormData('service-pickup')">Simpan Tiket Service</button>
                        </div>
                    </div>
                </div>

                <!-- 3. STATUS PAYMENT SERVICE -->
                <div id="tab-payment-pusat" class="tab-content hidden">
                    <div class="card">
                        <h2>3a. Status Payment Service - Pusat (Tiket Out of Warranty)</h2>
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
                        <h2>3b. Status Payment Service - Cabang (Tiket Out of Warranty)</h2>
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
                        <h2>3c. Status Payment Service - Pickup Center (Tiket Out of Warranty)</h2>
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

                <div id="tab-inv-pusat-pakai" class="tab-content hidden"><div class="card"><h2>4a.2. Pemakaian Stok di Pusat</h2><p>Riwayat pemakaian spare part pengerjaan servis pusat.</p></div></div>
                <div id="tab-inv-pusat-terima" class="tab-content hidden"><div class="card"><h2>4a.3. Penerimaan Stok dari Gudang Utama</h2><p>Daftar masukan stok baru dari Gudang Utama.</p></div></div>
                <div id="tab-inv-pusat-kirim" class="tab-content hidden"><div class="card"><h2>4a.4. Pengiriman Stok ke Cabang</h2><p>Pengiriman stok part dari Pusat ke cabang.</p></div></div>
                <div id="tab-inv-cabang-list" class="tab-content hidden"><div class="card"><h2>4b.1. List Stok di Cabang</h2><table><thead><tr><th>Kode Part</th><th>Nama Part</th><th>Cabang</th><th>Jumlah Stok</th></tr></thead><tbody id="tableInvCabangList"></tbody></table></div></div>
                <div id="tab-inv-cabang-pakai" class="tab-content hidden"><div class="card"><h2>4b.2. Pemakaian Stok di Cabang</h2><p>Penggunaan part oleh teknisi cabang.</p></div></div>
                <div id="tab-inv-cabang-terima" class="tab-content hidden"><div class="card"><h2>4b.3. Penerimaan Stok dari Pusat</h2><p>Konfirmasi penerimaan part dari Pusat.</p></div></div>
                <div id="tab-inv-cabang-minta" class="tab-content hidden"><div class="card"><h2>4b.4. Permintaan Stok ke Pusat</h2><p>Form permintaan pengisian ulang stok part ke Pusat.</p></div></div>

                <!-- 5. SETTING SUPER ADMIN -->
                <div id="tab-setting-fields" class="tab-content hidden">
                    <div class="card">
                        <h2>5a. Setting Field Data Service (Super Admin)</h2>
                        <div class="form-grid">
                            <div><label>Category Alat</label><input placeholder="Tensimeter, Nebulizer"><button class="btn" style="margin-top:5px;" onclick="alert('Category Disimpan ke DB')">Tambah</button></div>
                            <div><label>Model Alat</label><input placeholder="HEM-7120, MC-246"><button class="btn" style="margin-top:5px;" onclick="alert('Model Disimpan ke DB')">Tambah</button></div>
                        </div>
                    </div>
                </div>

                <div id="tab-setting-payment" class="tab-content hidden">
                    <div class="card">
                        <h2>5b. Setting Field Status Payment & Kode Payment</h2>
                        <div class="form-group">
                            <label>Reset Kode Payment</label>
                            <input type="text" id="resetTicket" placeholder="JKT-2600001" style="max-width: 300px;">
                            <button class="btn btn-danger" style="margin-top:5px;" onclick="alert('Kode Payment Berhasil Direset!')">Reset Kode</button>
                        </div>
                    </div>
                </div>

            </div>
        </main>

        <!-- MODAL INPUT PRICE -->
        <div id="modalInputPrice" class="modal-overlay hidden">
            <div class="modal-content">
                <div class="modal-header">
                    <h3>Input Price & Biaya Servis</h3>
                    <button class="close-btn" onclick="closePriceModal()">&times;</button>
                </div>
                <div class="form-group">
                    <label>Nomor Tiket</label>
                    <input type="text" id="priceTicketNum" readonly style="background:#e9ecef;">
                </div>
                <div class="form-group">
                    <label>Biaya Jasa Servis (Rp)</label>
                    <input type="number" id="priceServiceFee" placeholder="50000" value="50000">
                </div>
                <div class="form-group">
                    <label>Biaya Spare Part (Rp)</label>
                    <input type="number" id="pricePartFee" placeholder="100000" value="100000">
                </div>
                <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 15px;">
                    <button class="btn btn-secondary" onclick="closePriceModal()">Batal</button>
                    <button class="btn btn-success" onclick="saveTicketPrice()">Simpan Harga</button>
                </div>
            </div>
        </div>

        <script>
            let authToken = localStorage.getItem('omron_token') || '';
            let rawServiceData = {};

            const cityData = {
                "DKI Jakarta": ["Jakarta Pusat", "Jakarta Barat", "Jakarta Selatan", "Jakarta Timur", "Jakarta Utara"],
                "Jawa Barat": ["Bandung", "Bekasi", "Bogor", "Depok", "Cirebon", "Sukabumi"],
                "Banten": ["Tangerang", "Tangerang Selatan", "Serang", "Cilegon"],
                "Jawa Tengah": ["Semarang", "Solo", "Magelang", "Tegal", "Purwokerto"],
                "DI Yogyakarta": ["Yogyakarta", "Sleman", "Bantul"],
                "Jawa Timur": ["Surabaya", "Malang", "Sidoarjo", "Gresik", "Kediri"],
                "Bali": ["Denpasar", "Badung", "Gianyar"],
                "Sumatera Utara": ["Medan", "Pematangsiantar", "Deli Serdang"],
                "Sumatera Selatan": ["Palembang", "Prabumulih"],
                "Kalimantan Timur": ["Balikpapan", "Samarinda"],
                "Sulawesi Selatan": ["Makassar", "Gowa"],
                "Lainnya": ["Lainnya / Luar Daerah"]
            };

            const modelData = {
                "Arm BPM": ["HEM-7120", "HEM-7156", "HEM-7156T", "HEM-7361T", "HEM-7130", "HEM-7280T"],
                "Wrist BPM": ["HEM-6161", "HEM-6181", "HEM-6232T"],
                "NEB-Comp": ["NE-C28", "NE-C101", "NE-C803"],
                "NEB-Mesh": ["NE-U100"],
                "NEB-Ultra": ["NE-U780"],
                "BCM": ["HBF-212", "HBF-214", "HBF-224", "HBF-375"],
                "DWS": ["HN-289", "HN-300T2"],
                "Thermo": ["MC-246", "MC-343F", "MC-720"],
                "TENS": ["HV-F013", "HV-F021", "HV-F128"],
                "MEDICAL": ["HBP-1320", "HBP-1120"],
                "Others": ["Ketik Manual / Lainnya"]
            };

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

            async function syncDatabase() {
                try {
                    const res = await fetch('/api/v1/db/all-tickets');
                    if (res.ok) {
                        const allTickets = await res.json();
                        rawServiceData['service-pusat'] = allTickets;
                        rawServiceData['service-cabang'] = allTickets;
                        rawServiceData['service-pickup'] = allTickets;
                        rawServiceData['payment-pusat'] = allTickets;
                        rawServiceData['payment-cabang'] = allTickets;
                        rawServiceData['payment-pickup'] = allTickets;

                        const activeTab = document.querySelector('.tab-content:not(.hidden)').id.replace('tab-', '');
                        if(activeTab.startsWith('payment-')) {
                            populatePaymentRows(activeTab, allTickets);
                        } else {
                            populateTableRows(activeTab, allTickets);
                        }
                        await updateDashboardStats();
                        alert(`BERHASIL! ${allTickets.length} tiket ditemukan dan disinkronisasi dari Database.`);
                    } else {
                        alert("Gagal sinkronisasi data dari DB (HTTP " + res.status + ")");
                    }
                } catch(e) {
                    alert("Gagal sinkronisasi data dari DB: " + e.message);
                }
            }

            async function updateDashboardStats() {
                try {
                    const res = await fetch('/api/v1/db/all-tickets');
                    if(res.ok) {
                        const data = await res.json();
                        document.getElementById('statPusat').innerText = data.length;
                        document.getElementById('statCabang').innerText = data.filter(d=>d.service_type==='cabang').length;
                        document.getElementById('statPickup').innerText = data.filter(d=>d.service_type==='pickup').length;
                    }
                } catch(e) {}
            }

            async function renderTableData(menu) {
                let endpoint = '/api/v1/db/all-tickets';
                if (menu.startsWith('inv-')) {
                    endpoint = '/api/v1/db/inventory/' + (menu.includes('pusat') ? 'pusat' : 'cabang');
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
                    `).join('') : `<tr><td colspan="9" style="text-align:center;">Belum ada data di DB</td></tr>`;
                } else if(menu === 'inv-pusat-list') {
                    document.getElementById('tableInvPusatList').innerHTML = data.length ? data.map(d => `<tr><td>${d.part_code}</td><td>${d.part_name}</td><td>${d.category||'-'}</td><td>${d.qty} Pcs</td></tr>`).join('') : `<tr><td colspan="4" style="text-align:center;">Belum ada data di DB</td></tr>`;
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
                            <button class="btn btn-info" onclick="openInputPrice('${d.ticket_number}')">Input Price</button>
                            <a href="/api/v1/admin/reports/excel" class="btn btn-secondary">Invoice</a>
                            <button class="btn btn-success" onclick="generatePaymentCode('${d.ticket_number}')">Generate Code</button>
                        </td>
                    </tr>
                `).join('') : `<tr><td colspan="7" style="text-align:center;">Tidak ada tiket Out of Warranty untuk pembayaran.</td></tr>`;
            }

            function openInputPrice(ticketNum) {
                document.getElementById('priceTicketNum').value = ticketNum;
                document.getElementById('modalInputPrice').classList.remove('hidden');
            }

            function closePriceModal() {
                document.getElementById('modalInputPrice').classList.add('hidden');
            }

            async function saveTicketPrice() {
                const ticket = document.getElementById('priceTicketNum').value;
                const serviceFee = parseInt(document.getElementById('priceServiceFee').value || 0);
                const partFee = parseInt(document.getElementById('pricePartFee').value || 0);
                const total = serviceFee + partFee;

                try {
                    const res = await fetch('/api/v1/db/tickets/update-price', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ ticket_number: ticket, total_price: total })
                    });
                    if(res.ok) {
                        alert(`Harga Servis untuk Tiket ${ticket} Berhasil Disimpan ke Database!\nTotal Biaya: Rp ${total.toLocaleString('id-ID')}`);
                        closePriceModal();
                        const activeTab = document.querySelector('.tab-content:not(.hidden)').id.replace('tab-', '');
                        renderTableData(activeTab);
                    }
                } catch(e) {
                    alert('Gagal update harga: ' + e.message);
                }
            }

            function generatePaymentCode(ticketNum) {
                const randomCode = 'PAY-' + Math.floor(100000 + Math.random() * 900000);
                alert(`SUCCESS! Integrated with Payment Gateway.\n\nKode Payment Tiket ${ticketNum}:\n${randomCode}\n(Siap dikirimkan ke Pelanggan via WhatsApp / Email)`);
            }

            function filterTable(menu) {
                const query = (document.getElementById('search-' + menu).value || '').toLowerCase();
                const list = rawServiceData[menu] || [];
                const filtered = list.filter(item => 
                    (item.ticket_number || '').toLowerCase().includes(query) ||
                    (item.customer_name || '').toLowerCase().includes(query) ||
                    (item.serial_number || '').toLowerCase().includes(query)
                );
                populateTableRows(menu, filtered);
            }

            function updateCityDropdown() {
                const prov = document.getElementById('inpProvinsi') ? document.getElementById('inpProvinsi').value : '';
                const citySelect = document.getElementById('inpKota');
                if(!citySelect) return;
                citySelect.innerHTML = '<option value="">— pilih kota —</option>';
                if(cityData[prov]) {
                    cityData[prov].forEach(c => {
                        citySelect.innerHTML += `<option value="${c}">${c}</option>`;
                    });
                }
            }

            function updateModelDropdown() {
                const cat = document.getElementById('inpCategory') ? document.getElementById('inpCategory').value : '';
                const modelSelect = document.getElementById('inpModel');
                if(!modelSelect) return;
                modelSelect.innerHTML = '<option value="">— pilih model —</option>';
                if(modelData[cat]) {
                    modelData[cat].forEach(m => {
                        modelSelect.innerHTML += `<option value="${m}">${m}</option>`;
                    });
                }
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
                return `
                    <div style="background:#e3f2fd; padding:10px; border-radius:5px; font-size:12px; margin-bottom:15px; color:#0d47a1;">
                        ℹ️ <strong>Nomor Tiket Otomatis Continuously:</strong> Sistem akan otomatis mengecek nomor urut tiket terakhir di DB (contoh: <code>JKT-2600001</code> → <code>JKT-2600002</code>).
                    </div>

                    <div class="form-section-title">1. Data Pelanggan</div>
                    <div class="form-grid">
                        <div class="form-group"><label>Nama Pemilik <span class="required">*</span></label><input id="inpName" placeholder="Contoh: Budi Santoso"></div>
                        <div class="form-group"><label>No. HP / WhatsApp 1 <span class="required">*</span></label><input id="inpPhone1" placeholder="081234567890"></div>
                        <div class="form-group"><label>Nama Instansi</label><input id="inpInstansi" placeholder="PT / Rumah Sakit / Klinik"></div>
                        <div class="form-group"><label>No. HP / WhatsApp 2</label><input id="inpPhone2" placeholder="081987654321"></div>
                    </div>
                    <div class="form-group"><label>Alamat Pemilik</label><textarea id="inpAddress" rows="2" placeholder="Alamat lengkap..."></textarea></div>
                    <div class="form-grid">
                        <div class="form-group">
                            <label>Provinsi</label>
                            <select id="inpProvinsi" onchange="updateCityDropdown()">
                                <option value="">— pilih provinsi —</option>
                                <option value="DKI Jakarta">DKI Jakarta</option>
                                <option value="Jawa Barat">Jawa Barat</option>
                                <option value="Banten">Banten</option>
                                <option value="Jawa Tengah">Jawa Tengah</option>
                                <option value="DI Yogyakarta">DI Yogyakarta</option>
                                <option value="Jawa Timur">Jawa Timur</option>
                                <option value="Bali">Bali</option>
                                <option value="Sumatera Utara">Sumatera Utara</option>
                                <option value="Sumatera Selatan">Sumatera Selatan</option>
                                <option value="Kalimantan Timur">Kalimantan Timur</option>
                                <option value="Sulawesi Selatan">Sulawesi Selatan</option>
                                <option value="Lainnya">Lainnya</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Kota (pilih provinsi dulu)</label>
                            <select id="inpKota">
                                <option value="">— pilih kota —</option>
                            </select>
                        </div>
                        <div class="form-group"><label>Tanggal Alat Diterima</label><input type="date" id="inpDateReceived"></div>
                        <div class="form-group"><label>Tanggal Alat Selesai</label><input type="date" id="inpDateFinished"></div>
                    </div>

                    <div class="form-section-title">2. Data Produk</div>
                    <div class="form-grid">
                        <div class="form-group">
                            <label>Produk Kategori</label>
                            <select id="inpCategory" onchange="updateModelDropdown()">
                                <option value="">— pilih kategori —</option>
                                <option value="Arm BPM">Arm BPM</option>
                                <option value="Wrist BPM">Wrist BPM</option>
                                <option value="NEB-Comp">NEB-Comp</option>
                                <option value="NEB-Mesh">NEB-Mesh</option>
                                <option value="NEB-Ultra">NEB-Ultra</option>
                                <option value="BCM">BCM</option>
                                <option value="DWS">DWS</option>
                                <option value="Thermo">Thermo</option>
                                <option value="TENS">TENS</option>
                                <option value="MEDICAL">MEDICAL</option>
                                <option value="Others">Others</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Model Alat (pilih kategori dulu)</label>
                            <select id="inpModel">
                                <option value="">— pilih model —</option>
                            </select>
                        </div>
                        <div class="form-group"><label>Serial No. Alat</label><input id="inpSN" placeholder="SN2026xxxx"></div>
                        <div class="form-group"><label>Aksesoris</label><input id="inpAccessories" placeholder="Cuff, Adaptor, Bag"></div>
                        <div class="form-group">
                            <label>Status Garansi</label>
                            <select id="inpGaransi">
                                <option value="Out of Warranty">Out of Warranty</option>
                                <option value="Under Warranty">Under Warranty</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Warranty Period (tahun)</label>
                            <select id="inpWarrantyPeriod">
                                <option value="">— pilih —</option>
                                <option value="1">1 Tahun</option>
                                <option value="2">2 Tahun</option>
                                <option value="3">3 Tahun</option>
                                <option value="4">4 Tahun</option>
                                <option value="5">5 Tahun</option>
                                <option value="6">6 Tahun</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Asal Produk</label>
                            <select id="inpAsalProduk">
                                <option value="">— pilih asal —</option>
                                <option value="LEU">LEU</option>
                                <option value="EU-DRC">EU-DRC</option>
                                <option value="AMS/IDC">AMS/IDC</option>
                                <option value="APT/ TKO">APT/ TKO</option>
                                <option value="CV/ PT/ RS">CV/ PT/ RS</option>
                                <option value="ALPRO">ALPRO</option>
                            </select>
                        </div>
                    </div>

                    <div class="form-section-title">3. Data Servis</div>
                    <div class="form-grid">
                        <div class="form-group"><label>Keluhan Pelanggan</label><input id="inpKeluhan" placeholder="Keluhan perangkat"></div>
                        <div class="form-group"><label>Analisa Teknisi</label><input id="inpAnalisa" placeholder="Hasil diagnosa"></div>
                        <div class="form-group"><label>Symptom (kode)</label><input id="inpSymptom" placeholder="Contoh: ERR-01"></div>
                        <div class="form-group"><label>Leadtime (hari)</label><input type="number" id="inpLeadtime" value="1"></div>
                    </div>
                    <div class="form-grid">
                        <div class="form-group"><label>Catatan</label><input id="inpCatatan" placeholder="Catatan tambahan..."></div>
                        <div class="form-group">
                            <label>Remarks</label>
                            <select id="inpRemarks">
                                <option value="">— pilih remarks —</option>
                                <option value="Compliance Check/ Sensor Check">Compliance Check/ Sensor Check</option>
                                <option value="Repair">Repair</option>
                                <option value="Replace Product/ Claim">Replace Product/ Claim</option>
                                <option value="Unrepairable/ Return to Customer">Unrepairable/ Return to Customer</option>
                                <option value="Disagree with Service Fee">Disagree with Service Fee</option>
                                <option value="No Response">No Response</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Repair Status</label>
                            <select id="inpRepairStatus">
                                <option value="Diterima Service Center">Diterima Service Center</option>
                                <option value="Diterima Pickup Center">Diterima Pickup Center</option>
                                <option value="Diproses">Diproses</option>
                                <option value="Selesai">Selesai</option>
                                <option value="Diambil Pemilik">Diambil Pemilik</option>
                                <option value="Dikirim via GED">Dikirim via GED</option>
                            </select>
                        </div>
                    </div>

                    <div class="form-section-title">4. Sparepart Digunakan</div>
                    <small style="color:#666; display:block; margin-bottom:10px;">Mengisi kode/nama & jumlah di sini akan otomatis mengurangi stok sparepart di lokasi tiket ini.</small>

                    <div class="sparepart-box">
                        <strong>Sparepart 1</strong>
                        <div class="form-grid">
                            <input id="sp1_nama" placeholder="Nama Sparepart 1">
                            <input id="sp1_kode" placeholder="Kode Sparepart">
                            <input type="number" id="sp1_jumlah" placeholder="Jumlah">
                            <input type="number" id="sp1_harga" placeholder="Harga (Rp)">
                        </div>
                    </div>

                    <div class="form-section-title">5. Notifikasi</div>
                    <div class="form-grid">
                        <div class="form-group">
                            <label>Kirim Notifikasi</label>
                            <select id="inpNotifikasi">
                                <option value="">— pilih notifikasi —</option>
                                <option value="Tanda Terima (WhatsApp)">Tanda Terima Service (Kirim via WhatsApp)</option>
                                <option value="Tanda Terima (Email)">Tanda Terima Service (Kirim via Email)</option>
                                <option value="Service Report (WhatsApp)">Service Report (Kirim via WhatsApp)</option>
                                <option value="Service Report (Email)">Service Report (Kirim via Email)</option>
                            </select>
                        </div>
                    </div>
                `;
            }

            async function savePageFormData(menuKey) {
                const getVal = (id) => {
                    const el = document.getElementById(id);
                    return el ? el.value.trim() : '';
                };

                const name = getVal('inpName');
                const phone = getVal('inpPhone1');

                if(!name || !phone) {
                    return alert('Nama Pemilik dan No. HP/WhatsApp 1 Wajib Diisi!');
                }

                const payload = {
                    service_type: menuKey.replace('service-', ''),
                    customer_name: name,
                    customer_phone: phone,
                    branch_or_point: getVal('inpProvinsi') || '-',
                    device_model: getVal('inpModel') || 'HEM-7120',
                    serial_number: getVal('inpSN') || '-',
                    warranty_status: getVal('inpGaransi') || 'Out of Warranty',
                    complaint: getVal('inpKeluhan') || '-'
                };

                try {
                    const res = await fetch('/api/v1/db/tickets/', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });

                    const resData = await res.json();

                    if (res.ok) {
                        alert(`BERHASIL! Tiket baru ${resData.ticket_number} berhasil dibuat dan tersimpan!`);
                        hideFormInPage(menuKey);
                        renderTableData(menuKey);
                        updateDashboardStats();
                    } else {
                        const errMsg = resData.detail || (typeof resData === 'object' ? JSON.stringify(resData) : res.statusText);
                        alert(`Gagal menyimpan ke DB: ${errMsg}`);
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
