"""
Generator PDF untuk Tab Status Payment Service:
- generate_quotation_pdf()  -> "Penawaran Harga"
- generate_invoice_pdf()    -> "Invoice Service"
"""
import io
import os
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, HRFlowable,
)
from reportlab.lib.enums import TA_RIGHT, TA_CENTER

LOGO_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "omron_logo.png")

COMPANY_INFO = (
    "Omron Healthcare Service Center<br/>"
    "Call Center: 0800 1401 567 (bebas pulsa) / WA: 0811 1310 1567<br/>"
    "www.omronhealthcare-ap.com/id"
)

styles = getSampleStyleSheet()
STYLE_TITLE = ParagraphStyle("TitleDoc", parent=styles["Title"], fontSize=18, spaceAfter=2)
STYLE_NORMAL = styles["Normal"]
STYLE_RIGHT = ParagraphStyle("Right", parent=styles["Normal"], alignment=TA_RIGHT)
STYLE_CENTER = ParagraphStyle("Center", parent=styles["Normal"], alignment=TA_CENTER)
STYLE_SMALL = ParagraphStyle("Small", parent=styles["Normal"], fontSize=8, textColor=colors.grey)


def _fmt_rupiah(value) -> str:
    try:
        return f"Rp {int(round(float(value or 0))):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "Rp 0"


def _fmt_date(value) -> str:
    if not value:
        return "-"
    if isinstance(value, datetime):
        return value.strftime("%d %B %Y")
    return str(value)


def _header_block(doc_title: str, doc_number: str, doc_date: str):
    elements = []
    if os.path.exists(LOGO_PATH):
        elements.append(Image(LOGO_PATH, width=45 * mm, height=12 * mm))
    elements.append(Spacer(1, 6))
    elements.append(Paragraph(doc_title, STYLE_TITLE))
    elements.append(Paragraph(f"No: {doc_number}", STYLE_NORMAL))
    elements.append(Paragraph(f"Tanggal: {doc_date}", STYLE_NORMAL))
    elements.append(Spacer(1, 10))
    elements.append(HRFlowable(width="100%", color=colors.HexColor("#0056B3"), thickness=1.5))
    elements.append(Spacer(1, 10))
    return elements


def _customer_block(ticket):
    rows = [
        ["Kepada Yth.", ticket.customer_name or "-"],
        ["Instansi", ticket.instansi_name or "-"],
        ["Alamat", ticket.customer_address or "-"],
        ["No. Telepon", ticket.customer_phone or "-"],
    ]
    if getattr(ticket, "customer_id_number", None):
        rows.append(["NIK/NPWP", ticket.customer_id_number])

    table = Table(rows, colWidths=[35 * mm, 120 * mm])
    table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
    ]))
    return table


def _device_block(ticket):
    rows = [
        ["No. Tiket", ticket.ticket_number, "Model Alat", ticket.device_model or "-"],
        ["Serial No.", ticket.serial_number or "-", "Status Garansi", ticket.warranty_status or "-"],
    ]
    table = Table(rows, colWidths=[28 * mm, 55 * mm, 30 * mm, 55 * mm])
    table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F6F8FC")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
    ]))
    return table


def _spareparts_table(spareparts, total_price):
    header = ["No", "Deskripsi", "Kode", "Jumlah", "Harga Satuan", "Subtotal"]
    data = [header]
    running_subtotal = 0.0
    for i, sp in enumerate(spareparts or [], start=1):
        if not sp or not sp.name:
            continue
        qty = sp.quantity or 0
        price = sp.price or 0
        subtotal = qty * price
        running_subtotal += subtotal
        data.append([str(i), sp.name, sp.code or "-", str(qty), _fmt_rupiah(price), _fmt_rupiah(subtotal)])

    if len(data) == 1:
        data.append(["-", "Jasa Service", "-", "1", "-", "-"])

    data.append(["", "", "", "", "TOTAL", _fmt_rupiah(total_price)])

    table = Table(data, colWidths=[10 * mm, 55 * mm, 25 * mm, 18 * mm, 30 * mm, 32 * mm])
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0056B3")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -2), 0.5, colors.HexColor("#CCCCCC")),
        ("SPAN", (0, -1), (3, -1)),
        ("FONTNAME", (4, -1), (-1, -1), "Helvetica-Bold"),
        ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#0056B3")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    table.setStyle(TableStyle(style))
    return table


def _signature_block(label_left="Hormat kami,", label_right="Pelanggan,"):
    data = [
        [label_left, label_right],
        ["", ""],
        ["", ""],
        ["", ""],
        ["( Omron Healthcare Service Center )", "( " + " " * 30 + " )"],
    ]
    table = Table(data, colWidths=[85 * mm, 85 * mm])
    table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 1), (-1, 3), 14),
    ]))
    return table


def generate_quotation_pdf(ticket, spareparts=None) -> io.BytesIO:
    """PDF 'Penawaran Harga' - estimasi biaya SEBELUM invoice final diterbitkan."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm,
                             leftMargin=20 * mm, rightMargin=20 * mm)
    story = []
    story += _header_block("PENAWARAN HARGA SERVICE", f"QUO-{ticket.ticket_number}", _fmt_date(datetime.utcnow()))
    story.append(_customer_block(ticket))
    story.append(Spacer(1, 8))
    story.append(_device_block(ticket))
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"<b>Keluhan:</b> {ticket.complaint or '-'}", STYLE_NORMAL))
    story.append(Paragraph(f"<b>Analisa Teknisi:</b> {ticket.technician_analysis or '-'}", STYLE_NORMAL))
    story.append(Spacer(1, 10))
    story.append(_spareparts_table(spareparts, ticket.total_price))
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "<i>Penawaran ini berlaku 14 hari sejak tanggal diterbitkan. Harga dapat berubah "
        "apabila ditemukan kerusakan tambahan setelah pengecekan lebih lanjut.</i>",
        STYLE_SMALL,
    ))
    story.append(Spacer(1, 25))
    story.append(_signature_block("Hormat kami,", "Menyetujui,"))
    story.append(Spacer(1, 20))
    story.append(Paragraph(COMPANY_INFO, STYLE_SMALL))

    doc.build(story)
    buffer.seek(0)
    return buffer


def generate_invoice_pdf(ticket, spareparts=None) -> io.BytesIO:
    """PDF 'Invoice Service' - tagihan resmi, termasuk status & kode pembayaran kalau sudah ada."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm,
                             leftMargin=20 * mm, rightMargin=20 * mm)
    story = []
    story += _header_block("INVOICE SERVICE", f"INV-{ticket.ticket_number}", _fmt_date(datetime.utcnow()))
    story.append(_customer_block(ticket))
    story.append(Spacer(1, 8))
    story.append(_device_block(ticket))
    story.append(Spacer(1, 10))
    story.append(_spareparts_table(spareparts, ticket.total_price))
    story.append(Spacer(1, 10))

    payment_rows = [
        ["Status Pembayaran", ticket.payment_status or "Belum Lunas"],
    ]
    if ticket.payment_method:
        from app.services.doku_payment import PAYMENT_METHOD_LABELS
        payment_rows.append(["Metode Pembayaran", PAYMENT_METHOD_LABELS.get(ticket.payment_method, ticket.payment_method)])
    if ticket.payment_code:
        payment_rows.append(["Kode Bayar / VA", ticket.payment_code])
    if ticket.payment_url:
        payment_rows.append(["Link Pembayaran", ticket.payment_url])

    payment_table = Table(payment_rows, colWidths=[45 * mm, 125 * mm])
    payment_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(payment_table)
    story.append(Spacer(1, 25))
    story.append(_signature_block("Hormat kami,", "Diterima oleh,"))
    story.append(Spacer(1, 20))
    story.append(Paragraph(COMPANY_INFO, STYLE_SMALL))

    doc.build(story)
    buffer.seek(0)
    return buffer
