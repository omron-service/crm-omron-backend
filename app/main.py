from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, StreamingResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v1 import mutations, services_api, auth as auth_api, inventory_parts
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
app.include_router(services_api.catalog_router)
app.include_router(inventory_parts.router)


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

                <li>
                    <div class="menu-title" onclick="toggleSubmenu('sub-inventory')">4. Inventory Part <span>▼</span></div>
                    <ul id="sub-inventory" class="submenu">
                        <li><a href="#" data-loc="pusat" onclick="showTab('inventory-pusat')">a. Stok Sparepart di Pusat</a></li>
                        <li><a href="#" data-loc="cabang" onclick="showTab('inventory-cabang')">b. Stok Sparepart di Cabang</a></li>
                    </ul>
                </li>

                <li id="menu-setting">
                    <div class="menu-title" onclick="toggleSubmenu('sub-setting')">5. Setting (Super Admin) <span>▼</span></div>
                    <ul id="sub-setting" class="submenu">
                        <li><a href="#" onclick="showTab('setting-users')">a. Kelola User</a></li>
                        <li><a href="#" onclick="showTab('setting-devicemodels')">b. Kelola Model Alat</a></li>
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

                <!-- 4. INVENTORY PART (dibangun dari 1 template JS, lihat buildInventoryTabsHTML) -->
                <div id="tab-inventory-pusat" class="tab-content hidden"></div>
                <div id="tab-inventory-cabang" class="tab-content hidden"></div>

                <!-- 5. KELOLA USER (Super Admin) -->
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

                <!-- 4b. KELOLA MODEL ALAT (Super Admin) -->
                <div id="tab-setting-devicemodels" class="tab-content hidden">
                    <div class="card">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <h2 style="border:none; margin:0;">Kelola Model Alat per Kategori</h2>
                            <button class="btn btn-success" onclick="toggleDeviceModelForm()">+ Tambah Model</button>
                        </div>
                        <p style="font-size:12px; color:#666;">Model yang ditambahkan di sini akan otomatis muncul di dropdown "Model Alat" pada form input tiket, sesuai Kategori Produk yang dipilih.</p>

                        <div id="deviceModelFormBox" class="hidden" style="margin-top:12px; border:1px dashed #ccc; padding:10px; border-radius:6px;">
                            <div class="form-grid">
                                <div class="form-group">
                                    <label>Kategori Produk</label>
                                    <select id="dmCategory">
                                        <option value="Arm BPM">Arm BPM</option>
                                        <option value="Wrist BPM">Wrist BPM</option>
                                        <option value="BGM">BGM</option>
                                        <option value="BCM">BCM</option>
                                        <option value="DWS">DWS</option>
                                        <option value="NEB-Comp">NEB-Comp</option>
                                        <option value="NEB-Mesh">NEB-Mesh</option>
                                        <option value="NEB-Ultra">NEB-Ultra</option>
                                        <option value="Forehead Thermo">Forehead Thermo</option>
                                        <option value="Ear Thermo">Ear Thermo</option>
                                        <option value="Pen Thermo">Pen Thermo</option>
                                        <option value="MEDICAL">MEDICAL</option>
                                        <option value="TENS">TENS</option>
                                        <option value="Others">Others</option>
                                    </select>
                                </div>
                                <div class="form-group"><label>Nama Model</label><input id="dmModelName" placeholder="Contoh: HEM-7120"></div>
                            </div>
                            <button class="btn btn-success" onclick="createDeviceModel()">Simpan Model</button>
                        </div>

                        <table style="margin-top:15px;">
                            <thead><tr><th>Kategori</th><th>Nama Model</th><th>Aksi</th></tr></thead>
                            <tbody id="tableDeviceModels"></tbody>
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
                buildInventoryTabsHTML();
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

            // ---------- DATA REFERENSI (statis, tidak perlu API) ----------

            const PRODUCT_CATEGORIES = ["Arm BPM","Wrist BPM","BGM","BCM","DWS","NEB-Comp","NEB-Mesh","NEB-Ultra","Forehead Thermo","Ear Thermo","Pen Thermo","MEDICAL","TENS","Others"];
            const PRODUCT_ORIGINS = ["LEU","EU-DRC","AMS","IDC","APT/TKO","CV/PT/RS","ALPRO"];
            const WARRANTY_STATUS_OPTIONS = ["Under Warranty","Out of Warranty"];
            const WARRANTY_PERIOD_OPTIONS = ["1","2","3","4","5","6"];
            const REMARKS_OPTIONS = ["Compliance Check/Sensor Check","Repair","Replace Product/Claim","Unrepairable/Return to Customer","Disagree with Service Fee","No Response"];
            const REPAIR_STATUS_OPTIONS = ["Diterima","Diproses","Selesai/Dikirim","Selesai Diambil","Menunggu Sparepart"];
