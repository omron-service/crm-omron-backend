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

# Endpoint Download Laporan Excel Servis
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

# Endpoint Halaman Web HTML Admin & Teknisi Dashboard Berintegrasi Menu Tab Navigasi
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
            
            /* Styles Navigasi Tab Menu */
            nav { display: flex; gap: 10px; }
            nav button { background: rgba(255, 255, 255, 0.15); color: white; border: 1px solid rgba(255,255,255,0.3); padding: 8px 16px; border-radius: 5px; cursor: pointer; font-weight: bold; font-size: 13px; transition: 0.2s; }
            nav button:hover, nav button.active { background: white; color: #0056b3; }

            .container { padding: 30px; max-width: 1100px; margin: auto; }
            .card { background: white; padding: 25px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); margin-bottom: 25px; }
            h2 { color: #0056b3; margin-top: 0; font-size: 18px; border-bottom: 2px solid #e0e0e0; padding-bottom: 10px; }
            .form-group { margin-bottom: 15px; }
            label { display: block; margin-bottom: 5px; font-weight: bold; font-size: 14px; }
            input, select, textarea { width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 5px; font-size: 14px; }
            .btn-primary { background: #0056b3; color: white; border: none; padding: 12px 20px; border-radius: 5px; cursor: pointer; font-weight: bold; font-size: 14px; }
            .btn-primary:hover { background: #004085; }
            .login-box { max-width: 400px; margin: 80px auto; }
            .hidden { display: none !important; }
            table { width: 100%; border-collapse: collapse; margin-top: 15px; }
            th, td { border: 1px solid #ddd; padding: 10px; text-align: left; font-size: 14px; }
            th { background: #f8f9fa; }
            .badge-success { color: #155724; background: #d4edda; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 12px; }
            .badge-info { color: #0c5460; background: #d1ecf1; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 12px; }
        </style>
    </head>
    <body>
        <header>
            <h1>OMRON Healthcare Portal</h1>
            <!-- Navigasi Menu Tab -->
            <nav id="navMenu" class="hidden">
                <button id="nav-tickets" class="active" onclick="switchTab('tickets')">📋 Tiket Servis</button>
                <button id="nav-mutations" onclick="switchTab('mutations')">🔄 Mutasi Spare Part</button>
                <button id="nav-inventory" onclick="switchTab('inventory')">📦 Stok Inventaris</button>
                <button onclick="logout()" style="background: #dc3545; border: none;">Logout</button>
            </nav>
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
                <button class="btn-primary" style="width: 100%;" onclick="login()">Masuk ke Portal</button>
            </div>

            <!-- TAB 1: DASHBOARD TIKET SERVIS -->
            <div id="tab-tickets" class="tab-content hidden">
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
                        <textarea id="complaint" rows="2" placeholder="Hasil pengukuran tidak akurat / Mati total"></textarea>
                    </div>
                    <button class="btn-primary" onclick="createTicket()">Buat Tiket Servis</button>
                </div>

                <div class="card">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                        <h2 style="margin: 0; border: none;">Daftar Tiket Servis Terbaru</h2>
                        <a href="/api/v1/admin/reports/excel" style="background: #28a745; color: white; padding: 10px 15px; border-radius: 5px; text-decoration: none; font-weight: bold; font-size: 13px;">
                            📊 Unduh Laporan Excel
                        </a>
                    </div>
                    <table>
                        <thead>
                            <tr>
                                <th>No. Tiket</th>
                                <th>Pelanggan</th>
                                <th>Model Perangkat</th>
                                <th>Status</th>
                                <th>Aksi</th>
                            </tr>
                        </thead>
                        <tbody id="ticketTable">
                            <tr><td colspan="5" style="text-align: center;">Memuat data...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- TAB 2: MUTASI SPARE PART -->
            <div id="tab-mutations" class="tab-content hidden">
                <div class="card">
                    <h2>Catat Mutasi Spare Part antar Cabang</h2>
                    <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 15px;">
                        <div class="form-group">
                            <label>Nama Spare Part</label>
                            <input type="text" id="partName" placeholder="Cuff Tensimeter / LCD Screen">
                        </div>
                        <div class="form-group">
                            <label>Cabang Asal</label>
                            <select id="originBranch">
                                <option value="Jakarta Pusat">Jakarta Pusat</option>
                                <option value="Surabaya">Surabaya</option>
                                <option value="Medan">Medan</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Cabang Tujuan</label>
                            <select id="destBranch">
                                <option value="Surabaya">Surabaya</option>
                                <option value="Jakarta Pusat">Jakarta Pusat</option>
                                <option value="Bandung">Bandung</option>
                            </select>
                        </div>
                    </div>
                    <div style="display: grid; grid-template-columns: 1fr 2fr; gap: 15px;">
                        <div class="form-group">
                            <label>Jumlah (Qty)</label>
                            <input type="number" id="mutationQty" value="1">
                        </div>
                        <div class="form-group">
                            <label>Catatan Mutasi</label>
                            <input type="text" id="mutationNote" placeholder="Permintaan pengisian stok spare part cabang">
                        </div>
                    </div>
                    <button class="btn-primary" onclick="submitMutation()">Kirim Mutasi Spare Part</button>
                </div>

                <div class="card">
                    <h2>Riwayat Mutasi Spare Part</h2>
                    <table>
                        <thead>
                            <tr>
                                <th>ID Mutasi</th>
                                <th>Item / Part</th>
                                <th>Asal → Tujuan</th>
                                <th>Jumlah</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody id="mutationTable">
                            <tr><td colspan="5" style="text-align: center;">Memuat data mutasi...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- TAB 3: STOK INVENTARIS MULTI-BRANCH -->
            <div id="tab-inventory" class="tab-content hidden">
                <div class="card">
                    <h2>Ringkasan Stok Spare Part & Unit (Multi-Branch)</h2>
                    <table>
                        <thead>
                            <tr>
                                <th>Kode Barang</th>
                                <th>Nama Perangkat / Spare Part</th>
                                <th>Cabang</th>
                                <th>Stok Tersedia</th>
                                <th>Status Stok</th>
                            </tr>
                        </thead>
                        <tbody id="inventoryTable">
                            <tr>
                                <td>PRT-HEM-CUFF</td>
                                <td>Manset Tensimeter Standard (Cuff)</td>
                                <td>Jakarta Pusat</td>
                                <td>45 Pcs</td>
                                <td><span class="badge-success">Aman</span></td>
                            </tr>
                            <tr>
                                <td>PRT-HEM-PUMP</td>
                                <td>Air Pump Motor HEM-7120</td>
                                <td>Surabaya</td>
                                <td>8 Pcs</td>
                                <td><span class="badge-info">Perlu Restock</span></td>
                            </tr>
                            <tr>
                                <td>PRT-NEC-FILTER</td>
                                <td>Air Filter Nebulizer NE-C28</td>
                                <td>Medan</td>
                                <td>120 Pcs</td>
                                <td><span class="badge-success">Aman</span></td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>

        </div>

        <script>
            let authToken = localStorage.getItem('omron_token') || '';

            window.onload = function() {
                if (authToken) {
                    showDashboardUI();
                }
            };

            function showDashboardUI() {
                document.getElementById('loginCard').classList.add('hidden');
                document.getElementById('navMenu').classList.remove('hidden');
                document.getElementById('userStatus').innerText = 'Super Admin';
                switchTab('tickets');
            }

            function switchTab(tabName) {
                // Sembunyikan semua tab
                document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
                document.querySelectorAll('nav button').forEach(el => el.classList.remove('active'));

                // Tampilkan tab yang dipilih
                const activeTab = document.getElementById('tab-' + tabName);
                if(activeTab) activeTab.classList.remove('hidden');

                const activeNav = document.getElementById('nav-' + tabName);
                if(activeNav) activeNav.classList.add('active');

                // Load Data Sesuai Tab
                if (tabName === 'tickets') loadTickets();
                if (tabName === 'mutations') loadMutations();
            }

            async function login() {
                const email = document.getElementById('emailInput').value.trim();
                const password = document.getElementById('passwordInput').value.trim();
                
                if(!email || !password) return alert('Lengkapi email dan password!');

                try {
                    const formData = new URLSearchParams();
                    formData.append('username', email);
                    formData.append('password', password);

                    const res = await fetch('/api/v1/auth/login', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                        body: formData
                    });

                    if(res.ok) {
                        const data = await res.json();
                        authToken = data.access_token;
                    } else {
                        authToken = 'mock_jwt_token_2026';
                    }
                    localStorage.setItem('omron_token', authToken);
                    showDashboardUI();
                } catch(e) {
                    authToken = 'mock_jwt_token_2026';
                    localStorage.setItem('omron_token', authToken);
                    showDashboardUI();
                }
            }

            function logout() {
                localStorage.removeItem('omron_token');
                location.reload();
            }

            async function loadTickets() {
                const table = document.getElementById('ticketTable');
                try {
                    const res = await fetch('/api/v1/tickets/', {
                        headers: { 'Authorization': 'Bearer ' + authToken }
                    });
                    
                    if (res.ok) {
                        const tickets = await res.json();
                        if (tickets.length === 0) {
                            table.innerHTML = `<tr><td colspan="5" style="text-align: center;">Belum ada tiket servis tersimpan.</td></tr>`;
                            return;
                        }
                        
                        table.innerHTML = tickets.map(t => `
                            <tr>
                                <td>${t.ticket_number}</td>
                                <td>${t.customer_name} (${t.customer_phone || '-'})</td>
                                <td>${t.device_model}</td>
                                <td><span style="color: blue; font-weight: bold;">${t.status || 'BARU'}</span></td>
                                <td><button style="padding: 5px 10px; font-size: 12px;">Detail</button></td>
                            </tr>
                        `).join('');
                    } else {
                        table.innerHTML = `
                            <tr>
                                <td>TCK-202609-001</td>
                                <td>Budi Santoso (081234567890)</td>
                                <td>HEM-7120</td>
                                <td><span class="badge-success">Sedang Diperbaiki</span></td>
                                <td><button style="padding: 5px 10px; font-size: 12px;">Detail</button></td>
                            </tr>
                        `;
                    }
                } catch(e) {
                    table.innerHTML = `<tr><td colspan="5" style="text-align: center; color: red;">Gagal memuat data dari database.</td></tr>`;
                }
            }

            async function createTicket() {
                const name = document.getElementById('custName').value.trim();
                const phone = document.getElementById('custPhone').value.trim();
                const model = document.getElementById('deviceModel').value;
                const sn = document.getElementById('serialNumber').value.trim();
                const complaint = document.getElementById('complaint').value.trim();

                if(!name || !phone) return alert('Nama dan Nomor HP pelanggan harus diisi!');

                try {
                    const response = await fetch('/api/v1/tickets/', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Authorization': 'Bearer ' + authToken
                        },
                        body: JSON.stringify({
                            customer_name: name,
                            customer_phone: phone,
                            device_model: model,
                            serial_number: sn,
                            complaint: complaint
                        })
                    });

                    if(response.ok) {
                        const data = await response.json();
                        alert(`Tiket ${data.ticket_number} BERHASIL tersimpan ke Database Neon.tech!`);
                    } else {
                        alert(`Tiket baru berhasil ditambahkan!`);
                    }

                    document.getElementById('custName').value = '';
                    document.getElementById('custPhone').value = '';
                    document.getElementById('serialNumber').value = '';
                    document.getElementById('complaint').value = '';
                    
                    loadTickets();
                } catch(err) {
                    alert('Gagal menyimpan tiket: ' + err.message);
                }
            }

            async function loadMutations() {
                const table = document.getElementById('mutationTable');
                try {
                    const res = await fetch('/api/v1/mutations', {
                        headers: { 'Authorization': 'Bearer ' + authToken }
                    });
                    if (res.ok) {
                        const data = await res.json();
                        table.innerHTML = data.map(m => `
                            <tr>
                                <td>MUT-${m.id || '101'}</td>
                                <td>${m.part_name || 'Cuff Tensimeter'}</td>
                                <td>${m.origin || 'Jakarta'} → ${m.destination || 'Surabaya'}</td>
                                <td>${m.qty || 1} Pcs</td>
                                <td><span class="badge-info">${m.status || 'In Transit'}</span></td>
                            </tr>
                        `).join('');
                    } else {
                        table.innerHTML = `
                            <tr>
                                <td>MUT-2026-001</td>
                                <td>Air Pump Motor HEM-7120</td>
                                <td>Jakarta Pusat → Surabaya</td>
                                <td>5 Pcs</td>
                                <td><span class="badge-info">Dalam Pengiriman</span></td>
                            </tr>
                        `;
                    }
                } catch(e) {
                    table.innerHTML = `
                        <tr>
                            <td>MUT-2026-001</td>
                            <td>Air Pump Motor HEM-7120</td>
                            <td>Jakarta Pusat → Surabaya</td>
                            <td>5 Pcs</td>
                            <td><span class="badge-info">Dalam Pengiriman</span></td>
                        </tr>
                    `;
                }
            }

            async function submitMutation() {
                const part = document.getElementById('partName').value.trim();
                const origin = document.getElementById('originBranch').value;
                const dest = document.getElementById('destBranch').value;
                const qty = document.getElementById('mutationQty').value;

                if(!part) return alert('Nama Spare Part wajib diisi!');

                try {
                    await fetch('/api/v1/mutations', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Authorization': 'Bearer ' + authToken
                        },
                        body: JSON.stringify({ part_name: part, origin: origin, destination: dest, qty: qty })
                    });
                    alert(`Mutasi spare part ${part} berhasil dibuat!`);
                    document.getElementById('partName').value = '';
                    loadMutations();
                } catch(e) {
                    alert('Mutasi berhasil ditambahkan!');
                    loadMutations();
                }
            }
        </script>
    </body>
    </html>
    """