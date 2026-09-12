"""
Halaman publik Lacak Status Service (/track) - dipisah dari main.py.
Endpoint API-nya (POST /api/v1/public/track) TETAP di main.py - file ini
HANYA berisi halaman HTML/CSS/JS-nya.
"""
import os
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/track", response_class=HTMLResponse)
def track_ticket_page():
    turnstile_site_key = os.environ.get("TURNSTILE_SITE_KEY", "").strip()
    turnstile_script = (
        '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>'
        if turnstile_site_key else ""
    )
    turnstile_widget = (
        f'<div class="cf-turnstile" data-sitekey="{turnstile_site_key}" style="margin:14px 0;"></div>' if turnstile_site_key else ""
    )
    html = """
<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<title>Lacak Status Service — OMRON Healthcare</title>
__TURNSTILE_SCRIPT__
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex, nofollow">
<style>
  :root{
    --navy:#0b2f6b;
    --blue:#0f4fb0;
    --blue-light:#e8f0fd;
    --orange:#f2932d;
    --bg:#f4f6fb;
    --card:#ffffff;
    --border:#e1e6ef;
    --ink:#152238;
    --ink-soft:#5c6b83;
    --ok:#1f9d55;
    --warn:#c9781f;
    --danger:#c0392b;
    --radius:12px;
  }
  *{box-sizing:border-box;}
  body{margin:0;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;background:var(--bg);color:var(--ink);}
  .wrap{min-height:100vh;display:flex;flex-direction:column;align-items:center;padding:32px 16px 60px;}
  .top{display:flex;flex-direction:column;align-items:center;margin-bottom:22px;text-align:center;}
  .logo{font-weight:800;font-size:24px;letter-spacing:.5px;color:var(--navy);}
  .logo span{color:var(--orange);}
  .top .sub{font-size:13px;color:var(--ink-soft);margin-top:4px;}

  .card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
    padding:26px 24px;width:100%;max-width:440px;box-shadow:0 10px 30px rgba(15,40,90,.06);}
  .card h1{font-size:17px;margin:0 0 4px;color:var(--navy);}
  .card .desc{font-size:12.5px;color:var(--ink-soft);margin-bottom:20px;line-height:1.5;}
  .field{margin-bottom:14px;}
  label{font-size:12.5px;font-weight:700;color:var(--ink-soft);display:block;margin-bottom:5px;}
  input[type=text],input[type=tel]{
    width:100%;padding:11px 12px;border:1px solid var(--border);border-radius:8px;font-size:14px;
    background:#fff;color:var(--ink);font-family:inherit;
  }
  input:focus{outline:none;border-color:var(--blue);box-shadow:0 0 0 3px var(--blue-light);}
  .helper{font-size:11px;color:var(--ink-soft);margin-top:5px;line-height:1.4;}
  .btn{
    border:none;border-radius:8px;padding:12px 16px;font-size:14px;font-weight:700;cursor:pointer;
    width:100%;transition:.15s;display:flex;align-items:center;justify-content:center;gap:8px;
  }
  .btn-primary{background:var(--blue);color:#fff;margin-top:6px;}
  .btn-primary:hover{background:var(--navy);}
  .btn-primary:disabled{opacity:.6;cursor:not-allowed;}
  .btn-outline{background:#fff;color:var(--blue);border:1px solid var(--blue);margin-top:10px;}
  .btn-outline:hover{background:var(--blue-light);}
  .spinner{width:15px;height:15px;border:2px solid rgba(255,255,255,.4);border-top-color:#fff;
    border-radius:50%;animation:spin .7s linear infinite;}
  @keyframes spin{to{transform:rotate(360deg);}}

  .alert{padding:11px 13px;border-radius:8px;font-size:12.5px;margin-bottom:14px;display:none;line-height:1.5;white-space:pre-wrap;}
  .alert.show{display:block;}
  .alert-error{background:#fdecea;color:var(--danger);border:1px solid #f5c6c0;}

  .result{display:none;}
  .result.show{display:block;}
  .result-head{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;margin-bottom:4px;flex-wrap:wrap;}
  .section-title{font-size:11px;font-weight:800;color:var(--ink-soft);text-transform:uppercase;letter-spacing:.4px;margin:16px 0 6px;}
  .dash{color:#c2c8d4;font-weight:400;}
  .ticket-no{font-size:16px;font-weight:800;color:var(--navy);letter-spacing:.3px;}
  .cust-name{font-size:12.5px;color:var(--ink-soft);margin-bottom:14px;}
  .badge{display:inline-block;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:700;white-space:nowrap;}
  .badge-blue{background:#e5eeff;color:var(--blue);}
  .badge-green{background:#e7f8ee;color:var(--ok);}
  .badge-orange{background:#fef1e2;color:var(--warn);}
  .badge-gray{background:#eef1f6;color:var(--ink-soft);}

  .progress{display:flex;margin:20px 0 22px;}
  .step{flex:1;text-align:center;position:relative;}
  .step .dot{width:22px;height:22px;border-radius:50%;background:#e1e6ef;color:#8a97ad;font-size:11px;
    font-weight:800;display:flex;align-items:center;justify-content:center;margin:0 auto 6px;
    border:2px solid #e1e6ef;position:relative;z-index:2;}
  .step .lbl{font-size:9.5px;color:var(--ink-soft);line-height:1.25;padding:0 2px;}
  .step:before{content:'';position:absolute;top:11px;left:-50%;width:100%;height:2px;background:#e1e6ef;z-index:1;}
  .step:first-child:before{display:none;}
  .step.done .dot{background:var(--blue);border-color:var(--blue);color:#fff;}
  .step.done:before{background:var(--blue);}
  .step.current .dot{background:#fff;border-color:var(--blue);color:var(--blue);box-shadow:0 0 0 3px var(--blue-light);}
  .step.current .lbl{color:var(--navy);font-weight:700;}

  .info-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:6px;}
  .info-item{background:#f8f9fc;border:1px solid var(--border);border-radius:8px;padding:10px 12px;}
  .info-item .k{font-size:10.5px;color:var(--ink-soft);text-transform:uppercase;letter-spacing:.3px;margin-bottom:3px;}
  .info-item .v{font-size:13px;font-weight:600;color:var(--ink);word-break:break-word;}
  .info-item.full{grid-column:1/-1;}

  .foot-note{margin-top:26px;text-align:center;font-size:11.5px;color:var(--ink-soft);max-width:440px;line-height:1.6;}
  .foot-note b{color:var(--ink);}
  .privacy-note{display:flex;gap:8px;align-items:flex-start;background:var(--blue-light);border:1px solid #bcd4f7;
    border-radius:8px;padding:10px 12px;font-size:11.5px;color:var(--navy);margin-bottom:16px;line-height:1.5;}
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div class="logo">OMRON<span>&bull;</span>SERVICE</div>
    <div class="sub">Lacak Status Service Alat Anda</div>
  </div>

  <div class="card" id="formCard">
    <h1>Cek Status Service</h1>
    <div class="desc">Masukkan <b>Nomor Tiket</b> atau <b>Serial Number</b> alat, lalu konfirmasi dengan <b>5 digit terakhir</b> Nomor HP/WhatsApp 1 yang didaftarkan saat alat diserahkan.</div>

    <div class="alert alert-error" id="alertError"></div>

    <form id="trackForm" autocomplete="off">
      <div class="field">
        <label for="inpQuery">Nomor Tiket / Serial Number Alat</label>
        <input type="text" id="inpQuery" placeholder="Contoh: JKT-2600001 atau SN12345678" required>
      </div>
      <div class="field">
        <label for="inpPhone">5 Digit Terakhir No. HP/WhatsApp 1</label>
        <input type="tel" id="inpPhone" placeholder="Contoh: 45678" maxlength="5" inputmode="numeric" required>
        <div class="helper">Cukup 5 digit TERAKHIR dari nomor HP/WhatsApp yang didaftarkan saat menyerahkan alat.</div>
      </div>

      __TURNSTILE_WIDGET__

      <button type="submit" class="btn btn-primary" id="btnSubmit">Lacak Status</button>
    </form>
  </div>

  <div class="card result" id="resultCard">
    <div class="privacy-note">&#128274; Data ini hanya ditampilkan setelah Nomor Tiket/Serial dan 5 digit No. HP Anda terverifikasi cocok dengan data kami.</div>

    <div class="result-head">
      <div>
        <div class="ticket-no" id="resTicket">-</div>
        <div class="cust-name" id="resNama">-</div>
      </div>
    </div>

    <div class="section-title">Status Perbaikan</div>
    <span class="badge" id="resRepairBadge">-</span>

    <div class="section-title">Status Pengiriman</div>
    <span class="badge" id="resShipBadge">-</span>
    <div class="progress" id="resProgress"></div>
    <div class="info-item full" id="resAwbWrap" style="display:none; margin-top:8px;">
      <div class="k">No. Resi (AWB)</div><div class="v" id="resAwb">-</div>
    </div>
    <div class="info-item full" id="resReceiverWrap" style="display:none; margin-top:8px; background:#e7f8ee; border-color:#c3e6cb;">
      <div class="k">Nama Penerima (dari kurir)</div><div class="v" id="resReceiver">-</div>
    </div>

    <div class="info-grid" style="margin-top:16px;">
      <div class="info-item"><div class="k">Produk</div><div class="v" id="resProduk">-</div></div>
      <div class="info-item"><div class="k">Serial No.</div><div class="v" id="resSerial">-</div></div>
      <div class="info-item"><div class="k">Tgl. Diterima</div><div class="v" id="resTglTerima">-</div></div>
      <div class="info-item"><div class="k">Tgl. Selesai</div><div class="v" id="resTglSelesai">-</div></div>
      <div class="info-item"><div class="k">Status Garansi</div><div class="v" id="resGaransi">-</div></div>
      <div class="info-item"><div class="k">Rekomendasi</div><div class="v" id="resRemarks">-</div></div>
      <div class="info-item full" id="resKeluhanWrap">
        <div class="k">Keluhan yang Dilaporkan</div><div class="v" id="resKeluhan">-</div>
      </div>
    </div>

    <button type="button" class="btn btn-outline" id="btnAgain">Cek Tiket Lain</button>
  </div>

  <div class="foot-note">
    Butuh bantuan lebih lanjut? Hubungi Customer Service kami di<br>
    <b>08001401567</b> via telpon<br>
    <b>081113101567</b> via chat WhatsApp<br>
    Halaman ini hanya menampilkan data setelah verifikasi Nomor Tiket/Serial Number dan 5 digit terakhir Nomor HP/WhatsApp yang cocok.
  </div>
</div>

<script>
// Urutan tahap Status Pengiriman (gabungan Stage 1 khusus Pickup Center + Stage 2 semua asal)
// dipakai utk progress bar visual - label & urutan HARUS sinkron dgn app/services/shipping_status.py
const SHIPPING_STAGE_ORDER = [
  "Diterima Pickup Center", "Menunggu Kurir", "Diteruskan ke Omron",
  "Diterima Omron", "Diproses", "Dikirim Balik", "Diterima"
];
const SHIPPING_STAGE_LABELS = {
  "Diterima Pickup Center": "Diterima PKP", "Menunggu Kurir": "Menunggu Kurir",
  "Diteruskan ke Omron": "Ke Omron", "Diterima Omron": "Di Omron",
  "Diproses": "Diproses", "Dikirim Balik": "Dikirim Balik", "Diterima": "Diterima"
};
const SHIPPING_BADGE_CLASS = {
  "Diterima Pickup Center":"badge-blue", "Menunggu Kurir":"badge-orange", "Diteruskan ke Omron":"badge-orange",
  "Diterima Omron":"badge-blue", "Diproses":"badge-orange", "Dikirim Balik":"badge-orange", "Diterima":"badge-green"
};
const REPAIR_BADGE_CLASS = {
  "Diterima":"badge-blue", "Diproses":"badge-orange", "Menunggu Sparepart":"badge-orange",
  "Selesai/Dikirim":"badge-green", "Selesai Diambil":"badge-gray"
};

const form = document.getElementById('trackForm');
const btnSubmit = document.getElementById('btnSubmit');
const alertError = document.getElementById('alertError');
const formCard = document.getElementById('formCard');
const resultCard = document.getElementById('resultCard');

function showError(msg){
  alertError.textContent = msg;
  alertError.classList.add('show');
}
function hideError(){
  alertError.classList.remove('show');
  alertError.textContent = '';
}
function esc(v){ return (v===undefined||v===null) ? '' : String(v); }
function fmtDate(d){
  if(!d) return '-';
  try{
    const dt = new Date(d);
    if(isNaN(dt.getTime())) return esc(d);
    return dt.toLocaleDateString('id-ID', { day:'2-digit', month:'long', year:'numeric' });
  }catch(e){ return esc(d); }
}

form.addEventListener('submit', async (e)=>{
  e.preventDefault();
  hideError();

  const query = document.getElementById('inpQuery').value.trim();
  const phone = document.getElementById('inpPhone').value.trim();

  if(!query || !phone){
    showError('Nomor Tiket/Serial dan 5 digit terakhir No. HP/WhatsApp wajib diisi.');
    return;
  }

  btnSubmit.disabled = true;
  btnSubmit.innerHTML = '<span class="spinner"></span> Memeriksa...';

  try{
    const res = await fetch('/api/v1/public/track', {
      method:'POST',
      headers:{ 'Content-Type':'application/json' },
      body: JSON.stringify({ query, phone, turnstileToken: (window.turnstile && document.querySelector('.cf-turnstile')) ? turnstile.getResponse() : null })
    });
    const payload = await res.json().catch(()=>({ ok:false, message:'Respons server tidak valid.' }));

    if(!res.ok || !payload.ok){
      showError(payload.message || 'Data tidak ditemukan. Pastikan Nomor Tiket/Serial dan No. HP sesuai.');
      return;
    }

    renderResult(payload.data);
    formCard.style.display = 'none';
    resultCard.classList.add('show');

  }catch(err){
    showError('Gagal menghubungi server. Periksa koneksi internet Anda dan coba lagi.');
  }finally{
    btnSubmit.disabled = false;
    btnSubmit.textContent = 'Lacak Status';
  }
});

document.getElementById('btnAgain').addEventListener('click', ()=>{
  resultCard.classList.remove('show');
  formCard.style.display = 'block';
  form.reset();
  hideError();
});

function renderResult(d){
  document.getElementById('resTicket').textContent = d.ticket || '-';
  // Nama Customer SELALU tampil apa adanya - TIDAK PERNAH diganti nama instansi.
  document.getElementById('resNama').textContent = d.namaCustomer ? ('Atas nama: ' + d.namaCustomer) : '';

  // ---- Status Perbaikan - tampil "-----" kalau backend kirim null (alat blm dipegang teknisi) ----
  const repairBadge = document.getElementById('resRepairBadge');
  if (d.repairStatus) {
    repairBadge.innerHTML = esc(d.repairStatus);
    repairBadge.className = 'badge ' + (REPAIR_BADGE_CLASS[d.repairStatus] || 'badge-gray');
  } else {
    repairBadge.innerHTML = '<span class="dash">-----</span>';
    repairBadge.className = 'badge badge-gray';
  }

  // ---- Status Pengiriman - tampil "-----" kalau backend kirim null (sedang dikerjakan, blm ada aktivitas kirim) ----
  const shipBadge = document.getElementById('resShipBadge');
  if (d.shippingStatus) {
    shipBadge.innerHTML = esc(d.shippingStatus);
    shipBadge.className = 'badge ' + (SHIPPING_BADGE_CLASS[d.shippingStatus] || 'badge-gray');
  } else {
    shipBadge.innerHTML = '<span class="dash">-----</span>';
    shipBadge.className = 'badge badge-gray';
  }

  // ---- No. Resi (AWB) - hanya tampil kalau sudah ada ----
  const awbWrap = document.getElementById('resAwbWrap');
  if (d.awbNumber) {
    document.getElementById('resAwb').textContent = d.awbNumber;
    awbWrap.style.display = 'block';
  } else {
    awbWrap.style.display = 'none';
  }

  // ---- Nama Penerima - dari KURIR GED, hanya muncul di titik akhir "Diterima" ----
  const receiverWrap = document.getElementById('resReceiverWrap');
  if (d.receiverName) {
    document.getElementById('resReceiver').textContent = d.receiverName;
    receiverWrap.style.display = 'block';
  } else {
    receiverWrap.style.display = 'none';
  }

  document.getElementById('resProduk').textContent = [d.kategori, d.model].filter(Boolean).join(' - ') || '-';
  document.getElementById('resSerial').textContent = d.serialNo || '-';
  document.getElementById('resTglTerima').textContent = fmtDate(d.tglTerima);
  document.getElementById('resTglSelesai').textContent = d.tglSelesai ? fmtDate(d.tglSelesai) : 'Belum selesai';
  document.getElementById('resGaransi').textContent = d.statusGaransi || '-';
  document.getElementById('resRemarks').textContent = d.remarks || '-';

  const keluhanWrap = document.getElementById('resKeluhanWrap');
  if(d.keluhan){
    document.getElementById('resKeluhan').textContent = d.keluhan;
    keluhanWrap.style.display = 'block';
  } else {
    keluhanWrap.style.display = 'none';
  }

  renderProgress(d.shippingStatus);
}

function renderProgress(shippingStatus){
  const wrap = document.getElementById('resProgress');
  if (!shippingStatus) {
    // Belum ada Status Pengiriman sama sekali (mis. tiket Cabang, atau blm
    // pernah dikirim) - progress bar dikosongkan, tidak relevan ditampilkan.
    wrap.innerHTML = '';
    return;
  }
  let currentIdx = SHIPPING_STAGE_ORDER.indexOf(shippingStatus);
  if (currentIdx === -1) currentIdx = 0;
  wrap.innerHTML = SHIPPING_STAGE_ORDER.map((key, i)=>{
    let cls = 'step';
    if(i < currentIdx) cls += ' done';
    else if(i === currentIdx) cls += ' current';
    const icon = i < currentIdx ? '&#10003;' : (i+1);
    return `<div class="${cls}"><div class="dot">${icon}</div><div class="lbl">${SHIPPING_STAGE_LABELS[key]}</div></div>`;
  }).join('');
}
</script>
</body>
</html>
"""
    html = html.replace("__TURNSTILE_SCRIPT__", turnstile_script).replace("__TURNSTILE_WIDGET__", turnstile_widget)
    return html


