from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.api.v1 import mutations
from app.services.excel_export import generate_service_report_excel

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="CRM Omron Healthcare API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(mutations.router)

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
        "current_location": "Service Center Pusat (Jakarta)"
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
            "technician": "Ahmad Teknisi"
        }
    ]
    excel_file = generate_service_report_excel(mock_tickets)
    filename = "Laporan_Servis_Omron_September_2026.xlsx"
    return StreamingResponse(
        excel_file,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
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
            
            /* Sidebar Styling */
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

            /* Main Content Area */
            main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
            header { background: white; padding: 15px 30px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #ddd; }
            header h1 { margin: 0; font-size: 18px; color: #0056b3; }
            .content { padding: 25px; overflow-y: auto; flex: 1; }

            .card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.06); margin-bottom: 20px; }
            h2 { color: #0056b3; margin-top: 0; font-size: 16px; border-bottom: 2px solid #e0e0e0; padding-bottom: 8px; }
            
            /* Table & Form Styling */
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
        </style>
    </head>
    <body>

        <!-- SIDEBAR NAVIGATION MENU -->
        <aside id="sidebar" class="hidden">
            <div class="brand">OMRON SERVICE</div>
            <ul>
                <!-- 1. Dashboard -->
                <li>
                    <a href="#" class="single-menu" onclick="showTab('dashboard')">1. Dashboard</a>
                </li>

                <!-- 2. Data Service -->
                <li>
                    <div class="menu-title" onclick="toggleSubmenu('sub-service')">2. Data Service <span>▼</span></div>
                    <ul id="sub-service" class="submenu">
                        <li><a href="#" onclick="showTab('service-pusat')">a. Data di Pusat</a></li>
                        <li><a href="#" onclick="showTab('service-cabang')">b. Data di Cabang</a></li>
                        <li><a href="#" onclick="showTab('service-pickup')">c. Data di Pickup Center</a></li>
                    </ul>
                </li>

                <!-- 3. Status Payment Service -->
                <li>
                    <div class="menu-title" onclick="toggleSubmenu('sub-payment')">3. Status Payment Service <span>▼</span></div>
                    <ul id="sub-payment" class="submenu">
                        <li><a href="#" onclick="showTab('payment-pusat')">a. Payment di Pusat</a></li>
                        <li><a href="#" onclick="showTab('payment-cabang')">b. Payment di Cabang</a></li>
                        <li><a href="#" onclick="showTab('payment-pickup')">c. Payment di Pickup Center</a></li>
                    </ul>
                </li>

                <!-- 4. Inventory Part -->
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

                <!-- 5. Setting Super Admin -->
                <li>
                    <div class="menu-title" onclick="toggleSubmenu('sub-setting')">5. Setting (Super Admin) <span>▼</span></div>
                    <ul id="sub-setting" class="submenu">
                        <li><a href="#" onclick="showTab('setting-fields')">a. Field Data Service</a></li>
                        <li><a href="#" onclick="showTab('setting-payment')">b. Field Payment & Reset Kode</a></li>
                    </ul>
                </li>
            </ul>
        </aside>

        <!-- MAIN CONTENT AREA -->
        <main>
            <header>
                <h1 id="pageTitle">Portal Management System</h1>
                <div>
                    <span id="userStatus" style="font-weight: bold; font-size: 13px; margin-right: 15px;">Belum Login</span>
                    <button id="btnLogout" class="btn btn-danger hidden" onclick="logout()">Logout</button>
                </div>
            </header>

            <div class="content">
                
                <!-- LOGIN CARD -->
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

                <!-- 1. TAB DASHBOARD -->
                <div id="tab-dashboard" class="tab-content hidden">
                    <div class="card">
                        <h2>Ringkasan Dashboard Utama</h2>
                        <div class="form-grid">
                            <div style="background:#e3f2fd; padding:15px; border-radius:6px; text-align:center;">
                                <h3 style="margin:0; color:#0d47a1;">124</h3>
                                <small>Total Servis Pusat</small>
                            </div>
                            <div style="background:#e8f5e9; padding:15px; border-radius:6px; text-align:center;">
                                <h3 style="margin:0; color:#1b5e20;">48</h3>
                                <small>Total Servis Cabang</small>
                            </div>
                            <div style="background:#fff3e0; padding:15px; border-radius:6px; text-align:center;">
                                <h3 style="margin:0; color:#e65100;">12</h3>
                                <small>Servis Pickup Center</small>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- 2. DATA SERVICE -->
                <div id="tab-service-pusat" class="tab-content hidden">
                    <div class="card">
                        <h2>2a. Data Service - Pusat</h2>
                        <button class="btn btn-success" onclick="alert('Membuka Form Tambah Tiket Pusat')">+ Tambah Service Pusat</button>
                        <table>
                            <thead><tr><th>No. Tiket</th><th>Pelanggan</th><th>Model Alat</th><th>Keluhan</th><th>Status</th></tr></thead>
                            <tbody id="tableServicePusat"><tr><td colspan="5">Memuat data pusat...</td></tr></tbody>
                        </table>
                    </div>
                </div>

                <div id="tab-service-cabang" class="tab-content hidden">
                    <div class="card">
                        <h2>2b. Data Service - Cabang</h2>
                        <table>
                            <thead><tr><th>No. Tiket</th><th>Cabang</th><th>Pelanggan</th><th>Model Alat</th><th>Status</th></tr></thead>
                            <tbody><tr><td>TCK-CBG-001</td><td>Surabaya</td><td>Ahmad Yani</td><td>HEM-7120</td><td>Dalam Perbaikan</td></tr></tbody>
                        </table>
                    </div>
                </div>

                <div id="tab-service-pickup" class="tab-content hidden">
                    <div class="card">
                        <h2>2c. Data Service - Pickup Center</h2>
                        <table>
                            <thead><tr><th>No. Tiket</th><th>Pickup Point</th><th>Pelanggan</th><th>Status Kurir</th></tr></thead>
                            <tbody><tr><td>TCK-PKP-102</td><td>Apotek K-24 Jakarta</td><td>Dewi Sartika</td><td>Diterima di Pusat</td></tr></tbody>
                        </table>
                    </div>
                </div>

                <!-- 3. STATUS PAYMENT SERVICE -->
                <div id="tab-payment-pusat" class="tab-content hidden">
                    <div class="card">
                        <h2>3a. Status Payment Service - Pusat</h2>
                        <table>
                            <thead><tr><th>No. Tiket</th><th>Total Biaya</th><th>Metode</th><th>Kode Payment</th><th>Status</th></tr></thead>
                            <tbody><tr><td>TCK-202609-001</td><td>Rp 150.000</td><td>QRIS / Transfer</td><td>PAY-882910</td><td><span class="badge badge-lunas">Lunas</span></td></tr></tbody>
                        </table>
                    </div>
                </div>

                <div id="tab-payment-cabang" class="tab-content hidden">
                    <div class="card">
                        <h2>3b. Status Payment Service - Cabang</h2>
                        <table>
                            <thead><tr><th>No. Tiket</th><th>Cabang</th><th>Total Biaya</th><th>Kode Payment</th><th>Status</th></tr></thead>
                            <tbody><tr><td>TCK-CBG-001</td><td>Surabaya</td><td>Rp 85.000</td><td>PAY-331029</td><td><span class="badge badge-pending">Pending</span></td></tr></tbody>
                        </table>
                    </div>
                </div>

                <div id="tab-payment-pickup" class="tab-content hidden">
                    <div class="card">
                        <h2>3c. Status Payment Service - Pickup Center</h2>
                        <table>
                            <thead><tr><th>No. Tiket</th><th>Pickup Location</th><th>Biaya Kirim & Servis</th><th>Status</th></tr></thead>
                            <tbody><tr><td>TCK-PKP-102</td><td>Apotek K-24</td><td>Rp 120.000</td><td><span class="badge badge-lunas">Lunas</span></td></tr></tbody>
                        </table>
                    </div>
                </div>

                <!-- 4. INVENTORY PART PUSAT & CABANG -->
                <div id="tab-inv-pusat-list" class="tab-content hidden">
                    <div class="card">
                        <h2>4a.1. List Stok Spare Part di Pusat</h2>
                        <table>
                            <thead><tr><th>Kode Part</th><th>Nama Spare Part</th><th>Kategori</th><th>Stok Pusat</th></tr></thead>
                            <tbody><tr><td>PRT-001</td><td>Cuff / Manset Tensimeter Standard</td><td>Tensimeter</td><td>250 Pcs</td></tr></tbody>
                        </table>
                    </div>
                </div>

                <div id="tab-inv-pusat-pakai" class="tab-content hidden">
                    <div class="card">
                        <h2>4a.2. Catatan Pemakaian Stok di Pusat</h2>
                        <p>Riwayat penggunaan spare part untuk pengerjaan unit servis di Pusat.</p>
                    </div>
                </div>

                <div id="tab-inv-pusat-terima" class="tab-content hidden">
                    <div class="card">
                        <h2>4a.3. Penerimaan Stok dari Gudang Utama</h2>
                        <p>Daftar persetujuan dan masukan stok baru dari Gudang Utama Omron.</p>
                    </div>
                </div>

                <div id="tab-inv-pusat-kirim" class="tab-content hidden">
                    <div class="card">
                        <h2>4a.4. Pengiriman Stok ke Cabang</h2>
                        <p>Pengiriman pasokan spare part dari Pusat ke cabang-cabang daerah.</p>
                    </div>
                </div>

                <div id="tab-inv-cabang-list" class="tab-content hidden">
                    <div class="card">
                        <h2>4b.1. List Stok di Cabang</h2>
                        <table>
                            <thead><tr><th>Kode Part</th><th>Nama Part</th><th>Cabang</th><th>Jumlah Stok</th></tr></thead>
                            <tbody><tr><td>PRT-001</td><td>Cuff Tensimeter Standard</td><td>Surabaya</td><td>35 Pcs</td></tr></tbody>
                        </table>
                    </div>
                </div>

                <div id="tab-inv-cabang-pakai" class="tab-content hidden">
                    <div class="card"><h2>4b.2. Pemakaian Stok di Cabang</h2><p>Penggunaan part oleh teknisi cabang.</p></div>
                </div>
                <div id="tab-inv-cabang-terima" class="tab-content hidden">
                    <div class="card"><h2>4b.3. Penerimaan Stok dari Pusat</h2><p>Konfirmasi penerimaan part dari Pusat.</p></div>
                </div>
                <div id="tab-inv-cabang-minta" class="tab-content hidden">
                    <div class="card"><h2>4b.4. Permintaan Stok ke Pusat</h2><p>Form permintaan pengisian ulang stok part ke Pusat.</p></div>
                </div>

                <!-- 5. SETTING SUPER ADMIN -->
                <div id="tab-setting-fields" class="tab-content hidden">
                    <div class="card">
                        <h2>5a. Setting Field Data Service (Super Admin)</h2>
                        <p>Atur Master Data Field Sistem:</p>
                        <div class="form-grid">
                            <div><label>Category Alat</label><input placeholder="Tensimeter, Nebulizer"><button class="btn" style="margin-top:5px;">Tambah</button></div>
                            <div><label>Model Alat</label><input placeholder="HEM-7120, MC-246"><button class="btn" style="margin-top:5px;">Tambah</button></div>
                            <div><label>Source of Device</label><input placeholder="Official Store, Distributor"><button class="btn" style="margin-top:5px;">Tambah</button></div>
                            <div><label>Warranty Period</label><input placeholder="1 Tahun, 3 Tahun"><button class="btn" style="margin-top:5px;">Tambah</button></div>
                            <div><label>Data Provinsi</label><input placeholder="DKI Jakarta, Jawa Timur"><button class="btn" style="margin-top:5px;">Tambah</button></div>
                            <div><label>Data Kota/Kabupaten</label><input placeholder="Jakarta Pusat, Surabaya"><button class="btn" style="margin-top:5px;">Tambah</button></div>
                        </div>
                    </div>
                </div>

                <div id="tab-setting-payment" class="tab-content hidden">
                    <div class="card">
                        <h2>5b. Setting Field Status Payment & Kode Payment</h2>
                        <div class="form-group">
                            <label>Tambah Master Status Pembayaran</label>
                            <input type="text" placeholder="Contoh: Menunggu Konfirmasi Bank" style="max-width: 300px;">
                            <button class="btn" style="margin-top: 5px;">Simpan Status</button>
                        </div>
                        <hr style="margin:20px 0;">
                        <h2>Ganti / Reset Kode Payment</h2>
                        <div class="form-group">
                            <label>Masukkan Nomor Tiket / ID Transaksi</label>
                            <input type="text" placeholder="TCK-202609-001" style="max-width: 300px;">
                            <button class="btn btn-danger" style="margin-top: 5px;" onclick="alert('Kode Payment Berhasil Di-reset!')">Reset Kode Payment</button>
                        </div>
                    </div>
                </div>

            </div>
        </main>

        <script>
            let authToken = localStorage.getItem('omron_token') || '';

            window.onload = function() {
                if (authToken) {
                    showDashboardUI();
                }
            };

            function toggleSubmenu(id) {
                const el = document.getElementById(id);
                el.classList.toggle('open');
            }

            function showDashboardUI() {
                document.getElementById('loginCard').classList.add('hidden');
                document.getElementById('sidebar').classList.remove('hidden');
                document.getElementById('btnLogout').classList.remove('hidden');
                document.getElementById('userStatus').innerText = 'Super Admin Active';
                showTab('dashboard');
            }

            function showTab(tabId) {
                // Sembunyikan semua tab content
                document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
                
                // Tampilkan tab target
                const target = document.getElementById('tab-' + tabId);
                if(target) target.classList.remove('hidden');

                // Update judul halaman di header
                document.getElementById('pageTitle').innerText = 'Menu: ' + tabId.toUpperCase().replace(/-/g, ' ');

                // Load Data Jika Tab Service Pusat
                if(tabId === 'service-pusat') loadTicketsPusat();
            }

            async function login() {
                const email = document.getElementById('emailInput').value.trim();
                const password = document.getElementById('passwordInput').value.trim();
                if(!email || !password) return alert('Lengkapi email dan password!');

                authToken = 'jwt_superadmin_omron_2026';
                localStorage.setItem('omron_token', authToken);
                showDashboardUI();
            }

            function logout() {
                localStorage.removeItem('omron_token');
                location.reload();
            }

            async function loadTicketsPusat() {
                const table = document.getElementById('tableServicePusat');
                try {
                    const res = await fetch('/api/v1/tickets/', {
                        headers: { 'Authorization': 'Bearer ' + authToken }
                    });
                    if (res.ok) {
                        const data = await res.json();
                        table.innerHTML = data.map(t => `
                            <tr>
                                <td>${t.ticket_number}</td>
                                <td>${t.customer_name}</td>
                                <td>${t.device_model}</td>
                                <td>${t.complaint || '-'}</td>
                                <td><span class="badge badge-lunas">${t.status || 'BARU'}</span></td>
                            </tr>
                        `).join('');
                    } else {
                        table.innerHTML = `<tr><td>TCK-202609-001</td><td>Budi Santoso</td><td>HEM-7120</td><td>Mati Total</td><td><span class="badge badge-lunas">Diterima Pusat</span></td></tr>`;
                    }
                } catch(e) {
                    table.innerHTML = `<tr><td>TCK-202609-001</td><td>Budi Santoso</td><td>HEM-7120</td><td>Mati Total</td><td><span class="badge badge-lunas">Diterima Pusat</span></td></tr>`;
                }
            }
        </script>
    </body>
    </html>
    """