const PROVINCE_CITY_DATA = {"Aceh": ["Banda Aceh", "Langsa", "Lhokseumawe", "Sabang", "Meulaboh", "Aceh Besar", "Aceh Utara", "Aceh Tengah"], "Sumatera Utara": ["Medan", "Binjai", "Pematangsiantar", "Tebing Tinggi", "Sibolga", "Tanjungbalai", "Padang Sidempuan", "Deli Serdang", "Karo"], "Sumatera Barat": ["Padang", "Bukittinggi", "Padang Panjang", "Payakumbuh", "Sawahlunto", "Solok", "Pariaman", "Agam"], "Riau": ["Pekanbaru", "Dumai", "Kampar", "Bengkalis", "Indragiri Hulu", "Indragiri Hilir", "Rokan Hulu", "Rokan Hilir"], "Kepulauan Riau": ["Batam", "Tanjungpinang", "Bintan", "Karimun", "Natuna", "Lingga"], "Jambi": ["Jambi", "Sungai Penuh", "Batanghari", "Bungo", "Kerinci", "Merangin", "Muaro Jambi"], "Sumatera Selatan": ["Palembang", "Lubuklinggau", "Pagar Alam", "Prabumulih", "Ogan Komering Ilir", "Ogan Komering Ulu", "Musi Banyuasin", "Musi Rawas"], "Bangka Belitung": ["Pangkal Pinang", "Bangka", "Bangka Barat", "Bangka Tengah", "Bangka Selatan", "Belitung", "Belitung Timur"], "Bengkulu": ["Bengkulu", "Rejang Lebong", "Bengkulu Utara", "Bengkulu Selatan", "Kepahiang", "Kaur"], "Lampung": ["Bandar Lampung", "Metro", "Lampung Selatan", "Lampung Tengah", "Lampung Utara", "Lampung Timur", "Tulang Bawang", "Pesawaran"], "DKI Jakarta": ["Jakarta Pusat", "Jakarta Utara", "Jakarta Barat", "Jakarta Selatan", "Jakarta Timur", "Kepulauan Seribu"], "Jawa Barat": ["Bandung", "Bekasi", "Bogor", "Depok", "Cimahi", "Sukabumi", "Tasikmalaya", "Cirebon", "Banjar", "Karawang", "Purwakarta", "Subang", "Garut", "Ciamis"], "Banten": ["Serang", "Tangerang", "Tangerang Selatan", "Cilegon", "Pandeglang", "Lebak"], "Jawa Tengah": ["Semarang", "Surakarta", "Salatiga", "Magelang", "Pekalongan", "Tegal", "Purwokerto", "Kudus", "Klaten", "Sukoharjo", "Boyolali", "Sragen", "Cilacap"], "DI Yogyakarta": ["Yogyakarta", "Sleman", "Bantul", "Kulon Progo", "Gunungkidul"], "Jawa Timur": ["Surabaya", "Malang", "Kediri", "Madiun", "Blitar", "Mojokerto", "Pasuruan", "Probolinggo", "Batu", "Sidoarjo", "Gresik", "Jember", "Banyuwangi", "Tuban"], "Bali": ["Denpasar", "Badung", "Gianyar", "Tabanan", "Buleleng", "Karangasem", "Klungkung", "Bangli", "Jembrana"], "Nusa Tenggara Barat": ["Mataram", "Bima", "Lombok Barat", "Lombok Tengah", "Lombok Timur", "Lombok Utara", "Sumbawa", "Dompu"], "Nusa Tenggara Timur": ["Kupang", "Ende", "Maumere", "Manggarai", "Manggarai Barat", "Sumba Timur", "Sumba Barat", "Timor Tengah Selatan"], "Kalimantan Barat": ["Pontianak", "Singkawang", "Sambas", "Kubu Raya", "Ketapang", "Sanggau", "Sintang"], "Kalimantan Tengah": ["Palangka Raya", "Kotawaringin Barat", "Kotawaringin Timur", "Kapuas", "Barito Utara", "Barito Selatan"], "Kalimantan Selatan": ["Banjarmasin", "Banjarbaru", "Banjar", "Barito Kuala", "Tanah Laut", "Hulu Sungai Utara", "Hulu Sungai Selatan"], "Kalimantan Timur": ["Samarinda", "Balikpapan", "Bontang", "Kutai Kartanegara", "Kutai Timur", "Kutai Barat", "Berau", "Paser"], "Kalimantan Utara": ["Tarakan", "Bulungan", "Malinau", "Nunukan", "Tana Tidung"], "Sulawesi Utara": ["Manado", "Bitung", "Tomohon", "Kotamobagu", "Minahasa", "Minahasa Utara", "Minahasa Selatan"], "Gorontalo": ["Gorontalo", "Boalemo", "Bone Bolango", "Gorontalo Utara", "Pohuwato"], "Sulawesi Tengah": ["Palu", "Poso", "Banggai", "Donggala", "Toli-Toli", "Parigi Moutong", "Morowali"], "Sulawesi Barat": ["Mamuju", "Majene", "Polewali Mandar", "Mamasa", "Pasangkayu"], "Sulawesi Selatan": ["Makassar", "Parepare", "Palopo", "Gowa", "Maros", "Bone", "Bulukumba", "Pinrang", "Wajo", "Sidenreng Rappang"], "Sulawesi Tenggara": ["Kendari", "Baubau", "Kolaka", "Konawe", "Muna", "Bombana", "Wakatobi"], "Maluku": ["Ambon", "Tual", "Maluku Tengah", "Maluku Tenggara", "Buru", "Seram Bagian Barat"], "Maluku Utara": ["Ternate", "Tidore Kepulauan", "Halmahera Barat", "Halmahera Utara", "Halmahera Tengah", "Halmahera Selatan"], "Papua": ["Jayapura", "Keerom", "Sarmi", "Biak Numfor", "Jayawijaya", "Nabire", "Mimika", "Merauke"], "Papua Barat": ["Manokwari", "Sorong", "Fakfak", "Kaimana", "Teluk Bintuni", "Teluk Wondama", "Raja Ampat"], "Papua Barat Daya": ["Sorong", "Sorong Selatan", "Tambrauw", "Maybrat", "Raja Ampat"], "Papua Tengah": ["Nabire", "Paniai", "Mimika", "Puncak", "Puncak Jaya", "Dogiyai", "Deiyai"], "Papua Pegunungan": ["Jayawijaya", "Pegunungan Bintang", "Yahukimo", "Tolikara", "Yalimo", "Lanny Jaya", "Nduga"], "Papua Selatan": ["Merauke", "Boven Digoel", "Mappi", "Asmat"]};

            function opts(list, selected) {
                return list.map(v => `<option value="${v}" ${v === selected ? 'selected' : ''}>${v}</option>`).join('');
            }

            // ---------- BANGUN TAB DATA SERVICE DARI 1 TEMPLATE (fix bug duplikat id form) ----------

            function buildServiceTabsHTML() {
                LOCATIONS.forEach(loc => {
                    const k = loc.key;
                    const root = document.getElementById(`tab-service-${k}`);
                    root.innerHTML = `
                        <div id="view-table-service-${k}" class="card">
                            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
                                <h2 style="margin:0; border:none;">Data Service - ${loc.label}</h2>
                                <div class="action-header">
                                    <input type="text" id="search-service-${k}" class="search-input" placeholder="Cari tiket / nama / SN...">
                                    <button class="btn btn-secondary" onclick="downloadExcel('${k}')">📊 Download Excel</button>
                                    <button class="btn btn-success" onclick="showFormInPage('${k}')">+ Input Tiket ${loc.label.toUpperCase()}</button>
                                </div>
                            </div>
                            <table>
                                <thead>
                                    <tr><th>No. Tiket</th><th>Pemilik</th><th>Instansi</th><th>No. HP/WA</th><th>Model Alat</th><th>Serial No.</th><th>Garansi</th><th>Keluhan</th><th>Status</th><th>Tgl Diterima</th></tr>
                                </thead>
                                <tbody id="tableService-${k}"></tbody>
                            </table>
                        </div>

                        <div id="view-form-service-${k}" class="card hidden">
                            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px; border-bottom:2px solid #0056b3; padding-bottom:10px;">
                                <h2 style="margin:0; border:none;">Form Input Tiket Servis - ${loc.label} (${loc.prefix})</h2>
                                <button class="btn btn-secondary" onclick="hideFormInPage('${k}')">← Kembali ke Tabel</button>
                            </div>
                            <div style="background:#e3f2fd; padding:10px; border-radius:5px; font-size:12px; margin-bottom:15px; color:#0d47a1;">
                                ℹ️ Tiket ini akan terdaftar KHUSUS di data <strong>${loc.label}</strong> saja - tidak akan tampil atau tercatat di lokasi lain.
                            </div>

                            <div class="form-section-title">1. Data Pelanggan</div>
                            <div class="form-grid">
                                <div class="form-group"><label>Nama Customer <span class="required">*</span></label><input id="inpName-${k}" placeholder="Contoh: Budi Santoso"></div>
                                <div class="form-group"><label>Nama Instansi</label><input id="inpInstansi-${k}" placeholder="Contoh: RS Harapan Bunda"></div>
                                <div class="form-group"><label>No. HP / WhatsApp 1 <span class="required">*</span></label><input id="inpPhone1-${k}" placeholder="081234567890"></div>
                                <div class="form-group"><label>No. HP / WhatsApp 2</label><input id="inpPhone2-${k}" placeholder="(opsional)"></div>
                                <div class="form-group" style="grid-column: 1 / -1;"><label>Alamat</label><input id="inpAddress-${k}" placeholder="Alamat lengkap"></div>
                                <div class="form-group">
                                    <label>Provinsi</label>
                                    <select id="inpProvince-${k}" onchange="onProvinceChange('${k}')">
                                        <option value="">-- Pilih Provinsi --</option>
                                        ${Object.keys(PROVINCE_CITY_DATA).map(p => `<option value="${p}">${p}</option>`).join('')}
                                    </select>
                                </div>
                                <div class="form-group">
                                    <label>Kota</label>
                                    <select id="inpCity-${k}"><option value="">-- Pilih Provinsi dulu --</option></select>
                                </div>
                                <div class="form-group"><label>Tanggal Alat Diterima</label><input type="date" id="inpReceivedDate-${k}"></div>
                                <div class="form-group"><label>Tanggal Alat Selesai</label><input type="date" id="inpCompletedDate-${k}"></div>
                            </div>

                            <div class="form-section-title">2. Data Produk</div>
                            <div class="form-grid">
                                <div class="form-group">
                                    <label>Produk Kategori</label>
                                    <select id="inpCategory-${k}" onchange="onCategoryChange('${k}')">
                                        <option value="">-- Pilih Kategori --</option>
                                        ${opts(PRODUCT_CATEGORIES)}
                                    </select>
                                </div>
                                <div class="form-group">
                                    <label>Model Alat</label>
                                    <select id="inpModel-${k}"><option value="">-- Pilih Kategori dulu --</option></select>
                                </div>
                                <div class="form-group"><label>Serial No. Alat</label><input id="inpSN-${k}" placeholder="SN2026xxxx"></div>
                                <div class="form-group"><label>Aksesoris</label><input id="inpAccessories-${k}" placeholder="Contoh: Kabel, Adaptor"></div>
                                <div class="form-group">
                                    <label>Status Garansi</label>
                                    <select id="inpWarrantyStatus-${k}">${opts(WARRANTY_STATUS_OPTIONS, 'Out of Warranty')}</select>
                                </div>
                                <div class="form-group">
                                    <label>Warranty Period (tahun)</label>
                                    <select id="inpWarrantyPeriod-${k}">
                                        <option value="">-- Pilih --</option>
                                        ${opts(WARRANTY_PERIOD_OPTIONS)}
                                    </select>
                                </div>
                                <div class="form-group">
                                    <label>Asal Produk</label>
                                    <select id="inpOrigin-${k}">
                                        <option value="">-- Pilih --</option>
                                        ${opts(PRODUCT_ORIGINS)}
                                    </select>
                                </div>
                            </div>

                            <div class="form-section-title">3. Data Servis</div>
                            <div class="form-grid">
                                <div class="form-group" style="grid-column: 1 / -1;"><label>Keluhan Pelanggan</label><input id="inpKeluhan-${k}" placeholder="Keluhan perangkat"></div>
                                <div class="form-group" style="grid-column: 1 / -1;"><label>Analisa Teknisi</label><input id="inpAnalysis-${k}" placeholder="Hasil analisa teknisi"></div>
                                <div class="form-group"><label>Symptom (Kode)</label><input id="inpSymptom-${k}" placeholder="Contoh: PCB-01"></div>
                                <div class="form-group"><label>Leadtime (hari)</label><input type="number" min="0" id="inpLeadtime-${k}" value="1"></div>
                                <div class="form-group">
                                    <label>Remarks</label>
                                    <select id="inpRemarks-${k}">
                                        <option value="">-- Pilih --</option>
                                        ${opts(REMARKS_OPTIONS)}
                                    </select>
                                </div>
                                <div class="form-group">
                                    <label>Repair Status</label>
                                    <select id="inpStatus-${k}">${opts(REPAIR_STATUS_OPTIONS, 'Diterima')}</select>
                                </div>
                                <div class="form-group" style="grid-column: 1 / -1;"><label>Catatan</label><input id="inpNotes-${k}" placeholder="Catatan tambahan"></div>
                            </div>

                            <div class="form-section-title">4. Sparepart (opsional, maksimal 3)</div>
                            ${[1,2,3].map(n => `
                            <div class="sparepart-box" style="background:#f8f9fa; border:1px dashed #ccc; padding:10px; border-radius:6px; margin-bottom:10px;">
                                <div style="font-weight:bold; font-size:12px; color:#0056b3; margin-bottom:8px;">Sparepart ${n}</div>
                                <div class="form-grid">
                                    <div class="form-group"><label>Nama Sparepart</label><input id="inpSpName${n}-${k}" placeholder="Nama sparepart"></div>
                                    <div class="form-group"><label>Jumlah</label><input type="number" min="0" id="inpSpQty${n}-${k}"></div>
                                    <div class="form-group"><label>Kode Sparepart</label><input id="inpSpCode${n}-${k}" placeholder="Kode/part number"></div>
                                    <div class="form-group"><label>Harga (Rp)</label><input type="number" min="0" id="inpSpPrice${n}-${k}"></div>
                                </div>
                            </div>
                            `).join('')}

                            <div class="form-section-title">5. Notifikasi</div>
                            <div class="form-grid">
                                <div class="form-group">
                                    <label>Receipt Service</label>
                                    <label style="font-weight:normal; display:inline-block; margin-right:15px;"><input type="checkbox" id="inpNotifReceiptWA-${k}" style="width:auto;"> via WhatsApp</label>
                                    <label style="font-weight:normal; display:inline-block;"><input type="checkbox" id="inpNotifReceiptEmail-${k}" style="width:auto;"> via Email</label>
                                </div>
                                <div class="form-group">
                                    <label>Service Report</label>
                                    <label style="font-weight:normal; display:inline-block; margin-right:15px;"><input type="checkbox" id="inpNotifReportWA-${k}" style="width:auto;"> via WhatsApp</label>
                                    <label style="font-weight:normal; display:inline-block;"><input type="checkbox" id="inpNotifReportEmail-${k}" style="width:auto;"> via Email</label>
                                </div>
                            </div>

                            <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:20px;">
                                <button class="btn btn-secondary" onclick="hideFormInPage('${k}')">Batal</button>
                                <button class="btn btn-success" onclick="savePageFormData('${k}')">Simpan ke Data ${loc.label.toUpperCase()}</button>
                            </div>
                        </div>
                    `;
                    document.getElementById(`search-service-${k}`).addEventListener('keyup', () => filterTable(k));
                });
            }

            function onProvinceChange(locKey) {
                const province = document.getElementById(`inpProvince-${locKey}`).value;
                const citySelect = document.getElementById(`inpCity-${locKey}`);
                const cities = PROVINCE_CITY_DATA[province] || [];
                citySelect.innerHTML = cities.length
                    ? `<option value="">-- Pilih Kota --</option>` + opts(cities)
                    : `<option value="">-- Pilih Provinsi dulu --</option>`;
            }

            async function onCategoryChange(locKey) {
                const category = document.getElementById(`inpCategory-${locKey}`).value;
                const modelSelect = document.getElementById(`inpModel-${locKey}`);
                if (!category) {
                    modelSelect.innerHTML = `<option value="">-- Pilih Kategori dulu --</option>`;
                    return;
                }
                modelSelect.innerHTML = `<option value="">Memuat...</option>`;
                try {
                    const res = await authFetch(`/api/v1/device-models/?category=${encodeURIComponent(category)}`);
                    const models = res.ok ? await res.json() : [];
                    modelSelect.innerHTML = models.length
                        ? `<option value="">-- Pilih Model --</option>` + models.map(m => `<option value="${m.model_name}">${m.model_name}</option>`).join('')
                        : `<option value="">(Belum ada model utk kategori ini - tambah di Kelola Model Alat)</option>`;
                } catch(e) {
                    modelSelect.innerHTML = `<option value="">Gagal memuat model</option>`;
                }
            }

            function showTab(tabId) {
                document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
                const target = document.getElementById('tab-' + tabId);
                if (target) target.classList.remove('hidden');
                document.getElementById('pageTitle').innerText = 'Menu: ' + tabId.toUpperCase().replace(/-/g, ' ');

                if (tabId.startsWith('service-')) hideFormInPage(tabId.replace('service-', ''));
                if (tabId === 'setting-users') { renderUsers(); return; }
                if (tabId === 'setting-devicemodels') { renderDeviceModels(); return; }
                if (tabId.startsWith('inventory-')) { renderInventoryStock(tabId.replace('inventory-', '')); return; }

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
                        <td>${d.instansi_name || '-'}</td>
                        <td>${d.customer_phone || '-'}</td>
                        <td>${d.device_model}</td>
                        <td>${d.serial_number || '-'}</td>
                        <td>${d.warranty_status || 'Out of Warranty'}</td>
                        <td>${d.complaint || '-'}</td>
                        <td><span class="badge badge-lunas">${d.status || 'Diterima'}</span></td>
                        <td>${d.received_date ? d.received_date.split('T')[0] : (d.created_at ? d.created_at.split('T')[0] : '-')}</td>
                    </tr>
                `).join('') : `<tr><td colspan="10" style="text-align:center;">Belum ada data di lokasi ini</td></tr>`;
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
                resetTicketForm(locKey);
                document.getElementById('view-table-service-' + locKey).classList.add('hidden');
                document.getElementById('view-form-service-' + locKey).classList.remove('hidden');
            }

            function hideFormInPage(locKey) {
                const formView = document.getElementById('view-form-service-' + locKey);
                if (formView) formView.classList.add('hidden');
                const tableView = document.getElementById('view-table-service-' + locKey);
                if (tableView) tableView.classList.remove('hidden');
            }

            function setVal(id, value) {
                const el = document.getElementById(id);
                if (el) el.value = value;
            }

            function resetTicketForm(locKey) {
                // Dipanggil setiap kali form "+ Input Tiket" dibuka, supaya data dari
                // pengisian sebelumnya tidak ikut terbawa (form selalu mulai kosong).
                const k = locKey;

                setVal(`inpName-${k}`, '');
                setVal(`inpInstansi-${k}`, '');
                setVal(`inpPhone1-${k}`, '');
                setVal(`inpPhone2-${k}`, '');
                setVal(`inpAddress-${k}`, '');
                setVal(`inpReceivedDate-${k}`, '');
                setVal(`inpCompletedDate-${k}`, '');

                setVal(`inpProvince-${k}`, '');
                onProvinceChange(k);  // ikut kosongkan & reset dropdown Kota

                setVal(`inpCategory-${k}`, '');
                const modelSelect = document.getElementById(`inpModel-${k}`);
                if (modelSelect) modelSelect.innerHTML = `<option value="">-- Pilih Kategori dulu --</option>`;

                setVal(`inpSN-${k}`, '');
                setVal(`inpAccessories-${k}`, '');
                setVal(`inpWarrantyStatus-${k}`, 'Out of Warranty');
                setVal(`inpWarrantyPeriod-${k}`, '');
                setVal(`inpOrigin-${k}`, '');

                setVal(`inpKeluhan-${k}`, '');
                setVal(`inpAnalysis-${k}`, '');
                setVal(`inpSymptom-${k}`, '');
                setVal(`inpLeadtime-${k}`, '1');
                setVal(`inpRemarks-${k}`, '');
                setVal(`inpStatus-${k}`, 'Diterima');
                setVal(`inpNotes-${k}`, '');

                [1, 2, 3].forEach(n => {
                    setVal(`inpSpName${n}-${k}`, '');
                    setVal(`inpSpQty${n}-${k}`, '');
                    setVal(`inpSpCode${n}-${k}`, '');
                    setVal(`inpSpPrice${n}-${k}`, '');
                });

                ['inpNotifReceiptWA', 'inpNotifReceiptEmail', 'inpNotifReportWA', 'inpNotifReportEmail'].forEach(prefix => {
                    const el = document.getElementById(`${prefix}-${k}`);
                    if (el) el.checked = false;
                });
            }

            function valOf(id) {
                const el = document.getElementById(id);
                return el ? el.value.trim() : '';
            }

            function toIsoOrNull(dateStr) {
                return dateStr ? new Date(dateStr + 'T00:00:00').toISOString() : null;
            }

            async function savePageFormData(locKey) {
                // Setiap input punya id unik per-lokasi (mis. inpName-pusat, inpName-cabang),
                // jadi TIDAK ADA LAGI risiko membaca data sisa dari form lokasi lain
                // yang sebelumnya pernah dibuka (bug id duplikat pada versi lama).
                const k = locKey;
                const name = valOf(`inpName-${k}`);
                const phone1 = valOf(`inpPhone1-${k}`);

                if (!name || !phone1) return alert('Nama Customer dan No. HP/WhatsApp 1 Wajib Diisi!');

                const spareparts = [1, 2, 3].map(n => ({
                    name: valOf(`inpSpName${n}-${k}`) || null,
                    quantity: valOf(`inpSpQty${n}-${k}`) ? parseInt(valOf(`inpSpQty${n}-${k}`)) : null,
                    code: valOf(`inpSpCode${n}-${k}`) || null,
                    price: valOf(`inpSpPrice${n}-${k}`) ? parseFloat(valOf(`inpSpPrice${n}-${k}`)) : null,
                }));

                const payload = {
                    service_type: k,
                    customer_name: name,
                    instansi_name: valOf(`inpInstansi-${k}`) || null,
                    customer_phone: phone1,
                    customer_phone_2: valOf(`inpPhone2-${k}`) || null,
                    customer_address: valOf(`inpAddress-${k}`) || null,
                    province: valOf(`inpProvince-${k}`) || null,
                    city: valOf(`inpCity-${k}`) || null,
                    received_date: toIsoOrNull(valOf(`inpReceivedDate-${k}`)),
                    completed_date: toIsoOrNull(valOf(`inpCompletedDate-${k}`)),
                    product_category: valOf(`inpCategory-${k}`) || null,
                    device_model: valOf(`inpModel-${k}`) || '-',
                    serial_number: valOf(`inpSN-${k}`) || '-',
                    accessories: valOf(`inpAccessories-${k}`) || null,
                    warranty_status: valOf(`inpWarrantyStatus-${k}`) || 'Out of Warranty',
                    warranty_period: valOf(`inpWarrantyPeriod-${k}`) || null,
                    product_origin: valOf(`inpOrigin-${k}`) || null,
                    complaint: valOf(`inpKeluhan-${k}`) || '-',
                    technician_analysis: valOf(`inpAnalysis-${k}`) || null,
                    symptom_code: valOf(`inpSymptom-${k}`) || null,
                    leadtime_days: valOf(`inpLeadtime-${k}`) ? parseInt(valOf(`inpLeadtime-${k}`)) : 1,
                    notes: valOf(`inpNotes-${k}`) || null,
                    remarks: valOf(`inpRemarks-${k}`) || null,
                    status: valOf(`inpStatus-${k}`) || 'Diterima',
                    spareparts: spareparts,
                    notif_receipt_whatsapp: document.getElementById(`inpNotifReceiptWA-${k}`).checked,
                    notif_receipt_email: document.getElementById(`inpNotifReceiptEmail-${k}`).checked,
                    notif_report_whatsapp: document.getElementById(`inpNotifReportWA-${k}`).checked,
                    notif_report_email: document.getElementById(`inpNotifReportEmail-${k}`).checked,
                };

                try {
                    const res = await authFetch('/api/v1/db/tickets/', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                    const resData = await res.json();

                    if (res.ok) {
                        alert(`BERHASIL! Tiket ${resData.ticket_number} berhasil masuk khusus ke Data ${k.toUpperCase()}!`);
                        hideFormInPage(k);
                        renderTableData('service-' + k);
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

            // ---------- KELOLA MODEL ALAT (Super Admin) ----------

            function toggleDeviceModelForm() {
                document.getElementById('deviceModelFormBox').classList.toggle('hidden');
            }

            async function renderDeviceModels() {
                try {
                    const res = await authFetch('/api/v1/device-models/');
                    if (!res.ok) return;
                    const models = await res.json();
                    const el = document.getElementById('tableDeviceModels');
                    el.innerHTML = models.length ? models.map(m => `
                        <tr>
                            <td>${m.category}</td>
                            <td>${m.model_name}</td>
                            <td><button class="btn btn-danger" onclick="deactivateDeviceModel(${m.id})">Nonaktifkan</button></td>
                        </tr>
                    `).join('') : `<tr><td colspan="3" style="text-align:center;">Belum ada model alat ditambahkan.</td></tr>`;
                } catch(e) { console.error(e); }
            }

            async function createDeviceModel() {
                const category = document.getElementById('dmCategory').value;
                const model_name = document.getElementById('dmModelName').value.trim();
                if (!model_name) return alert('Nama Model wajib diisi.');

                try {
                    const res = await authFetch('/api/v1/device-models/', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ category, model_name })
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Gagal menambah model.');
                    document.getElementById('dmModelName').value = '';
                    renderDeviceModels();
                } catch(e) {
                    alert(e.message);
                }
            }

            async function deactivateDeviceModel(modelId) {
                if (!confirm('Nonaktifkan model ini? Model tidak akan muncul lagi di dropdown, tapi tiket lama yang sudah pakai model ini tetap aman.')) return;
                try {
                    const res = await authFetch(`/api/v1/device-models/${modelId}`, { method: 'DELETE' });
                    if (!res.ok) {
                        const data = await res.json();
                        throw new Error(data.detail || 'Gagal menonaktifkan model.');
                    }
                    renderDeviceModels();
                } catch(e) {
                    alert(e.message);
                }
            }

            // ---------- INVENTORY PART (Stok Sparepart Pusat & Cabang) ----------

            const INVENTORY_LOCATION_LABELS = { pusat: 'Pusat', cabang: 'Cabang' };

            const INVENTORY_ACTIONS = {
                pusat: [
                    { type: 'terima_gudang', label: 'Terima dari Gudang' },
                    { type: 'kirim_ke_cabang', label: 'Kirim ke Cabang' },
                    { type: 'terima_dari_cabang', label: 'Terima dari Cabang' },
                    { type: 'terpakai_pusat', label: 'Terpakai di Pusat' },
                ],
                cabang: [
                    { type: 'terima_dari_pusat', label: 'Terima dari Pusat' },
                    { type: 'kirim_balik_ke_pusat', label: 'Kirim Balik ke Pusat' },
                    { type: 'terpakai_cabang', label: 'Terpakai di Cabang' },
                ],
            };

            const INVENTORY_REPORTS = {
                pusat: [
                    { kind: 'stock-list', label: 'Total List Sparepart Pusat' },
                    { kind: 'movement', movement_type: 'kirim_ke_cabang', label: 'Total Kirim ke Cabang' },
                    { kind: 'movement', movement_type: 'terpakai_pusat', label: 'Total Terpakai di Pusat' },
                    { kind: 'opname', label: 'Hasil Stok Opname Pusat' },
                ],
                cabang: [
                    { kind: 'stock-list', label: 'Total List Sparepart Cabang' },
                    { kind: 'movement', movement_type: 'terpakai_cabang', label: 'Total Terpakai di Cabang' },
                    { kind: 'opname', label: 'Hasil Stok Opname Cabang' },
                ],
            };

            let currentMovementType = {};

            function buildInventoryTabsHTML() {
                Object.keys(INVENTORY_ACTIONS).forEach(loc => {
                    const label = INVENTORY_LOCATION_LABELS[loc];
                    const root = document.getElementById(`tab-inventory-${loc}`);
                    const actionButtons = INVENTORY_ACTIONS[loc]
                        .map(a => `<button class="btn btn-success" onclick="openMovementForm('${loc}','${a.type}','${a.label}')">+ ${a.label}</button>`)
                        .join(' ');
                    const reportOptions = INVENTORY_REPORTS[loc]
                        .map((r, idx) => `<option value="${idx}">${r.label}</option>`)
                        .join('');

                    root.innerHTML = `
                        <div class="card">
                            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px; flex-wrap:wrap; gap:10px;">
                                <h2 style="margin:0; border:none;">Inventory Part - Stok Sparepart ${label}</h2>
                                <div class="action-header" style="flex-wrap:wrap;">
                                    <select onchange="if(this.value !== ''){ downloadInventoryReport('${loc}', parseInt(this.value)); this.selectedIndex = 0; }">
                                        <option value="">📊 Download Laporan ▾</option>
                                        ${reportOptions}
                                    </select>
                                    ${actionButtons}
                                    <button class="btn btn-warning" onclick="toggleOpnameForm('${loc}')">+ Stok Opname</button>
                                </div>
                            </div>

                            <div id="invMovementFormBox-${loc}" class="hidden" style="background:#f8f9fa; border:1px dashed #ccc; padding:10px; border-radius:6px; margin-bottom:15px;">
                                <div style="font-weight:bold; color:#0056b3; margin-bottom:8px;" id="invMovementTitle-${loc}"></div>
                                <div class="form-grid">
                                    <div class="form-group"><label>Kode Sparepart <span class="required">*</span></label><input id="invCode-${loc}" placeholder="Kode/part number"></div>
                                    <div class="form-group"><label>Nama Sparepart</label><input id="invName-${loc}" placeholder="Nama sparepart"></div>
                                    <div class="form-group"><label>Jumlah <span class="required">*</span></label><input type="number" min="1" id="invQty-${loc}"></div>
                                    <div class="form-group" style="grid-column:1/-1;"><label>Catatan</label><input id="invNote-${loc}" placeholder="Opsional"></div>
                                </div>
                                <div style="display:flex; gap:10px; justify-content:flex-end;">
                                    <button class="btn btn-secondary" onclick="closeMovementForm('${loc}')">Batal</button>
                                    <button class="btn btn-success" onclick="submitMovement('${loc}')">Simpan</button>
                                </div>
                            </div>

                            <div id="invOpnameFormBox-${loc}" class="hidden" style="background:#fff3cd; border:1px dashed #ffc107; padding:10px; border-radius:6px; margin-bottom:15px;">
                                <div style="font-weight:bold; color:#856404; margin-bottom:8px;">Stok Opname (Hitung Fisik) - ${label}</div>
                                <div class="form-grid">
                                    <div class="form-group"><label>Kode Sparepart <span class="required">*</span></label><input id="invOpCode-${loc}" placeholder="Kode/part number"></div>
                                    <div class="form-group"><label>Nama Sparepart</label><input id="invOpName-${loc}" placeholder="Nama sparepart"></div>
                                    <div class="form-group"><label>Jumlah Hasil Hitung Fisik <span class="required">*</span></label><input type="number" min="0" id="invOpQty-${loc}"></div>
                                    <div class="form-group" style="grid-column:1/-1;"><label>Catatan</label><input id="invOpNote-${loc}" placeholder="Opsional"></div>
                                </div>
                                <div style="display:flex; gap:10px; justify-content:flex-end;">
                                    <button class="btn btn-secondary" onclick="toggleOpnameForm('${loc}')">Batal</button>
                                    <button class="btn btn-warning" onclick="submitOpname('${loc}')">Simpan Stok Opname</button>
                                </div>
                            </div>

                            <table>
                                <thead><tr><th>Kode</th><th>Nama Sparepart</th><th>Jumlah Stok</th><th>Harga Satuan</th><th>Update Terakhir</th></tr></thead>
                                <tbody id="tableInventory-${loc}"></tbody>
                            </table>
                        </div>
                    `;
                });
            }

            function openMovementForm(loc, type, label) {
                document.getElementById(`invOpnameFormBox-${loc}`).classList.add('hidden');
                currentMovementType[loc] = type;
                document.getElementById(`invMovementTitle-${loc}`).innerText = label;
                setVal(`invCode-${loc}`, '');
                setVal(`invName-${loc}`, '');
                setVal(`invQty-${loc}`, '');
                setVal(`invNote-${loc}`, '');
                document.getElementById(`invMovementFormBox-${loc}`).classList.remove('hidden');
            }

            function closeMovementForm(loc) {
                document.getElementById(`invMovementFormBox-${loc}`).classList.add('hidden');
            }

            function toggleOpnameForm(loc) {
                document.getElementById(`invMovementFormBox-${loc}`).classList.add('hidden');
                const box = document.getElementById(`invOpnameFormBox-${loc}`);
                box.classList.toggle('hidden');
                if (!box.classList.contains('hidden')) {
                    setVal(`invOpCode-${loc}`, '');
                    setVal(`invOpName-${loc}`, '');
                    setVal(`invOpQty-${loc}`, '');
                    setVal(`invOpNote-${loc}`, '');
                }
            }

            async function submitMovement(loc) {
                const code = valOf(`invCode-${loc}`);
                const qty = valOf(`invQty-${loc}`);
                if (!code || !qty) return alert('Kode Sparepart dan Jumlah wajib diisi.');

                const payload = {
                    location: loc,
                    movement_type: currentMovementType[loc],
                    code: code,
                    name: valOf(`invName-${loc}`) || null,
                    quantity: parseInt(qty),
                    note: valOf(`invNote-${loc}`) || null,
                };

                try {
                    const res = await authFetch('/api/v1/inventory-parts/movement', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Gagal menyimpan pergerakan stok.');
                    alert(`Berhasil! Stok ${data.code} di ${loc.toUpperCase()} sekarang: ${data.new_quantity}`);
                    closeMovementForm(loc);
                    renderInventoryStock(loc);
                } catch(e) {
                    alert(e.message);
                }
            }

            async function submitOpname(loc) {
                const code = valOf(`invOpCode-${loc}`);
                const qty = valOf(`invOpQty-${loc}`);
                if (!code || qty === '') return alert('Kode Sparepart dan Jumlah Hasil Hitung Fisik wajib diisi.');

                const payload = {
                    location: loc,
                    code: code,
                    name: valOf(`invOpName-${loc}`) || null,
                    counted_quantity: parseInt(qty),
                    note: valOf(`invOpNote-${loc}`) || null,
                };

                try {
                    const res = await authFetch('/api/v1/inventory-parts/opname', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Gagal menyimpan stok opname.');
                    alert(`Stok Opname tersimpan.\\nStok sistem sebelumnya: ${data.system_quantity}\\nHasil hitung fisik: ${data.counted_quantity}\\nSelisih: ${data.difference}`);
                    toggleOpnameForm(loc);
                    renderInventoryStock(loc);
                } catch(e) {
                    alert(e.message);
                }
            }

            async function renderInventoryStock(loc) {
                try {
                    const res = await authFetch(`/api/v1/inventory-parts/stock/${loc}`);
                    const el = document.getElementById(`tableInventory-${loc}`);
                    if (!res.ok || !el) return;
                    const data = await res.json();
                    el.innerHTML = data.length ? data.map(d => `
                        <tr>
                            <td><strong>${d.code}</strong></td>
                            <td>${d.name || '-'}</td>
                            <td>${d.quantity}</td>
                            <td>Rp ${(d.unit_price || 0).toLocaleString('id-ID')}</td>
                            <td>${d.updated_at ? d.updated_at.split('T')[0] : '-'}</td>
                        </tr>
                    `).join('') : `<tr><td colspan="5" style="text-align:center;">Belum ada sparepart di lokasi ini</td></tr>`;
                } catch(e) { console.error(e); }
            }

            async function downloadInventoryReport(loc, idx) {
                const report = INVENTORY_REPORTS[loc][idx];
                let url = '';
                if (report.kind === 'stock-list') url = `/api/v1/inventory-parts/report/stock-list?location=${loc}`;
                else if (report.kind === 'movement') url = `/api/v1/inventory-parts/report/movements?location=${loc}&movement_type=${report.movement_type}`;
                else if (report.kind === 'opname') url = `/api/v1/inventory-parts/report/opname?location=${loc}`;

                try {
                    const res = await authFetch(url);
                    if (!res.ok) {
                        const err = await res.json().catch(() => ({}));
                        throw new Error(err.detail || 'Gagal mengunduh laporan.');
                    }
                    const blob = await res.blob();
                    const dlUrl = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = dlUrl;
                    a.download = `${report.label.replace(/ /g, '_')}_${loc}.xlsx`;
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    window.URL.revokeObjectURL(dlUrl);
                } catch(e) {
                    alert(e.message);
                }
            }
        </script>
    </body>
    </html>
    """
