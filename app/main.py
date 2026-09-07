from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, StreamingResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v1 import mutations, services_api, auth as auth_api
from app.db.session import get_db, init_db
from app.core.deps import get_current_user, require_department_access
from app.models.schema import ServiceTicket, User
from app.services.excel_export import generate_service_report_excel

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="CRM Omron Healthcare API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.on_event("startup")
def _on_startup():
    # Aman dipanggil berkali-kali: hanya membuat tabel yang belum ada,
    # TIDAK PERNAH menghapus/mengubah tabel atau data yang sudah ada.
    init_db()


app.include_router(auth_api.router)
app.include_router(auth_api.admin_users_router)
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

    # Verifikasi disederhanakan & diperketat: bandingkan 8 digit terakhir SAJA
    # (bukan lagi substring bebas), supaya nomor pendek tidak salah cocok
    # dengan potongan nomor lain.
    if not db_phone or not input_phone or len(input_phone) < 8 or db_phone[-8:] != input_phone[-8:]:
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
def download_excel_report(
    service_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    DIPERBAIKI: sebelumnya endpoint ini SELALU mengembalikan 1 baris data mock
    yang di-hardcode, tidak peduli tombol "Download Excel" yang mana yang
    diklik. Sekarang laporan diambil dari data ASLI di database, dan wajib
    login (tidak lagi publik), serta staff hanya bisa unduh data
    departemennya sendiri.
    """
    query = db.query(ServiceTicket)

    if service_type:
        srv = service_type.lower().strip()
        require_department_access(current_user, srv)
        query = query.filter(func.lower(ServiceTicket.service_type) == srv)
    elif current_user.role != "superadmin":
        query = query.filter(func.lower(ServiceTicket.service_type) == current_user.department)

    tickets = query.order_by(ServiceTicket.id).all()

    rows = [
        {
            "ticket_number": t.ticket_number,
            "created_at": t.created_at.strftime("%Y-%m-%d") if t.created_at else "-",
            "customer_name": t.customer_name,
            "customer_phone": t.customer_phone,
            "device_model": t.device_model,
            "serial_number": t.serial_number or "-",
            "status": t.status or "Diproses",
            "technician": t.technician_analysis or "-",
        }
        for t in tickets
    ]

    excel_file = generate_service_report_excel(rows)
    label = service_type or (current_user.department if current_user.role != "superadmin" else "semua")
    filename = f"Laporan_Servis_Omron_{label}_{datetime.utcnow().strftime('%Y%m%d')}.xlsx"
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
            aside .single-menu.hidden-menu { display: none; }

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
            .login-box { max-width: 400px; margin: 60px auto; }
            .badge { padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 11px; }
            .badge-lunas { background: #d4edda; color: #155724; }
            .badge-pending { background: #fff3cd; color: #856404; }
            .badge-active { background: #d4edda; color: #155724; }
            .badge-inactive { background: #f8d7da; color: #721c24; }
            .required { color: red; }
            .auth-tabs { display: flex; margin-bottom: 15px; border-bottom: 1px solid #ddd; }
            .auth-tabs div { flex: 1; text-align: center; padding: 10px; cursor: pointer; font-weight: bold; color: #888; font-size: 13px; }
            .auth-tabs div.active { color: #0056b3; border-bottom: 3px solid #0056b3; }
            .auth-error { color: #721c24; background: #f8d7da; border: 1px solid #f5c6cb; padding: 8px; border-radius: 5px; font-size: 12px; margin-bottom: 10px; display: none; }
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
                        <li><a href="#" data-loc="pusat" class="active" onclick="showTab('service-pusat')">a. Data di Pusat</a></li>
                        <li><a href="#" data-loc="cabang" onclick="showTab('service-cabang')">b. Data di Cabang</a></li>
                        <li><a href="#" data-loc="pickup" onclick="showTab('service-pickup')">c. Data di Pickup Center</a></li>
                    </ul>
                </li>

                <li>
                    <div class="menu-title" onclick="toggleSubmenu('sub-payment')">3. Status Payment Service <span>▼</span></div>
                    <ul id="sub-payment" class="submenu">
                        <li><a href="#" data-loc="pusat" onclick="showTab('payment-pusat')">a. Payment di Pusat</a></li>
                        <li><a href="#" data-loc="cabang" onclick="showTab('payment-cabang')">b. Payment di Cabang</a></li>
                        <li><a href="#" data-loc="pickup" onclick="showTab('payment-pickup')">c. Payment di Pickup Center</a></li>
                    </ul>
                </li>

                <li id="menu-setting">
                    <div class="menu-title" onclick="toggleSubmenu('sub-setting')">4. Setting (Super Admin) <span>▼</span></div>
                    <ul id="sub-setting" class="submenu">
                        <li><a href="#" onclick="showTab('setting-users')">a. Kelola User</a></li>
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
                <div id="authCard" class="card login-box">
                    <div class="auth-tabs">
                        <div id="tabLoginBtn" class="active" onclick="switchAuthTab('login')">Login</div>
                        <div id="tabBootstrapBtn" onclick="switchAuthTab('bootstrap')">Setup Awal</div>
                    </div>

                    <div id="authError" class="auth-error"></div>

                    <div id="loginPane">
                        <div class="form-group">
                            <label>Email</label>
                            <input type="email" id="loginEmail" placeholder="nama@omron.co.id">
                        </div>
                        <div class="form-group">
                            <label>Password</label>
                            <input type="password" id="loginPassword">
                        </div>
                        <button class="btn" style="width: 100%;" onclick="login()">Masuk ke Sistem</button>
                    </div>

                    <div id="bootstrapPane" class="hidden">
                        <p style="font-size:12px; color:#666;">Form ini hanya bisa dipakai SATU KALI, saat sistem belum punya akun sama sekali, untuk membuat akun Super Admin pertama.</p>
                        <div class="form-group">
                            <label>Nama Lengkap</label>
                            <input type="text" id="bsName">
                        </div>
                        <div class="form-group">
                            <label>Email</label>
                            <input type="email" id="bsEmail">
                        </div>
                        <div class="form-group">
                            <label>Password (min. 8 karakter)</label>
                            <input type="password" id="bsPassword">
                        </div>
                        <button class="btn btn-success" style="width: 100%;" onclick="bootstrapSuperadmin()">Buat Akun Super Admin</button>
                    </div>
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

                <!-- 2a/b/c DATA SERVICE (dibuat dari 1 template JS, id tetap unik per lokasi) -->
                <div id="tab-service-pusat" class="tab-content hidden"></div>
                <div id="tab-service-cabang" class="tab-content hidden"></div>
                <div id="tab-service-pickup" class="tab-content hidden"></div>

                <!-- 3. STATUS PAYMENT SERVICE -->
                <div id="tab-payment-pusat" class="tab-content hidden">
                    <div class="card">
                        <h2>3a. Status Payment Service - Pusat (Out of Warranty)</h2>
                        <table>
                            <thead>
                                <tr><th>No. Tiket</th><th>Pemilik</th><th>Model Alat</th><th>Total Biaya</th><th>Kode Payment</th><th>Status Bayar</th></tr>
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
                                <tr><th>No. Tiket</th><th>Pemilik</th><th>Model Alat</th><th>Total Biaya</th><th>Kode Payment</th><th>Status Bayar</th></tr>
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
                                <tr><th>No. Tiket</th><th>Pemilik</th><th>Model Alat</th><th>Total Biaya</th><th>Kode Payment</th><th>Status Bayar</th></tr>
                            </thead>
                            <tbody id="tablePaymentPickup"></tbody>
                        </table>
                    </div>
                </div>

                <!-- 4. KELOLA USER (Super Admin) -->
                <div id="tab-setting-users" class="tab-content hidden">
                    <div class="card">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <h2 style="border:none; margin:0;">Kelola User per Departemen</h2>
                            <button class="btn btn-success" onclick="toggleUserForm()">+ Tambah User</button>
                        </div>

                        <div id="userFormBox" class="sparepart-box hidden" style="margin-top:12px; border:1px dashed #ccc; padding:10px; border-radius:6px;">
                            <div class="form-grid">
                                <div class="form-group"><label>Nama Lengkap</label><input id="nuName"></div>
                                <div class="form-group"><label>Email</label><input id="nuEmail" type="email"></div>
                                <div class="form-group"><label>Password</label><input id="nuPassword" type="password"></div>
                                <div class="form-group">
                                    <label>Role</label>
                                    <select id="nuRole" onchange="onRoleChange()">
                                        <option value="staff">Staff (dibatasi 1 departemen)</option>
                                        <option value="superadmin">Super Admin (akses semua)</option>
                                    </select>
                                </div>
                                <div class="form-group" id="nuDeptWrap">
                                    <label>Departemen</label>
                                    <select id="nuDept">
                                        <option value="pusat">Pusat</option>
                                        <option value="cabang">Cabang</option>
                                        <option value="pickup">Pickup Center</option>
                                    </select>
                                </div>
                            </div>
                            <button class="btn btn-success" onclick="createUser()">Simpan User</button>
                        </div>

                        <table style="margin-top:15px;">
                            <thead><tr><th>Nama</th><th>Email</th><th>Role</th><th>Departemen</th><th>Status</th><th>Aksi</th></tr></thead>
                            <tbody id="tableUsers"></tbody>
                        </table>
                    </div>
                </div>

            </div>
        </main>

        <script>
            let authToken = localStorage.getItem('omron_token') || '';
            let currentRole = localStorage.getItem('omron_role') || '';
            let currentDept = localStorage.getItem('omron_dept') || '';

            const LOCATIONS = [
                { key: 'pusat',  label: 'Pusat',          prefix: 'JKT' },
                { key: 'cabang', label: 'Cabang',         prefix: 'CBG' },
                { key: 'pickup', label: 'Pickup Center',  prefix: 'PKP' },
            ];

            window.onload = async function() {
                buildServiceTabsHTML();
                if (authToken) {
                    await enterDashboard();
                } else {
                    await checkBootstrapStatus();
                }
            };

            // ---------- AUTH ----------

            async function checkBootstrapStatus() {
                try {
                    const res = await fetch('/api/v1/auth/bootstrap-status');
                    const data = await res.json();
                    if (data.needs_bootstrap) switchAuthTab('bootstrap');
                } catch(e) {}
            }

            function switchAuthTab(which) {
                document.getElementById('authError').style.display = 'none';
                document.getElementById('tabLoginBtn').classList.toggle('active', which === 'login');
                document.getElementById('tabBootstrapBtn').classList.toggle('active', which === 'bootstrap');
                document.getElementById('loginPane').classList.toggle('hidden', which !== 'login');
                document.getElementById('bootstrapPane').classList.toggle('hidden', which !== 'bootstrap');
            }

            function showAuthError(msg) {
                const box = document.getElementById('authError');
                box.textContent = msg;
                box.style.display = 'block';
            }

            async function authFetch(url, options = {}) {
                options.headers = Object.assign({}, options.headers, {
                    'Authorization': 'Bearer ' + authToken,
                });
                const res = await fetch(url, options);
                if (res.status === 401) {
                    logout();
                    throw new Error('Sesi berakhir, silakan login kembali.');
                }
                return res;
            }

            async function bootstrapSuperadmin() {
                const full_name = document.getElementById('bsName').value.trim();
                const email = document.getElementById('bsEmail').value.trim();
                const password = document.getElementById('bsPassword').value;
                if (!full_name || !email || !password) return showAuthError('Semua field wajib diisi.');

                try {
                    const res = await fetch('/api/v1/auth/bootstrap', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ full_name, email, password })
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Gagal membuat Super Admin.');
                    alert('Akun Super Admin berhasil dibuat! Silakan login.');
                    switchAuthTab('login');
                    document.getElementById('loginEmail').value = email;
                } catch(e) {
                    showAuthError(e.message);
                }
            }

            async function login() {
                const email = document.getElementById('loginEmail').value.trim();
                const password = document.getElementById('loginPassword').value;
                if (!email || !password) return showAuthError('Email dan password wajib diisi.');

                try {
                    const res = await fetch('/api/v1/auth/login', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ email, password })
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Login gagal.');

                    authToken = data.access_token;
                    currentRole = data.role;
                    currentDept = data.department || '';
                    localStorage.setItem('omron_token', authToken);
                    localStorage.setItem('omron_role', currentRole);
                    localStorage.setItem('omron_dept', currentDept);

                    await enterDashboard();
                } catch(e) {
                    showAuthError(e.message);
                }
            }

            function logout() {
                localStorage.removeItem('omron_token');
                localStorage.removeItem('omron_role');
                localStorage.removeItem('omron_dept');
                location.reload();
            }

            async function enterDashboard() {
                document.getElementById('authCard').classList.add('hidden');
                document.getElementById('sidebar').classList.remove('hidden');
                document.getElementById('btnLogout').classList.remove('hidden');
                document.getElementById('userStatus').innerText =
                    currentRole === 'superadmin' ? 'Super Admin' : `Staff - ${currentDept}`;

                // Staff (non-superadmin) hanya melihat menu sesuai departemennya,
                // dan tidak melihat menu "Setting (Super Admin)" sama sekali.
                document.getElementById('menu-setting').style.display = (currentRole === 'superadmin') ? '' : 'none';
                document.querySelectorAll('[data-loc]').forEach(el => {
                    const loc = el.getAttribute('data-loc');
                    if (currentRole !== 'superadmin' && loc !== currentDept) {
                        el.parentElement.style.display = 'none';
                    }
                });

                const startTab = (currentRole === 'superadmin') ? 'dashboard' : `service-${currentDept}`;
                showTab(startTab);
            }

            function toggleSubmenu(id) {
                document.getElementById(id).classList.toggle('open');
            }

            // ---------- BANGUN TAB DATA SERVICE DARI 1 TEMPLATE (fix bug duplikat id form) ----------

            function buildServiceTabsHTML() {
                LOCATIONS.forEach(loc => {
                    const root = document.getElementById(`tab-service-${loc.key}`);
                    root.innerHTML = `
                        <div id="view-table-service-${loc.key}" class="card">
                            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
                                <h2 style="margin:0; border:none;">Data Service - ${loc.label}</h2>
                                <div class="action-header">
                                    <input type="text" id="search-service-${loc.key}" class="search-input" placeholder="Cari tiket / nama / SN...">
                                    <button class="btn btn-secondary" onclick="downloadExcel('${loc.key}')">📊 Download Excel</button>
                                    <button class="btn btn-success" onclick="showFormInPage('${loc.key}')">+ Input Tiket ${loc.label.toUpperCase()}</button>
                                </div>
                            </div>
                            <table>
                                <thead>
                                    <tr><th>No. Tiket</th><th>Pemilik</th><th>No. HP/WA</th><th>Model Alat</th><th>Serial No.</th><th>Garansi</th><th>Keluhan</th><th>Status</th><th>Tgl Diterima</th></tr>
                                </thead>
                                <tbody id="tableService-${loc.key}"></tbody>
                            </table>
                        </div>

                        <div id="view-form-service-${loc.key}" class="card hidden">
                            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px; border-bottom:2px solid #0056b3; padding-bottom:10px;">
                                <h2 style="margin:0; border:none;">Form Input Tiket Servis - ${loc.label} (${loc.prefix})</h2>
                                <button class="btn btn-secondary" onclick="hideFormInPage('${loc.key}')">← Kembali ke Tabel</button>
                            </div>
                            <div style="background:#e3f2fd; padding:10px; border-radius:5px; font-size:12px; margin-bottom:15px; color:#0d47a1;">
                                ℹ️ Tiket ini akan terdaftar KHUSUS di data <strong>${loc.label}</strong> saja - tidak akan tampil atau tercatat di lokasi lain.
                            </div>
                            <div class="form-section-title">1. Data Pelanggan</div>
                            <div class="form-grid">
                                <div class="form-group"><label>Nama Pemilik <span class="required">*</span></label><input id="inpName-${loc.key}" placeholder="Contoh: Budi Santoso"></div>
                                <div class="form-group"><label>No. HP / WhatsApp <span class="required">*</span></label><input id="inpPhone-${loc.key}" placeholder="081234567890"></div>
                            </div>
                            <div class="form-section-title">2. Data Produk</div>
                            <div class="form-grid">
                                <div class="form-group"><label>Model Alat</label><input id="inpModel-${loc.key}" value="HEM-7120"></div>
                                <div class="form-group"><label>Serial No. Alat</label><input id="inpSN-${loc.key}" placeholder="SN2026xxxx"></div>
                                <div class="form-group"><label>Keluhan</label><input id="inpKeluhan-${loc.key}" placeholder="Keluhan perangkat"></div>
                            </div>
                            <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:20px;">
                                <button class="btn btn-secondary" onclick="hideFormInPage('${loc.key}')">Batal</button>
                                <button class="btn btn-success" onclick="savePageFormData('${loc.key}')">Simpan ke Data ${loc.label.toUpperCase()}</button>
                            </div>
                        </div>
                    `;
                    document.getElementById(`search-service-${loc.key}`).addEventListener('keyup', () => filterTable(loc.key));
                });
            }

            function showTab(tabId) {
                document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
                const target = document.getElementById('tab-' + tabId);
                if (target) target.classList.remove('hidden');
                document.getElementById('pageTitle').innerText = 'Menu: ' + tabId.toUpperCase().replace(/-/g, ' ');

                if (tabId.startsWith('service-')) hideFormInPage(tabId.replace('service-', ''));
                if (tabId === 'setting-users') { renderUsers(); return; }

                renderTableData(tabId);
                updateDashboardStats();
            }

            async function updateDashboardStats() {
                try {
                    const res = await authFetch('/api/v1/db/all-tickets');
                    if (res.ok) {
                        const data = await res.json();
                        document.getElementById('statPusat').innerText = data.filter(d => (d.service_type || '').toLowerCase() === 'pusat').length;
                        document.getElementById('statCabang').innerText = data.filter(d => (d.service_type || '').toLowerCase() === 'cabang').length;
                        document.getElementById('statPickup').innerText = data.filter(d => (d.service_type || '').toLowerCase() === 'pickup').length;
                    }
                } catch(e) {}
            }

            async function renderTableData(menu) {
                let endpoint = '/api/v1/db/all-tickets';
                if (menu.startsWith('service-') || menu.startsWith('payment-')) {
                    const srvType = menu.replace('service-', '').replace('payment-', '');
                    endpoint = '/api/v1/db/tickets/' + srvType;
                }
                try {
                    const res = await authFetch(endpoint);
                    if (res.ok) {
                        const data = await res.json();
                        if (menu.startsWith('payment-')) populatePaymentRows(menu, data);
                        else if (menu.startsWith('service-')) populateTableRows(menu.replace('service-', ''), data);
                    }
                } catch(e) { console.error('Error fetching database:', e); }
            }

            function populateTableRows(locKey, data) {
                const el = document.getElementById(`tableService-${locKey}`);
                if (!el) return;
                el.innerHTML = data.length ? data.map(d => `
                    <tr>
                        <td><strong>${d.ticket_number}</strong></td>
                        <td>${d.customer_name}</td>
                        <td>${d.customer_phone || '-'}</td>
                        <td>${d.device_model}</td>
                        <td>${d.serial_number || '-'}</td>
                        <td>${d.warranty_status || 'Out of Warranty'}</td>
                        <td>${d.complaint || '-'}</td>
                        <td><span class="badge badge-lunas">${d.status || 'Diproses'}</span></td>
                        <td>${d.created_at ? d.created_at.split('T')[0] : '-'}</td>
                    </tr>
                `).join('') : `<tr><td colspan="9" style="text-align:center;">Belum ada data di lokasi ini</td></tr>`;
            }

            function populatePaymentRows(menu, data) {
                const filtered = data.filter(d => !d.warranty_status || d.warranty_status === 'Out of Warranty');
                const targetEl = menu === 'payment-pusat' ? 'tablePaymentPusat' : (menu === 'payment-cabang' ? 'tablePaymentCabang' : 'tablePaymentPickup');
                const el = document.getElementById(targetEl);
                if (!el) return;
                el.innerHTML = filtered.length ? filtered.map(d => `
                    <tr>
                        <td><strong>${d.ticket_number}</strong></td>
                        <td>${d.customer_name}</td>
                        <td>${d.device_model}</td>
                        <td>Rp ${(d.total_price || 0).toLocaleString('id-ID')}</td>
                        <td><code>${d.payment_code || '-'}</code></td>
                        <td><span class="badge ${d.payment_status === 'Lunas' ? 'badge-lunas' : 'badge-pending'}">${d.payment_status || 'Belum Lunas'}</span></td>
                    </tr>
                `).join('') : `<tr><td colspan="6" style="text-align:center;">Tidak ada tiket Out of Warranty untuk pembayaran di lokasi ini.</td></tr>`;
            }

            function filterTable(locKey) {
                const q = document.getElementById(`search-service-${locKey}`).value.toLowerCase();
                document.querySelectorAll(`#tableService-${locKey} tr`).forEach(row => {
                    row.style.display = row.innerText.toLowerCase().includes(q) ? '' : 'none';
                });
            }

            function showFormInPage(locKey) {
                document.getElementById('view-table-service-' + locKey).classList.add('hidden');
                document.getElementById('view-form-service-' + locKey).classList.remove('hidden');
            }

            function hideFormInPage(locKey) {
                const formView = document.getElementById('view-form-service-' + locKey);
                if (formView) formView.classList.add('hidden');
                const tableView = document.getElementById('view-table-service-' + locKey);
                if (tableView) tableView.classList.remove('hidden');
            }

            async function savePageFormData(locKey) {
                // Setiap input punya id unik per-lokasi (mis. inpName-pusat, inpName-cabang),
                // jadi TIDAK ADA LAGI risiko membaca data sisa dari form lokasi lain
                // yang sebelumnya pernah dibuka (bug id duplikat pada versi lama).
                const name = document.getElementById(`inpName-${locKey}`).value.trim();
                const phone = document.getElementById(`inpPhone-${locKey}`).value.trim();

                if (!name || !phone) return alert('Nama Pemilik dan No. HP/WhatsApp Wajib Diisi!');

                const payload = {
                    service_type: locKey,
                    customer_name: name,
                    customer_phone: phone,
                    device_model: document.getElementById(`inpModel-${locKey}`).value.trim() || 'HEM-7120',
                    serial_number: document.getElementById(`inpSN-${locKey}`).value.trim() || '-',
                    complaint: document.getElementById(`inpKeluhan-${locKey}`).value.trim() || '-'
                };

                try {
                    const res = await authFetch('/api/v1/db/tickets/', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                    const resData = await res.json();

                    if (res.ok) {
                        alert(`BERHASIL! Tiket ${resData.ticket_number} berhasil masuk khusus ke Data ${locKey.toUpperCase()}!`);
                        hideFormInPage(locKey);
                        renderTableData('service-' + locKey);
                        updateDashboardStats();
                    } else {
                        alert(resData.detail || 'Gagal menyimpan tiket.');
                    }
                } catch(e) {
                    alert('Error koneksi: ' + e.message);
                }
            }

            async function downloadExcel(locKey) {
                try {
                    const res = await authFetch(`/api/v1/admin/reports/excel?service_type=${locKey}`);
                    if (!res.ok) {
                        const err = await res.json().catch(() => ({}));
                        throw new Error(err.detail || 'Gagal mengunduh laporan.');
                    }
                    const blob = await res.blob();
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `Laporan_Servis_Omron_${locKey}.xlsx`;
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    window.URL.revokeObjectURL(url);
                } catch(e) {
                    alert(e.message);
                }
            }

            // ---------- KELOLA USER (Super Admin) ----------

            function onRoleChange() {
                const isStaff = document.getElementById('nuRole').value === 'staff';
                document.getElementById('nuDeptWrap').style.display = isStaff ? '' : 'none';
            }

            function toggleUserForm() {
                document.getElementById('userFormBox').classList.toggle('hidden');
            }

            async function renderUsers() {
                try {
                    const res = await authFetch('/api/v1/admin/users/');
                    if (!res.ok) return;
                    const users = await res.json();
                    const el = document.getElementById('tableUsers');
                    el.innerHTML = users.map(u => `
                        <tr>
                            <td>${u.full_name}</td>
                            <td>${u.email}</td>
                            <td>${u.role}</td>
                            <td>${u.department || '-'}</td>
                            <td><span class="badge ${u.is_active ? 'badge-active' : 'badge-inactive'}">${u.is_active ? 'Aktif' : 'Nonaktif'}</span></td>
                            <td>
                                ${u.is_active
                                    ? `<button class="btn btn-danger" onclick="setUserActive(${u.id}, false)">Nonaktifkan</button>`
                                    : `<button class="btn btn-success" onclick="setUserActive(${u.id}, true)">Aktifkan</button>`}
                            </td>
                        </tr>
                    `).join('');
                } catch(e) { console.error(e); }
            }

            async function createUser() {
                const payload = {
                    full_name: document.getElementById('nuName').value.trim(),
                    email: document.getElementById('nuEmail').value.trim(),
                    password: document.getElementById('nuPassword').value,
                    role: document.getElementById('nuRole').value,
                    department: document.getElementById('nuRole').value === 'staff' ? document.getElementById('nuDept').value : null,
                };
                if (!payload.full_name || !payload.email || !payload.password) return alert('Semua field wajib diisi.');

                try {
                    const res = await authFetch('/api/v1/admin/users/', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Gagal membuat user.');
                    alert('User berhasil dibuat!');
                    document.getElementById('userFormBox').classList.add('hidden');
                    renderUsers();
                } catch(e) {
                    alert(e.message);
                }
            }

            async function setUserActive(userId, active) {
                const endpoint = `/api/v1/admin/users/${userId}/${active ? 'reactivate' : 'deactivate'}`;
                try {
                    const res = await authFetch(endpoint, { method: 'PATCH' });
                    if (!res.ok) {
                        const data = await res.json();
                        throw new Error(data.detail || 'Gagal mengubah status user.');
                    }
                    renderUsers();
                } catch(e) {
                    alert(e.message);
                }
            }
        </script>
    </body>
    </html>
    """
