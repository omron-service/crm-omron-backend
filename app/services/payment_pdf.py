"""
Generator PDF untuk Tab Status Payment Service, format PERSIS mengikuti
template resmi yang diberikan (Omron-_098-INV-MD-2026.pdf dan
Omron-_067-SPH-MD-2026.pdf):
- generate_quotation_pdf()  -> "Surat Penawaran Harga"
- generate_invoice_pdf()    -> "INVOICE"
"""
import io
import os
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak,
)
from reportlab.lib.enums import TA_RIGHT, TA_CENTER

LOGO_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "omron_logo.png")

COMPANY_LINES = [
    "PT. Omron Healthcare Indonesia",
    "Menara Bidakara 2 Lt. 11 unit 1,2 dan 3",
    "Jl. Jend. Gatot Subroto Menteng Dalam, Tebet, Kota Adm Jakarta Selatan DKI jakarta",
    "Nomor Telepon: 0800 1401 567",
    "NPWP: 315954909015000 / 0315954909015000",
    "NITKU: 0315954909015000000000",
]

PPN_RATE = 0.11

AGREEMENT_CLAUSES = [
    "Customer wajib mengikuti peraturan yang berlaku di OHSC",
    "Customer harap memastikan kelengkapan alat sebelum dikirim dan setelah diterima",
    "Pihak OHSC akan mengirimkan SPH (Surat Penawaran Harga) ke customer, dan harap di berikan approval maksimal 5 hari kerja",
    "Apabila lebih dari 5 hari kerja, SPH belum di berikan approval dari pihak customer, maka OHSC akan mengirimkan kembali alat customer",
    "Apabila customer setuju dengan SPH dari OHSC, maka customer diharapkan melakukan pembayaran service alat dengan jangka waktu 10 hari kerja",
    "Apabila customer belum melakukan pembayaran service dalam jangka waktu yang diberikan, pihak OHSC akan mengembalikan alat customer",
    "Alat akan mulai di service oleh team OHSC setelah customer melakukan pembayaran service dari pihak customer",
    "Biaya service seluruhnya yang disebutkan di surat penawaran harga di tanggung oleh pihak customer",
    "Garansi service alat setelah melakukan service di OHSC adalah 3 bulan",
    "Garansi service alat tidak berlaku, apabila pengaman/ segel telah rusak",
    "Garansi service alat tidak berlaku jika kerusakan disebabkan oleh kesalahan penggunaan atau efek lingkungan (hama, serangga, terkena cairan, robek, terbakar dll)",
    "Pembayaran biaya service dapat dilakukan melalui OVO, Virtual Account, dan Alfamart",
    "Apabila pihak customer memerlukan faktur pajak, harap menghubungi team OHSC, yang mana faktur pajak akan diberikan pada bulan berikutnya. (Contoh: bulan invoice pada April 2023, maka faktur pajak akan didaftarkan di system pajak pada bulan April 2023, tetapi baru bisa di berikan oleh pihak OHSC pada bulan Mei 2023)",
    "Apabila terdapat pertanyaan terkait proses service, pihak customer dapat menghubungi team OHSC di line telpon berikut 08001401567 (bebas pulsa) dan 081113101567 (via chat whatsapp)",
]

styles = getSampleStyleSheet()
STYLE_TITLE = ParagraphStyle("DocTitle", parent=styles["Title"], fontName="Times-Bold", fontSize=18, alignment=TA_CENTER)
STYLE_NORMAL = ParagraphStyle("N", parent=styles["Normal"], fontSize=9, leading=13)
STYLE_RIGHT = ParagraphStyle("R", parent=STYLE_NORMAL, alignment=TA_RIGHT)
STYLE_CENTER = ParagraphStyle("C", parent=STYLE_NORMAL, alignment=TA_CENTER)
STYLE_BOLD = ParagraphStyle("B", parent=STYLE_NORMAL, fontName="Helvetica-Bold")


def _terbilang(n: int) -> str:
    """Ubah angka jadi teks Bahasa Indonesia, mis. 4440000 -> 'Empat Juta Empat Ratus Empat Puluh Ribu'."""
    satuan = ["", "Satu", "Dua", "Tiga", "Empat", "Lima", "Enam", "Tujuh", "Delapan", "Sembilan", "Sepuluh", "Sebelas"]

    def helper(x):
        if x < 12:
            return satuan[x]
        if x < 20:
            return (helper(x - 10) + " Belas").strip()
        if x < 100:
            return (helper(x // 10) + " Puluh" + (" " + helper(x % 10) if x % 10 else "")).strip()
        if x < 200:
            return ("Seratus" + (" " + helper(x - 100) if x - 100 else "")).strip()
        if x < 1000:
            return (helper(x // 100) + " Ratus" + (" " + helper(x % 100) if x % 100 else "")).strip()
        if x < 2000:
            return ("Seribu" + (" " + helper(x - 1000) if x - 1000 else "")).strip()
        if x < 1000000:
            return (helper(x // 1000) + " Ribu" + (" " + helper(x % 1000) if x % 1000 else "")).strip()
        if x < 1000000000:
            return (helper(x // 1000000) + " Juta" + (" " + helper(x % 1000000) if x % 1000000 else "")).strip()
        if x < 1000000000000:
            return (helper(x // 1000000000) + " Miliar" + (" " + helper(x % 1000000000) if x % 1000000000 else "")).strip()
        return (helper(x // 1000000000000) + " Triliun" + (" " + helper(x % 1000000000000) if x % 1000000000000 else "")).strip()

    n = int(round(n))
    return "Nol" if n == 0 else helper(n)


def _fmt_rupiah(value) -> str:
    try:
        return f"Rp{int(round(float(value or 0))):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "Rp0"


def _fmt_date_long(value=None) -> str:
    """Format 'DD Month YYYY' berbahasa Indonesia, mis. '04 September 2026'."""
    bulan_id = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
                "Agustus", "September", "Oktober", "November", "Desember"]
    d = value or datetime.utcnow()
    return f"{d.day:02d} {bulan_id[d.month - 1]} {d.year}"


def _header_with_logo():
    """Blok alamat perusahaan (kiri) + logo Omron (kanan), tanpa border - sesuai template asli."""
    company_para = Paragraph("<br/>".join(COMPANY_LINES), STYLE_NORMAL)
    logo_cell = ""
    if os.path.exists(LOGO_PATH):
        try:
            logo_cell = Image(LOGO_PATH, width=42 * mm, height=11 * mm)
        except ImportError:
            logo_cell = ""
    table = Table([[company_para, logo_cell]], colWidths=[115 * mm, 55 * mm])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
    ]))
    return table


def _compute_items(items):
    """Susun baris tabel Item Service (2 baris per item: judul jenis layanan + detail unit),
    dan hitung subtotal keseluruhan."""
    rows = []
    subtotal = 0.0
    for idx, item in enumerate(items, start=1):
        qty = item.quantity or 0
        price = item.price or 0
        line_total = qty * price
        subtotal += line_total

        header_label = f"{item.service_type or 'Perbaikan'} Alat"
        detail_bits = []
        if item.description:
            detail_bits.append(item.description.strip())
        detail_bits.append(f"Serial No. {item.serial_number or '-'}")
        detail_bits.append(item.device_model or "-")
        detail_line = ", ".join(detail_bits)

        # Paragraph (bukan string polos) supaya teks panjang otomatis "wrap"
        # ke baris berikutnya DI DALAM sel-nya sendiri, bukan bocor/tumpang
        # tindih ke kolom Qty/Harga di sebelahnya.
        rows.append([Paragraph(str(idx) + ".", STYLE_NORMAL), Paragraph(header_label, STYLE_BOLD), "", "", ""])
        rows.append([
            "", Paragraph(detail_line, STYLE_NORMAL), Paragraph(str(qty), STYLE_CENTER),
            Paragraph(_fmt_rupiah(price), STYLE_RIGHT), Paragraph(_fmt_rupiah(line_total), STYLE_RIGHT),
        ])
        rows.append(["", "", "", "", ""])  # baris kosong pemisah, sesuai template asli
    return rows, subtotal



def _price_table(items, ppn_free, pph23_amount=None, admin_bank_fee=None, use_manual_breakdown=False):
    header = ["No", "Item Service", "Qty", "Harga Satuan", "Jumlah"]
    item_rows, subtotal = _compute_items(items)
    ppn = 0.0 if ppn_free else subtotal * PPN_RATE

    pph23 = float(pph23_amount or 0) if use_manual_breakdown else 0.0
    admin_bank = float(admin_bank_fee or 0) if use_manual_breakdown else 0.0
    # PPh 23 dipotong LANGSUNG oleh customer & disetor sendiri ke kantor pajak
    # (jadi MENGURANGI yang perlu ditransfer ke Omron). Biaya Admin Bank
    # sebaliknya MENAMBAH (biaya transfer ditanggung customer).
    total = subtotal + ppn - pph23 + admin_bank

    terbilang_row = [
        Paragraph("Terbilang", STYLE_BOLD), "", "",
        Paragraph("JUMLAH", STYLE_BOLD), Paragraph(_fmt_rupiah(subtotal), STYLE_RIGHT),
    ]
    words_row = [
        Paragraph(f"{_terbilang(total)} Rupiah", STYLE_NORMAL), "", "",
        Paragraph("PPN 11%" if not ppn_free else "PPN (Bebas PPN)", STYLE_BOLD),
        Paragraph(_fmt_rupiah(ppn), STYLE_RIGHT),
    ]
    trailing_rows = [terbilang_row, words_row]
    if use_manual_breakdown and pph23:
        trailing_rows.append(["", "", "", Paragraph("PPH 23", STYLE_BOLD), Paragraph(f"- {_fmt_rupiah(pph23)}", STYLE_RIGHT)])
    if use_manual_breakdown and admin_bank:
        trailing_rows.append(["", "", "", Paragraph("Biaya Admin Bank", STYLE_BOLD), Paragraph(_fmt_rupiah(admin_bank), STYLE_RIGHT)])
    total_row = ["", "", "", Paragraph("<b>TOTAL</b>", STYLE_BOLD), Paragraph(f"<b>{_fmt_rupiah(total)}</b>", STYLE_RIGHT)]
    trailing_rows.append(total_row)

    data = [header] + item_rows + trailing_rows

    n_item_rows = len(item_rows)
    span_start = 1 + n_item_rows  # baris pertama setelah header+item (index Terbilang)

    table = Table(data, colWidths=[10 * mm, 78 * mm, 12 * mm, 28 * mm, 30 * mm])
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (2, 0), (-1, 0), "CENTER"),
        ("ALIGN", (2, 1), (2, -1), "CENTER"),
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, span_start - 1), 0.5, colors.HexColor("#999999")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#999999")),
        ("SPAN", (0, span_start), (2, span_start)),
        ("SPAN", (0, span_start + 1), (2, span_start + 1)),
        ("LINEABOVE", (3, span_start), (-1, span_start), 0.5, colors.HexColor("#999999")),
        ("LINEBELOW", (3, -1), (-1, -1), 0.5, colors.HexColor("#999999")),
        ("BOX", (3, span_start), (-1, -1), 0.5, colors.HexColor("#999999")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    for row_idx in range(span_start + 1, len(data) - 1):
        style.append(("LINEBELOW", (3, row_idx), (-1, row_idx), 0.5, colors.HexColor("#999999")))
    table.setStyle(TableStyle(style))
    return table, subtotal, ppn, total


def _agreement_page():
    """Halaman ke-2 'Surat Perjanjian Service' - teks baku, sama persis di
    setiap dokumen Penawaran Harga (bukan diambil dari data tiket)."""
    elements = [PageBreak()]
    elements.append(Paragraph("Surat Perjanjian Service", STYLE_TITLE))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph(
        "Berikut ini kami informasikan ketentuan service (perbaikan dan kalibrasi) di OMRON "
        "Healthcare Service Center yang disebut OHSC,", STYLE_NORMAL,
    ))
    elements.append(Spacer(1, 8))

    for idx, clause in enumerate(AGREEMENT_CLAUSES, start=1):
        elements.append(Paragraph(f"{idx}. {clause}", STYLE_NORMAL))
        elements.append(Spacer(1, 3))

    elements.append(Spacer(1, 12))
    elements.append(Paragraph(
        "Dengan menyetujui ketentuan service yang disebutkan diatas, pihak customer bersedia "
        "untuk patuh dan menandatangani surat perjanjian service yang dibuat oleh OMRON "
        "Healthcare Service Center.", STYLE_NORMAL,
    ))
    elements.append(Spacer(1, 30))

    sig_table = Table([
        [Paragraph("Hormat Kami,", STYLE_NORMAL), Paragraph("Menyetujui,", STYLE_NORMAL)],
        ["", ""],
        ["", ""],
        [Paragraph("", STYLE_NORMAL), Paragraph("Ttd &amp; Stempel", STYLE_NORMAL)],
        ["", ""],
        [Paragraph("", STYLE_NORMAL), Paragraph("Nama PIC Customer:", STYLE_NORMAL)],
        ["", ""],
        ["", ""],
        [Paragraph("OMRON Healthcare Service Center", STYLE_NORMAL), Paragraph("_" * 30, STYLE_NORMAL)],
    ], colWidths=[85 * mm, 85 * mm])
    sig_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    elements.append(sig_table)
    return elements


def generate_quotation_pdf(ticket, items) -> io.BytesIO:
    """PDF 'Surat Penawaran Harga' - format persis template resmi Omron."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=15 * mm, bottomMargin=15 * mm,
                             leftMargin=20 * mm, rightMargin=20 * mm)
    story = [_header_with_logo(), Spacer(1, 10)]

    story.append(Table([[
        Paragraph("Surat Penawaran Harga", STYLE_TITLE),
        Paragraph(_fmt_date_long(), STYLE_RIGHT),
    ]], colWidths=[110 * mm, 60 * mm]))
    story.append(Spacer(1, 4))

    quotation_number = ticket.quotation_number or "-"
    story.append(Paragraph(f"No : {quotation_number}", STYLE_NORMAL))
    story.append(Paragraph("Hal : SPH", STYLE_NORMAL))
    story.append(Spacer(1, 10))

    owner_name = ticket.invoice_owner_name or ticket.customer_name or "-"
    address = ticket.invoice_address or ticket.customer_address or "-"
    story.append(Paragraph("Kepada Yth,", STYLE_NORMAL))
    story.append(Paragraph(owner_name, STYLE_NORMAL))
    story.append(Paragraph(address, STYLE_NORMAL))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Dengan hormat,", STYLE_NORMAL))
    story.append(Paragraph("Sehubungan dengan adanya kerusakan pada alat", STYLE_NORMAL))
    story.append(Spacer(1, 8))

    device_rows = [["No", "Model Alat", "Qty", "Keterangan"]]
    service_label = (items[0].service_type if items else "Perbaikan").lower()
    for idx, item in enumerate(items, start=1):
        device_rows.append([
            f"{idx}.", item.device_model or "-", str(item.quantity or 1),
            (item.service_type or "Perbaikan").lower(),
        ])
    device_rows.append(["", "", "", ""])
    device_table = Table(device_rows, colWidths=[10 * mm, 60 * mm, 15 * mm, 73 * mm])
    device_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#999999")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(device_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph(f"Maka dengan ini kami mengajukan penawaran harga <b>{service_label}</b>", STYLE_NORMAL))
    story.append(Paragraph("dengan perincian sebagai berikut :", STYLE_NORMAL))
    story.append(Spacer(1, 6))

    price_table, subtotal, ppn, total = _price_table(
        items, ticket.ppn_free, ticket.pph23_amount, ticket.admin_bank_fee, ticket.use_manual_price_breakdown,
    )
    story.append(price_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Apabila Bapak / Ibu setuju dengan penawaran harga diatas,", STYLE_NORMAL))
    story.append(Paragraph("harap membalas surat penawaran ini dengan perjanjian service terlampir", STYLE_NORMAL))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Demikian penawaran harga dari kami, atas perhatian dan kerjasamanya kami ucapkan terima kasih.", STYLE_NORMAL))
    story.append(Spacer(1, 16))

    story.append(Table([[Paragraph("Hormat kami,", STYLE_NORMAL)]], colWidths=[170 * mm], style=[("ALIGN", (0, 0), (0, 0), "RIGHT")]))
    story.append(Spacer(1, 16))
    story.append(Table([[Paragraph("Service Team", STYLE_NORMAL)]], colWidths=[170 * mm], style=[("ALIGN", (0, 0), (0, 0), "RIGHT")]))

    # Halaman ke-2: Surat Perjanjian Service (lampiran wajib, teks baku)
    story.extend(_agreement_page())

    doc.build(story)
    buffer.seek(0)
    return buffer


def generate_invoice_pdf(ticket, items) -> io.BytesIO:
    """PDF 'INVOICE' - format persis template resmi Omron."""
    from app.services.doku_payment import PAYMENT_METHOD_LABELS

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=15 * mm, bottomMargin=15 * mm,
                             leftMargin=20 * mm, rightMargin=20 * mm)
    story = [_header_with_logo(), Spacer(1, 14)]

    story.append(Paragraph("INVOICE", STYLE_TITLE))
    story.append(Spacer(1, 10))

    owner_name = ticket.invoice_owner_name or ticket.customer_name or "-"
    address = ticket.invoice_address or ticket.customer_address or "-"
    id_number = ticket.customer_id_number or "-"
    invoice_number = ticket.invoice_number or "-"
    payment_via = PAYMENT_METHOD_LABELS.get(ticket.payment_method, ticket.payment_method) if ticket.payment_method else "-"
    payment_code = ticket.payment_code or "-"

    left_col = Paragraph(
        f"Invoice to:<br/>{owner_name}<br/>{address}<br/>NIK/ NPWP: {id_number}", STYLE_NORMAL
    )
    right_col = Table([
        ["Invoice No", f": {invoice_number}"],
        ["Invoice Date", f": {_fmt_date_long()}"],
        ["", ""],
        ["Payment Via", f": {payment_via}"],
        ["Payment Code", f": {payment_code}"],
    ], colWidths=[28 * mm, 45 * mm])
    right_col.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))

    info_table = Table([[left_col, right_col]], colWidths=[95 * mm, 75 * mm])
    info_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(info_table)
    story.append(Spacer(1, 10))

    price_table, subtotal, ppn, total = _price_table(
        items, ticket.ppn_free, ticket.pph23_amount, ticket.admin_bank_fee, ticket.use_manual_price_breakdown,
    )
    story.append(price_table)
    story.append(Spacer(1, 30))

    story.append(Table([[Paragraph("Hormat kami,", STYLE_NORMAL)]], colWidths=[170 * mm], style=[("ALIGN", (0, 0), (0, 0), "RIGHT")]))
    story.append(Spacer(1, 24))
    story.append(Table([[Paragraph("Service Team", STYLE_NORMAL)]], colWidths=[170 * mm], style=[("ALIGN", (0, 0), (0, 0), "RIGHT")]))

    doc.build(story)
    buffer.seek(0)
    return buffer
