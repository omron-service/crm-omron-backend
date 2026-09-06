import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from io import BytesIO

def generate_service_report_excel(tickets_data):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Rekapitulasi Servis"

    header_fill = PatternFill(start_color="0056B3", end_color="0056B3", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    thin_border = Border(
        left=Side(style='thin', color='CCCCCC'),
        right=Side(style='thin', color='CCCCCC'),
        top=Side(style='thin', color='CCCCCC'),
        bottom=Side(style='thin', color='CCCCCC')
    )

    headers = [
        "No. Tiket", "Tanggal Masuk", "Nama Pelanggan", 
        "No. HP", "Model Perangkat", "Serial Number", 
        "Status", "Teknisi Penanggung Jawab"
    ]
    
    ws.append(headers)

    for col_num in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row_idx, t in enumerate(tickets_data, start=2):
        row = [
            t.get("ticket_number", ""),
            t.get("created_at", ""),
            t.get("customer_name", ""),
            t.get("customer_phone", ""),
            t.get("device_model", ""),
            t.get("serial_number", ""),
            t.get("status", ""),
            t.get("technician", "Belum Ditugaskan")
        ]
        ws.append(row)
        for col_idx in range(1, len(row) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.border = thin_border

    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = openpyxl.utils.get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output
