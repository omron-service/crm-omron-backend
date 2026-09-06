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

# Register Router Modul
app.include_router(mutations.router)
app.include_router(services_api.router)  # Router Database PostgreSQL Neon.tech


@app.get("/")
def root():
    return {"status": "online", "system": "CRM Omron Healthcare API"}


@app.get("/api/v1/public/track/{ticket_number}")
@limiter.limit("10/minute")
def track_ticket_api(request: Request, ticket_number: str):
    return {
        "ticket_number": ticket_number,
        "device_model": "Omron HEM-7120",
        "status": "Sedang Diperbaiki Teknisi",
        "current_location": "Service Center Pusat (Jakarta)",
    }


@app.get("/api/v1/admin/reports/excel")
def download_excel_report():
    mock_tickets = [
        {
            "ticket_number": "TCK-202609-001",
            "created_at": "2026-09-01",
            "customer_name": "Budi Santoso",
            "customer_phone": "081234567890",
            "device_model": "Omron HEM-7120",
            "serial_number": "SN7120-9921",
            "status": "Sedang Diperbaiki Teknisi",
            "technician": "Ahmad Teknisi",
        }
    ]
    excel_file = generate_service_report_excel(mock_tickets)
    filename = "Laporan_Servis_Omron_September_2026.xlsx"
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
            .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 15px; }
            .form-group { margin-bottom: 10px; }
            label { display: block; margin-bottom: 5px; font-weight: bold; font-size: 12px; color: #555; }
            input, select, textarea { width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px; font-size: 13px; }
            .btn { background: #0056b3; color: white; border: none; padding: 9px 16px; border-radius: 4px; cursor: pointer; font-weight: bold; font-size: 13px; }
            .btn:hover { background: #004085; }
            .btn-danger { background: #dc3545; }
            .btn-success { background: #28a745; }
            .hidden { display: none !important; }
            .login-box { max-width: 400px; margin: 80px auto; }
            .badge { padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 11px; }
            .badge-lunas { background: #d4edda; color: #155724; }
            .badge-pending { background: #fff3cd; color: #856404; }

            .modal-overlay { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); display: flex; justify-content: center; align-items: center; z-index: 999; }
            .modal-content { background: white; width: 100%; max-width: 600px; border-radius: 8px; padding: 25px; box-shadow: 0 4px 15px rgba(0,0,0,0.2); }
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
                        <h2>Ringkasan Dashboard Utama (Database Neon.tech)</h2>
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

                <!-- 2. DATA SERVICE -->
                <div id="tab-service-pusat" class="tab-content hidden">
                    <div class="card">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                            <h2 style="margin: 0; border: none;">2a. Data Service - Pusat</h2>
                            <button class="btn btn-success" onclick="openModal('service-pusat')">+ Tambah Service Pusat</button>
                        </div>
                        <table>
                            <thead><tr><th>No. Tiket</th><th>Pelanggan</th><th>No. HP</th><th>Model Alat</th><th>Keluhan</th><th>Status</th></tr></thead>
                            <tbody id="tableServicePusat"></tbody>
                        </table>
                    </div>
                </div>

                <div id="tab-service-cabang" class="tab-content hidden">
                    <div class="card">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                            <h2 style="margin: 0; border: none;">2b. Data Service - Cabang</h2>
                            <button class="btn btn-success" onclick="openModal('service-cabang')">+ Tambah Service Cabang</button>
                        </div>
                        <table>
                            <thead><tr><th>No. Tiket</th><th>Cabang</th><th>Pelanggan</th><th>Model Alat</th><th>Status</th></tr></thead>
                            <tbody id="tableServiceCabang"></tbody>
                        </table>
                    </div>
                </div>

                <div id="tab-service-pickup" class="tab-content hidden">
                    <div class="card">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                            <h2 style="margin: 0; border: none;">2c. Data Service - Pickup Center</h2>
                            <button class="btn btn-success" onclick="openModal('service-pickup')">+ Tambah Service Pickup</button>
                        </div>
                        <table>
                            <thead><tr><th>No. Tiket</th><th>Pickup Point</th><th>Pelanggan</th><th>Status Kurir</th></tr></thead>
                            <tbody id="tableServicePickup"></tbody>
                        </table>
                    </div>
                </div>

                <!-- 3. STATUS PAYMENT SERVICE -->
                <div id="tab-payment-pusat" class="tab-content hidden">
                    <div class="card">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                            <h2 style="margin: 0; border: none;">3a. Status Payment Service - Pusat</h2>
                            <button class="btn btn-success" onclick="openModal('payment-pusat')">+ Catat Payment Pusat</button>
                        </div>
                        <table>
                            <thead><tr><th>No. Tiket</th><th>Total Biaya</th><th>Metode</th><th>Kode Payment</th><th>Status</th></tr></thead>
                            <tbody id="tablePaymentPusat"></tbody>
                        </table>
                    </div>
                </div>

                <div id="tab-payment-cabang" class="tab-content hidden">
                    <div class="card">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                            <h2 style="margin: 0; border: none;">3b. Status Payment Service - Cabang</h2>
                            <button class="btn btn-success" onclick="openModal('payment-cabang')">+ Catat Payment Cabang</button>
                        </div>
                        <table>
                            <thead><tr><th>No. Tiket</th><th>Cabang</th><th>Total Biaya</th><th>Kode Payment</th><th>Status</th></tr></thead>
                            <tbody id="tablePaymentCabang"></tbody>
                        </table>
                    </div>
                </div>

                <div id="tab-payment-pickup" class="tab-content hidden">
                    <div class="card">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                            <h2 style="margin: 0; border: none;">3c. Status Payment Service - Pickup Center</h2>
                            <button class="btn btn-success" onclick="openModal('payment-pickup')">+ Catat Payment Pickup</button>
                        </div>
                        <table>
                            <thead><tr><th>No. Tiket</th><th>Pickup Location</th><th>Biaya Kirim & Servis</th><th>Status</th></tr></thead>
                            <tbody id="tablePaymentPickup"></tbody>
                        </table>
                    </div>
                </div>

                <!-- 4. INVENTORY PART -->
                <div id="tab-inv-pusat-list" class="tab-content hidden">
                    <div class="card">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                            <h2 style="margin: 0; border: none;">4a.1. List Stok Spare Part di Pusat</h2>
                            <button class="btn btn-success" onclick="openModal('inv-pusat-list')">+ Tambah Stok Part Pusat</button>
                        </div>
                        <table>
                            <thead><tr><th>Kode Part</th><th>Nama Spare Part</th><th>Kategori</th><th>Stok Pusat</th></tr></thead>
                            <tbody id="tableInvPusatList"></tbody>
                        </table>
                    </div>
                </div>

                <div id="tab-inv-pusat-pakai" class="tab-content hidden"><div class="card"><h2>4a.2. Pemakaian Stok di Pusat</h2><p>Riwayat pemakaian spare part pengerjaan servis pusat.</p></div></div>
                <div id="tab-inv-pusat-terima" class="tab-content hidden"><div class="card"><h2>4a.3. Penerimaan Stok dari Gudang Utama</h2><p>Daftar masukan stok baru dari Gudang Utama.</p></div></div>
                <div id="tab-inv-pusat-kirim" class="tab-content hidden"><div class="card"><h2>4a.4. Pengiriman Stok ke Cabang</h2><p>Pengiriman stok part dari Pusat ke cabang.</p></div></div>
                <div id="tab-inv-cabang-list" class="tab-content hidden">
                    <div class="card">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                            <h2 style="margin: 0; border: none;">4b.1. List Stok di Cabang</h2>
                            <button class="btn btn-success" onclick="openModal('inv-cabang-list')">+ Tambah Stok Part Cabang</button>
                        </div>
                        <table>
                            <thead><tr><th>Kode Part</th><th>Nama Part</th><th>Cabang</th><th>Jumlah Stok</th></tr></thead>
                            <tbody id="tableInvCabangList"></tbody>
                        </table>
                    </div>
                </div>
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
                            <input type="text" id="resetTicket" placeholder="TCK-123456" style="max-width: 300px;">
                            <button class="btn btn-danger" style="margin-top:5px;" onclick="alert('Kode Payment Berhasil Direset!')">Reset Kode</button>
                        </div>
                    </div>
                </div>

            </div>
        </main>

        <!-- MODAL DYNAMIC FORM -->
        <div id="modalForm" class="modal-overlay hidden">
            <div class="modal-content">
                <div class="modal-header">
                    <h3 id="modalTitle">Form Tambah Data</h3>
                    <button class="close-btn" onclick="closeModal()">&times;</button>
                </div>
                <div id="modalBody"></div>
                <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 15px;">
                    <button class="btn" style="background:#6c757d;" onclick="closeModal()">Batal</button>
                    <button class="btn btn-success" onclick="saveModalData()">Simpan Data Ke Neon.tech</button>
                </div>
            </div>
        </div>

        <script>
            let authToken = localStorage.getItem('omron_token') || '';
            let currentActiveMenu = '';

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
                document.getElementById('userStatus').innerText = 'Super Admin Active';
                showTab('dashboard');
            }

            function showTab(tabId) {
                document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
                
                const target = document.getElementById('tab-' + tabId);
                if(target) target.classList.remove('hidden');

                document.getElementById('pageTitle').innerText = 'Menu: ' + tabId.toUpperCase().replace(/-/g, ' ');

                renderTableData(tabId);
                updateDashboardStats();
            }

            async function updateDashboardStats() {
                try {
                    const resPusat = await fetch('/api/v1/db/tickets/pusat');
                    const resCabang = await fetch('/api/v1/db/tickets/cabang');
                    const resPickup = await fetch('/api/v1/db/tickets/pickup');

                    if(resPusat.ok) document.getElementById('statPusat').innerText = (await resPusat.json()).length;
                    if(resCabang.ok) document.getElementById('statCabang').innerText = (await resCabang.json()).length;
                    if(resPickup.ok) document.getElementById('statPickup').innerText = (await resPickup.json()).length;
                } catch(e) {}
            }

            async function renderTableData(menu) {
                let endpoint = '';
                if (menu.startsWith('service-')) endpoint = '/api/v1/db/tickets/' + menu.replace('service-', '');
                else if (menu.startsWith('payment-')) endpoint = '/api/v1/db/payments/' + menu.replace('payment-', '');
                else if (menu.startsWith('inv-')) endpoint = '/api/v1/db/inventory/' + (menu.includes('pusat') ? 'pusat' : 'cabang');

                if (!endpoint) return;

                try {
                    const res = await fetch(endpoint);
                    if (res.ok) {
                        const data = await res.json();
                        
                        if(menu === 'service-pusat') {
                            document.getElementById('tableServicePusat').innerHTML = data.length ? data.map(d => `<tr><td>${d.ticket_number}</td><td>${d.customer_name}</td><td>${d.customer_phone}</td><td>${d.device_model}</td><td>${d.complaint||'-'}</td><td><span class="badge badge-lunas">${d.status}</span></td></tr>`).join('') : `<tr><td colspan="6" style="text-align:center;">Belum ada data di DB</td></tr>`;
                        } else if(menu === 'service-cabang') {
                            document.getElementById('tableServiceCabang').innerHTML = data.length ? data.map(d => `<tr><td>${d.ticket_number}</td><td>${d.branch_or_point||'-'}</td><td>${d.customer_name}</td><td>${d.device_model}</td><td><span class="badge badge-pending">${d.status}</span></td></tr>`).join('') : `<tr><td colspan="5" style="text-align:center;">Belum ada data di DB</td></tr>`;
                        } else if(menu === 'service-pickup') {
                            document.getElementById('tableServicePickup').innerHTML = data.length ? data.map(d => `<tr><td>${d.ticket_number}</td><td>${d.branch_or_point||'-'}</td><td>${d.customer_name}</td><td><span class="badge badge-lunas">${d.status}</span></td></tr>`).join('') : `<tr><td colspan="4" style="text-align:center;">Belum ada data di DB</td></tr>`;
                        } else if(menu === 'payment-pusat') {
                            document.getElementById('tablePaymentPusat').innerHTML = data.length ? data.map(d => `<tr><td>${d.ticket_number}</td><td>Rp ${parseFloat(d.amount).toLocaleString('id-ID')}</td><td>${d.payment_method||'-'}</td><td>${d.payment_code}</td><td><span class="badge badge-lunas">${d.status}</span></td></tr>`).join('') : `<tr><td colspan="5" style="text-align:center;">Belum ada data di DB</td></tr>`;
                        } else if(menu === 'payment-cabang') {
                            document.getElementById('tablePaymentCabang').innerHTML = data.length ? data.map(d => `<tr><td>${d.ticket_number}</td><td>${d.branch_or_point||'-'}</td><td>Rp ${parseFloat(d.amount).toLocaleString('id-ID')}</td><td>${d.payment_code}</td><td><span class="badge badge-pending">${d.status}</span></td></tr>`).join('') : `<tr><td colspan="5" style="text-align:center;">Belum ada data di DB</td></tr>`;
                        } else if(menu === 'payment-pickup') {
                            document.getElementById('tablePaymentPickup').innerHTML = data.length ? data.map(d => `<tr><td>${d.ticket_number}</td><td>${d.branch_or_point||'-'}</td><td>Rp ${parseFloat(d.amount).toLocaleString('id-ID')}</td><td><span class="badge badge-lunas">${d.status}</span></td></tr>`).join('') : `<tr><td colspan="4" style="text-align:center;">Belum ada data di DB</td></tr>`;
                        } else if(menu === 'inv-pusat-list') {
                            document.getElementById('tableInvPusatList').innerHTML = data.length ? data.map(d => `<tr><td>${d.part_code}</td><td>${d.part_name}</td><td>${d.category||'-'}</td><td>${d.qty} Pcs</td></tr>`).join('') : `<tr><td colspan="4" style="text-align:center;">Belum ada data di DB</td></tr>`;
                        } else if(menu === 'inv-cabang-list') {
                            document.getElementById('tableInvCabangList').innerHTML = data.length ? data.map(d => `<tr><td>${d.part_code}</td><td>${d.part_name}</td><td>${d.branch||'-'}</td><td>${d.qty} Pcs</td></tr>`).join('') : `<tr><td colspan="4" style="text-align:center;">Belum ada data di DB</td></tr>`;
                        }
                    }
                } catch(e) {
                    console.error('Error fetching database:', e);
                }
            }

            function openModal(menu) {
                currentActiveMenu = menu;
                const modalBody = document.getElementById('modalBody');
                document.getElementById('modalTitle').innerText = 'Tambah Data: ' + menu.toUpperCase();

                if(menu.startsWith('service-')) {
                    modalBody.innerHTML = `
                        <div class="form-grid">
                            <div class="form-group"><label>Nama Pelanggan</label><input id="inpName" placeholder="Budi Santoso"></div>
                            <div class="form-group"><label>No. HP</label><input id="inpPhone" placeholder="081234567890"></div>
                            ${menu === 'service-cabang' ? '<div class="form-group"><label>Nama Cabang</label><input id="inpBranch" placeholder="Surabaya"></div>' : ''}
                            ${menu === 'service-pickup' ? '<div class="form-group"><label>Pickup Point</label><input id="inpPoint" placeholder="Apotek K-24"></div>' : ''}
                            <div class="form-group"><label>Model Alat</label><input id="inpModel" placeholder="HEM-7120"></div>
                            <div class="form-group"><label>Serial Number (SN)</label><input id="inpSN" placeholder="SN2026xxxx"></div>
                        </div>
                        <div class="form-group"><label>Keluhan / Kerusakan</label><textarea id="inpComplaint" rows="2"></textarea></div>
                    `;
                } else if(menu.startsWith('payment-')) {
                    modalBody.innerHTML = `
                        <div class="form-grid">
                            <div class="form-group"><label>No. Tiket</label><input id="inpTicket" placeholder="TCK-123456"></div>
                            <div class="form-group"><label>Total Biaya (Rp)</label><input id="inpAmount" type="number" placeholder="150000"></div>
                            ${menu === 'payment-cabang' ? '<div class="form-group"><label>Nama Cabang</label><input id="inpBranch" placeholder="Surabaya"></div>' : ''}
                            ${menu === 'payment-pickup' ? '<div class="form-group"><label>Pickup Location</label><input id="inpPoint" placeholder="Apotek K-24"></div>' : ''}
                            ${menu === 'payment-pusat' ? '<div class="form-group"><label>Metode Pembayaran</label><input id="inpMethod" placeholder="QRIS / Transfer"></div>' : ''}
                        </div>
                    `;
                } else if(menu.startsWith('inv-')) {
                    modalBody.innerHTML = `
                        <div class="form-grid">
                            <div class="form-group"><label>Kode Spare Part</label><input id="inpCode" placeholder="PRT-001"></div>
                            <div class="form-group"><label>Nama Spare Part</label><input id="inpPartName" placeholder="Cuff Tensimeter"></div>
                            ${menu === 'inv-pusat-list' ? '<div class="form-group"><label>Kategori</label><input id="inpCategory" placeholder="Tensimeter"></div>' : ''}
                            ${menu === 'inv-cabang-list' ? '<div class="form-group"><label>Cabang</label><input id="inpBranch" placeholder="Surabaya"></div>' : ''}
                            <div class="form-group"><label>Jumlah (Qty)</label><input id="inpQty" type="number" placeholder="50"></div>
                        </div>
                    `;
                }
                document.getElementById('modalForm').classList.remove('hidden');
            }

            function closeModal() {
                document.getElementById('modalForm').classList.add('hidden');
            }

            async function saveModalData() {
                let payload = {};
                let endpoint = '';

                if (currentActiveMenu.startsWith('service-')) {
                    endpoint = '/api/v1/db/tickets/';
                    payload = {
                        service_type: currentActiveMenu.replace('service-', ''),
                        customer_name: document.getElementById('inpName').value || 'Tanpa Nama',
                        customer_phone: document.getElementById('inpPhone').value || '-',
                        branch_or_point: (document.getElementById('inpBranch') || document.getElementById('inpPoint') || {}).value || null,
                        device_model: document.getElementById('inpModel').value || 'HEM-7120',
                        serial_number: document.getElementById('inpSN').value || null,
                        complaint: document.getElementById('inpComplaint').value || null
                    };
                } else if (currentActiveMenu.startsWith('payment-')) {
                    endpoint = '/api/v1/db/payments/';
                    payload = {
                        service_type: currentActiveMenu.replace('payment-', ''),
                        ticket_number: document.getElementById('inpTicket').value || 'TCK-MOCK',
                        amount: parseFloat(document.getElementById('inpAmount').value || 0),
                        payment_method: (document.getElementById('inpMethod') || {}).value || 'Transfer',
                        branch_or_point: (document.getElementById('inpBranch') || document.getElementById('inpPoint') || {}).value || null
                    };
                } else if (currentActiveMenu.startsWith('inv-')) {
                    endpoint = '/api/v1/db/inventory/';
                    payload = {
                        inventory_type: currentActiveMenu.includes('pusat') ? 'pusat' : 'cabang',
                        part_code: document.getElementById('inpCode').value || 'PRT-' + Math.floor(Math.random()*1000),
                        part_name: document.getElementById('inpPartName').value || 'Sparepart Baru',
                        category: (document.getElementById('inpCategory') || {}).value || null,
                        branch: (document.getElementById('inpBranch') || {}).value || null,
                        qty: parseInt(document.getElementById('inpQty').value || 0)
                    };
                }

                try {
                    const res = await fetch(endpoint, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });

                    if (res.ok) {
                        alert('BERHASIL! Data tersimpan di PostgreSQL Neon.tech!');
                        closeModal();
                        renderTableData(currentActiveMenu);
                        updateDashboardStats();
                    } else {
                        alert('Gagal menyimpan ke DB: ' + res.statusText);
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