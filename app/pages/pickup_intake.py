"""
Halaman publik Drop-Off Pickup Center (/pickup-intake) - dipisah dari
main.py. Endpoint API-nya (POST /api/v1/public/pickup-intake) TETAP di
main.py - file ini HANYA berisi halaman HTML/CSS/JS-nya.
"""
import os
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/pickup-intake", response_class=HTMLResponse)
def pickup_intake_page():
    turnstile_site_key = os.environ.get("TURNSTILE_SITE_KEY", "").strip()
    turnstile_script = (
        '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>'
        if turnstile_site_key else ""
    )
    turnstile_widget = (
        f'<div class="cf-turnstile" data-sitekey="{turnstile_site_key}" data-expired-callback="onTurnstileExpired" data-error-callback="onTurnstileExpired"></div>' if turnstile_site_key else ""
    )
    html = """
    <!DOCTYPE html>
    <html lang="id">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Drop-Off Pickup Center - Omron Healthcare</title>
        __TURNSTILE_SCRIPT__
        <style>
            * { box-sizing: border-box; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
            body { background: #f0f2f5; margin: 0; padding: 20px; }
            .wrap { max-width: 640px; margin: 0 auto; }
            .card { background: white; padding: 25px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); margin-bottom: 20px; }
            .logo { font-size: 22px; font-weight: bold; color: #0056b3; margin-bottom: 2px; }
            .subtitle { color: #666; font-size: 13px; margin-bottom: 20px; }
            .form-group { margin-bottom: 14px; }
            label { font-size: 13px; font-weight: bold; color: #444; display: block; margin-bottom: 4px; }
            input, select { width: 100%; padding: 11px; border: 1px solid #ccc; border-radius: 6px; box-sizing: border-box; font-size: 14px; }
            .required { color: red; }
            button { width: 100%; padding: 13px; background: #0056b3; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: bold; font-size: 15px; margin-top: 8px; }
            button:hover { background: #004085; }
            .success-box { display: none; background: #d4edda; border: 1px solid #c3e6cb; color: #155724; padding: 18px; border-radius: 8px; text-align: center; }
            .success-box .ticket-no { font-size: 22px; font-weight: bold; margin: 8px 0; }
            .error-box { display: none; background: #f8d7da; border: 1px solid #f5c6cb; color: #721c24; padding: 12px; border-radius: 6px; font-size: 13px; margin-bottom: 15px; }
        </style>
    </head>
    <body>
        <div class="wrap">
            <div class="card">
                <div class="logo">OMRON</div>
                <div class="subtitle">Form Drop-Off Perangkat - Pickup Center</div>

                <div id="successBox" class="success-box">
                    ✅ Drop-off berhasil dicatat!
                    <div class="ticket-no" id="successTicketNo"></div>
                    Simpan nomor tiket ini untuk pelanggan.
                    <div style="margin-top:12px;"><button onclick="resetForm()">+ Input Drop-Off Baru</button></div>
                </div>

                <div id="errorBox" class="error-box"></div>

                <form id="intakeForm">
                    <div class="form-group"><label>Nama Customer <span class="required">*</span></label><input id="pName" required></div>
                    <div class="form-group">
                        <label>Nama Instansi</label>
                        <input id="pInstansi" list="pInstansiList" placeholder="Ketik atau pilih dari daftar Pickup Center aktif">
                        <datalist id="pInstansiList"></datalist>
                    </div>
                    <div class="form-group"><label>No. HP / WhatsApp 1 <span class="required">*</span></label><input id="pPhone1" required placeholder="081234567890"></div>
                    <div class="form-group"><label>No. HP / WhatsApp 2</label><input id="pPhone2" placeholder="(opsional)"></div>
                    <div class="form-group"><label>Alamat</label><input id="pAddress"></div>
                    <div class="form-group"><label>Tanggal Alat Diterima</label><input type="date" id="pReceivedDate"></div>
                    <div class="form-group">
                        <label>Produk Kategori</label>
                        <select id="pCategory" onchange="onCategoryChange()">
                            <option value="">-- Pilih Kategori --</option>
                            <option>Arm BPM</option><option>BCM</option><option>BGM</option><option>Comp-NEB</option>
                            <option>DWS</option><option>Ear Thermo</option><option>Forehead Thermo</option>
                            <option>MEDICAL</option><option>Mesh-NEB</option><option>Pen Thermo</option>
                            <option>TENS</option><option>Ultra-NEB</option><option>Wrist BPM</option><option>Others</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Model Alat</label>
                        <select id="pModel"><option value="">-- Pilih Kategori dulu --</option></select>
                    </div>
                    <div class="form-group"><label>Serial No. Alat</label><input id="pSerial"></div>
                    <div class="form-group"><label>Aksesoris</label><input id="pAccessories" placeholder="Contoh: Kabel, Adaptor"></div>
                    <div class="form-group"><label>Keluhan Pelanggan</label><input id="pComplaint"></div>

                    __TURNSTILE_WIDGET__

                    <button type="submit" id="pickupSubmitBtn">Simpan Drop-Off</button>
                </form>
            </div>
        </div>

        <script>
            function esc(value) {
                if (value === null || value === undefined) return '';
                return String(value)
                    .replace(/&/g, '&amp;')
                    .replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;')
                    .replace(/"/g, '&quot;')
                    .replace(/'/g, '&#39;');
            }

            // Token Turnstile hanya berlaku beberapa menit - kalau pengisian form
            // lebih lama dari itu (wajar di HP, mengetik lebih lambat), token jadi
            // basi TANPA ada tanda visual apa pun (centang tetap kelihatan tercentang).
            // Fungsi ini dipanggil OTOMATIS oleh widget Turnstile sendiri saat itu
            // terjadi - mereset widget diam-diam supaya dapat token baru, TANPA
            // menghapus data yang sudah diketik user di form.
            function onTurnstileExpired() {
                if (window.turnstile) {
                    try { turnstile.reset(); } catch(e) { /* diamkan */ }
                }
            }

            async function loadInstansiOptions() {
                try {
                    const res = await fetch('/api/v1/pickup-centers/public');
                    if (!res.ok) return;
                    const list = await res.json();
                    document.getElementById('pInstansiList').innerHTML =
                        list.map(p => `<option value="${esc(p.store_name)}">`).join('');
                } catch(e) { /* diamkan - form tetap bisa diisi manual kalau daftar gagal dimuat */ }
            }
            loadInstansiOptions();

            async function onCategoryChange() {
                const category = document.getElementById('pCategory').value;
                let modelEl = document.getElementById('pModel');

                if (!category) {
                    if (modelEl.tagName !== 'SELECT') {
                        modelEl.outerHTML = '<select id="pModel"><option value="">-- Pilih Kategori dulu --</option></select>';
                    } else {
                        modelEl.innerHTML = '<option value="">-- Pilih Kategori dulu --</option>';
                    }
                    return;
                }

                if (category === 'Others') {
                    modelEl.outerHTML = '<input id="pModel" placeholder="Ketik nama model alat">';
                    return;
                }

                if (modelEl.tagName !== 'SELECT') {
                    modelEl.outerHTML = '<select id="pModel"><option value="">Memuat...</option></select>';
                } else {
                    modelEl.innerHTML = '<option value="">Memuat...</option>';
                }
                modelEl = document.getElementById('pModel');

                try {
                    const res = await fetch(`/api/v1/device-models/public?category=${encodeURIComponent(category)}`);
                    const models = res.ok ? await res.json() : [];
                    modelEl.innerHTML = models.length
                        ? '<option value="">-- Pilih Model --</option>' + models.map(m => `<option value="${esc(m.model_name)}">${esc(m.model_name)}</option>`).join('')
                        : '<option value="">(Belum ada model utk kategori ini)</option>';
                } catch(e) {
                    modelEl.innerHTML = '<option value="">Gagal memuat model</option>';
                }
            }

            function resetForm() {
                document.getElementById('intakeForm').reset();
                document.getElementById('pModel').outerHTML = '<select id="pModel"><option value="">-- Pilih Kategori dulu --</option></select>';
                document.getElementById('successBox').style.display = 'none';
                document.getElementById('errorBox').style.display = 'none';
                document.getElementById('intakeForm').style.display = 'block';
            }

            document.getElementById('intakeForm').addEventListener('submit', async function(e) {
                e.preventDefault();
                const errorBox = document.getElementById('errorBox');
                errorBox.style.display = 'none';

                const submitBtn = document.getElementById('pickupSubmitBtn');
                if (submitBtn.disabled) return; // sedang diproses - abaikan klik dobel

                const name = document.getElementById('pName').value.trim();
                const phone1 = document.getElementById('pPhone1').value.trim();
                if (!name || !phone1) {
                    errorBox.textContent = 'Nama Customer dan No. HP/WhatsApp 1 wajib diisi.';
                    errorBox.style.display = 'block';
                    return;
                }

                submitBtn.disabled = true;
                const submitBtnOriginalText = submitBtn.innerText;
                submitBtn.innerText = 'Menyimpan...';
                const receivedDateVal = document.getElementById('pReceivedDate').value;
                const payload = {
                    customer_name: name,
                    instansi_name: document.getElementById('pInstansi').value.trim() || null,
                    customer_phone: phone1,
                    customer_phone_2: document.getElementById('pPhone2').value.trim() || null,
                    customer_address: document.getElementById('pAddress').value.trim() || null,
                    received_date: receivedDateVal ? new Date(receivedDateVal + 'T00:00:00').toISOString() : null,
                    product_category: document.getElementById('pCategory').value || null,
                    device_model: document.getElementById('pModel').value || null,
                    serial_number: document.getElementById('pSerial').value.trim() || '-',
                    accessories: document.getElementById('pAccessories').value.trim() || null,
                    complaint: document.getElementById('pComplaint').value.trim() || '-',
                    turnstileToken: (window.turnstile && document.querySelector('.cf-turnstile')) ? turnstile.getResponse() : null,
                };

                try {
                    const res = await fetch('/api/v1/public/pickup-intake', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Gagal menyimpan data.');

                    document.getElementById('intakeForm').style.display = 'none';
                    document.getElementById('successTicketNo').innerText = data.ticket_number;
                    document.getElementById('successBox').style.display = 'block';
                } catch(err) {
                    // Kalau errornya soal CAPTCHA (token basi/gagal), reset widget
                    // Turnstile SAJA - form yang sudah diisi TETAP UTUH, user
                    // tinggal centang ulang & klik Simpan lagi (tidak perlu refresh
                    // halaman dan mengetik ulang semua dari awal).
                    if (err.message && err.message.toUpperCase().includes('CAPTCHA') && window.turnstile) {
                        try { turnstile.reset(); } catch(e) { /* diamkan */ }
                        errorBox.textContent = 'Verifikasi keamanan kedaluwarsa - silakan centang kotak verifikasi di bawah lagi, lalu klik Simpan (data isian Anda tetap tersimpan).';
                    } else {
                        errorBox.textContent = err.message;
                    }
                    errorBox.style.display = 'block';
                } finally {
                    submitBtn.disabled = false;
                    submitBtn.innerText = submitBtnOriginalText;
                }
            });
        </script>
    </body>
    </html>
    """
    html = html.replace("__TURNSTILE_SCRIPT__", turnstile_script).replace("__TURNSTILE_WIDGET__", turnstile_widget)
    return html


