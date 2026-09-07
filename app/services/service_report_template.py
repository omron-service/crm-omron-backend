"""
Generator file Excel "FORMULIR PERBAIKAN" (Service Report) per tiket, meniru
persis layout template asli yang diberikan (ServiceReport-OEC-....xlsx):
judul, data pelanggan/alat dalam kotak berlabel, tabel sparepart, syarat &
ketentuan, dan logo Omron.
"""
import io
import os
from datetime import datetime
from typing import Iterable, Optional

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
from openpyxl.drawing.image import Image as XLImage

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "..", "assets")
LOGO_PATH = os.path.join(ASSETS_DIR, "omron_logo.png")
BANNER_PATH = os.path.join(ASSETS_DIR, "omron_healthcare_banner.png")

HEADER_FILL = PatternFill(start_color="FFF6F8FC", end_color="FFF6F8FC", fill_type="solid")
THIN = Side(style="thin", color="000000")
BOX = Border(top=THIN, bottom=THIN, left=THIN, right=THIN)

FONT_TITLE = Font(name="Calibri", size=18, bold=True)
FONT_LABEL = Font(name="Calibri", size=11, bold=False)
FONT_LABEL_BOLD = Font(name="Calibri", size=11, bold=True)
FONT_FOOTER = Font(name="Calibri", size=14, bold=True, color="FF005EB8")

ALIGN_CENTER = Alignment(horizontal="center", vertical="center")
ALIGN_LEFT = Alignment(horizontal="left", vertical="center")
ALIGN_LEFT_WRAP = Alignment(horizontal="left", vertical="top", wrap_text=True)
ALIGN_RIGHT = Alignment(horizontal="right", vertical="center")

COLUMN_WIDTHS = {"A": 3.73, "B": 21.18, "C": 23.0, "D": 14.18, "E": 15.18, "F": 15.27, "G": 8.82}
ROW_HEIGHTS = {
    1: 12, 2: 12, 3: 19.25, 4: 12, 5: 12, 6: 12, 7: 12, 8: 12, 9: 12, 10: 24,
    11: 12, 12: 12, 13: 24, 14: 100, 15: 12, 16: 12, 17: 12, 18: 12, 19: 12,
    20: 12, 21: 12, 22: 12, 23: 12, 24: 12, 25: 12, 26: 12, 27: 12, 28: 12,
    29: 12, 30: 12, 31: 12, 32: 12, 33: 12, 34: 12, 35: 12, 36: 12, 37: 12,
    38: 12, 39: 12, 40: 17.65,
}

TERMS_1 = (
    "1. Garansi tidak berlaku jika kerusakan disebabkan oleh kesalahan penggunaan "
    "atau efek lingkungan (hama, serangga, terkena cairan, robek, terbakar, dll)."
)
TERMS_2 = (
    "2. Omron Healthcare Service Center tidak bertanggung jawab atas kehilangan dan "
    "kerusakan alat yang disebabkan oleh FORCE MAJEURE (gempa bumi, banjir, kebakaran, "
    "pencurian, perampokan, dll)."
)


def _fmt_date(value) -> str:
    if not value:
        return "-"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _label(ws, coord: str, text: str):
    cell = ws[coord]
    cell.value = text
    cell.font = FONT_LABEL
    cell.fill = HEADER_FILL
    cell.border = BOX
    cell.alignment = ALIGN_LEFT
    return cell


def _value(ws, coord: str, value, align: Alignment = ALIGN_CENTER):
    cell = ws[coord]
    cell.value = value
    cell.font = FONT_LABEL
    cell.border = BOX
    cell.alignment = align
    return cell


def generate_ticket_service_report(ticket, spareparts: Optional[Iterable] = None) -> io.BytesIO:
    """
    ticket: instance ServiceTicket (butuh atribut: ticket_number, warranty_status,
        customer_name, received_date, completed_date, customer_phone,
        customer_address, device_model, serial_number, accessories, complaint,
        technician_analysis, created_at).
    spareparts: iterable TicketSparePart (name, code, quantity, price, slot_no)
        - maksimal 5 baris ditampilkan sesuai template asli.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "BizForm"

    for col, w in COLUMN_WIDTHS.items():
        ws.column_dimensions[col].width = w
    for row, h in ROW_HEIGHTS.items():
        ws.row_dimensions[row].height = h

    # ---- Judul + logo ----
    ws.merge_cells("B2:D3")
    title_cell = ws["B2"]
    title_cell.value = "FORMULIR  PERBAIKAN"
    title_cell.font = FONT_TITLE
    title_cell.alignment = ALIGN_LEFT

    if os.path.exists(LOGO_PATH):
        logo_img = XLImage(LOGO_PATH)
        logo_img.width = 190
        logo_img.height = 50
        ws.add_image(logo_img, "E2")

    # ---- Data tiket & pelanggan ----
    _label(ws, "B6", "NO - ERF Number")
    _value(ws, "C6", ticket.ticket_number)
    _label(ws, "D6", "KONTRAK ID")
    ws.merge_cells("E6:F6")
    _value(ws, "E6", "")

    _label(ws, "B7", "STATUS GARANSI")
    _value(ws, "C7", ticket.warranty_status or "-")
    ws.merge_cells("D7:D8")
    _label(ws, "D7", "NAMA PEMILIK")
    ws.merge_cells("E7:F8")
    _value(ws, "E7", ticket.customer_name or "-")

    _label(ws, "B8", "TANGGAL TERIMA")
    _value(ws, "C8", _fmt_date(ticket.received_date or ticket.created_at))

    _label(ws, "B9", "TANGGAL SELESAI")
    _value(ws, "C9", _fmt_date(ticket.completed_date))
    _label(ws, "D9", "NO. TELEPON")
    ws.merge_cells("E9:F9")
    _value(ws, "E9", ticket.customer_phone or "-")

    _label(ws, "B10", "ALAMAT")
    ws.merge_cells("C10:F10")
    _value(ws, "C10", ticket.customer_address or "-", ALIGN_LEFT)

    _label(ws, "B11", "PRODUK")
    _value(ws, "C11", ticket.device_model or "-")
    _label(ws, "D11", "NO. SERIAL")
    ws.merge_cells("E11:F11")
    _value(ws, "E11", ticket.serial_number or "-")

    _label(ws, "B12", "AKSESORIS")
    ws.merge_cells("C12:F12")
    _value(ws, "C12", ticket.accessories or "-", ALIGN_LEFT)

    _label(ws, "B13", "PROBLEM")
    ws.merge_cells("C13:F13")
    _value(ws, "C13", ticket.complaint or "-", ALIGN_LEFT_WRAP)

    _label(ws, "B14", "KESIMPULAN")
    ws.merge_cells("C14:F14")
    _value(ws, "C14", ticket.technician_analysis or "-", ALIGN_LEFT_WRAP)

    # ---- Tabel sparepart (maks 5 baris, sesuai template asli) ----
    ws.merge_cells("E16:F16")
    for coord, text in [("B16", "Nama Spare Part"), ("C16", "Kode Spare Part"),
                        ("D16", "Jumlah"), ("E16", "Harga. Rp.")]:
        cell = ws[coord]
        cell.value = text
        cell.font = FONT_LABEL_BOLD
        cell.fill = HEADER_FILL
        cell.border = BOX
        cell.alignment = ALIGN_CENTER

    sp_list = list(spareparts or [])[:5]
    total = 0.0
    for i in range(5):
        row = 17 + i
        sp = sp_list[i] if i < len(sp_list) else None
        ws.merge_cells(f"E{row}:F{row}")
        _value(ws, f"B{row}", sp.name if sp and sp.name else "", ALIGN_LEFT)
        _value(ws, f"C{row}", sp.code if sp and sp.code else "", ALIGN_CENTER)
        _value(ws, f"D{row}", sp.quantity if sp and sp.quantity else "", ALIGN_CENTER)
        line_total = (sp.price or 0) * (sp.quantity or 0) if sp else 0
        _value(ws, f"E{row}", line_total if sp else "", ALIGN_RIGHT)
        total += line_total

    ws["D22"].value = "Total"
    ws["D22"].font = FONT_LABEL
    ws["D22"].alignment = ALIGN_RIGHT
    ws.merge_cells("E22:F22")
    _value(ws, "E22", total, ALIGN_RIGHT)

    # ---- Syarat & Ketentuan ----
    ws["B25"].value = "Syarat & Ketentuan"
    ws["B25"].font = FONT_LABEL_BOLD

    ws.merge_cells("B26:F27")
    ws["B26"].value = TERMS_1
    ws["B26"].font = FONT_LABEL
    ws["B26"].alignment = ALIGN_LEFT_WRAP

    ws.merge_cells("B28:F30")
    ws["B28"].value = TERMS_2
    ws["B28"].font = FONT_LABEL
    ws["B28"].alignment = ALIGN_LEFT_WRAP

    ws["B35"].value = "Pemilik : "
    ws["B35"].font = FONT_LABEL
    ws["D35"].value = "Teknisi:"
    ws["D35"].font = FONT_LABEL
    ws["D35"].alignment = ALIGN_CENTER

    if os.path.exists(BANNER_PATH):
        banner_img = XLImage(BANNER_PATH)
        banner_img.width = 209
        banner_img.height = 74
        ws.add_image(banner_img, "D39")

    ws["B40"].value = "ALL for Healthcare"
    ws["B40"].font = FONT_FOOTER

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer
